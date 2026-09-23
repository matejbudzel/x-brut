# X Brut X4 MicroPython user module.
add_library(usermod_xbrut_x4 INTERFACE)

target_sources(usermod_xbrut_x4 INTERFACE
    ${CMAKE_CURRENT_LIST_DIR}/xbrut_x4.c
)

target_include_directories(usermod_xbrut_x4 INTERFACE
    ${CMAKE_CURRENT_LIST_DIR}
)

target_link_libraries(usermod INTERFACE usermod_xbrut_x4)
