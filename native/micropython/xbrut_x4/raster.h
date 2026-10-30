// Pure drawing operations. Native panel bits are 0=black, 1=white.
#ifndef XBRUT_RASTER_H
#define XBRUT_RASTER_H
#include <stddef.h>
#include <stdbool.h>
#include <stdint.h>

static void x4_raster_rect(uint8_t *frame, int x, int y, int width, int height, bool black) {
    int64_t right = (int64_t)x + width, bottom = (int64_t)y + height;
    if (width <= 0 || height <= 0) return;
    if (x < 0) x = 0;
    if (y < 0) y = 0;
    if (right > 800) right = 800;
    if (bottom > 480) bottom = 480;
    for (; y < bottom; ++y) {
        for (int column = x; column < right; ++column) {
            uint8_t *byte = frame + y * 100 + column / 8;
            uint8_t mask = 128 >> (column & 7);
            if (black) *byte &= (uint8_t)~mask;
            else *byte |= mask;
        }
    }
}

// Packed portrait source: 1=black, 0=transparent, rows padded to whole bytes.
// Rotation: portrait (x,y) -> physical (y,479-x).
static void x4_raster_blit_portrait(uint8_t *frame, int x, int y, int width, int height, const uint8_t *source) {
    if (width <= 0 || height <= 0) return;
    int64_t right = (int64_t)x + width, bottom = (int64_t)y + height;
    int left = x < 0 ? 0 : x, top = y < 0 ? 0 : y;
    if (right > 480) right = 480;
    if (bottom > 800) bottom = 800;
    size_t stride = ((size_t)width + 7) / 8;
    for (int row = top; row < bottom; ++row) {
        for (int column = left; column < right; ++column) {
            size_t sx = (size_t)((int64_t)column - x);
            size_t sy = (size_t)((int64_t)row - y);
            if (source[sy * stride + sx / 8] & (128 >> (sx & 7))) {
                frame[(479 - column) * 100 + row / 8] &= (uint8_t)~(128 >> (row & 7));
            }
        }
    }
}
#endif
