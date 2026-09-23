// X Brut X4 hardware support for MicroPython. SPI2 is initialised here once:
// SD and the SSD1677 are individual devices and every transfer releases it.
#include <string.h>
#include "py/mphal.h"
#include "py/mperrno.h"
#include "py/obj.h"
#include "py/runtime.h"
#include "py/stream.h"
#include "extmod/vfs_fat.h"
#include "driver/gpio.h"
#include "driver/sdspi_host.h"
#include "driver/spi_master.h"
#include "esp_adc/adc_oneshot.h"
#include "esp_err.h"
#include "esp_sleep.h"
#include "sdmmc_cmd.h"

#define X4_POWER_BUTTON_GPIO GPIO_NUM_3
#define X4_PANEL_DC_GPIO GPIO_NUM_4
#define X4_PANEL_RESET_GPIO GPIO_NUM_5
#define X4_PANEL_BUSY_GPIO GPIO_NUM_6
#define X4_SPI_MISO_GPIO GPIO_NUM_7
#define X4_SPI_SCK_GPIO GPIO_NUM_8
#define X4_SPI_MOSI_GPIO GPIO_NUM_10
#define X4_SD_CS_GPIO GPIO_NUM_12
#define X4_USB_PRESENT_GPIO GPIO_NUM_20
#define X4_PANEL_CS_GPIO GPIO_NUM_21
#define X4_SPI_HOST SPI2_HOST
#define X4_FRAME_BYTES (800 * 480 / 8)
#define X4_PANEL_CHUNK_BYTES 1024
#define X4_BATTERY_ADC_UNIT ADC_UNIT_1
#define X4_BATTERY_ADC_CHANNEL ADC_CHANNEL_0
#define X4_BUTTONS_LEFT_ADC_CHANNEL ADC_CHANNEL_1
#define X4_BUTTONS_RIGHT_ADC_CHANNEL ADC_CHANNEL_2

typedef struct _x4_sdcard_obj_t {
    mp_obj_base_t base;
    sdmmc_host_t host;
    sdmmc_card_t card;
    bool card_ready;
} x4_sdcard_obj_t;
extern const mp_obj_type_t x4_sdcard_type;
static x4_sdcard_obj_t x4_sdcard = { .base = { &x4_sdcard_type } };
static adc_oneshot_unit_handle_t adc_unit;
static bool adc_ready, spi_ready, panel_has_frame, framebuffer_update_pending, framebuffer_busy_seen;
static mp_uint_t framebuffer_update_started;
static spi_device_handle_t panel_device;
// The active UI frame belongs in RAM.  The controller's RED RAM already
// stores the prior displayed frame for differential refresh, so X4 needs only
// this one 48 KiB working buffer (rather than an SD-backed scratch file or a
// second RAM frame).
static uint8_t panel_framebuffer[X4_FRAME_BYTES];

static void x4_check(esp_err_t err) { if (err != ESP_OK) mp_raise_OSError(-err); }
static void x4_output(gpio_num_t pin, int level) {
    gpio_config_t cfg = { .pin_bit_mask = 1ULL << pin, .mode = GPIO_MODE_OUTPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE, .pull_down_en = GPIO_PULLDOWN_DISABLE, .intr_type = GPIO_INTR_DISABLE };
    x4_check(gpio_config(&cfg)); x4_check(gpio_set_level(pin, level));
}
static void x4_input(gpio_num_t pin, gpio_pull_mode_t pull) {
    gpio_config_t cfg = { .pin_bit_mask = 1ULL << pin, .mode = GPIO_MODE_INPUT,
        .pull_up_en = pull == GPIO_PULLUP_ONLY ? GPIO_PULLUP_ENABLE : GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE, .intr_type = GPIO_INTR_DISABLE };
    x4_check(gpio_config(&cfg));
}
static void x4_setup_adc(void) {
    if (adc_ready) return;
    adc_oneshot_unit_init_cfg_t u = { .unit_id = X4_BATTERY_ADC_UNIT };
    adc_oneshot_chan_cfg_t c = { .bitwidth = ADC_BITWIDTH_DEFAULT, .atten = ADC_ATTEN_DB_12 };
    x4_check(adc_oneshot_new_unit(&u, &adc_unit));
    x4_check(adc_oneshot_config_channel(adc_unit, X4_BATTERY_ADC_CHANNEL, &c));
    x4_check(adc_oneshot_config_channel(adc_unit, X4_BUTTONS_LEFT_ADC_CHANNEL, &c));
    x4_check(adc_oneshot_config_channel(adc_unit, X4_BUTTONS_RIGHT_ADC_CHANNEL, &c)); adc_ready = true;
}
static int x4_adc_read(adc_channel_t channel) { int value; x4_setup_adc(); x4_check(adc_oneshot_read(adc_unit, channel, &value)); return value; }

