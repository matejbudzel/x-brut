"""Device orchestration; a damaged project never prevents the settings UI."""
import supervisor, time
from xbrut_storage import read_json
from xbrut_log import configure, debug, error as log_error, exception as log_exception, info, safe_url
from xbrut_paths import BASE_CONFIG_PATH, SPLASH_PATH
from ui import BaseUI
from ota import OTA
from navigation import Navigation


def _load_project():
    debug("boot", "project load begin")
    for name in ("project", "project_bak"):
        try:
            if name == "project_bak":
                # CircuitPython import uses .py names; copy backup fallback into module namespace.
                namespace = {}; exec(open("/project.py.bak").read(), namespace)
                info("boot", "loaded project backup")
                return type("Project", (), namespace)
            project = __import__(name)
            info("boot", "loaded project module=%s" % name)
            return project
        except Exception as problem:
            log_error("boot", "project %s failed: %r" % (name, problem))
    log_error("boot", "no project available")
    return None


def _run():
    conf = read_json(BASE_CONFIG_PATH, {}) or {}
    configure(conf)
    info("boot", "run begin log_level=%s" % conf.get("log_level", "debug"))
    from hardware import X4Platform
    debug("boot", "constructing platform")
    platform = X4Platform()
    project = _load_project()
    ui = BaseUI(platform)
    navigation = Navigation("home")
    splash_loaded = False
    try:
        debug("boot", "loading cached splash")
        platform.present_file(SPLASH_PATH)
        splash_loaded = True
        info("boot", "cached splash displayed")
    except (OSError, ValueError) as problem:
        debug("boot", "cached splash unavailable: %r" % problem)
    if not splash_loaded:
        debug("boot", "displaying fallback splash")
        ui.splash(getattr(project, "PROJECT_NAME", ""))
    time.sleep(1)
    debug("boot", "displaying home")
    ui.home(project)
    # A project may draw its home screen but base always intercepts left/settings and power.
    if project and hasattr(project, "main"):
        try:
            info("boot", "project main begin")
            project.main(platform)
            info("boot", "project main returned")
        except Exception as problem: log_error("boot", "project main failed: %r" % problem)
    info("boot", "entering base event loop")
    while True:
        button = platform.button()
        if button == "power":
            info("boot", "power action begin")
            try:
                ui.splash(getattr(project, "PROJECT_NAME", ""))
                debug("boot", "sleep screen displayed; calling platform.sleep")
                platform.sleep()
                info("boot", "platform.sleep returned; displaying home")
                ui.home(project)
                info("boot", "power action complete")
            except Exception as problem:
                log_error("boot", "power action failed: %r" % problem)
                raise
        elif button == "left":
            debug("boot", "left action page=%s" % ui.page)
            if navigation.route == "home":
                navigation.push("settings", {"focus": 0})
                ui.settings(project)
            else:
                _back(navigation, ui, project)
        elif ui.page == "settings" and button:
            result = ui.button(button)
            debug("boot", "settings result=%s" % result)
            if result == "ota":
                navigation.update(focus=ui.focus); navigation.push("ota")
                _ota_screen(navigation, ui, platform, project)
            elif result == "splash":
                navigation.update(focus=ui.focus); navigation.push("splash")
                _splash_screen(navigation, ui, platform, project)
            elif result == "ap":
                navigation.update(focus=ui.focus); navigation.push("ap")
                _ap_screen(navigation, ui, platform, project)
            elif result and result.startswith("document:"):
                navigation.update(focus=ui.focus); navigation.push("document", {"index": int(result.split(":", 1)[1])})
                _document_screen(navigation, ui, platform, project, navigation.state["index"])
        time.sleep(0.05)


def run():
    try: _run()
    except Exception as problem:
        log_exception("boot", "fatal base failure", problem)
        raise


def _back(navigation, ui, project):
    """Apply the one universal Back policy and restore parent route state."""
    entry = navigation.back()
    if entry is None:
        return
    if entry["route"] == "settings":
        ui.settings(project, focus=entry["state"].get("focus", 0))
    else:
        ui.home(project)


