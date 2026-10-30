"""Minimal portrait framebuffer API backed by the MicroPython X4 adapter."""

WIDTH, HEIGHT = 480, 800
FONT = {" ": (0, 0, 0, 0, 0, 0, 0)}
for char, rows in {"X": (17,17,10,4,10,17,17), "B": (30,17,17,30,17,17,30),
                   "R": (30,17,17,30,20,18,17), "U": (17,17,17,17,17,17,14),
                   "T": (31,4,4,4,4,4,4), "M": (17,27,21,21,17,17,17),
                   "I": (31,4,4,4,4,4,31), "C": (15,16,16,16,16,16,15),
                   "P": (30,17,17,30,16,16,16), "Y": (17,17,10,4,4,4,4),
                   "H": (17,17,17,31,17,17,17), "O": (14,17,17,17,17,17,14),
                   "N": (17,25,21,19,17,17,17), "A": (14,17,17,31,17,17,17),
                   "D": (30,17,17,17,17,17,30), "E": (31,16,16,30,16,16,31),
                   "F": (31,16,16,30,16,16,16), "L": (16,16,16,16,16,16,31),
                   "S": (15,16,16,14,1,1,30),
                   "0": (14,17,19,21,25,17,14), "1": (4,12,4,4,4,4,14),
                   "2": (14,17,1,2,4,8,31), "3": (30,1,1,14,1,1,30),
                   "4": (2,6,10,18,31,2,2), "5": (31,16,16,30,1,1,30),
                   "6": (14,16,16,30,17,17,14), "7": (31,1,2,4,8,8,8),
                   "8": (14,17,17,14,17,17,14), "9": (14,17,17,15,1,1,14),
                   "-": (0,0,0,31,0,0,0), ":": (0,12,12,0,12,12,0)}.items():
    FONT[char] = rows


class Framebuffer:
    def __init__(self, platform):
        self.platform = platform

    def clear(self): self.platform.clear()
    def pixel(self, x, y, on=True): self.platform.pixel(x, y, on)
    def rect(self, x, y, width, height, on=True): self.platform.fill_rect(x, y, width, height, on)
    def refresh(self): self.platform.refresh()
    def outline(self, x, y, width, height, on=True):
        self.rect(x, y, width, 1, on); self.rect(x, y + height - 1, width, 1, on)
        self.rect(x, y, 1, height, on); self.rect(x + width - 1, y, 1, height, on)
    def text(self, x, y, text, scale=1):
        for char in text.upper():
            for row, bits in enumerate(FONT.get(char, FONT[" "])):
                for column in range(5):
                    if bits & (16 >> column): self.rect(x + column * scale, y + row * scale, scale, scale)
            x += 6 * scale
