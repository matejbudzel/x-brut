// X Brut X4 board initialisation: the native xbrut_epd module owns SSD1677.
#include "supervisor/board.h"

#include "mpconfigboard.h"
#include "shared-bindings/board/__init__.h"
#include "shared-bindings/busio/SPI.h"

void board_init(void) {
    busio_spi_obj_t *spi = MP_OBJ_TO_PTR(common_hal_board_create_spi(0));
    common_hal_busio_spi_never_reset(spi);
}

void board_deinit(void) {
}
