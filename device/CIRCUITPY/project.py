"""xViewer: URL-managed XTC/XTH document library for the X Brut base."""
import os, re
from xbrut_storage import read_json, write_json
from xbrut_paths import BOOKMARKS_PATH, DATA_ROOT, DOCUMENTS_PATH, PROJECT_CONFIG_PATH, THUMBNAILS_PATH

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
    value["document_urls"] = [url.strip() if isinstance(url, str) and url.strip() else None for url in value.get("document_urls", [])]
    manifests = []
    for item in value.get("document_manifests", []):
        if not isinstance(item, dict): continue
        url = (item.get("url") or "").strip()
        if url: manifests.append({"name": (item.get("name") or url).strip(), "url": url})
    # Read old configurations without requiring an AP settings round trip.
    legacy = (value.get("document_manifest_url") or "").strip()
    if not manifests and legacy: manifests.append({"name": "REMOTE DOCS", "url": legacy})
    value["document_manifests"] = manifests
    return value


def save_urls(urls):
    value = config()
    value["document_urls"] = [url.strip() for url in urls if url and url.strip()]
    write_json(_path(PROJECT_CONFIG_PATH), value)


def save_manifests(manifests):
    value = config()
    value["document_manifests"] = [{"name": (item.get("name") or item.get("url") or "").strip(), "url": item["url"].strip()} for item in manifests if isinstance(item, dict) and (item.get("url") or "").strip()]
    value.pop("document_manifest_url", None)
    write_json(_path(PROJECT_CONFIG_PATH), value)


def add_url(url):
    """Add one remote acquisition without duplicating a configured document."""
    value = config()
    urls = value["document_urls"]
    if not any(configured and _url_identity(configured) == _url_identity(url) for configured in urls):
        urls.append(url)
        value["document_urls"] = urls
        write_json(_path(PROJECT_CONFIG_PATH), value)


def remove_url(url, delete_download=False):
    """Unconfigure a URL without shifting other documents' stable file slots."""
    value = config()
    for index, configured in enumerate(value["document_urls"]):
        if not configured or _url_identity(configured) != _url_identity(url): continue
        value["document_urls"][index] = None
        write_json(_path(PROJECT_CONFIG_PATH), value)
        if delete_download:
            filename = document_name(index)
            for path in (_path(DOCUMENTS_PATH + "/" + filename), thumbnail_path(filename)):
                try: os.remove(path)
                except OSError: pass
            clear_bookmark(filename)
        return True
    return False


def has_download(url):
    """Whether an unconfigured remote item still has local reader data."""
    for index, configured in enumerate(config()["document_urls"]):
        if not configured or _url_identity(configured) != _url_identity(url): continue
        filename = document_name(index)
        for path in (_path(DOCUMENTS_PATH + "/" + filename), thumbnail_path(filename)):
            try: os.stat(path); return True
            except OSError: pass
    return False


def has_url(url):
    return any(configured and _url_identity(configured) == _url_identity(url) for configured in config()["document_urls"])


def _url_identity(url):
    """Compare URLs regardless of query-parameter ordering in OPDS feeds."""
    base, separator, query = url.partition("?")
    return base + separator + "&".join(sorted(query.split("&")))


def remote_documents(platform, manifest_index):
    """Read XTC acquisitions from an OPDS Atom feed, preserving signed URLs."""
    manifests = config()["document_manifests"]
    if not 0 <= manifest_index < len(manifests): return []
    url = manifests[manifest_index]["url"]
    xml = platform.bytes(url).decode("utf-8", "replace")
    documents, seen = [], set()
    for entry in re.findall(r"<entry(?:\s[^>]*)?>(.*?)</entry>", xml, re.I | re.S):
        title = re.search(r"<title(?:\s[^>]*)?>(.*?)</title>", entry, re.I | re.S)
        label = re.sub(r"<[^>]+>", "", title.group(1)).strip() if title else "XTC DOCUMENT"
        for link in re.findall(r"<link\b[^>]*>", entry, re.I):
            kind = re.search(r"\btype\s*=\s*['\"]([^'\"]+)['\"]", link, re.I)
            href = re.search(r"\bhref\s*=\s*['\"]([^'\"]+)['\"]", link, re.I)
            if not kind or not href or kind.group(1).lower() != "application/x-xteink-xtc": continue
            address = href.group(1).replace("&amp;", "&").replace("&quot;", "\"")
            if address not in seen:
                documents.append((label.replace("&amp;", "&"), address)); seen.add(address)
    return documents


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


def document_index(filename):
    for index, url in enumerate(config()["document_urls"]):
        if url and document_name(index) == filename: return index
    return None