static void x4_setup_spi(void) {
    if (spi_ready) return;
    x4_output(X4_PANEL_CS_GPIO, 1); x4_output(X4_PANEL_DC_GPIO, 0); x4_output(X4_PANEL_RESET_GPIO, 1); x4_input(X4_PANEL_BUSY_GPIO, GPIO_FLOATING);
    spi_bus_config_t bus = { .miso_io_num = X4_SPI_MISO_GPIO, .mosi_io_num = X4_SPI_MOSI_GPIO, .sclk_io_num = X4_SPI_SCK_GPIO,
        .data2_io_num = GPIO_NUM_NC, .data3_io_num = GPIO_NUM_NC, .max_transfer_sz = X4_PANEL_CHUNK_BYTES,
        .flags = SPICOMMON_BUSFLAG_MASTER | SPICOMMON_BUSFLAG_SCLK | SPICOMMON_BUSFLAG_MISO | SPICOMMON_BUSFLAG_MOSI };
    x4_check(spi_bus_initialize(X4_SPI_HOST, &bus, SPI_DMA_CH_AUTO));
    sdspi_device_config_t sddev = SDSPI_DEVICE_CONFIG_DEFAULT(); sddev.host_id = X4_SPI_HOST; sddev.gpio_cs = X4_SD_CS_GPIO;
    sdspi_dev_handle_t handle; x4_check(sdspi_host_init_device(&sddev, &handle));
    sdmmc_host_t host = SDSPI_HOST_DEFAULT(); host.max_freq_khz = 20000; host.slot = handle; x4_sdcard.host = host;
    spi_device_interface_config_t panel = { .clock_speed_hz = 10000000, .mode = 0, .spics_io_num = X4_PANEL_CS_GPIO, .queue_size = 1 };
    x4_check(spi_bus_add_device(X4_SPI_HOST, &panel, &panel_device)); spi_ready = true;
}
static esp_err_t x4_ensure_card(void) {
    x4_setup_spi(); if (x4_sdcard.card_ready) return ESP_OK;
    esp_err_t err = sdmmc_card_init(&x4_sdcard.host, &x4_sdcard.card);
    if (err == ESP_OK) { x4_sdcard.card.host.slot = x4_sdcard.host.slot; x4_sdcard.card_ready = true; } return err;
}
static void x4_panel_tx(bool data, const uint8_t *buf, size_t len) {
    x4_setup_spi(); x4_check(gpio_set_level(X4_PANEL_DC_GPIO, data));
    spi_transaction_t t = { .length = len * 8, .tx_buffer = buf }; x4_check(spi_device_transmit(panel_device, &t));
}
static void x4_cmd(uint8_t byte) { x4_panel_tx(false, &byte, 1); }
static void x4_byte(uint8_t byte) { x4_panel_tx(true, &byte, 1); }
static void x4_data(const uint8_t *buf, size_t len) { while (len) { size_t n = len > X4_PANEL_CHUNK_BYTES ? X4_PANEL_CHUNK_BYTES : len; x4_panel_tx(true, buf, n); buf += n; len -= n; } }
// The X4's SSD1677 holds BUSY high while a reset or display update is in
// progress.  Fixed delays are not safe here: panel timing varies with
// temperature, and the RED-RAM sync must not begin until a differential pass
// has actually finished.
static void x4_wait_busy(uint32_t timeout_ms) {
    for (uint32_t elapsed = 0; gpio_get_level(X4_PANEL_BUSY_GPIO); ++elapsed) {
        if (elapsed >= timeout_ms) mp_raise_OSError(MP_ETIMEDOUT);
        mp_hal_delay_ms(1);
    }
}
static void x4_panel_init(void) {
    x4_setup_spi(); x4_check(gpio_set_level(X4_PANEL_RESET_GPIO, 1)); mp_hal_delay_ms(20); x4_check(gpio_set_level(X4_PANEL_RESET_GPIO, 0)); mp_hal_delay_ms(2); x4_check(gpio_set_level(X4_PANEL_RESET_GPIO, 1)); mp_hal_delay_ms(20);
    x4_cmd(0x12); x4_wait_busy(1000); x4_cmd(0x18); x4_byte(0x80);
    const uint8_t booster[] = {0xae,0xc7,0xc3,0xc0,0x40}, power[] = {0xdf,0x01,0x02}, xwin[] = {0,0,0x1f,0x03}, ywin[] = {0xdf,0x01,0,0}, xcur[] = {0,0}, ycur[] = {0xdf,0x01};
    x4_cmd(0x0c); x4_data(booster, sizeof(booster)); x4_cmd(0x01); x4_data(power, sizeof(power)); x4_cmd(0x11); x4_byte(0x01); x4_cmd(0x3c); x4_byte(0x01);
    x4_cmd(0x44); x4_data(xwin, sizeof(xwin)); x4_cmd(0x45); x4_data(ywin, sizeof(ywin)); x4_cmd(0x4e); x4_data(xcur, sizeof(xcur)); x4_cmd(0x4f); x4_data(ycur, sizeof(ycur));
}
static void x4_activate_full(void) { x4_cmd(0x21); x4_byte(0x40); x4_cmd(0x1a); x4_byte(0x5a); x4_cmd(0x22); x4_byte(0xf4); x4_cmd(0x20); x4_wait_busy(30000); }
// Factory X4 differential waveform.  The final five bytes configure voltage
// registers after the 105-byte LUT table.
static const uint8_t x4_fast_lut[110] = {
    0x00,0x4a,0x88,0,0,0,0,0,0,0, 0x80,0x62,0,0,0,0,0,0,0,0,
    0x88,0x60,0,0,0,0,0,0,0,0, 0xa8,0x44,0x04,0,0,0,0,0,0,0,
    0,0,0,0,0,0,0,0,0,0, 0x09,0x0c,0x03,0x03,0,
    0x0f,0x03,0x07,0x03,0, 0x03,0,0x02,0,0,
    0,0,0,0,0, 0,0,0,0,0, 0,0,0,0,0, 0,0,0,0,0,
    0,0,0,0,0, 0,0,0,0,0, 0,0,0,0,0,
    0x44,0x44,0x44,0x44,0x44, 0x17,0x41,0xa8,0x32,0x50
};
static void x4_load_fast_lut(void) { x4_cmd(0x32); x4_data(x4_fast_lut, 105); x4_cmd(0x03); x4_byte(x4_fast_lut[105]); x4_cmd(0x04); x4_data(x4_fast_lut + 106, 3); x4_cmd(0x2c); x4_byte(x4_fast_lut[109]); }
// Use the controller's native monochrome differential LUT.  The extracted
// factory LUT produces clean solid fills, but corrupts sparse UI transitions
// on this X4 panel.  0x1c reloads the controller's normal fast waveform.
static void x4_activate_fast(void) { x4_cmd(0x21); x4_byte(0x00); x4_cmd(0x22); x4_byte(0x1c); x4_cmd(0x20); x4_wait_busy(30000); }
static void x4_start_fast(void) { x4_cmd(0x21); x4_byte(0x00); x4_cmd(0x22); x4_byte(0x1c); x4_cmd(0x20); }

