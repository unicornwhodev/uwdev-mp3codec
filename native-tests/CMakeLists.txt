# SPDX-License-Identifier: MIT
cmake_minimum_required(VERSION 3.22.1)
project(uwdev_mp3_native_tests LANGUAGES CXX)

option(UWDEV_SANITIZERS "Build host tests with address/undefined sanitizers" OFF)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CODEC_DIR "${CMAKE_CURRENT_LIST_DIR}/../encoder-android/src/main/cpp/codec")

add_library(uwdev_mp3_codec STATIC
    "${CODEC_DIR}/encoder.cpp"
    "${CODEC_DIR}/dsp.cpp"
    "${CODEC_DIR}/resampler.cpp"
    "${CODEC_DIR}/mpeg.cpp")
target_sources(uwdev_mp3_codec PRIVATE "${CODEC_DIR}/synthesis.cpp")
target_include_directories(uwdev_mp3_codec PUBLIC "${CODEC_DIR}/..")
if(MSVC)
    target_compile_options(uwdev_mp3_codec PRIVATE /W4 /fp:precise)
else()
    target_compile_options(uwdev_mp3_codec PRIVATE
        -Wall -Wextra -Wpedantic -Wconversion -Wshadow -Wformat=2)
endif()

if(UWDEV_SANITIZERS)
    if(MSVC)
    target_compile_options(uwdev_mp3_codec PUBLIC /fsanitize=address /Zi)
    target_link_options(uwdev_mp3_codec PUBLIC /INCREMENTAL:NO)
    message(STATUS "MSVC: AddressSanitizer enabled; UndefinedBehaviorSanitizer is unavailable")
    else()
    target_compile_options(uwdev_mp3_codec PUBLIC -fsanitize=address,undefined -fno-omit-frame-pointer)
    target_link_options(uwdev_mp3_codec PUBLIC -fsanitize=address,undefined)
    endif()
endif()

find_package(Threads REQUIRED)
add_executable(mp3_encode encode_cli.cpp)
target_link_libraries(mp3_encode PRIVATE uwdev_mp3_codec Threads::Threads)
add_executable(codec_tests codec_tests.cpp)
target_link_libraries(codec_tests PRIVATE uwdev_mp3_codec Threads::Threads)
add_executable(dsp_checks dsp_checks.cpp)
add_executable(seeded_fuzz seeded_fuzz.cpp)
target_link_libraries(seeded_fuzz PRIVATE uwdev_mp3_codec Threads::Threads)
target_link_libraries(dsp_checks PRIVATE uwdev_mp3_codec)
target_include_directories(dsp_checks PRIVATE "${CODEC_DIR}")
enable_testing()
add_test(NAME codec_contracts COMMAND codec_tests)
add_test(NAME dsp_reconstruction_and_resampling COMMAND dsp_checks)
add_test(NAME deterministic_seeded_fuzz COMMAND seeded_fuzz)
if(UWDEV_SANITIZERS)
    # Instrumented quantization/reconstruction trials have substantial host overhead.
    set_tests_properties(deterministic_seeded_fuzz PROPERTIES TIMEOUT 1200)
else()
    set_tests_properties(deterministic_seeded_fuzz PROPERTIES TIMEOUT 300)
endif()
