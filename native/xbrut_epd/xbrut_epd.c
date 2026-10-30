// X Brut's X4-only native SSD1677 presenter.
//
// It deliberately owns the panel instead of going through displayio: the
// controller's RED RAM is retained as the previous frame for fast updates.
#include "py/obj.h"
#include "py/runtime.h"
#include "py/stream.h"
#include "shared-bindings/board/__init__.h"
#include "shared-bindings/busio/SPI.h"
#include "shared-bindings/fourwire/FourWire.h"
#include "shared-bindings/microcontroller/Pin.h"
#include "shared-module/displayio/__init__.h"

extern const mcu_pin_obj_t pin_GPIO4;
extern const mcu_pin_obj_t pin_GPIO5;
extern const mcu_pin_obj_t pin_GPIO21;

#define FRAME_BYTES 48000
#define CHUNK_BYTES 400

static fourwire_fourwire_obj_t panel_bus;
static bool panel_ready;
static bool panel_has_frame;

// Factory X4 fast LUT, extracted by the Crosspoint project from Xteink's
// V3.1.9_CH_X4 firmware.  The trailing five values are the voltage registers.
static const uint8_t fast_lut[110] = {
    0x00,0x4a,0x88,0,0,0,0,0,0,0, 0x80,0x62,0,0,0,0,0,0,0,0,
    0x88,0x60,0,0,0,0,0,0,0,0, 0xa8,0x44,0x04,0,0,0,0,0,0,0,
    0,0,0,0,0,0,0,0,0,0, 0x09,0x0c,0x03,0x03,0,
    0x0f,0x03,0x07,0x03,0, 0x03,0,0x02,0,0,
    0,0,0,0,0, 0,0,0,0,0, 0,0,0,0,0, 0,0,0,0,0,
    0,0,0,0,0, 0,0,0,0,0, 0,0,0,0,0,
    0x44,0x44,0x44,0x44,0x44, 0x17,0x41,0xa8,0x32,0x50
};

static void tx(uint8_t kind, const uint8_t *data, size_t length) {
    common_hal_fourwire_fourwire_send(MP_OBJ_FROM_PTR(&panel_bus), kind,
        CHIP_SELECT_TOGGLE_EVERY_BYTE, data, length);
}
static void command(uint8_t value) { tx(DISPLAY_COMMAND, &value, 1); }
static void data(const uint8_t *value, size_t length) { tx(DISPLAY_DATA, value, length); }
static void data_byte(uint8_t value) { data(&value, 1); }

static void begin_transaction(void) {
    while (!common_hal_fourwire_fourwire_begin_transaction(MP_OBJ_FROM_PTR(&panel_bus))) {
        RUN_BACKGROUND_TASKS;
    }
}
static void end_transaction(void) { common_hal_fourwire_fourwire_end_transaction(MP_OBJ_FROM_PTR(&panel_bus)); }

static void controller_init(void) {
    mp_printf(&mp_plat_print, "xbrut_epd:init-reset\n");
    common_hal_fourwire_fourwire_reset(MP_OBJ_FROM_PTR(&panel_bus));
    mp_hal_delay_ms(20);
    mp_printf(&mp_plat_print, "xbrut_epd:init-config\n"); begin_transaction();
    command(0x12); end_transaction(); mp_hal_delay_ms(30);
    begin_transaction();
    command(0x18); data_byte(0x80);
    command(0x0c); { const uint8_t v[] = {0xae,0xc7,0xc3,0xc0,0x40}; data(v, sizeof(v)); }
    command(0x01); { const uint8_t v[] = {0xdf,0x01,0x02}; data(v, sizeof(v)); }
    command(0x11); data_byte(0x01);
    command(0x3c); data_byte(0x01);
    command(0x44); { const uint8_t v[] = {0,0,0x1f,0x03}; data(v, sizeof(v)); }
    command(0x45); { const uint8_t v[] = {0xdf,0x01,0,0}; data(v, sizeof(v)); }
    command(0x4e); { const uint8_t v[] = {0,0}; data(v, sizeof(v)); }
    command(0x4f); { const uint8_t v[] = {0xdf,0x01}; data(v, sizeof(v)); }
    end_transaction();
}

