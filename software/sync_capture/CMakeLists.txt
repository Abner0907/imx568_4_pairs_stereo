cmake_minimum_required(VERSION 3.10)
project(imx568_sync_capture CXX)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()
add_compile_options(-Wall -Wextra)

add_library(multicam src/multicam.cpp)
target_include_directories(multicam PUBLIC include)

add_executable(imx568_sync_capture src/main.cpp)
target_link_libraries(imx568_sync_capture multicam)

enable_testing()
add_executable(test_assembler tests/test_assembler.cpp)
target_link_libraries(test_assembler multicam)
add_test(NAME assembler COMMAND test_assembler)
