"""UKB-KG/rag retrieval with manuscript settings, online extraction and no UMLS."""
from collections import OrderedDict
import logging
import threading
import time
import numpy as np
from shared.release_files import EMBEDDINGS_FILE
from shared.rag_settings import (K1, K2, K3, CONTEXT_TOKENS, CONFIDENCE_WEIGHT,
                                 FREQUENCY_WEIGHT, RELEVANCE_WEIGHT, retrieval_parameters)

log = logging.getLogger('ukb')


def masked_mean_pool(hidden_states, attention_mask):
    mask = attention_mask.unsqueeze(-1).type_as(hidden_states)
    return (hidden_states * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1e-9)


def unique_triples(edges):
    """Retain the first record for each directed semantic triple, as in rag/core.py."""
    seen = set()
    result = []
    for edge in edges:
        key = (edge['head'], edge['relation'], edge['tail'])
        if key not in seen:
            result.append(edge)
            seen.add(key)
    return result


def normalize(similarity):
    return (similarity + 1) / 2


def score(confidence, frequency, similarity):
    return CONFIDENCE_WEIGHT * confidence + FREQUENCY_WEIGHT * frequency + RELEVANCE_WEIGHT * normalize(similarity)


def path_text(path, catalog):
    # Use traversal node IDs, not name-prefix/suffix guesses; preserve stored directions.
    nodes = path['nodes']
    if len(nodes) != len(path['edges']) + 1:
        raise ValueError('Invalid path node/relationship counts')
    if not path['edges']:
        return ''
    text = catalog.nodes[nodes[0]]['name']
    for left, eid, right in zip(nodes, path['edges'], nodes[1:]):
        edge = catalog.edges[eid]
        rel, name = edge['relation'], catalog.nodes[right]['name']
        if edge['source'] == left and edge['target'] == right:
            text += f' -({rel})-> {name}'
        elif edge['target'] == left and edge['source'] == right:
            text += f' <-({rel})- {name}'
        else:
            raise ValueError('Relationship endpoints do not match path nodes')
    return '[' + text + ']'


