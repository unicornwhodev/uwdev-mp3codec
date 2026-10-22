# SPDX-License-Identifier: MIT
cmake_minimum_required(VERSION 3.22.1)
project(uwdev_mp3codec LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

add_library(uwdev_mp3_codec STATIC
    codec/encoder.cpp codec/dsp.cpp codec/resampler.cpp codec/mpeg.cpp codec/synthesis.cpp)
set_target_properties(uwdev_mp3_codec PROPERTIES POSITION_INDEPENDENT_CODE ON)
target_include_directories(uwdev_mp3_codec PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}")
target_compile_options(uwdev_mp3_codec PRIVATE
    -Wall -Wextra -Wpedantic -Wconversion -Wshadow -Wformat=2
    -fvisibility=hidden -fvisibility-inlines-hidden)

add_library(uwdev_mp3codec SHARED jni/encoder_jni.cpp)
target_link_libraries(uwdev_mp3codec PRIVATE uwdev_mp3_codec)
target_compile_options(uwdev_mp3codec PRIVATE
    -Wall -Wextra -Wpedantic -Wconversion -Wshadow
    -fvisibility=hidden -fvisibility-inlines-hidden)
target_link_options(uwdev_mp3codec PRIVATE
    "-Wl,--version-script=${CMAKE_CURRENT_SOURCE_DIR}/jni/exports.map"
    "-Wl,-z,max-page-size=16384" "-Wl,-z,common-page-size=16384"
    "-Wl,--no-undefined")
set_target_properties(uwdev_mp3codec PROPERTIES
    LINK_DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/jni/exports.map")
