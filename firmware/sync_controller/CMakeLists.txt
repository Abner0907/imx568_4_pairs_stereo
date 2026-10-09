cmake_minimum_required(VERSION 3.13)

# export PICO_SDK_PATH=/path/to/pico-sdk
include($ENV{PICO_SDK_PATH}/external/pico_sdk_import.cmake)

project(imx568_sync C CXX ASM)
set(CMAKE_C_STANDARD 11)
pico_sdk_init()

add_executable(imx568_sync main.c)
pico_generate_pio_header(imx568_sync ${CMAKE_CURRENT_LIST_DIR}/trigger.pio)
target_link_libraries(imx568_sync pico_stdlib hardware_pio hardware_clocks)
pico_enable_stdio_usb(imx568_sync 1)
pico_enable_stdio_uart(imx568_sync 0)
pico_add_extra_outputs(imx568_sync)
