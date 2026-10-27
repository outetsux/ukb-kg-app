from pathlib import Path
import json
import os
import uuid
import httpx
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]


def setting(key, default=''):
    try:
        return st.secrets.get(key, os.getenv(key, default))
    except (FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
        return os.getenv(key, default)


class ServiceError(Exception):
    pass


def api(path, payload=None, params=None):
    st.session_state.setdefault('service_session', uuid.uuid4().hex)
    from urllib.parse import urlparse
    base = str(setting('UKB_BACKEND_URL')).rstrip('/')
    url = urlparse(base)
    if (url.scheme != 'https' or not url.hostname or not url.hostname.endswith('.modal.run')
            or url.username or url.password or url.query or url.fragment or url.path):
        raise ServiceError('Configure the HTTPS Modal backend URL in Streamlit Secrets.')
    credentials = {name: str(setting(name)) for name in
                   ('UKB_SERVICE_TOKEN', 'UKB_MODAL_KEY', 'UKB_MODAL_SECRET')}
    if any(not value or value.startswith('REPLACE_') for value in credentials.values()):
        raise ServiceError('Configure the backend credentials in Streamlit Secrets.')
    try:
        response = httpx.request('GET' if payload is None else 'POST',
            base + '/v1/' + path,
            params=params, json=payload,
            headers={'Authorization': 'Bearer ' + credentials['UKB_SERVICE_TOKEN'],
                     'Modal-Key': credentials['UKB_MODAL_KEY'],
                     'Modal-Secret': credentials['UKB_MODAL_SECRET'],
                     'X-Session-ID': st.session_state.service_session},
            timeout=httpx.Timeout(240, connect=10), follow_redirects=False, trust_env=False)
        if response.status_code != 200:
            if response.status_code == 503 and path == 'rag/retrieve':
                raise ServiceError('RAG retrieval is unavailable. Please retry; no answer was generated.')
            messages = {401: 'The service connection is not configured correctly.',
                        429: 'The service is busy. Please wait a minute and retry.',
                        503: 'This service is temporarily unavailable. Please retry.',
                        504: 'The request timed out. Please narrow the query and retry.'}
            if response.status_code in {404, 422}:
                detail = response.json().get('detail')
                if isinstance(detail, str):
                    raise ServiceError(detail)
            raise ServiceError(messages.get(response.status_code, 'The request could not be completed.'))
        return response.json()
    except (httpx.HTTPError, ValueError):
        raise ServiceError('Unable to reach the graph service. Please retry shortly.') from None


def release():
    # Per-session metadata only. Never cache credentials or model responses globally.
    import time
    if 'release_info' not in st.session_state or time.monotonic() - st.session_state.get('release_loaded', 0) > 60:
        st.session_state.release_info = api('release')
        st.session_state.release_loaded = time.monotonic()
    return st.session_state.release_info


def providers():
    default = [{'name':'OpenAI', 'base_url':'https://api.openai.com/v1',
                'api':'responses', 'models':['gpt-5-mini', 'gpt-4.1'], 'default_model':'gpt-5-mini'}]
    raw = setting('UKB_PROVIDERS_JSON')
    path = ROOT / str(setting('UKB_PROVIDERS_FILE', 'config/providers.json'))
    try:
        items = json.loads(raw) if raw else json.loads(path.read_text()) if path.exists() else default
        if not isinstance(items, list) or not items:
            raise ValueError
        for item in items:
            if not item['models'] or item['default_model'] not in item['models']:
                raise ValueError
    except (ValueError, KeyError, TypeError):
        raise ServiceError('Invalid administrator model provider configuration.') from None
    from urllib.parse import urlparse
    for item in items:
        url = urlparse(item['base_url'])
        if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ServiceError('A model provider has an invalid administrator configuration.')
        if item['api'] not in {'responses', 'chat_completions'}:
            raise ServiceError('Unsupported provider API configuration.')
    return items
