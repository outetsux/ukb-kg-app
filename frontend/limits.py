"""Shared process limits for provider calls, without storing keys or prompts."""
from collections import defaultdict, deque
from contextlib import contextmanager
import threading
import time
import uuid
import streamlit as st


class ModelGate:
    def __init__(self):
        self.lock = threading.Lock()
        self.active = 0
        self.events = defaultdict(deque)

    @contextmanager
    def enter(self, session):
        with self.lock:
            now = time.monotonic()
            for name in list(self.events):
                while self.events[name] and self.events[name][0] <= now - 60:
                    self.events[name].popleft()
                if not self.events[name]:
                    del self.events[name]
            if self.active >= 2 or len(self.events['all']) >= 20 or len(self.events[session]) >= 6:
                raise ValueError('Model requests are busy. Please wait a minute and retry.')
            self.events['all'].append(now)
            self.events[session].append(now)
            self.active += 1
        try:
            yield
        finally:
            with self.lock:
                self.active -= 1


@st.cache_resource(show_spinner=False)
def model_gate():
    return ModelGate()


@contextmanager
def model_slot():
    session = st.session_state.setdefault('model_limit_session', uuid.uuid4().hex)
    with model_gate().enter(session):
        yield