static mp_obj_t x4_sdcard_info(mp_obj_t self_in) { x4_sdcard_obj_t *s = MP_OBJ_TO_PTR(self_in); x4_check(x4_ensure_card()); mp_obj_t a[] = {mp_obj_new_int_from_ull((uint64_t)s->card.csd.capacity * s->card.csd.sector_size), mp_obj_new_int_from_uint(s->card.csd.sector_size)}; return mp_obj_new_tuple(2, a); }
static MP_DEFINE_CONST_FUN_OBJ_1(x4_sdcard_info_obj, x4_sdcard_info);
static mp_obj_t x4_sdcard_readblocks(mp_obj_t self_in, mp_obj_t block, mp_obj_t buffer_in) { x4_sdcard_obj_t *s = MP_OBJ_TO_PTR(self_in); mp_buffer_info_t b; mp_get_buffer_raise(buffer_in, &b, MP_BUFFER_WRITE); if (x4_ensure_card() != ESP_OK) return MP_OBJ_NEW_SMALL_INT(-MP_EIO); return MP_OBJ_NEW_SMALL_INT(sdmmc_read_sectors(&s->card, b.buf, mp_obj_get_int(block), b.len / s->card.csd.sector_size) == ESP_OK ? 0 : -MP_EIO); }
static MP_DEFINE_CONST_FUN_OBJ_3(x4_sdcard_readblocks_obj, x4_sdcard_readblocks);
static mp_obj_t x4_sdcard_writeblocks(mp_obj_t self_in, mp_obj_t block, mp_obj_t buffer_in) { x4_sdcard_obj_t *s = MP_OBJ_TO_PTR(self_in); mp_buffer_info_t b; mp_get_buffer_raise(buffer_in, &b, MP_BUFFER_READ); if (x4_ensure_card() != ESP_OK) return MP_OBJ_NEW_SMALL_INT(-MP_EIO); return MP_OBJ_NEW_SMALL_INT(sdmmc_write_sectors(&s->card, b.buf, mp_obj_get_int(block), b.len / s->card.csd.sector_size) == ESP_OK ? 0 : -MP_EIO); }
static MP_DEFINE_CONST_FUN_OBJ_3(x4_sdcard_writeblocks_obj, x4_sdcard_writeblocks);
static mp_obj_t x4_sdcard_ioctl(mp_obj_t self_in, mp_obj_t cmd, mp_obj_t arg) { x4_sdcard_obj_t *s = MP_OBJ_TO_PTR(self_in); switch (mp_obj_get_int(cmd)) { case MP_BLOCKDEV_IOCTL_INIT: return MP_OBJ_NEW_SMALL_INT(x4_ensure_card() == ESP_OK ? 0 : -1); case MP_BLOCKDEV_IOCTL_DEINIT: s->card_ready = false; return MP_OBJ_NEW_SMALL_INT(0); case MP_BLOCKDEV_IOCTL_SYNC: return MP_OBJ_NEW_SMALL_INT(0); case MP_BLOCKDEV_IOCTL_BLOCK_COUNT: return MP_OBJ_NEW_SMALL_INT(x4_ensure_card() == ESP_OK ? s->card.csd.capacity : -1); case MP_BLOCKDEV_IOCTL_BLOCK_SIZE: return MP_OBJ_NEW_SMALL_INT(x4_ensure_card() == ESP_OK ? s->card.csd.sector_size : -1); default: return MP_OBJ_NEW_SMALL_INT(-1); } }
static MP_DEFINE_CONST_FUN_OBJ_3(x4_sdcard_ioctl_obj, x4_sdcard_ioctl);
static const mp_rom_map_elem_t x4_sdcard_locals_table[] = {{MP_ROM_QSTR(MP_QSTR_info), MP_ROM_PTR(&x4_sdcard_info_obj)}, {MP_ROM_QSTR(MP_QSTR_readblocks), MP_ROM_PTR(&x4_sdcard_readblocks_obj)}, {MP_ROM_QSTR(MP_QSTR_writeblocks), MP_ROM_PTR(&x4_sdcard_writeblocks_obj)}, {MP_ROM_QSTR(MP_QSTR_ioctl), MP_ROM_PTR(&x4_sdcard_ioctl_obj)}};
static MP_DEFINE_CONST_DICT(x4_sdcard_locals, x4_sdcard_locals_table);
MP_DEFINE_CONST_OBJ_TYPE(x4_sdcard_type, MP_QSTR_SDCard, MP_TYPE_FLAG_NONE, locals_dict, &x4_sdcard_locals);
static mp_obj_t xbrut_x4_sdcard(void) { x4_setup_spi(); return MP_OBJ_FROM_PTR(&x4_sdcard); }
static MP_DEFINE_CONST_FUN_OBJ_0(xbrut_x4_sdcard_obj, xbrut_x4_sdcard);

