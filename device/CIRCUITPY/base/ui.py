from framebuffer import Framebuffer
from __init__ import BASE_VERSION

CONTENT_X = 18


class BaseUI:
    """Reusable base screen template and deterministic button navigation."""
    def __init__(self, platform):
        self.platform, self.frame, self.page, self.focus = platform, Framebuffer(platform), "home", 0
        self.lines, self.actions = [], []
        self.title = "xBrut"
        self.bottom_labels, self.side_labels = ("", "", "", ""), ("", "")

    def show(self, page, title, lines=(), actions=(), bottom_labels=("Back", "Open", "v", "v"), side_labels=("v", "v"), focus=0):
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
        self._labels(); self.platform.refresh()

    def splash(self, project_name=""):
        """Fallback splash when no downloaded raw splash is installed."""
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

    def home(self, project=None):
        project_label = getattr(project, "HOME_ACTION_LABEL", "") if project else ""
        title = getattr(project, "PROJECT_NAME", "xBrut") if project else "xBrut"
        self.show("home", title, ["READY"], bottom_labels=("Settings", project_label, "", ""), side_labels=("", ""))

    def _label_centered(self, center, y, label, rotated=False):
        if label:
            x = center - len(label) * 4
            if rotated: self.frame.text_rotated_180(x + (len(label) - 1) * 8, y, label)
            else: self.frame.text(x, y, label)

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

    def settings(self, project, focus=0):
        name = getattr(project, "PROJECT_NAME", "- NO PROJECT INSTALLED -") if project else "- NO PROJECT INSTALLED -"
        version = getattr(project, "PROJECT_VERSION", "") if project else ""
        lines = [("Base version: ", BASE_VERSION), ("Project: ", name)]
        if version: lines.append(("Project version: ", version))
        actions = [("CHECK OTA", "ota"), ("UPDATE SPLASH SCREEN", "splash"), ("AP MODE", "ap")]
        if project and hasattr(project, "config"):
            urls = project.config().get("document_urls", [])
            if urls:
                actions.append((project.PROJECT_NAME, "section"))
                for index, url in enumerate(urls): actions.append((project.short_url(url), "document:%d" % index))
        self.show("settings", "SETTINGS", lines, actions, focus=focus)

    def button(self, name):
        if name == "left": return "back"
        if name in ("up", "side_up", "button_3") and self.actions:
            self.focus = (self.focus - 1) % len(self.actions)
            while self.actions[self.focus][1] == "section": self.focus = (self.focus - 1) % len(self.actions)
        elif name in ("down", "side_down", "button_4") and self.actions:
            self.focus = (self.focus + 1) % len(self.actions)
            while self.actions[self.focus][1] == "section": self.focus = (self.focus + 1) % len(self.actions)
        elif name in ("confirm", "button_2") and self.actions and self.actions[self.focus][1] != "section": return self.actions[self.focus][1]
        self.show(
            self.page, self.title, self.lines, self.actions,
            self.bottom_labels, self.side_labels, self.focus,
        )
