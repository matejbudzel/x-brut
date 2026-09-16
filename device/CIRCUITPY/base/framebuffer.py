"""The shared portrait 480x800 monochrome drawing surface using Sweet16 Mono."""
# X Brut is portrait-first. The X4 adapter rotates the physical panel.
WIDTH, HEIGHT, ROW_BYTES = 480, 800, 60

# A compact 5x7 seed alphabet, stretched into a Sweet16-like 8x16 bitmap cell.
# Unknown glyphs render as '?'; the base only needs ASCII.
_FONT = {
 " ": (0,0,0,0,0,0,0), "-": (0,0,0,31,0,0,0), ".": (0,0,0,0,0,12,12), ":": (0,12,12,0,12,12,0),
 "/": (1,2,4,8,16,0,0), "_": (0,0,0,0,0,0,31), "?": (14,17,2,4,4,0,4),
}
for _ch, _rows in {"A":(14,17,17,31,17,17,17),"B":(30,17,17,30,17,17,30),"C":(15,16,16,16,16,16,15),"D":(30,17,17,17,17,17,30),"E":(31,16,16,30,16,16,31),"F":(31,16,16,30,16,16,16),"G":(15,16,16,23,17,17,15),"H":(17,17,17,31,17,17,17),"I":(31,4,4,4,4,4,31),"J":(7,2,2,2,18,18,12),"K":(17,18,20,24,20,18,17),"L":(16,16,16,16,16,16,31),"M":(17,27,21,21,17,17,17),"N":(17,25,21,19,17,17,17),"O":(14,17,17,17,17,17,14),"P":(30,17,17,30,16,16,16),"Q":(14,17,17,17,21,18,13),"R":(30,17,17,30,20,18,17),"S":(15,16,16,14,1,1,30),"T":(31,4,4,4,4,4,4),"U":(17,17,17,17,17,17,14),"V":(17,17,17,17,17,10,4),"W":(17,17,17,21,21,21,10),"X":(17,17,10,4,10,17,17),"Y":(17,17,10,4,4,4,4),"Z":(31,1,2,4,8,16,31),"0":(14,17,19,21,25,17,14),"1":(4,12,4,4,4,4,14),"2":(14,17,1,2,4,8,31),"3":(30,1,1,14,1,1,30),"4":(2,6,10,18,31,2,2),"5":(31,16,16,30,1,1,30),"6":(14,16,16,30,17,17,14),"7":(31,1,2,4,8,8,8),"8":(14,17,17,14,17,17,14),"9":(14,17,17,15,1,1,14)}.items(): _FONT[_ch] = _rows
try:
    with open("/base/sweet16mono.f8", "rb") as _font_file: _SWEET16 = _font_file.read()
except OSError:  # Desktop simulator imports the same module directly.
    import os
    with open(os.path.join(os.path.dirname(__file__), "sweet16mono.f8"), "rb") as _font_file: _SWEET16 = _font_file.read()


class Framebuffer:
    """Drawing API backed directly by the one displayio bitmap on the X4."""
    def __init__(self, bitmap): self.bitmap = bitmap
    def clear(self): self.bitmap.fill(0)
    def pixel(self, x, y, on=True):
        if 0 <= x < WIDTH and 0 <= y < HEIGHT:
            self.bitmap[x, y] = 1 if on else 0
    def rect(self, x, y, width, height, on=True):
        for yy in range(y, y + height):
            for xx in range(x, x + width): self.pixel(xx, yy, on)
    def outline(self, x, y, width, height, on=True):
        for xx in range(x, x + width):
            self.pixel(xx, y, on); self.pixel(xx, y + height - 1, on)
        for yy in range(y, y + height):
            self.pixel(x, yy, on); self.pixel(x + width - 1, yy, on)
    def text(self, x, y, text, scale=1):
        for char in text:
            code = ord(char) if ord(char) < 384 else ord("?")
            glyph = _SWEET16[code * 16:(code + 1) * 16]
            for row, bits in enumerate(glyph):
                for col in range(8):
                    if bits & (128 >> col): self.rect(x + col * scale, y + row * scale, scale, scale)
            x += 8 * scale

    def text_bold(self, x, y, text, scale=1):
        """Slight bitmap emboldening without adding a second font asset."""
        self.text(x, y, text, scale)
        self.text(x + scale, y, text, scale)

    def text_rotated_180(self, x, y, text, scale=1):
        """Draw Sweet16 text rotated in bitmap space, without a second glyph."""
        for char in text:
            code = ord(char) if ord(char) < 384 else ord("?")
            glyph = _SWEET16[code * 16:(code + 1) * 16]
            for row, bits in enumerate(glyph):
                for col in range(8):
                    if bits & (128 >> col):
                        self.rect(x + (7 - col) * scale, y + (15 - row) * scale, scale, scale)
            x -= 8 * scale
