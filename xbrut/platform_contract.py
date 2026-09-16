"""Desktop-only typing contract for portable X Brut platform services.

Device modules deliberately do not import this module.  Keeping the Protocol on
the development side avoids adding ``typing`` (or annotation objects) to the
CircuitPython runtime while Pyright still checks both platform implementations.

X4-only orchestration hooks such as ``button``, ``present_file``, ``socket_pool``
and ``ap_address`` are intentionally outside this contract.  Portable UI,
download, and project code only relies on the services below.
"""

from collections.abc import Callable
from typing import Protocol


Progress = Callable[[int], None]


class PlatformContract(Protocol):
    """Services shared by the real X4 and desktop simulator platforms."""

    def clear(self) -> None: ...

    def pixel(self, x: int, y: int, on: bool = True) -> None: ...

    def present(self, packed: bytes) -> None: ...

    def refresh(self) -> None: ...

    def sleep(self) -> None: ...

    def connect(self, ssid: str, password: str) -> None: ...

    def disconnect(self) -> None: ...

    def json(self, url: str) -> dict[str, object]: ...

    def bytes(self, url: str, progress: Progress | None = None) -> bytes: ...

    def start_ap(self, conf: dict[str, str]) -> None: ...
