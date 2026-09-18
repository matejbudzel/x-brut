"""xViewer: URL-managed XTC/XTH document library for the X Brut base."""
import os
from xbrut_storage import read_json, write_json
from xbrut_paths import BOOKMARKS_PATH, DATA_ROOT, DOCUMENTS_PATH, PROJECT_CONFIG_PATH

PROJECT_NAME = "xViewer"
PROJECT_VERSION = "0.1.0"
_ROOT = None


def set_root(path):
    """Simulator hook. Device defaults to the microSD data root."""
    global _ROOT
    _ROOT = path.rstrip("/")


def _path(path): return path if _ROOT is None else _ROOT + path[len(DATA_ROOT):]


def config():
    value = read_json(_path(PROJECT_CONFIG_PATH), {}) or {}
    value["document_urls"] = [url for url in value.get("document_urls", []) if url]
    return value


def save_urls(urls):
    value = config()
    value["document_urls"] = [url.strip() for url in urls if url and url.strip()]
    write_json(_path(PROJECT_CONFIG_PATH), value)


def bookmarks():
    value = read_json(_path(BOOKMARKS_PATH), {}) or {}
    if not isinstance(value, dict): return {}
    return {name: page for name, page in value.items() if isinstance(name, str) and isinstance(page, int) and page >= 0}


def bookmark(filename): return bookmarks().get(filename, 0)


def save_bookmark(filename, page):
    value = bookmarks()
    value[filename] = page
    write_json(_path(BOOKMARKS_PATH), value)


def clear_bookmark(filename):
    value = bookmarks()
    if filename in value:
        del value[filename]
        write_json(_path(BOOKMARKS_PATH), value)


def short_url(url, limit=42):
    """Path-only URL label; keep both ends when it needs truncation."""
    path = url.split("?", 1)[0].split("#", 1)[0]
    path = path.split("://", 1)[-1]
    path = path[path.find("/"):] if "/" in path else path
    if len(path) <= limit: return path
    half = (limit - 3) // 2
    return path[:half] + "..." + path[-(limit - 3 - half):]


def document_name(index): return "doc-%03d.xth" % index


def metadata(path):
    """Read Crosspoint's optional title/author from the 248-byte XTC header."""
    with open(path, "rb") as handle: data = handle.read(248)
    if len(data) < 22:
        raise ValueError("NOT AN XTH DOCUMENT")
    if data[:4] in (b"XTH\0", b"XTG\0"):
        return {"title": "", "author": "", "pages": 1}
    if len(data) < 56 or data[:4] not in (b"XTC\0", b"XTCH"):
        raise ValueError("NOT AN XTH DOCUMENT")
    if not data[9]: return {"title": "", "author": "", "pages": int.from_bytes(data[6:8], "little")}
    def field(start, length): return data[start:start + length].split(b"\0", 1)[0].decode("utf-8", "replace")
    return {"title": field(0x38, 127), "author": field(0xB8, 63), "pages": int.from_bytes(data[6:8], "little")}


def downloaded():
    try: names = os.listdir(_path(DOCUMENTS_PATH))
    except OSError: return []
    result = []
    for name in names:
        if name.endswith((".xtc", ".xth")):
            try: result.append((name, metadata(_path(DOCUMENTS_PATH + "/" + name))) )
            except Exception: pass
    return sorted(result)


def home(ui, focus=0):
    """Render the reader library, leaving tile drawing and focus to the base UI."""
    documents = downloaded()
    ui.document_grid(PROJECT_NAME, [(filename, info.get("title") or filename) for filename, info in documents], focus)


def page_count(path): return metadata(path)["pages"]


def _frame_header(handle, offset):
    handle.seek(offset)
    header = handle.read(22)
    if len(header) != 22 or header[:4] not in (b"XTG\0", b"XTH\0"):
        raise ValueError("INVALID PAGE")
    width, height = int.from_bytes(header[4:6], "little"), int.from_bytes(header[6:8], "little")
    data_size = int.from_bytes(header[10:14], "little")
    if width != 480 or height != 800 or header[9] != 0:
        raise ValueError("UNSUPPORTED PAGE")
    expected = 48000 if header[:4] == b"XTG\0" else 96000
    if data_size != expected: raise ValueError("INVALID PAGE")
    return header[:4], offset + 22


def render_page(platform, path, page):
    """Present one XTG/XTH page directly, without any base UI decoration."""
    with open(path, "rb") as handle:
        header = handle.read(56)
        if header[:4] in (b"XTC\0", b"XTCH"):
            pages = int.from_bytes(header[6:8], "little")
            if not 0 <= page < pages: raise ValueError("PAGE OUT OF RANGE")
            index_offset = int.from_bytes(header[24:32], "little")
            handle.seek(index_offset + page * 16)
            entry = handle.read(16)
            if len(entry) != 16: raise ValueError("INVALID PAGE INDEX")
            kind, data_offset = _frame_header(handle, int.from_bytes(entry[:8], "little"))
        else:
            if page != 0: raise ValueError("PAGE OUT OF RANGE")
            kind, data_offset = _frame_header(handle, 0)
        if kind == b"XTG\0":
            handle.seek(data_offset)
            packed = handle.read(48000)
            if len(packed) != 48000: raise ValueError("TRUNCATED PAGE")
            # XTG's 0 is black whereas the X Brut framebuffer's 1 is black.
            platform.present(bytes(value ^ 255 for value in packed))
            return
        _render_xth(platform, handle, data_offset)


def _render_xth(platform, handle, data_offset):
    """Dither XTH's two vertical bitplanes into the X4's 1-bit framebuffer."""
    packed, column_bytes = bytearray(48000), 100
    # The four XTH levels become a stable 2x2 ordered dither on this 1-bit panel.
    thresholds = (2, 0, 1, 2)
    for column in range(480):
        handle.seek(data_offset + column * column_bytes)
        first = handle.read(column_bytes)
        handle.seek(data_offset + 48000 + column * column_bytes)
        second = handle.read(column_bytes)
        if len(first) != column_bytes or len(second) != column_bytes: raise ValueError("TRUNCATED PAGE")
        x, mask = 479 - column, 128 >> ((479 - column) & 7)
        for block in range(column_bytes):
            one, two = first[block], second[block]
            for bit in range(8):
                level = (2 if one & (128 >> bit) else 0) + (1 if two & (128 >> bit) else 0)
                y = block * 8 + bit
                if level > thresholds[(y & 1) * 2 + (x & 1)]: packed[y * 60 + x // 8] |= mask
    platform.present(bytes(packed))


def download(platform, index, progress=None):
    urls = config()["document_urls"]
    data = platform.bytes(urls[index], progress)
    directory = _path(DOCUMENTS_PATH)
    try: os.mkdir(directory)
    except OSError: pass
    path = directory + "/" + document_name(index)
    with open(path + ".new", "wb") as handle: handle.write(data)
    metadata(path + ".new")
    try: os.rename(path, path + ".bak")
    except OSError: pass
    os.rename(path + ".new", path)
    clear_bookmark(document_name(index))
    return metadata(path)
