"""Used API from Adafruit_CircuitPython_Requests 4.1.17."""

from collections.abc import Iterator, Mapping

import socketpool


class Response:
    headers: Mapping[str, str]

    def iter_content(
        self, chunk_size: int = 1, decode_unicode: bool = False
    ) -> Iterator[bytes]: ...

    def close(self) -> None: ...


class Session:
    def __init__(
        self,
        socket_pool: socketpool.SocketPool,
        ssl_context: object | None = None,
        session_id: str | None = None,
    ) -> None: ...

    def get(
        self,
        url: str,
        *,
        data: object | None = None,
        json: object | None = None,
        headers: dict[str, str] | None = None,
        stream: bool = False,
        timeout: float = 60,
        allow_redirects: bool = True,
        files: dict[str, tuple[object, ...]] | None = None,
    ) -> Response: ...