def _ota_screen(navigation, ui, platform, project):
    info("boot", "OTA screen enter")
    back_only = ("Back", "", "", "")
    start_download = ("Back", "Start", "", "")
    no_sides = ("", "")
    conf = read_json(BASE_CONFIG_PATH, {}) or {}
    if not conf.get("manifest_url"):
        info("boot", "OTA unavailable: no manifest URL")
        ui.show("ota", "OTA", ["NO SOURCE URL PROVIDED.", "CONFIGURE ONE VIA AP MODE."], bottom_labels=back_only, side_labels=no_sides)
        while platform.button() != "left": time.sleep(0.05)
        _back(navigation, ui, project)
        return
    ui.show("ota", "OTA", ["- FETCHING MANIFEST -"], bottom_labels=back_only, side_labels=no_sides)
    try:
        if not conf.get("wifi_ssid") or not conf.get("wifi_password"): raise RuntimeError("NO_WIFI")
        debug("boot", "OTA connecting wifi")
        platform.connect(conf["wifi_ssid"], conf["wifi_password"])
        manifest = OTA(platform).manifest(conf["manifest_url"])
        ui.show("ota", "OTA", ["UPDATE AVAILABLE"], [("DOWNLOAD", "download")], start_download, no_sides)
        can_download = True
        while True:
            button = platform.button()
            if button == "left":
                info("boot", "OTA screen exit before download")
                platform.disconnect()
                _back(navigation, ui, project)
                return
            if button in ("confirm", "button_2") and can_download:
                try:
                    info("boot", "OTA install requested")
                    def progress(line): ui.show("ota", "OTA", [line], bottom_labels=back_only, side_labels=no_sides)
                    OTA(platform).install(manifest, progress)
                    ui.show("ota", "OTA", ["DONE"], bottom_labels=back_only, side_labels=no_sides)
                    info("boot", "OTA install complete")
                except Exception as problem:
                    log_error("boot", "update failed: %r" % problem); ui.show("ota", "OTA", ["- FETCH FAILED -"], bottom_labels=back_only, side_labels=no_sides)
                can_download = False
            time.sleep(0.05)
    except RuntimeError as problem:
        log_error("boot", "OTA runtime failure: %r" % problem)
        message = "- NO WIFI AVAILABLE -" if str(problem) == "NO_WIFI" else "- INCORRECT WIFI PASSWORD -"; ui.show("ota", "OTA", [message], bottom_labels=back_only, side_labels=no_sides)
    except Exception as problem: log_error("boot", "manifest failed: %r" % problem); ui.show("ota", "OTA", ["- MANIFEST NOT AVAILABLE -"], bottom_labels=back_only, side_labels=no_sides)
    while True:
        if platform.button() == "left": break
        time.sleep(0.05)
    platform.disconnect()
    _back(navigation, ui, project)
    info("boot", "OTA screen exit")