static void seek_start(mp_obj_t stream) {
    int err = 0;
    if (mp_stream_seek(stream, 0, MP_SEEK_SET, &err) < 0) mp_raise_OSError(err);
}
static void write_frame(mp_obj_t stream, uint8_t ram_command) {
    uint8_t buffer[CHUNK_BYTES];
    int err = 0;
    seek_start(stream);
    mp_printf(&mp_plat_print, "xbrut_epd:frame-%x\n", ram_command);
    begin_transaction(); command(ram_command); end_transaction();
    for (size_t sent = 0; sent < FRAME_BYTES;) {
        size_t wanted = FRAME_BYTES - sent;
        if (wanted > sizeof(buffer)) wanted = sizeof(buffer);
        mp_uint_t got = mp_stream_read_exactly(stream, buffer, wanted, &err);
        if (got == MP_STREAM_ERROR) mp_raise_OSError(err);
        // The framebuffer lives on microSD, which shares this SPI bus. Read
        // before taking the panel lock; hold it only for this transfer.
        begin_transaction(); data(buffer, got); end_transaction();
        sent += got;
    }
    mp_printf(&mp_plat_print, "xbrut_epd:frame-done\n");
}
static void load_fast_lut(void) {
    begin_transaction();
    command(0x32); data(fast_lut, 105);
    command(0x03); data_byte(fast_lut[105]);
    command(0x04); data(fast_lut + 106, 3);
    command(0x2c); data_byte(fast_lut[109]);
    end_transaction();
}
static void activate(bool fast) {
    mp_printf(&mp_plat_print, "xbrut_epd:activate-%d\n", fast);
    begin_transaction();
    command(0x21); data_byte(fast ? 0x00 : 0x40);
    if (!fast) { command(0x1a); data_byte(0x5a); }
    command(0x22); data_byte(fast ? 0x0c : 0xd4);
    command(0x20); end_transaction();
    mp_hal_delay_ms(fast ? 750 : 2200);
    mp_printf(&mp_plat_print, "xbrut_epd:activate-done\n");
}

static mp_obj_t xbrut_epd_refresh(size_t n_args, const mp_obj_t *args) {
    mp_obj_t stream = args[0];
    mp_get_stream_raise(stream, MP_STREAM_OP_READ | MP_STREAM_OP_IOCTL);
    bool full = n_args == 2 && mp_obj_is_true(args[1]);
    if (!panel_ready) {
        busio_spi_obj_t *spi = MP_OBJ_TO_PTR(common_hal_board_create_spi(0));
        common_hal_busio_spi_never_reset(spi);
        panel_bus.base.type = &fourwire_fourwire_type;
        common_hal_fourwire_fourwire_construct(&panel_bus, spi, MP_OBJ_FROM_PTR(&pin_GPIO4),
            MP_OBJ_FROM_PTR(&pin_GPIO21), MP_OBJ_FROM_PTR(&pin_GPIO5), 40000000, 0, 0);
        panel_ready = true;
    }
    if (!panel_has_frame || full) {
        controller_init();
        write_frame(stream, 0x24);
        write_frame(stream, 0x26);
        activate(false);
        panel_has_frame = true;
    } else {
        load_fast_lut();
        write_frame(stream, 0x24);
        activate(true);
        // Red RAM becomes the previous-frame source for the next differential update.
        write_frame(stream, 0x26);
    }
    mp_printf(&mp_plat_print, "xbrut_epd:done\n");
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(xbrut_epd_refresh_obj, 1, 2, xbrut_epd_refresh);

static mp_obj_t xbrut_epd_sleep(void) {
    if (!panel_ready) return mp_const_none;
    begin_transaction(); command(0x21); data_byte(0x40); command(0x22); data_byte(0x03); command(0x20); end_transaction();
    mp_hal_delay_ms(100); begin_transaction(); command(0x10); data_byte(0x01); end_transaction();
    panel_has_frame = false;
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_0(xbrut_epd_sleep_obj, xbrut_epd_sleep);

static const mp_rom_map_elem_t xbrut_epd_globals_table[] = {
    { MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR_xbrut_epd) },
    { MP_ROM_QSTR(MP_QSTR_refresh), MP_ROM_PTR(&xbrut_epd_refresh_obj) },
    { MP_ROM_QSTR(MP_QSTR_sleep), MP_ROM_PTR(&xbrut_epd_sleep_obj) },
};
static MP_DEFINE_CONST_DICT(xbrut_epd_globals, xbrut_epd_globals_table);
const mp_obj_module_t xbrut_epd_module = { .base = { &mp_type_module }, .globals = (mp_obj_dict_t *)&xbrut_epd_globals };
MP_REGISTER_MODULE(MP_QSTR_xbrut_epd, xbrut_epd_module);
