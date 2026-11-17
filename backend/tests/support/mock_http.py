"""Route table for httpx2.MockTransport, shared by provider and fetcher tests.

Unmatched requests are recorded (and raise inside the transport). Because SDKs may catch
transport errors and retry, the `mock_http` fixture also fails the test at teardown if anything
went unmatched, so a missing route can never be masked as "provider unavailable".
"""

from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field

import httpx2

Handler = Callable[[httpx2.Request], httpx2.Response]
Responder = httpx2.Response | Exception


class UnmatchedRequestError(AssertionError):
    pass


@dataclass
class Route:
    method: str
    url: str
    handler: Handler | None = None
    responses: list[Responder] = field(default_factory=list)
    calls: list[httpx2.Request] = field(default_factory=list)

    @property
    def call_count(self) -> int:
        return len(self.calls)

    @property
    def last_request(self) -> httpx2.Request:
        assert self.calls, f"{self.method} {self.url} was never called"
        return self.calls[-1]

    def respond(self, request: httpx2.Request) -> httpx2.Response:
        self.calls.append(request)
        if self.handler is not None:
            return self.handler(request)
        if not self.responses:
            raise UnmatchedRequestError(f"{self.method} {self.url}: no responses left")
        responder = self.responses[0] if len(self.responses) == 1 else self.responses.pop(0)
        if isinstance(responder, Exception):
            raise responder
        return responder


class MockRouter:
    def __init__(self, base_url: str = "") -> None:
        self._base_url = base_url.rstrip("/")
        self._routes: list[Route] = []
        self.unmatched: list[str] = []

    def add(
        self,
        method: str,
        path: str,
        responses: Sequence[Responder] | Responder | None = None,
        *,
        handler: Handler | None = None,
    ) -> Route:
        """Register a route. The last of several responses repeats once the others are used."""
        if (responses is None) == (handler is None):
            raise ValueError("Pass exactly one of `responses` or `handler`.")
        if isinstance(responses, httpx2.Response | Exception):
            responses = [responses]
        route = Route(method.upper(), self._base_url + path, handler, list(responses or []))
        self._routes.append(route)
        return route

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        url = str(request.url).split("?", 1)[0]
        for route in self._routes:
            if route.method == request.method and route.url == url:
                return route.respond(request)
        self.unmatched.append(f"{request.method} {url}")
        raise UnmatchedRequestError(f"Unmatched request: {request.method} {url}")

    def client(self, **kwargs: object) -> httpx2.Client:
        return httpx2.Client(transport=httpx2.MockTransport(self), **kwargs)

    def assert_all_called(self) -> None:
        idle = [f"{r.method} {r.url}" for r in self._routes if not r.calls]
        assert not idle, f"Routes never called: {idle}"

    def assert_no_unmatched(self) -> None:
        assert not self.unmatched, f"Unmatched requests: {self.unmatched}"


def mock_router_fixture(base_url: str = "") -> Iterator[MockRouter]:
    router = MockRouter(base_url)
    yield router
    router.assert_no_unmatched()
