#define MICROPY_HW_BOARD_NAME "X Brut X4"
#define MICROPY_HW_MCU_NAME "ESP32-C3"

// The X4 exposes the ESP32-C3 USB Serial/JTAG interface.
#define MICROPY_HW_ENABLE_UART_REPL (1)
// SPI2 is owned by xbrut_x4 so SD and the panel can safely share it.
#define MICROPY_PY_MACHINE_SDCARD (0)
