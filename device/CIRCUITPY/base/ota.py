import hashlib, os
from xbrut_log import debug, error, info, safe_url


class OTA:
    def __init__(self, network, root=""):
        self.network, self.root = network, root.rstrip("/")
        debug("ota", "initialized root=%s" % (self.root or "/"))
    def _path(self, path): return self.root + path
    def manifest(self, url):
        """Load a manifest and expand its repository-relative file URLs."""
        info("ota", "manifest fetch begin %s" % safe_url(url))
        manifest = self.network.json(url)
        base = url.rsplit("/", 1)[0] + "/"
        for item in manifest.get("files", []):
            source = item.get("url", "")
            if source and "://" not in source:
                item["url"] = base + source.lstrip("./")
        info("ota", "manifest ready files=%d" % len(manifest.get("files", [])))
        return manifest
    def download_splash(self, url):
        """Validate, proportionally fit and rotate an uncompressed 1-bit BMP."""
        info("ota", "splash download begin %s" % safe_url(url))
        data = self.network.bytes(url)
        debug("ota", "splash downloaded bytes=%d" % len(data))
        if data[:2] != b"BM" or len(data) < 54: raise ValueError("UNSUPPORTED_FORMAT")
        offset = int.from_bytes(data[10:14], "little")
        width = int.from_bytes(data[18:22], "little", signed=True)
        height = int.from_bytes(data[22:26], "little", signed=True)
        bits = int.from_bytes(data[28:30], "little")
        compression = int.from_bytes(data[30:34], "little")
        debug("ota", "splash BMP width=%d height=%d bits=%d compression=%d offset=%d" % (width, height, bits, compression, offset))
        if width <= 0 or height == 0 or bits != 1 or compression != 0: raise ValueError("UNSUPPORTED_FORMAT")
        source_h, bottom_up = abs(height), height > 0
        stride = ((width + 31) // 32) * 4
        if offset + stride * source_h > len(data): raise ValueError("UNSUPPORTED_FORMAT")
        # Fit source image inside 800×480 without distortion.
        scale = min(800 / width, 480 / source_h)
        drawn_w, drawn_h = max(1, int(width * scale)), max(1, int(source_h * scale))
        debug("ota", "splash fit width=%d height=%d scale=%s" % (drawn_w, drawn_h, scale))
        landscape = bytearray(48000)
        left, top = (800 - drawn_w) // 2, (480 - drawn_h) // 2
        for dy in range(drawn_h):
            sy = min(source_h - 1, int(dy / scale))
            row = source_h - 1 - sy if bottom_up else sy
            for dx in range(drawn_w):
                sx = min(width - 1, int(dx / scale))
                if data[offset + row * stride + sx // 8] & (128 >> (sx & 7)):
                    x, y = left + dx, top + dy
                    landscape[y * 100 + x // 8] |= 128 >> (x & 7)
        # Rotate physical landscape output clockwise into the shared portrait surface.
        portrait = bytearray(48000)
        for y in range(480):
            for x in range(800):
                if landscape[y * 100 + x // 8] & (128 >> (x & 7)):
                    px, py = 479 - y, x
                    portrait[py * 60 + px // 8] |= 128 >> (px & 7)
        with open(self._path("/splash.bin.new"), "wb") as handle: handle.write(portrait)
        try: os.rename(self._path("/splash.bin"), self._path("/splash.bin.bak"))
        except OSError as problem: debug("ota", "splash backup skipped: %r" % problem)
        os.rename(self._path("/splash.bin.new"), self._path("/splash.bin"))
        info("ota", "splash installed")

    @staticmethod
    def revert_splash(root=""):
        root = root.rstrip("/")
        info("ota", "splash revert begin root=%s" % (root or "/"))
        try: os.remove(root + "/splash.bin")
        except OSError as problem: debug("ota", "current splash remove skipped: %r" % problem)
        try: os.rename(root + "/splash.bin.bak", root + "/splash.bin")
        except OSError as problem: debug("ota", "splash restore skipped: %r" % problem)
        info("ota", "splash revert complete")
    def install(self, manifest, progress):
        info("ota", "install begin files=%d" % len(manifest.get("files", [])))
        for item in manifest.get("files", []):
            path, url = self._path("/" + item["path"].lstrip("/")), item["url"]
            info("ota", "install file begin path=%s" % item["path"])
            progress("DOWNLOADING " + item["path"])
            data = self.network.bytes(url)
            debug("ota", "install file downloaded path=%s bytes=%d" % (item["path"], len(data)))
            digest = item.get("sha256")
            if digest and hashlib.sha256(data).hexdigest().lower() != digest.lower():
                error("ota", "sha256 mismatch path=%s" % item["path"])
                raise ValueError("SHA256 " + item["path"])
            temporary, backup = path + ".new", path + ".bak"
            if self.root:
                parent = path.rsplit("/", 1)[0]
                os.makedirs(parent, exist_ok=True)
            with open(temporary, "wb") as handle: handle.write(data)
            try: os.rename(path, backup)
            except OSError as problem: debug("ota", "backup skipped path=%s: %r" % (path, problem))
            os.rename(temporary, path)
            info("ota", "install file complete path=%s" % item["path"])
        info("ota", "install complete")
        return "DONE"
