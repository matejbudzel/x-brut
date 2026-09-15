"""Device orchestration; a damaged project never prevents the settings UI."""
import supervisor, time
from storage import read_json, append_log
from ui import BaseUI
from ota import OTA


def _load_project():
    for name in ("project", "project_bak"):
        try:
            if name == "project_bak":
                # CircuitPython import uses .py names; copy backup fallback into module namespace.
                namespace = {}; exec(open("/project.py.bak").read(), namespace); return type("Project", (), namespace)
            return __import__(name)
        except Exception as error:
            append_log("project %s failed: %r" % (name, error))
    return None


def run():
    from hardware import X4Platform
    platform, project = X4Platform(), _load_project()
    ui = BaseUI(platform)
    splash_loaded = False
    try:
        with open("/splash.bin", "rb") as handle:
            splash = handle.read()
        if len(splash) == 48000: platform.present(splash); splash_loaded = True
    except OSError: pass
    if not splash_loaded: ui.splash(getattr(project, "PROJECT_NAME", ""))
    time.sleep(1)
    ui.home(project)
    # A project may draw its home screen but base always intercepts left/settings and power.
    if project and hasattr(project, "main"):
        try: project.main(platform)
        except Exception as error: append_log("project main failed: %r" % error)
    while True:
        button = platform.button()
        if button == "power":
            ui.splash(getattr(project, "PROJECT_NAME", ""))
            platform.sleep()
            ui.home(project)
        elif button == "left":
            if ui.page == "home": ui.settings(project)
            else: ui.home(project)
        elif ui.page == "settings" and button:
            result = ui.button(button)
            if result == "ota": _ota_screen(ui, platform)
            elif result == "splash": _splash_screen(ui, platform)
            elif result == "ap": _ap_screen(ui, platform)
        time.sleep(0.05)


def _ota_screen(ui, platform):
    back_only = ("Back", "", "", "")
    start_download = ("Back", "Start", "", "")
    no_sides = ("", "")
    conf = read_json("/base-conf.json", {}) or {}
    if not conf.get("manifest_url"):
        ui.show("ota", "OTA", ["NO SOURCE URL PROVIDED.", "CONFIGURE ONE VIA AP MODE."], bottom_labels=back_only, side_labels=no_sides)
        while platform.button() != "left": time.sleep(0.05)
        ui.settings(_load_project())
        return
    ui.show("ota", "OTA", ["- FETCHING MANIFEST -"], bottom_labels=back_only, side_labels=no_sides)
    try:
        if not conf.get("wifi_ssid") or not conf.get("wifi_password"): raise RuntimeError("NO_WIFI")
        platform.connect(conf["wifi_ssid"], conf["wifi_password"])
        manifest = OTA(platform).manifest(conf["manifest_url"])
        ui.show("ota", "OTA", ["UPDATE AVAILABLE"], [("DOWNLOAD", "download")], start_download, no_sides)
        can_download = True
        while True:
            button = platform.button()
            if button == "left":
                platform.disconnect()
                ui.settings(_load_project())
                return
            if button in ("confirm", "button_2") and can_download:
                try:
                    def progress(line): ui.show("ota", "OTA", [line], bottom_labels=back_only, side_labels=no_sides)
                    OTA(platform).install(manifest, progress)
                    ui.show("ota", "OTA", ["DONE"], bottom_labels=back_only, side_labels=no_sides)
                except Exception as error:
                    append_log("update: %r" % error); ui.show("ota", "OTA", ["- FETCH FAILED -"], bottom_labels=back_only, side_labels=no_sides)
                can_download = False
            time.sleep(0.05)
    except RuntimeError as error:
        message = "- NO WIFI AVAILABLE -" if str(error) == "NO_WIFI" else "- INCORRECT WIFI PASSWORD -"; ui.show("ota", "OTA", [message], bottom_labels=back_only, side_labels=no_sides)
    except Exception as error: append_log("manifest: %r" % error); ui.show("ota", "OTA", ["- MANIFEST NOT AVAILABLE -"], bottom_labels=back_only, side_labels=no_sides)
    while True:
        if platform.button() == "left": break
        time.sleep(0.05)
    platform.disconnect()
    ui.settings(_load_project())