THUMB_WIDTH, THUMB_HEIGHT, THUMB_ROW_BYTES = 200, 333, 25


def thumbnail_path(filename): return _path(THUMBNAILS_PATH + "/" + filename + ".bmp")


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
    # Backfill at most one cache entry per active home render.  Nothing creates
    # thumbnails while the library is not visible.
    for filename, unused in documents:
        if thumbnail(filename) is None:
            try: create_thumbnail(filename)
            except Exception: pass
            break
    ui.document_grid(PROJECT_NAME, [(filename, info.get("title") or filename, thumbnail(filename)) for filename, info in documents], focus)


def page_count(path): return metadata(path)["pages"]


def toc(path):
    """Return the XTC chapter list as (title, zero-based first-page) pairs."""
    try:
        with open(path, "rb") as handle:
            header = handle.read(56)
            if header[:4] not in (b"XTC\0", b"XTCH") or not header[11]: return []
            metadata_offset = int.from_bytes(header[16:24], "little")
            chapter_offset = int.from_bytes(header[48:56], "little")
            index_offset = int.from_bytes(header[24:32], "little")
            maximum = max(0, (index_offset - chapter_offset) // 96)
            handle.seek(metadata_offset + 246)
            count_data = handle.read(2)
            if len(count_data) != 2: return []
            count = int.from_bytes(count_data, "little")
            # Some writers leave the fixed metadata tail at 0xff even though
            # they provide a valid, bounded chapter region before the index.
            if not 0 < count <= maximum: count = maximum
            result = []
            for index in range(count):
                handle.seek(chapter_offset + index * 96)
                entry = handle.read(96)
                if len(entry) != 96: return []
                title = entry[:80].split(b"\0", 1)[0].decode("utf-8", "replace") or "CHAPTER %d" % (index + 1)
                # XTC chapter records count pages from one; the viewer uses
                # zero-based page indexes for rendering and bookmarks.
                result.append((title, max(0, int.from_bytes(entry[80:82], "little") - 1)))
            return result
    except (OSError, ValueError): return []


def toc_focus(chapters, page):
    focus = 0
    for index, chapter in enumerate(chapters):
        if chapter[1] > page: break
        focus = index
    return focus


def _frame_header(handle, offset):
    handle.seek(offset)
    header = handle.read(22)
    if len(header) != 22 or header[:4] not in (b"XTG\0", b"XTH\0"):
        raise ValueError("INVALID PAGE")
    width, height = int.from_bytes(header[4:6], "little"), int.from_bytes(header[6:8], "little")
    data_size = int.from_bytes(header[10:14], "little")
    if not width or not height or header[9] != 0: raise ValueError("UNSUPPORTED PAGE")
    expected = ((width + 7) // 8) * height if header[:4] == b"XTG\0" else width * ((height + 7) // 8) * 2
    if data_size != expected: raise ValueError("INVALID PAGE")
    return header[:4], offset + 22, width, height


def _page_frame(handle, page):
    header = handle.read(56)
    if header[:4] in (b"XTC\0", b"XTCH"):
        pages = int.from_bytes(header[6:8], "little")
        if not 0 <= page < pages: raise ValueError("PAGE OUT OF RANGE")
        index_offset = int.from_bytes(header[24:32], "little")
        handle.seek(index_offset + page * 16)
        entry = handle.read(16)
        if len(entry) != 16: raise ValueError("INVALID PAGE INDEX")
        return _frame_header(handle, int.from_bytes(entry[:8], "little"))
    if page != 0: raise ValueError("PAGE OUT OF RANGE")
    return _frame_header(handle, 0)


def _frame_packed(handle, kind, data_offset, width, height):
    row_bytes = (width + 7) // 8
    if kind == b"XTG\0":
        handle.seek(data_offset)
        packed = handle.read(row_bytes * height)
        if len(packed) != row_bytes * height: raise ValueError("TRUNCATED PAGE")
        return bytes(value ^ 255 for value in packed)
    packed, column_bytes, plane_size = bytearray(row_bytes * height), (height + 7) // 8, width * ((height + 7) // 8)
    thresholds = (2, 0, 1, 2)
    for column in range(width):
        handle.seek(data_offset + column * column_bytes); first = handle.read(column_bytes)
        handle.seek(data_offset + plane_size + column * column_bytes); second = handle.read(column_bytes)
        if len(first) != column_bytes or len(second) != column_bytes: raise ValueError("TRUNCATED PAGE")
        x, mask = width - 1 - column, 128 >> ((width - 1 - column) & 7)
        for block in range(column_bytes):
            for bit in range(8):
                y = block * 8 + bit
                if y >= height: break
                level = (2 if first[block] & (128 >> bit) else 0) + (1 if second[block] & (128 >> bit) else 0)
                if level > thresholds[(y & 1) * 2 + (x & 1)]: packed[y * row_bytes + x // 8] |= mask
    return bytes(packed)


def page_packed(path, page=0):
    with open(path, "rb") as handle:
        kind, data_offset, width, height = _page_frame(handle, page)
        if width != 480 or height != 800: raise ValueError("UNSUPPORTED PAGE")
        return _frame_packed(handle, kind, data_offset, width, height)


def render_page(platform, path, page):
    """Present one XTG/XTH page directly, without any base UI decoration."""
    platform.present(page_packed(path, page))


def thumbnail(filename):
    """Load a cached top-to-bottom 200x333 1-bit BMP as packed screen bits."""
    try:
        with open(thumbnail_path(filename), "rb") as handle:
            header = handle.read(62)
            if header[:2] != b"BM" or int.from_bytes(header[10:14], "little") != 62:
                return None
            if int.from_bytes(header[18:22], "little") != THUMB_WIDTH or int.from_bytes(header[22:26], "little") != THUMB_HEIGHT:
                return None
            rows = [handle.read(28) for unused in range(THUMB_HEIGHT)]
            if any(len(row) != 28 for row in rows): return None
            return b"".join(row[:THUMB_ROW_BYTES] for row in reversed(rows))
    except OSError: return None


def _write_thumbnail(filename, packed):
    directory, path = _path(THUMBNAILS_PATH), thumbnail_path(filename)
    try: os.mkdir(directory)
    except OSError: pass
    header = b"BM" + (62 + 28 * THUMB_HEIGHT).to_bytes(4, "little") + b"\0\0\0\0" + (62).to_bytes(4, "little") + (40).to_bytes(4, "little") + THUMB_WIDTH.to_bytes(4, "little") + THUMB_HEIGHT.to_bytes(4, "little") + b"\1\0\1\0" + b"\0" * 16 + (2).to_bytes(4, "little") + b"\0" * 4 + b"\xff\xff\xff\0\0\0\0\0"
    with open(path + ".new", "wb") as handle:
        handle.write(header)
        for row in range(THUMB_HEIGHT - 1, -1, -1): handle.write(packed[row * THUMB_ROW_BYTES:(row + 1) * THUMB_ROW_BYTES] + b"\0\0\0")
    try: os.rename(path, path + ".bak")
    except OSError: pass
    os.rename(path + ".new", path)


def _shrink(source, width=480, height=800):
    result = bytearray(THUMB_ROW_BYTES * THUMB_HEIGHT)
    row_bytes = (width + 7) // 8
    for y in range(THUMB_HEIGHT):
        source_y = y * height // THUMB_HEIGHT
        for x in range(THUMB_WIDTH):
            source_x = x * width // THUMB_WIDTH
            if source[source_y * row_bytes + source_x // 8] & (128 >> (source_x & 7)):
                result[y * THUMB_ROW_BYTES + x // 8] |= 128 >> (x & 7)
    return bytes(result)


def create_thumbnail(filename):
    """Prefer an embedded thumbnail when usable, otherwise shrink page one."""
    path = _path(DOCUMENTS_PATH + "/" + filename)
    # The currently documented XTC thumbnail layout starts with a frame at the
    # thumbnail offset.  Unsupported bundled layouts fall back to page one.
    try:
        with open(path, "rb") as handle:
            header = handle.read(56)
            if header[:4] in (b"XTC\0", b"XTCH") and header[10]:
                thumb_offset = int.from_bytes(header[40:48], "little")
                try: kind, data_offset, width, height = _frame_header(handle, thumb_offset)
                except ValueError:
                    # Other writers put a normal 16-byte page-index entry here.
                    handle.seek(thumb_offset)
                    entry = handle.read(16)
                    if len(entry) != 16: raise ValueError("INVALID THUMBNAIL")
                    offset = int.from_bytes(entry[:8], "little")
                    try: kind, data_offset, width, height = _frame_header(handle, offset)
                    except ValueError: kind, data_offset, width, height = _frame_header(handle, thumb_offset + offset)
                embedded = _frame_packed(handle, kind, data_offset, width, height)
                if width == THUMB_WIDTH and height == THUMB_HEIGHT:
                    _write_thumbnail(filename, embedded)
                else: _write_thumbnail(filename, _shrink(embedded, width, height))
                return
    except (OSError, ValueError): pass
    _write_thumbnail(filename, _shrink(page_packed(path)))


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
    try: create_thumbnail(document_name(index))
    except Exception: pass
    return metadata(path)
