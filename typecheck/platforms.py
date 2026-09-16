"""Static-only assertions that both adapters satisfy the portable contract."""

from hardware import X4Platform
from xbrut.platform_contract import PlatformContract
from xbrut.simulator.server import Platform as SimulatorPlatform


def _accepts_platform(platform: PlatformContract) -> None:
    pass


_accepts_platform(X4Platform())
_accepts_platform(SimulatorPlatform())
