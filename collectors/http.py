"""Bounded, sequential HTTP. No browser, cookies, credentials or third-party API."""
import time
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler


class FetchError(RuntimeError):
    pass


class OfficialRedirects(HTTPRedirectHandler):
    def __init__(self, host):
        self.host = host

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlparse(newurl).hostname != self.host or urlparse(newurl).scheme != 'https':
            raise FetchError('Redirect outside configured official HTTPS host')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class HttpClient:
    def __init__(self, host, timeout=20, retries=1, delay=0.1):
        self.host, self.timeout, self.retries, self.delay = host, timeout, retries, delay
        self.opener = build_opener(OfficialRedirects(host))
        self.requests = 0

    def get(self, url):
        if urlparse(url).hostname != self.host or urlparse(url).scheme != 'https':
            raise FetchError('URL outside configured official HTTPS host')
        for attempt in range(self.retries + 1):
            if self.requests:
                time.sleep(self.delay)
            self.requests += 1
            try:
                request = Request(url, headers={'User-Agent': 'SigmaLegalSearch/0.1 (local vacancy checker)',
                                               'Accept': 'text/html', 'Cache-Control': 'no-cache'})
                with self.opener.open(request, timeout=self.timeout) as response:
                    if response.status != 200:
                        raise FetchError(f'Unexpected HTTP {response.status}: {url}')
                    if 'text/html' not in response.headers.get('Content-Type', ''):
                        raise FetchError(f'Expected HTML: {url}')
                    data = response.read(2_000_001)
                    if len(data) > 2_000_000:
                        raise FetchError(f'Page exceeds 2 MB safety limit: {url}')
                    return data.decode(response.headers.get_content_charset() or 'utf-8')
            except HTTPError as exc:
                if exc.code not in (429, 500, 502, 503, 504) or attempt == self.retries:
                    raise FetchError(f'HTTP {exc.code}: {url}') from exc
            except (URLError, TimeoutError, OSError, HTTPException, UnicodeError) as exc:
                if attempt == self.retries:
                    raise FetchError(f'{type(exc).__name__}: {exc}: {url}') from exc
            time.sleep(min(2 ** attempt, 4))
        raise FetchError(f'Unable to retrieve {url}')
