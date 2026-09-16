import hashlib, os
from xbrut_storage import append_log


class OTA:
    def __init__(self, network, root=""):
        self.network, self.root = network, root.rstrip("/")
    def _path(self, path): return self.root + path
    def manifest(self, url):
        """Load a manifest and expand its repository-relative file URLs."""
        manifest = self.network.json(url)
        base = url.rsplit("/", 1)[0] + "/"
        for item in manifest.get("files", []):
            source = item.get("url", "")
            if source and "://" not in source:
                item["url"] = base + source.lstrip("./")
        return manifest
    def download_splash(self, url):
        """Validate, proportionally fit and rotate an uncompressed 1-bit BMP."""
        data = self.network.bytes(url)
        if data[:2] != b"BM" or len(data) < 54: raise ValueError("UNSUPPORTED_FORMAT")
        offset = int.from_bytes(data[10:14], "little")
        width = int.from_bytes(data[18:22], "little", signed=True)
        height = int.from_bytes(data[22:26], "little", signed=True)
        bits = int.from_bytes(data[28:30], "little")
        compression = int.from_bytes(data[30:34], "little")
        if width <= 0 or height == 0 or bits != 1 or compression != 0: raise ValueError("UNSUPPORTED_FORMAT")
        source_h, bottom_up = abs(height), height > 0
        stride = ((width + 31) // 32) * 4
        if offset + stride * source_h > len(data): raise ValueError("UNSUPPORTED_FORMAT")
        # Fit source image inside 800×480 without distortion.
        scale = min(800 / width, 480 / source_h)
        drawn_w, drawn_h = max(1, int(width * scale)), max(1, int(source_h * scale))
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
        except OSError: pass
        os.rename(self._path("/splash.bin.new"), self._path("/splash.bin"))

    @staticmethod
    def revert_splash(root=""):
        root = root.rstrip("/")
        try: os.remove(root + "/splash.bin")
        except OSError: pass
        try: os.rename(root + "/splash.bin.bak", root + "/splash.bin")
        except OSError: pass
    def install(self, manifest, progress):
        for item in manifest.get("files", []):
            path, url = self._path("/" + item["path"].lstrip("/")), item["url"]
            progress("DOWNLOADING " + item["path"])
            data = self.network.bytes(url)
            digest = item.get("sha256")
            if digest and hashlib.sha256(data).hexdigest().lower() != digest.lower(): raise ValueError("SHA256 " + item["path"])
            temporary, backup = path + ".new", path + ".bak"
            if self.root:
                parent = path.rsplit("/", 1)[0]
                os.makedirs(parent, exist_ok=True)
            with open(temporary, "wb") as handle: handle.write(data)
            try: os.rename(path, backup)
            except OSError: pass
            os.rename(temporary, path)
        return "DONE"
