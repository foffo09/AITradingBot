"""Bounded HTTP transport for the pinned Alpaca SDK; no cross-provider fallback."""
from urllib.parse import urlsplit

from requests import Session


class AlpacaSession(Session):
    def __init__(self, host: str, *, read_only: bool):
        super().__init__()
        self.trust_env = False  # Do not load personal netrc credentials or implicit proxies.
        self.host = host
        self.read_only = read_only

    def request(self, method, url, **kwargs):
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or parsed.netloc != self.host:
            raise ValueError('Unexpected Alpaca destination; request blocked.')
        if self.read_only and method.upper() not in {'GET', 'HEAD'}:
            raise ValueError('Alpaca market-data transport is read-only.')
        kwargs['timeout'] = (3.05, 10.0)
        kwargs['allow_redirects'] = False
        response = super().request(method, url, **kwargs)
        if 300 <= response.status_code < 400:
            response.close()
            raise ValueError('Alpaca redirect blocked.')
        return response
