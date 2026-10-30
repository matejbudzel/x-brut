"""Render the first portrait base compatibility screen on an X4.

The current development firmware's flash importer is under investigation;
loading these two local files explicitly keeps this hardware smoke test
independent of it.
"""
exec(open("xbrut_hardware.py").read())
exec(open("xbrut_framebuffer.py").read())

platform = X4Platform()
frame = Framebuffer(platform)
frame.clear()
frame.outline(12, 12, 456, 776)
frame.text(42, 44, "X BRUT", 4)
frame.text(42, 110, "MICROPYTHON BASE", 2)
frame.text(42, 160, "PORTRAIT 480 X 800", 2)
frame.text(42, 210, "NATIVE RAM FRAME", 2)
percent, usb = platform.battery_status()
frame.text(42, 730, "BAT %d USB %s" % (percent, "ON" if usb else "OFF"), 2)
frame.text(42, 765, "PORTRAIT ADAPTER OK", 1)
platform.refresh()
