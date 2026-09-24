"""Portable base boot policy, independent of CircuitPython supervisor APIs.

The caller owns the concrete renderer and hardware loop.  This module owns
project loading, route history, and the meaning of base-level button actions.
"""
import gc

from navigation import Navigation
from xbrut_log import configure, debug, error as log_error, info
from xbrut_paths import BASE_CONFIG_PATH
from xbrut_storage import read_json, sd_available, sd_card_status


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
    def __init__(self, ui, project_loader=load_project):
        self.ui = ui
        self.project_loader = project_loader
        self.project = None
        self.navigation = Navigation("home")

    def start(self):
        conf = read_json(BASE_CONFIG_PATH, {}) or {}
        conf.setdefault("log_level", "info")
        configure(conf)
        self.project = self.project_loader()
        self.ui.read_only = not sd_available()
        gc.collect()
        self.ui.home(self.project)
        info("boot", "base home ready")
        return self.project

    def _settings(self, focus=0):
        self.ui.settings(self.project, focus=focus, sd_status=sd_card_status())

    def _home(self):
        self.navigation.home()
        self.ui.home(self.project)

    def _back(self):
        entry = self.navigation.back()
        if entry is None:
            return
        if entry["route"] == "settings":
            self._settings(entry["state"].get("focus", 0))
        else:
            self.ui.home(self.project, entry["state"].get("focus", 0))

    def handle(self, button):
        """Apply one normalized button event and return an external action.

        Return values such as ``sleep``, ``ota``, and ``sd_manager`` are
        deliberately executed by the platform-specific loop, not here.
        """
        if not button:
            return None
        if button == "power":
            return "sleep"
        if button == "left_long":
            self._home()
            return "render"
        if button == "left":
            if self.navigation.route == "home":
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
        if result in ("ota", "splash", "ap", "download_all", "manage_sd"):
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
