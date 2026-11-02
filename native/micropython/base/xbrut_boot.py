"""Portable base boot policy, independent of CircuitPython supervisor APIs.

The caller owns the concrete renderer and hardware loop.  This module owns
project loading, route history, and the meaning of base-level button actions.
"""
import gc

from navigation import Navigation
from xbrut_log import configure, debug, error as log_error, info
from xbrut_paths import BASE_CONFIG_PATH, DATA_ROOT


def load_project(root=""):
    """Load a project, with the same backup fallback as the CP base."""
    for name in ("project", "project_bak"):
        try:
            if name == "project_bak":
                namespace = {}
                with open(root.rstrip("/") + "/project.py.bak") as handle:
                    exec(handle.read(), namespace)
                info("boot", "loaded project backup")
                return type("Project", (), namespace)
            project = __import__(name)
            info("boot", "loaded project module=" + name)
            return project
        except Exception as problem:
            log_error("boot", "project %s failed: %r" % (name, problem))
    log_error("boot", "no project available")
    return None


class BootController:
    """Base route policy; renderer and hardware calls stay in the caller."""
    def __init__(self, ui, project_loader=load_project, storage=None, sd_root=DATA_ROOT, sd_manager_api=None, web=None):
        if storage is None:
            import xbrut_storage
            storage = xbrut_storage
        self.web, self._web_screen_state = web, None
        self.sd_root, self.sd_manager_api = sd_root, sd_manager_api
        self.manager, self._delete_ready = None, False
        self.storage = storage
        self.ui = ui
        self.project_loader = project_loader
        self.project = None
        self.navigation = Navigation("home")

    def start(self):
        conf = self.storage.read_json(BASE_CONFIG_PATH, {}) or {}
        conf.setdefault("log_level", "info")
        configure(conf)
        self.project = self.project_loader()
        self.ui.read_only = not self.storage.sd_available()
        gc.collect()
        self.ui.home(self.project)
        info("boot", "base home ready")
        return self.project

    def _settings(self, focus=0):
        self.ui.settings(self.project, focus=focus, sd_status=self.storage.sd_card_status(), web_settings=True)

    def _home(self):
        self.stop_web()
        self.navigation.home()
        self.manager, self._delete_ready = None, False
        self.ui.home(self.project)

    def _back(self):
        entry = self.navigation.back()
        if entry is None:
            return
        if entry["route"] == "settings":
            self._settings(entry["state"].get("focus", 0))
        elif entry["route"] in ("ap", "web_settings"):
            self._show_web()
        elif entry["route"] == "sd_manager" and self.manager is not None:
            self.ui.sd_manager(self.manager)
        else:
            self.ui.home(self.project, entry["state"].get("focus", 0))

    def _open_web(self, mode):
        if self.web is None:
            from xbrut_web import WebSettings
            self.web = WebSettings(self.storage)
        self.web.start(mode)
        self._show_web()

    def _show_web(self):
        title, lines = self.web.screen()
        self._web_screen_state = (title, lines)
        self.ui.show(self.navigation.route, title, lines, bottom_labels=("Back", "", "", ""), side_labels=("", ""))

    def poll_services(self):
        if self.web is not None:
            self.web.poll()
            if self.navigation.route in ("ap", "web_settings") and self.web.screen() != self._web_screen_state:
                self._show_web()

    def stop_web(self):
        if self.web is not None:
            self.web.stop()
        self._web_screen_state = None

    def _sd_unavailable(self, problem):
        log_error("boot", "SD manager unavailable: %r" % problem)
        self.ui.read_only = True
        self._home()

    def _open_sd_manager(self):
        if self.sd_manager_api is None:
            import sd_manager
            self.sd_manager_api = sd_manager
        try:
            self.manager = self.sd_manager_api.SDManager(self.sd_root, self.storage.sd_available)
            self._delete_ready = False
            self.ui.sd_manager(self.manager)
        except self.sd_manager_api.SDCardError as problem:
            self._sd_unavailable(problem)

    def display_ready(self):
        # Called only after a submitted screen has finished presentation.
        if self.navigation.route == "sd_manager" and self.manager is not None and self.manager.modal:
            self._delete_ready = True

    def _sd_button(self, button):
        if button == "left" and not self.manager.modal:
            self.manager, self._delete_ready = None, False
            self._back()
            return "render"
        # Coalesced input must not confirm a deletion before its dialog has
        # actually completed presentation. A second quick press is ignored.
        if self.manager.modal and button in ("confirm", "button_2") and not self._delete_ready:
            return "render"
        try:
            self.manager.button(button)
            self._delete_ready = False
            self.ui.sd_manager(self.manager)
        except self.sd_manager_api.SDCardError as problem:
            self._sd_unavailable(problem)
        return "render"

    def unavailable(self, action):
        """Fallback for handoffs not implemented by the portrait checkpoint."""
        if action in ("sleep", "soft_reload", "hard_reload"):
            self.navigation.update(focus=self.ui.focus)
            self.navigation.push("unavailable")
        self.ui.show("unavailable", "UNAVAILABLE", ["PRESS BACK TO RETURN"], bottom_labels=("Back", "", "", ""))

    def handle(self, button):
        """Apply one normalized button event and return an external action.

        Return values such as ``sleep``, ``ota``, and ``download_all`` are
        deliberately executed by the platform-specific loop, not here.
        """
        if not button:
            return None
        if button == "power":
            return "sleep"
        if button == "left_long":
            self._home()
            return "render"
        if self.navigation.route == "sd_manager" and self.manager is not None:
            return self._sd_button(button)
        if button == "left":
            if self.navigation.route in ("ap", "web_settings"):
                self.stop_web()
                self._back()
                return "render"
            if self.navigation.route == "home":
                self.navigation.update(focus=self.ui.focus)
                self.navigation.push("settings", {"focus": 0})
                self._settings()
            else:
                self._back()
            return "render"
        if self.ui.page == "home":
            result = self.ui.button(button)
            if result and result.startswith("read:"):
                self.navigation.update(focus=self.ui.focus)
                self.navigation.push("viewer", {"filename": result[5:]})
                return "viewer:" + result[5:]
            return "render" if result is not None else None
        if self.ui.page != "settings":
            return "render"
        result = self.ui.button(button)
        if not result:
            return None
        if result in ("ap", "web_settings"):
            self.navigation.update(focus=self.ui.focus)
            self.navigation.push(result)
            self._open_web("ap" if result == "ap" else "station")
            return "render"
        if result == "manage_sd":
            self.navigation.update(focus=self.ui.focus)
            self.navigation.push("sd_manager")
            self._open_sd_manager()
            return "render"
        if result in ("ota", "splash", "download_all"):
            self.navigation.update(focus=self.ui.focus)
            self.navigation.push(result, {})
            return result
        if result in ("soft_reload", "hard_reload", "sleep"):
            return result
        if result.startswith("remote_docs:"):
            self.navigation.update(focus=self.ui.focus)
            self.navigation.push("remote_docs", {"index": int(result.split(":", 1)[1])})
            return result
        if result.startswith("document:"):
            self.navigation.update(focus=self.ui.focus)
            self.navigation.push("document", {"index": int(result.split(":", 1)[1])})
            return result
        debug("boot", "unhandled UI result=" + result)
        return "render"