class RagEngine:
    def __init__(self, settings, catalog, graph):
        if getattr(catalog, 'missing_scores', 0):
            raise ValueError('Complete source scores are required for RAG; browsing remains available.')
        import torch
        import spacy
        import spacy_transformers  # register the transformer factory before loading the exported model
        import tiktoken
        from transformers import AutoTokenizer, AutoModel
        self.torch, self.catalog, self.graph = torch, catalog, graph
        import hashlib
        for relative, info in getattr(catalog, 'manifest', {}).get('models', {}).items():
            path = settings.model_dir / relative
            digest = hashlib.sha256()
            with path.open('rb') as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    digest.update(block)
            if digest.hexdigest() != info['sha256']:
                raise ValueError('Model checksum differs from the release manifest.')
        torch.set_num_threads(2)
        self.nlp = spacy.load(settings.model_dir / 'en_core_sci_scibert-0.5.4')
        self.tokenizer = AutoTokenizer.from_pretrained(settings.model_dir / 'biobert_v1.2', local_files_only=True)
        self.model = AutoModel.from_pretrained(settings.model_dir / 'biobert_v1.2', local_files_only=True).eval()
        # Object strings in this legacy NPZ require pickle; Catalog verifies its trusted checksum first.
        with np.load(settings.data_dir / EMBEDDINGS_FILE, allow_pickle=True) as data:
            self.names = data['entities'].astype(str)
            self.vectors = data['embeddings'].astype(np.float32)
        if set(self.names) != set(catalog.names) or len(self.names) != len(catalog.names):
            raise ValueError('Node embeddings do not match the published graph.')
        if not np.isfinite(self.vectors).all():
            raise ValueError('Invalid node embeddings.')
        self.encoder = tiktoken.encoding_for_model('gpt-4o')
        self.cache = OrderedDict()
        self.cache_lock, self.model_lock = threading.Lock(), threading.Lock()

    def extract(self, question):
        with self.model_lock:
            doc = self.nlp(question)
        return list(dict.fromkeys(ent.text for ent in doc.ents
                                 if any(t.pos_ in {'NOUN', 'PROPN'} for t in ent)))

    def embed_batch(self, texts):
        # Match the revised graph/question encoder: padding contributes neither sum nor count.
        with self.model_lock, self.torch.no_grad():
            inputs = self.tokenizer(texts, return_tensors='pt', padding=True, truncation=True,
                                    max_length=self.model.config.max_position_embeddings)
            hidden = self.model(**inputs).last_hidden_state
            return masked_mean_pool(hidden, inputs['attention_mask']).cpu().numpy()

    def embed(self, text, cache=False):
        if cache:
            with self.cache_lock:
                value = self.cache.get(text)
                if value is not None:
                    self.cache.move_to_end(text)
                    return value
        value = self.embed_batch([text])[0]
        if cache:
            with self.cache_lock:
                self.cache[text] = value
                while len(self.cache) > 2000:
                    self.cache.popitem(last=False)
        return value

    def retrieve(self, question, entities, deadline=None):
        from sklearn.metrics.pairwise import cosine_similarity
        deadline = deadline or time.monotonic() + 180
        def check_time():
            if time.monotonic() >= deadline:
                raise TimeoutError('Retrieval exceeded its time budget. Please narrow the question.')
        warnings = []
        if not entities:
            warnings.append('No biomedical entities were retained; the whole question was used for matching.')
        embeddings = self.embed_batch(entities or [question])
        matched = []
        for vector in embeddings:
            check_time()
            sims = cosine_similarity([vector], self.vectors)[0]
            matched.extend(self.names[sims.argsort()[-K1:][::-1]].tolist())
        # Stable deduplication replaces non-deterministic Python set iteration only.
        matched = list(dict.fromkeys(matched))
        candidates = unique_triples(self.catalog.candidates(matched))
        q = self.embed(question)
        scored = []
        for edge in candidates:
            check_time()
            vector = self.embed(f"[{edge['head']},{edge['relation']},{edge['tail']}]", cache=True)
            sim = float(cosine_similarity([q], [vector])[0, 0])
            scored.append((edge, score(edge['confidence'], edge['frequency'], sim)))
        scored.sort(key=lambda pair: pair[1], reverse=True)
        triples = [{**edge, 'retrieval_score': value} for edge, value in scored[:K2]]
        paths = []
        paths_available = True
        path_start=time.monotonic()
        stage='query'
        try:
            check_time()
            raw_paths = self.graph.shortest_paths(matched, timeout=deadline-time.monotonic())
            stage='ranking'
            for path in raw_paths:
                check_time()
                text = path_text(path, self.catalog)
                if not text:
                    continue
                sim = float(cosine_similarity([q], [self.embed(text, cache=True)])[0, 0])
                paths.append({**path, 'text': text, 'retrieval_score': normalize(sim)})
            paths.sort(key=lambda p: p['retrieval_score'], reverse=True)
            paths = paths[:K3]
        except Exception as exc:
            log.warning('rag_paths_failed stage=%s type=%s elapsed=%.3f',
                        stage,type(exc).__name__,time.monotonic()-path_start)
            paths_available = False
            paths = []
            warnings.append('Path retrieval was unavailable; only neighbor evidence was used.'
                            if triples else 'Path retrieval was unavailable; no graph evidence was found.')
        check_time()
        context = '## Neighbor-based Context:\n\nTriples:\n'
        context += ''.join(f"{i}. [{e['head']} -({e['relation']})-> {e['tail']}]\n"
                           for i, e in enumerate(triples, 1))
        context = context.strip()
        if paths_available:
            context += '\n\n## Path-based Context:\n\nPaths:\n'
            context += ''.join(f"{i}. {p['text']}\n" for i, p in enumerate(paths, 1))
        tokens = self.encoder.encode(context)
        context = self.encoder.decode(tokens[:CONTEXT_TOKENS])
        if len(tokens) > CONTEXT_TOKENS:
            warnings.append('Context was truncated to 10,000 tokens. The exact model context is available below.')
        # Only selected path records are exposed for visualization. No extra retrieval or re-ranking.
        path_graph = self.catalog.graph(eid for path in paths for eid in path['edges']) if paths else {'nodes':[], 'edges':[]}
        return {'matched_entities': [self.catalog.nodes[key] for n in matched for key in self.catalog.name_to_ids[n]],
                'entities': entities, 'triples': triples, 'paths': paths, 'context': context,
                'path_graph': {**path_graph, 'paths':paths}, 'retrieval_parameters':retrieval_parameters(),
                'has_context': bool(triples or paths), 'truncated': len(tokens) > CONTEXT_TOKENS,
                'context_tokens': min(len(tokens), CONTEXT_TOKENS), 'warnings': warnings}