def _splash_screen(navigation, ui, platform, project):
    info("boot", "splash update screen enter")
    back_only, start = ("Back", "", "", ""), ("Back", "Start", "", "")
    conf = read_json(BASE_CONFIG_PATH, {}) or {}
    if not conf.get("splash_url"):
        info("boot", "splash update unavailable: no URL")
        ui.show("splash_update", "SPLASH SCREEN", ["NO SOURCE URL PROVIDED.", "CONFIGURE ONE VIA AP MODE."], bottom_labels=back_only, side_labels=("", ""))
        while platform.button() != "left": time.sleep(0.05)
        _back(navigation, ui, project)
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
                info("boot", "splash update exit")
                platform.disconnect(); _back(navigation, ui, project); return
            if button in ("confirm", "button_2") and ready:
                try:
                    info("boot", "splash download requested")
                    OTA(platform).download_splash(conf["splash_url"])
                    ui.show("splash_update", "SPLASH SCREEN", ["SPLASH SCREEN REPLACED"], bottom_labels=("Back", "Preview", "", "Revert"), side_labels=("", ""))
                    ready = False
                except ValueError as problem:
                    log_error("boot", "splash validation failed: %r" % problem)
                    message = "UNSUPPORTED FORMAT" if str(problem) == "UNSUPPORTED_FORMAT" else "- FETCH FAILED -"
                    ui.show("splash_update", "SPLASH SCREEN", [message], [("DOWNLOAD", "download")], start, ("", ""))
                except Exception as problem:
                    log_error("boot", "splash failed: %r" % problem); ui.show("splash_update", "SPLASH SCREEN", ["- FETCH FAILED -"], [("DOWNLOAD", "download")], start, ("", ""))
            elif not ready and button in ("confirm", "button_2"):
                debug("boot", "splash preview requested")
                try:
                    platform.present_file(SPLASH_PATH)
                except OSError as problem:
                    debug("boot", "splash preview fallback: %r" % problem); ui.splash("")
                while not platform.button(): time.sleep(0.05)
                ui.show("splash_update", "SPLASH SCREEN", ["SPLASH SCREEN REPLACED"], bottom_labels=("Back", "Preview", "", "Revert"), side_labels=("", ""))
            elif not ready and button == "button_4":
                info("boot", "splash revert requested")
                OTA.revert_splash(); ui.show("splash_update", "SPLASH SCREEN", ["SPLASH REVERTED"], bottom_labels=back_only, side_labels=("", "")); ready = False
            time.sleep(0.05)
    except RuntimeError as problem:
        log_error("boot", "splash runtime failure: %r" % problem)
        message = "- NO WIFI AVAILABLE -" if str(problem) == "NO_WIFI" else "- INCORRECT WIFI PASSWORD -"; ui.show("splash_update", "SPLASH SCREEN", [message], bottom_labels=back_only, side_labels=("", ""))
    except Exception as problem:
        log_error("boot", "splash manifest failed: %r" % problem); ui.show("splash_update", "SPLASH SCREEN", ["- FETCH FAILED -"], bottom_labels=back_only, side_labels=("", ""))
    while platform.button() != "left": time.sleep(0.05)
    platform.disconnect(); _back(navigation, ui, project)
    info("boot", "splash update screen exit")

def _ap_screen(navigation, ui, platform, project):
    info("boot", "AP screen enter")
    from ap import start
    conf, server = start(platform)
    ui.show(
        "ap", "AP MODE",
        [("SSID: ", conf.get("ap_ssid", "X-BRUT")), ("PWD: ", conf.get("ap_password", "")), "VISIT HTTP://192.168.4.1"],
        bottom_labels=("Exit", "", "", ""), side_labels=("", ""),
    )
    while True:
        try: server.poll()
        except OSError as problem: debug("boot", "AP poll ignored: %r" % problem)
        if platform.button() == "left": break
        time.sleep(0.02)
    platform.disconnect()
    _back(navigation, ui, project)
    info("boot", "AP screen exit")


def _document_screen(navigation, ui, platform, project, index):
    url = project.config()["document_urls"][index]
    info("boot", "document screen enter index=%d url=%s" % (index, safe_url(url)))
    ui.show("document", "DOWNLOAD", ["DOWNLOAD", project.short_url(url)], [("DOWNLOAD", "download")], ("Back", "Start", "", ""), ("", ""))
    while True:
        button = platform.button()
        if button == "left": info("boot", "document screen exit"); _back(navigation, ui, project); return
        if button in ("confirm", "button_2"):
            try:
                info("boot", "document download begin index=%d" % index)
                ui.show("document", "DOWNLOAD", ["DOWNLOADING..."])
                document_info = project.download(platform, index)
                ui.show("document", "DOWNLOAD", [("Title: ", document_info.get("title") or "-"), ("Author: ", document_info.get("author") or "-")], bottom_labels=("Back", "Read", "", ""), side_labels=("", ""))
                debug("boot", "document download complete index=%d" % index)
            except Exception as problem:
                log_error("boot", "document failed: %r" % problem); ui.show("document", "DOWNLOAD", ["- FETCH FAILED -"])
        time.sleep(0.05)
