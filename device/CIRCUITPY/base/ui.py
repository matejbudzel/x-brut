from framebuffer import Framebuffer
from __init__ import BASE_VERSION
from xbrut_log import debug, info

CONTENT_X = 18


class BaseUI:
    """Reusable base screen template and deterministic button navigation."""
    def __init__(self, platform):
        self.platform, self.frame, self.page, self.focus = platform, Framebuffer(platform), "home", 0
        self.lines, self.actions = [], []
        self.title = "xBrut"
        self.bottom_labels, self.side_labels = ("", "", "", ""), ("", "")
        self.read_only = False
        debug("ui", "BaseUI initialized")

    def show(self, page, title, lines=(), actions=(), bottom_labels=("Back", "Open", "v", "v"), side_labels=("v", "v"), focus=0):
        info("ui", "show page=%s title=%s focus=%d lines=%d actions=%d" % (page, title, focus, len(lines), len(actions)))
        self.page, self.title, self.focus, self.lines, self.actions = page, title, focus, list(lines), list(actions)
        self.bottom_labels, self.side_labels = bottom_labels, side_labels
        self.frame.clear(); self.frame.text(CONTENT_X, 22, title, 2)
        y = 82
        for line in self.lines:
            if isinstance(line, tuple):
                label, value = line
                self.frame.text_bold(CONTENT_X, y, label)
                self.frame.text(CONTENT_X + len(label) * 8, y, value)
            else:
                self.frame.text(CONTENT_X, y, line)
            y += 28
        y = 82 + (len(self.lines) + 1) * 28
        document_gap = True
        for index, action in enumerate(self.actions):
            if action[1] == "section":
                y += 20
                self.frame.text_bold(CONTENT_X, y, "[ " + action[0] + " ]")
                y += 28
                document_gap = False
                continue
            if document_gap and action[1].startswith("document:"):
                y += 20
                document_gap = False
            if index == self.focus: self.frame.outline(CONTENT_X, y - 5, 480 - CONTENT_X, 26); self.frame.text(CONTENT_X + 4, y, action[0], 1)
            else: self.frame.text(CONTENT_X + 4, y, action[0], 1)
            y += 28
        self._battery(); self._labels(); self.platform.refresh()
        debug("ui", "show complete page=%s" % page)

    def splash(self, project_name=""):
        """Fallback splash when no downloaded raw splash is installed."""
        info("ui", "show sleeping splash project=%s" % (project_name or "-"))
        self.page, self.actions, self.lines = "splash", [], []
        self.frame.clear()
        # Sweet16 Mono is eight pixels wide per glyph. Keep title/name centered
        # as a single visual block even when only the default xBrut is shown.
        if project_name:
            title_scale, name_scale = 2, 3
            title_x = (480 - len("xBrut") * 8 * title_scale) // 2
            name_x = (480 - len(project_name) * 8 * name_scale) // 2
            self.frame.text(title_x, 320, "xBrut", title_scale)
            self.frame.text(name_x, 360, project_name, name_scale)
        else:
            title_scale = 4
            title_x = (480 - len("xBrut") * 8 * title_scale) // 2
            self.frame.text(title_x, 350, "xBrut", title_scale)
        self.frame.text(16, 770, "sleeping...")
        self.platform.refresh()
        debug("ui", "sleeping splash refresh complete")

    def home(self, project=None):
        debug("ui", "home requested project=%s" % getattr(project, "PROJECT_NAME", "none"))
        project_label = getattr(project, "HOME_ACTION_LABEL", "") if project else ""
        title = getattr(project, "PROJECT_NAME", "xBrut") if project else "xBrut"
        lines = ["NO SD CARD - READ ONLY"] if self.read_only else ["READY"]
        self.show("home", title, lines, bottom_labels=("Settings", project_label, "", ""), side_labels=("", ""))

    def _label_centered(self, center, y, label, rotated=False):
        if label:
            x = center - len(label) * 4
            if rotated: self.frame.text_rotated_180(x + (len(label) - 1) * 8, y, label)
            else: self.frame.text(x, y, label)

    def _battery(self):
        """Three-cell indicator; <10% intentionally renders as empty."""
        if not hasattr(self.platform, "battery_status"): return
        try: percent, charging = self.platform.battery_status()
        except Exception: return
        cells = 0 if percent < 10 else min(3, (percent + 32) // 33)
        if charging:
            self.frame.text(394, 18, "*>")
        for index in range(3):
            x, y = 414 + index * 20, 18
            self.frame.outline(x, y, 14, 14)
            if index < cells: self.frame.rect(x + 3, y + 3, 8, 8)

    def _labels(self):
        """Place legends in the X4's four footer zones and two side zones."""
        for index, label in enumerate(self.bottom_labels):
            self._label_centered(60 + 120 * index, 770, label, rotated=(index == 2 and label == "v"))
        for index, x in enumerate((120, 240, 360)):
            if self.bottom_labels[index] and self.bottom_labels[index + 1]: self.frame.pixel(x, 778)
        # The side pair is indicated only by its separator dot, not a border.
        if self.side_labels[0] and self.side_labels[1]: self.frame.pixel(470, 400)
        self._label_centered(470, 372, self.side_labels[0], rotated=(self.side_labels[0] == "v"))
        self._label_centered(470, 412, self.side_labels[1])

    def settings(self, project, focus=0, sd_status=""):
        info("ui", "settings requested focus=%d" % focus)
        name = getattr(project, "PROJECT_NAME", "- NO PROJECT INSTALLED -") if project else "- NO PROJECT INSTALLED -"
        version = getattr(project, "PROJECT_VERSION", "") if project else ""
        lines = [("Base version: ", BASE_VERSION), ("Project: ", name)]
        if version: lines.append(("Project version: ", version))
        if self.read_only: lines.append("NO SD CARD - DOWNLOADS DISABLED")
        if hasattr(self.platform, "battery_status"):
            try: lines.append(("Battery: ", "%d%%" % self.platform.battery_status()[0]))
            except Exception: pass
        actions = [("CHECK OTA", "ota"), ("UPDATE SPLASH SCREEN", "splash"), ("AP MODE", "ap")]
        if project and hasattr(project, "config"):
            urls = project.config().get("document_urls", [])
            if urls:
                actions.append((project.PROJECT_NAME, "section"))
                for index, url in enumerate(urls): actions.append((project.short_url(url), "document:%d" % index))
        actions.append(("Device", "section"))
        if not self.read_only: actions.append(("MANAGE SD CARD", "manage_sd"))
        actions.extend([("SOFT RELOAD", "soft_reload"), ("HARD RELOAD", "hard_reload"), ("SLEEP", "sleep")])
        if sd_status: lines.append(("SD Card: ", sd_status))
        selected = actions[focus][1] if 0 <= focus < len(actions) else ""
        verb = "Do" if selected in ("soft_reload", "hard_reload", "sleep") else "Open"
        self.show("settings", "SETTINGS", lines, actions, bottom_labels=("Back", verb, "v", "v"), focus=focus)

    def button(self, name):
        debug("ui", "button name=%s page=%s focus=%d" % (name, self.page, self.focus))
        if name == "left": return "back"
        if name in ("up", "side_up", "button_3") and self.actions:
            self.focus = (self.focus - 1) % len(self.actions)
            while self.actions[self.focus][1] == "section": self.focus = (self.focus - 1) % len(self.actions)
        elif name in ("down", "side_down", "button_4") and self.actions:
            self.focus = (self.focus + 1) % len(self.actions)
            while self.actions[self.focus][1] == "section": self.focus = (self.focus + 1) % len(self.actions)
        elif name in ("confirm", "button_2") and self.actions and self.actions[self.focus][1] != "section":
            result = self.actions[self.focus][1]
            info("ui", "button action=%s" % result)
            return result
        if self.page == "settings":
            selected = self.actions[self.focus][1] if self.actions else ""
            verb = "Do" if selected in ("soft_reload", "hard_reload", "sleep") else "Open"
            self.bottom_labels = ("Back", verb, "v", "v")
        self.show(
            self.page, self.title, self.lines, self.actions,
            self.bottom_labels, self.side_labels, self.focus,
        )

    def sd_manager(self, manager):
        """Render the compact scrollable SD tree without generic action rows."""
        self.page, self.title = "sd_manager", "SD CARD"
        self.frame.clear(); self.frame.text(CONTENT_X, 22, self.title, 2)
        rows, focus, visible = manager.rows, manager.focus, 21
        start = max(0, min(focus - visible // 2, max(0, len(rows) - visible)))
        for offset, row in enumerate(rows[start:start + visible]):
            y, index = 82 + offset * 28, start + offset
            if index == focus and row.get("focusable"):
                self.frame.outline(CONTENT_X, y - 5, 480 - CONTENT_X - 12, 26)
            self.frame.text(CONTENT_X + 4, y, row["text"][:54], 1)
        if len(rows) > visible:
            height = max(12, visible * 28 * visible // len(rows))
            top = 82 + (visible * 28 - height) * start // max(1, len(rows) - visible)
            self.frame.rect(468, top, 5, height)
        if manager.modal:
            selected = manager.selected()
            self.frame.rect(30, 315, 420, 150, False); self.frame.outline(30, 315, 420, 150)
            self.frame.text(52, 340, "DELETE?", 2)
            self.frame.text(52, 385, (selected or {}).get("text", "")[:45])
            self.frame.text(52, 420, "BACK CANCELS / DELETE CONFIRMS")
            self.bottom_labels, self.side_labels = ("Back", "Delete", "", ""), ("", "")
        else:
            self.bottom_labels, self.side_labels = ("Back", "Delete", "v", "v"), ("", "")
        self._battery(); self._labels(); self.platform.refresh()
