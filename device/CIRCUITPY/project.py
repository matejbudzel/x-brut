"""xViewer: URL-managed XTC/XTH document library for the X Brut base."""
import os
from storage import read_json, write_json

PROJECT_NAME = "xViewer"
PROJECT_VERSION = "0.1.0"
PROJECT_CONFIG_PATH = "/project-conf.json"
DOCUMENTS_DIRECTORY = "/xviewer-docs"


def config():
    value = read_json(PROJECT_CONFIG_PATH, {}) or {}
    value["document_urls"] = [url for url in value.get("document_urls", []) if url]
    return value


def save_urls(urls):
    value = config()
    value["document_urls"] = [url.strip() for url in urls if url and url.strip()]
    write_json(PROJECT_CONFIG_PATH, value)


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
    try: names = os.listdir(DOCUMENTS_DIRECTORY)
    except OSError: return []
    result = []
    for name in names:
        if name.endswith(".xth"):
            try: result.append((name, metadata(DOCUMENTS_DIRECTORY + "/" + name)))
            except Exception: pass
    return result


def download(platform, index):
    urls = config()["document_urls"]
    data = platform.bytes(urls[index])
    try: os.mkdir(DOCUMENTS_DIRECTORY)
    except OSError: pass
    path = DOCUMENTS_DIRECTORY + "/" + document_name(index)
    with open(path + ".new", "wb") as handle: handle.write(data)
    metadata(path + ".new")
    try: os.rename(path, path + ".bak")
    except OSError: pass
    os.rename(path + ".new", path)
    return metadata(path)
