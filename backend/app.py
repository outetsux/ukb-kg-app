from collections import defaultdict, deque
from contextlib import asynccontextmanager
import asyncio
import hmac
import logging
import time
import uuid
from fastapi import FastAPI, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from .config import settings
from .limits import RequestGuard
from .catalog import Catalog, TYPE_NAMES
from .graph import GraphStore
from .papers import PaperStore
from .schema import Question, RetrievalRequest, SubgraphRequest
from shared.rag_settings import retrieval_parameters

log = logging.getLogger('ukb')


class HeavyGate:
    def __init__(self, running=1, waiting=2, timeout=180):
        self.timeout = timeout
        self.capacity = running + waiting
        self.active = 0
        self.semaphore = asyncio.Semaphore(running)

    async def run(self, fn, *args):
        if self.active >= self.capacity:
            raise HTTPException(429, 'The service is busy. Please try again shortly.', headers={'Retry-After': '60'})
        self.active += 1
        deadline = time.monotonic() + self.timeout
        try:
            await asyncio.wait_for(self.semaphore.acquire(), self.timeout)
        except BaseException:
            self.active -= 1
            raise
        # A timeout must not release a worker slot while its thread is still computing.
        task = asyncio.create_task(asyncio.to_thread(fn, *args, deadline=deadline))
        def finished(t):
            self.active -= 1
            self.semaphore.release()
            if not t.cancelled():
                t.exception()
        task.add_done_callback(finished)
        return await asyncio.wait_for(asyncio.shield(task), max(.01, deadline-time.monotonic()))


@asynccontextmanager
async def lifespan(app):
    settings.validate()
    app.state.catalog = Catalog(settings.data_dir)
    app.state.papers = PaperStore(settings.data_dir)
    app.state.graph = GraphStore(settings, app.state.catalog)
    app.state.graph_ready = False
    try:
        app.state.graph.verify()
        app.state.graph_ready = True
    except Exception as exc:
        log.warning('graph_not_ready type=%s', type(exc).__name__)
    app.state.rag = None
    app.state.rag_error = None
    if settings.rag_enabled:
        try:
            from .rag import RagEngine
            app.state.rag = RagEngine(settings, app.state.catalog, app.state.graph)
        except Exception as exc:
            app.state.rag_error = type(exc).__name__
            log.error('rag_startup_failed type=%s', type(exc).__name__)
    app.state.gate = HeavyGate()
    app.state.graph_gate = HeavyGate(running=2, waiting=2, timeout=20)
    app.state.rate = defaultdict(deque)
    yield
    app.state.graph.close()