def _splash_screen(ui, platform):
    back_only, start = ("Back", "", "", ""), ("Back", "Start", "", "")
    conf = read_json("/base-conf.json", {}) or {}
    if not conf.get("splash_url"):
        ui.show("splash_update", "SPLASH SCREEN", ["NO SOURCE URL PROVIDED.", "CONFIGURE ONE VIA AP MODE."], bottom_labels=back_only, side_labels=("", ""))
        while platform.button() != "left": time.sleep(0.05)
        ui.settings(_load_project(), focus=1)
        return
    ui.show("splash_update", "SPLASH SCREEN", ["- FETCHING -"], bottom_labels=back_only, side_labels=("", ""))
    try:
        if not conf.get("wifi_ssid") or not conf.get("wifi_password"): raise RuntimeError("NO_WIFI")
        platform.connect(conf["wifi_ssid"], conf["wifi_password"])
        ui.show("splash_update", "SPLASH SCREEN", ["SPLASH AVAILABLE"], [("DOWNLOAD", "download")], start, ("", ""))
        ready = True
        while True:
            button = platform.button()
            if button == "left":
                platform.disconnect(); ui.settings(_load_project(), focus=1); return
            if button in ("confirm", "button_2") and ready:
                try:
                    OTA(platform).download_splash(conf["splash_url"])
                    ui.show("splash_update", "SPLASH SCREEN", ["SPLASH SCREEN REPLACED"], bottom_labels=("Back", "Preview", "", "Revert"), side_labels=("", ""))
                    ready = False
                except ValueError as error:
                    message = "UNSUPPORTED FORMAT" if str(error) == "UNSUPPORTED_FORMAT" else "- FETCH FAILED -"
                    ui.show("splash_update", "SPLASH SCREEN", [message], [("DOWNLOAD", "download")], start, ("", ""))
                except Exception as error:
                    append_log("splash: %r" % error); ui.show("splash_update", "SPLASH SCREEN", ["- FETCH FAILED -"], [("DOWNLOAD", "download")], start, ("", ""))
            elif not ready and button in ("confirm", "button_2"):
                try:
                    with open("/splash.bin", "rb") as handle: platform.present(handle.read())
                except OSError: ui.splash("")
                while not platform.button(): time.sleep(0.05)
                ui.show("splash_update", "SPLASH SCREEN", ["SPLASH SCREEN REPLACED"], bottom_labels=("Back", "Preview", "", "Revert"), side_labels=("", ""))
            elif not ready and button == "button_4":
                OTA.revert_splash(); ui.show("splash_update", "SPLASH SCREEN", ["SPLASH REVERTED"], bottom_labels=back_only, side_labels=("", "")); ready = False
            time.sleep(0.05)
    except RuntimeError as error:
        message = "- NO WIFI AVAILABLE -" if str(error) == "NO_WIFI" else "- INCORRECT WIFI PASSWORD -"; ui.show("splash_update", "SPLASH SCREEN", [message], bottom_labels=back_only, side_labels=("", ""))
    except Exception as error:
        append_log("splash manifest: %r" % error); ui.show("splash_update", "SPLASH SCREEN", ["- FETCH FAILED -"], bottom_labels=back_only, side_labels=("", ""))
    while platform.button() != "left": time.sleep(0.05)
    platform.disconnect(); ui.settings(_load_project(), focus=1)

def _ap_screen(ui, platform):
    from ap import start
    conf, server = start(platform)
    ui.show(
        "ap", "AP MODE",
        [("SSID: ", conf.get("ap_ssid", "X-BRUT")), ("PWD: ", conf.get("ap_password", "")), "VISIT HTTP://192.168.4.1"],
        bottom_labels=("Exit", "", "", ""), side_labels=("", ""),
    )
    while True:
        try: server.poll()
        except OSError: pass
        if platform.button() == "left": break
        time.sleep(0.02)
    platform.disconnect()
    ui.settings(_load_project(), focus=2)
