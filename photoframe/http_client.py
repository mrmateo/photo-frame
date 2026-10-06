"""HTTP policy shared by services; each client owns its own session."""
from __future__ import annotations

from concurrent.futures import CancelledError
from threading import Event

import requests

TRANSIENT_STATUS_CODES = {408, 429, 500, 502, 503, 504}


class HttpClient:
    def __init__(self, *, timeout: float = 10, attempts: int = 3, backoff: float = 1.5,
                 cancel_event: Event | None = None, session: requests.Session | None = None) -> None:
        if timeout <= 0 or attempts < 1 or backoff < 0:
            raise ValueError('HTTP timeout/attempts must be positive; backoff must be nonnegative.')
        self.timeout = timeout
        self.attempts = attempts
        self.backoff = backoff
        self.cancel_event = cancel_event if cancel_event is not None else Event()
        self.session = session if session is not None else requests.Session()

    def check_cancelled(self) -> None:
        if self.cancel_event.is_set():
            raise CancelledError('Operation cancelled.')

    def request(self, method: str, url: str, *, retry: bool | None = None, **kwargs) -> requests.Response:
        # POST is only retried when the caller explicitly identifies a read-only query.
        retry = method.upper() in {'GET', 'HEAD'} if retry is None else retry
        attempts = self.attempts if retry else 1
        kwargs.setdefault('timeout', self.timeout)
        for attempt in range(attempts):
            self.check_cancelled()
            response = None
            try:
                response = self.session.request(method, url, **kwargs)
                self.check_cancelled()
                response.raise_for_status()
                return response
            except CancelledError:
                if response is not None:
                    response.close()
                raise
            except requests.RequestException as error:
                transient = (isinstance(error, (requests.Timeout, requests.ConnectionError))
                             or (response is not None and response.status_code in TRANSIENT_STATUS_CODES))
                if response is not None:
                    response.close()
                if not transient or attempt == attempts - 1:
                    raise
                delay = self.backoff ** attempt if self.backoff else 0
                if self.cancel_event.wait(delay):
                    self.check_cancelled()
        raise AssertionError('Request loop must return or raise.')

    def close(self) -> None:
        self.session.close()