app = FastAPI(title='UKB-KG service', lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware('http')
async def request_context(request, call_next):
    request.state.request_id = uuid.uuid4().hex
    start = time.monotonic()
    # Only small JSON requests are accepted; never log bodies or authorization headers.
    try:
        response = await call_next(request)
    except Exception as exc:
        log.error('request_failed id=%s type=%s', request.state.request_id, type(exc).__name__)
        response = JSONResponse({'detail': 'Service unavailable. Please retry.',
                                 'request_id': request.state.request_id}, status_code=503)
    response.headers['X-Request-ID'] = request.state.request_id
    log.info('request id=%s status=%s elapsed=%.3f', request.state.request_id,
             response.status_code, time.monotonic()-start)
    return response


async def authorize(request: Request, authorization: str = Header(default=''),
                    x_session_id: str = Header(default='')):
    if not settings.token or not hmac.compare_digest(authorization.encode(), ('Bearer ' + settings.token).encode()):
        raise HTTPException(401, 'Service authentication failed.')
    if not x_session_id or len(x_session_id) > 100:
        raise HTTPException(400, 'Missing session identifier.')
    now = time.monotonic()
    rate = request.app.state.rate
    # Expire inactive keys so untrusted session churn cannot grow memory indefinitely.
    for key in list(rate):
        while rate[key] and rate[key][0] < now - 60:
            rate[key].popleft()
        if not rate[key]:
            del rate[key]
    heavy = request.url.path in {'/v1/entities/extract', '/v1/rag/retrieve'}
    keys = [('all', 180), ('session:' + x_session_id, 30)]
    if heavy:
        keys += [('heavy:all', 8), ('heavy:' + x_session_id, 4)]
    if request.url.path == '/v1/subgraph':
        keys += [('graph:all', 20), ('graph:' + x_session_id, 6)]
    if any(len(rate[k]) >= limit for k, limit in keys):
        raise HTTPException(429, 'Request limit reached. Please wait a minute.', headers={'Retry-After': '60'})
    for key, _ in keys:
        rate[key].append(now)


def envelope(request, data):
    return {'version': request.app.state.catalog.version, 'request_id': request.state.request_id,
            'truncated': False, 'warnings': [], **data}


@app.get('/healthz')
def health():
    return {'status': 'up'}


@app.get('/v1/release', dependencies=[Depends(authorize)])
def release(request: Request):
    c = request.app.state.catalog
    return envelope(request, {'stats': c.stats, 'generated_at': c.manifest['generated_at'],
        'rag_ready': request.app.state.rag is not None, 'export_enabled': settings.export_enabled,
        'rag_parameters': retrieval_parameters(),
        'graph_ready': request.app.state.graph_ready,
        'missing_scores': c.missing_scores,
        'papers': len(request.app.state.papers.papers), 'baselines': len(request.app.state.papers.baselines)})


@app.get('/v1/entities/search', dependencies=[Depends(authorize)])
def search(request: Request, q: str = ''):
    if len(q) > 200:
        raise HTTPException(422, 'Search text is too long.')
    return envelope(request, request.app.state.catalog.search(q))


@app.get('/v1/entities/{key}/neighbors', dependencies=[Depends(authorize)])
def neighbors(request: Request, key: str):
    try:
        return envelope(request, request.app.state.catalog.neighborhood(key))
    except KeyError:
        raise HTTPException(404, 'Entity not found.')


@app.post('/v1/subgraph', dependencies=[Depends(authorize)])
async def subgraph(spec: SubgraphRequest, request: Request):
    if any(t not in TYPE_NAMES for t in spec.target_types):
        raise HTTPException(422, 'Unknown entity type.')
    def work(*, deadline):
        graph = request.app.state.graph
        if not graph.verified:
            graph.verify(timeout=max(.01, deadline-time.monotonic()))
            request.app.state.graph_ready = True
        return graph.subgraph(spec, deadline=deadline)
    try:
        return envelope(request, await request.app.state.graph_gate.run(work))
    except (TimeoutError, asyncio.TimeoutError):
        raise HTTPException(504, 'Graph query timed out. Please narrow the query.')
    except ValueError:
        raise HTTPException(422, 'Select valid entities from the current release.')


@app.get('/v1/papers/{key}', dependencies=[Depends(authorize)])
def paper(key: str, request: Request):
    try:
        return envelope(request, request.app.state.papers.get(key))
    except ValueError as exc:
        raise HTTPException(422, str(exc))


def require_rag(request):
    if request.app.state.rag is None:
        raise HTTPException(503, 'The retrieval models are not ready. Graph search is still available.')
    return request.app.state.rag


@app.post('/v1/entities/extract', dependencies=[Depends(authorize)])
async def extract(spec: Question, request: Request):
    rag = require_rag(request)
    def work(*, deadline):
        return rag.extract(spec.question)
    try:
        candidates = await request.app.state.gate.run(work)
        return envelope(request, {'candidates': candidates})
    except (TimeoutError, asyncio.TimeoutError):
        raise HTTPException(504, 'Entity extraction timed out. Please retry.')


@app.post('/v1/rag/retrieve', dependencies=[Depends(authorize)])
async def retrieve(spec: RetrievalRequest, request: Request):
    rag = require_rag(request)
    try:
        result = await request.app.state.gate.run(rag.retrieve, spec.question, spec.entities)
        return envelope(request, result)
    except (TimeoutError, asyncio.TimeoutError):
        raise HTTPException(504, 'Retrieval timed out. Please narrow the question and retry.')


app.add_middleware(RequestGuard, token=settings.token)
