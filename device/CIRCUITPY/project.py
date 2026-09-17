"""xViewer: URL-managed XTC/XTH document library for the X Brut base."""
import os
from xbrut_storage import read_json, write_json
from xbrut_paths import DATA_ROOT, DOCUMENTS_PATH, PROJECT_CONFIG_PATH

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
        if name.endswith(".xth"):
            try: result.append((name, metadata(_path(DOCUMENTS_PATH + "/" + name))) )
            except Exception: pass
    return result


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
    return metadata(path)