static mp_obj_t xbrut_x4_init(void) { x4_output(X4_PANEL_DC_GPIO, 0); x4_output(X4_PANEL_RESET_GPIO, 1); x4_output(X4_PANEL_CS_GPIO, 1); x4_input(X4_POWER_BUTTON_GPIO, GPIO_PULLUP_ONLY); x4_input(X4_USB_PRESENT_GPIO, GPIO_FLOATING); x4_setup_adc(); return mp_const_none; }
static MP_DEFINE_CONST_FUN_OBJ_0(xbrut_x4_init_obj, xbrut_x4_init);
static mp_obj_t xbrut_x4_power_button(void) { return mp_obj_new_bool(gpio_get_level(X4_POWER_BUTTON_GPIO) == 0); }
static MP_DEFINE_CONST_FUN_OBJ_0(xbrut_x4_power_button_obj, xbrut_x4_power_button);
static mp_obj_t xbrut_x4_usb_present(void) { return mp_obj_new_bool(gpio_get_level(X4_USB_PRESENT_GPIO) != 0); }
static MP_DEFINE_CONST_FUN_OBJ_0(xbrut_x4_usb_present_obj, xbrut_x4_usb_present);
static mp_obj_t xbrut_x4_adc_raw(void) { mp_obj_t a[] = {mp_obj_new_int(x4_adc_read(X4_BATTERY_ADC_CHANNEL)), mp_obj_new_int(x4_adc_read(X4_BUTTONS_LEFT_ADC_CHANNEL)), mp_obj_new_int(x4_adc_read(X4_BUTTONS_RIGHT_ADC_CHANNEL))}; return mp_obj_new_tuple(3, a); }
static MP_DEFINE_CONST_FUN_OBJ_0(xbrut_x4_adc_raw_obj, xbrut_x4_adc_raw);
static mp_obj_t xbrut_x4_panel_reset(void) { x4_panel_init(); return mp_const_none; }
static MP_DEFINE_CONST_FUN_OBJ_0(xbrut_x4_panel_reset_obj, xbrut_x4_panel_reset);
static mp_obj_t xbrut_x4_panel_clear(void) { x4_panel_init(); uint8_t white[X4_PANEL_CHUNK_BYTES]; memset(white, 0xff, sizeof(white)); for (uint8_t plane = 0; plane < 2; ++plane) { x4_cmd(plane ? 0x26 : 0x24); for (size_t sent = 0; sent < X4_FRAME_BYTES;) { size_t count = X4_FRAME_BYTES - sent; if (count > sizeof(white)) count = sizeof(white); x4_data(white, count); sent += count; } } x4_activate_full(); panel_has_frame = true; return mp_const_none; }
static MP_DEFINE_CONST_FUN_OBJ_0(xbrut_x4_panel_clear_obj, xbrut_x4_panel_clear);
// Read each chunk before acquiring the panel device.  This is the critical
// shared-bus boundary: an SD-backed file read completes before its bytes are
// transferred to the SSD1677, and no transaction spans both operations.
static void x4_write_stream_plane(mp_obj_t stream, uint8_t command) {
    uint8_t buffer[X4_PANEL_CHUNK_BYTES];
    int error = 0;
    if (mp_stream_seek(stream, 0, MP_SEEK_SET, &error) < 0) mp_raise_OSError(error);
    x4_cmd(command);
    for (size_t sent = 0; sent < X4_FRAME_BYTES;) {
        size_t wanted = X4_FRAME_BYTES - sent;
        if (wanted > sizeof(buffer)) wanted = sizeof(buffer);
        mp_uint_t got = mp_stream_read_exactly(stream, buffer, wanted, &error);
        if (got == MP_STREAM_ERROR) mp_raise_OSError(error);
        x4_data(buffer, got);
        sent += got;
    }
}
static void x4_write_framebuffer_plane(uint8_t command) {
    x4_cmd(command);
    x4_data(panel_framebuffer, sizeof(panel_framebuffer));
}
static mp_obj_t xbrut_x4_panel_refresh(mp_obj_t stream) {
    mp_get_stream_raise(stream, MP_STREAM_OP_READ | MP_STREAM_OP_IOCTL);
    x4_panel_init();
    x4_write_stream_plane(stream, 0x24);
    x4_write_stream_plane(stream, 0x26);
    x4_activate_full();
    panel_has_frame = true;
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(xbrut_x4_panel_refresh_obj, xbrut_x4_panel_refresh);
static mp_obj_t xbrut_x4_panel_refresh_fast(mp_obj_t stream) {
    mp_get_stream_raise(stream, MP_STREAM_OP_READ | MP_STREAM_OP_IOCTL);
    // The first refresh after boot must establish both RAM planes.
    if (!panel_has_frame) return xbrut_x4_panel_refresh(stream);
    x4_write_stream_plane(stream, 0x24);
    x4_activate_fast();
    // Keep RED RAM equal to the frame just displayed for the next update.
    x4_write_stream_plane(stream, 0x26);
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(xbrut_x4_panel_refresh_fast_obj, xbrut_x4_panel_refresh_fast);
static mp_obj_t xbrut_x4_framebuffer_clear(void) {
    memset(panel_framebuffer, 0xff, sizeof(panel_framebuffer));
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_0(xbrut_x4_framebuffer_clear_obj, xbrut_x4_framebuffer_clear);
static mp_obj_t xbrut_x4_framebuffer_rect(size_t n_args, const mp_obj_t *args) {
    mp_int_t x = mp_obj_get_int(args[0]), y = mp_obj_get_int(args[1]);
    mp_int_t width = mp_obj_get_int(args[2]), height = mp_obj_get_int(args[3]);
    if (width <= 0 || height <= 0) return mp_const_none;
    mp_int_t x_end = x + width, y_end = y + height;
    if (x < 0) x = 0;
    if (y < 0) y = 0;
    if (x_end > 800) x_end = 800;
    if (y_end > 480) y_end = 480;
    if (x >= x_end || y >= y_end) return mp_const_none;
    for (; y < y_end; ++y) {
        uint8_t *row = panel_framebuffer + y * 100;
        for (mp_int_t column = x; column < x_end; ++column) row[column >> 3] &= (uint8_t)~(0x80 >> (column & 7));
    }
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(xbrut_x4_framebuffer_rect_obj, 4, 4, xbrut_x4_framebuffer_rect);
static mp_obj_t xbrut_x4_framebuffer_present(void) {
    if (framebuffer_update_pending) mp_raise_msg(&mp_type_RuntimeError, MP_ERROR_TEXT("framebuffer update pending"));
    if (!panel_has_frame) {
        x4_panel_init();
        x4_write_framebuffer_plane(0x24);
        x4_write_framebuffer_plane(0x26);
        x4_activate_full();
        panel_has_frame = true;
    } else {
        x4_write_framebuffer_plane(0x24);
        x4_start_fast();
        framebuffer_update_pending = true;
        framebuffer_busy_seen = false;
        framebuffer_update_started = mp_hal_ticks_ms();
    }
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_0(xbrut_x4_framebuffer_present_obj, xbrut_x4_framebuffer_present);
static mp_obj_t xbrut_x4_framebuffer_ready(void) {
    if (!framebuffer_update_pending) return mp_const_true;
    if (gpio_get_level(X4_PANEL_BUSY_GPIO)) framebuffer_busy_seen = true;
    // BUSY can assert a few milliseconds after MASTER_ACTIVATION.  Do not
    // mistake that short low interval for completion.
    if (!framebuffer_busy_seen && mp_hal_ticks_ms() - framebuffer_update_started < 50) return mp_const_false;
    if (gpio_get_level(X4_PANEL_BUSY_GPIO)) return mp_const_false;
    x4_write_framebuffer_plane(0x26);
    framebuffer_update_pending = false;
    return mp_const_true;
}
static MP_DEFINE_CONST_FUN_OBJ_0(xbrut_x4_framebuffer_ready_obj, xbrut_x4_framebuffer_ready);
static mp_obj_t xbrut_x4_sleep(void) { x4_check(esp_deep_sleep_enable_gpio_wakeup(1ULL << X4_POWER_BUTTON_GPIO, ESP_GPIO_WAKEUP_GPIO_LOW)); esp_deep_sleep_start(); return mp_const_none; }
static MP_DEFINE_CONST_FUN_OBJ_0(xbrut_x4_sleep_obj, xbrut_x4_sleep);
static const mp_rom_map_elem_t xbrut_x4_globals_table[] = {{MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR_xbrut_x4)}, {MP_ROM_QSTR(MP_QSTR_init), MP_ROM_PTR(&xbrut_x4_init_obj)}, {MP_ROM_QSTR(MP_QSTR_SDCard), MP_ROM_PTR(&xbrut_x4_sdcard_obj)}, {MP_ROM_QSTR(MP_QSTR_power_button), MP_ROM_PTR(&xbrut_x4_power_button_obj)}, {MP_ROM_QSTR(MP_QSTR_usb_present), MP_ROM_PTR(&xbrut_x4_usb_present_obj)}, {MP_ROM_QSTR(MP_QSTR_adc_raw), MP_ROM_PTR(&xbrut_x4_adc_raw_obj)}, {MP_ROM_QSTR(MP_QSTR_panel_reset), MP_ROM_PTR(&xbrut_x4_panel_reset_obj)}, {MP_ROM_QSTR(MP_QSTR_panel_clear), MP_ROM_PTR(&xbrut_x4_panel_clear_obj)}, {MP_ROM_QSTR(MP_QSTR_panel_refresh), MP_ROM_PTR(&xbrut_x4_panel_refresh_obj)}, {MP_ROM_QSTR(MP_QSTR_panel_refresh_fast), MP_ROM_PTR(&xbrut_x4_panel_refresh_fast_obj)}, {MP_ROM_QSTR(MP_QSTR_framebuffer_clear), MP_ROM_PTR(&xbrut_x4_framebuffer_clear_obj)}, {MP_ROM_QSTR(MP_QSTR_framebuffer_rect), MP_ROM_PTR(&xbrut_x4_framebuffer_rect_obj)}, {MP_ROM_QSTR(MP_QSTR_framebuffer_present), MP_ROM_PTR(&xbrut_x4_framebuffer_present_obj)}, {MP_ROM_QSTR(MP_QSTR_framebuffer_ready), MP_ROM_PTR(&xbrut_x4_framebuffer_ready_obj)}, {MP_ROM_QSTR(MP_QSTR_sleep), MP_ROM_PTR(&xbrut_x4_sleep_obj)}};
static MP_DEFINE_CONST_DICT(xbrut_x4_globals, xbrut_x4_globals_table);
const mp_obj_module_t xbrut_x4_module = {.base = {&mp_type_module}, .globals = (mp_obj_dict_t *)&xbrut_x4_globals};
MP_REGISTER_MODULE(MP_QSTR_xbrut_x4, xbrut_x4_module);
