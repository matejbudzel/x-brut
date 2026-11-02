"""Opt-in portrait/input checkpoint. The validation browser stays the default."""
import sys
import time
sys.path.insert(0, "/base")
from ui import BaseUI
from xbrut_storage import mount_sd
from xbrut_hardware import X4Platform
from xbrut_boot import BootController
from xbrut_library import Library
from xbrut_runtime import Runtime
from xbrut_input import Input, Actions
from xbrut_lifecycle import Lifecycle, Device
from xbrut_log import error


def create_runtime():
    """Build the same application graph used by boot and hardware checks."""
    platform = X4Platform()
    mount_sd()
    ui = BaseUI(platform, deferred=True)
    controller = BootController(ui, project_loader=Library)
    controller.start()

    def action(name):
        # Reader and OTA handoffs are later migration milestones.
        error("boot", "unsupported action " + name)
        controller.unavailable(name)

    try:
        controls = Actions(Input(platform.hardware))
    except (OSError, ValueError, KeyError) as problem:
        error("input", "calibration unavailable: %r" % problem)
        ui.show("input_error", "BUTTON SETUP REQUIRED", ["RUN THE VALIDATION BROWSER"])
        if platform.ready(): ui.render_pending()
        return
    lifecycle = Lifecycle(controller, Device(platform), released=controls.released)
    return Runtime(controller, platform, controls, on_action=action, lifecycle=lifecycle)


def main():
    runtime = create_runtime()
    if runtime is None:
        return
    try:
        while True:
            runtime.step()
            if runtime.display_error is not None:
                print("X Brut display stopped:", repr(runtime.display_error))
                return
            time.sleep_ms(10)
    finally:
        runtime.controller.stop_web(force=True)


if __name__ == "__main__":
    main()
