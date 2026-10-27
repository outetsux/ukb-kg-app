"""Bound request memory and admission before FastAPI parses request bodies."""
import asyncio
import hmac
from starlette.datastructures import Headers
from starlette.responses import JSONResponse


class RequestGuard:
    def __init__(self, app, token, max_bytes=20000, max_active=16):
        self.app, self.token = app, token
        self.max_bytes, self.max_active, self.active = max_bytes, max_active, 0

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        headers = Headers(scope=scope)
        async def reject(status, detail):
            response = JSONResponse({'detail': detail}, status_code=status,
                                    headers={'Retry-After': '60'} if status == 429 else None)
            await response(scope, receive, send)
        if scope['path'].startswith('/v1/') and (not self.token or not hmac.compare_digest(
                headers.get('authorization', '').encode(), ('Bearer ' + self.token).encode())):
            return await reject(401, 'Service authentication failed.')
        if self.active >= self.max_active:
            return await reject(429, 'The service is busy. Please retry shortly.')
        try:
            length = int(headers.get('content-length', '0'))
            if length < 0:
                raise ValueError
        except ValueError:
            return await reject(400, 'Invalid request size.')
        if length > self.max_bytes:
            return await reject(413, 'Request is too large.')
        self.active += 1
        try:
            body = bytearray()
            async def read_body():
                while True:
                    message = await receive()
                    if message['type'] == 'http.disconnect':
                        return False
                    body.extend(message.get('body', b''))
                    if len(body) > self.max_bytes:
                        return False
                    if not message.get('more_body', False):
                        return True
            try:
                complete = await asyncio.wait_for(read_body(), timeout=10)
            except (TimeoutError, asyncio.TimeoutError):
                return await reject(408, 'Request body timed out.')
            if not complete:
                return await reject(413, 'Request is too large or incomplete.')
            replayed = False
            async def replay():
                nonlocal replayed
                if not replayed:
                    replayed = True
                    return {'type': 'http.request', 'body': bytes(body), 'more_body': False}
                return await receive()
            await self.app(scope, replay, send)
        finally:
            self.active -= 1
