"""Bounded, safe microSD tree operations and their focused UI controller."""
import os

MAX_ITEMS = 50
MAX_DEPTH = 3


class SDCardError(RuntimeError):
    pass


def _join(root, name):
    return root.rstrip("/") + "/" + name


def _directory(path):
    # CircuitPython's stat module is intentionally small; FAT directories use
    # the POSIX directory bit just like CPython.
    return bool(os.stat(path)[0] & 0x4000)


def safe_path(root, path):
    """Return path only if it names a descendant of root, never root itself."""
    root = root.rstrip("/") or "/"
    if not isinstance(path, str) or not path.startswith(root + "/"):
        raise ValueError("path is outside SD root")
    relative = path[len(root) + 1:]
    if not relative or "/" in relative and any(part in ("", ".", "..") for part in relative.split("/")):
        raise ValueError("invalid SD path")
    if relative in (".", "..") or ".." in relative.split("/"):
        raise ValueError("invalid SD path")
    return path


def build_tree(root):
    """Build deterministic display rows without descending beyond MAX_DEPTH."""
    rows, count, overflow = [], [0], [False]

    def visit(directory, depth):
        try:
            names = os.listdir(directory)
        except OSError as problem:
            raise SDCardError("SD card unavailable") from problem
        entries = []
        for name in names:
            path = _join(directory, name)
            try:
                entries.append((name, path, _directory(path)))
            except OSError as problem:
                raise SDCardError("SD card unavailable") from problem
        entries.sort(key=lambda entry: (not entry[2], entry[0].lower(), entry[0]))
        for name, path, is_dir in entries:
            if count[0] >= MAX_ITEMS:
                overflow[0] = True
                return False
            rows.append({"text": "  " * (depth - 1) + ("[D] " if is_dir else "    ") + name,
                         "path": path, "directory": is_dir, "focusable": True})
            count[0] += 1
            if is_dir:
                if depth >= MAX_DEPTH:
                    try:
                        has_children = bool(os.listdir(path))
                    except OSError as problem:
                        raise SDCardError("SD card unavailable") from problem
                    if has_children:
                        rows.append({"text": "  " * depth + "... lower levels trimmed ...", "focusable": False})
                elif not visit(path, depth + 1):
                    return False
        return True

    visit(root, 1)
    if overflow[0]: rows.append({"text": "... other items not shown ...", "focusable": False})
    return rows


def remove_tree(root, path):
    """Recursively remove one validated SD descendant, never the SD root."""
    path = safe_path(root, path)
    try:
        if _directory(path):
            for name in os.listdir(path):
                remove_tree(root, _join(path, name))
            os.rmdir(path)
        else:
            os.remove(path)
    except OSError as problem:
        raise SDCardError("SD card unavailable") from problem


class SDManager:
    """Stateful focus/modal handling shared by the device and simulator."""
    def __init__(self, root, available):
        self.root, self.available = root, available
        self.rows, self.focus, self.modal = [], 0, False
        self.refresh()

    def refresh(self, preferred_path=None):
        self._check_available()
        self.rows = build_tree(self.root)
        focusable = self.focusable()
        if not focusable:
            self.focus = 0
            return
        if preferred_path:
            for index in focusable:
                if self.rows[index].get("path") >= preferred_path:
                    self.focus = index
                    return
        self.focus = min(self.focus if self.focus in focusable else focusable[0], focusable[-1])

    def focusable(self):
        return [index for index, row in enumerate(self.rows) if row.get("focusable")]

    def _check_available(self):
        if not self.available(): raise SDCardError("SD card unavailable")
        try:
            if not _directory(self.root): raise SDCardError("SD root is not a directory")
        except OSError as problem:
            raise SDCardError("SD card unavailable") from problem

    def selected(self):
        if self.focus in self.focusable(): return self.rows[self.focus]
        return None

    def move(self, step):
        items = self.focusable()
        if not items: return
        try: position = items.index(self.focus)
        except ValueError: position = 0
        self.focus = items[(position + step) % len(items)]

    def button(self, name):
        self._check_available()
        if self.modal:
            if name == "left": self.modal = False; return "render"
            if name in ("confirm", "button_2"):
                selected = self.selected()
                self.modal = False
                if selected:
                    path = selected["path"]
                    remove_tree(self.root, path)
                    self.refresh(path)
                return "render"
            return "render"
        if name in ("up", "side_up", "button_3"): self.move(-1); return "render"
        if name in ("down", "side_down", "button_4"): self.move(1); return "render"
        if name in ("confirm", "button_2") and self.selected(): self.modal = True; return "render"
        if name == "left": return "back"
        return "render"
