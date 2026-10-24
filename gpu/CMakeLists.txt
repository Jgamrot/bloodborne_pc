# bbport GPU library: shadPS4 video core + shader recompiler + Gnm/VideoOut
# drivers, adapted to the native_probe runtime through shims in shim/.
cmake_minimum_required(VERSION 3.24)
project(bbgpu LANGUAGES C CXX)
set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
if (NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE RelWithDebInfo)
endif()
# Frame pointers keep the loader's thread dumps (watchdog, SIGUSR2 sampling) walkable.
add_compile_options(-fno-omit-frame-pointer)
# Newer libc++ (MSYS2 clang 23) no longer includes the C library headers transitively, and the
# vendored code (shadPS4, sirit, the FSR SDK) relies on it: std::abort, _countof, swprintf_s,
# log2, placement new. Include them everywhere instead of patching every vendored file.
if (WIN32)
    foreach(header stdlib.h wchar.h cstdlib cstring cmath new)
        add_compile_options("$<$<COMPILE_LANGUAGE:CXX>:SHELL:-include ${header}>")
    endforeach()
endif()

# bbport: link-time optimization (BB_LTO, default on) and profile-guided optimization
# (BB_PGO: off, generate = instrumented build writing into BB_PGO_DIR, use = build with that
# profile). Covers bbgpu and the static libraries linked into it. No -march: the same build
# runs on the Steam Deck.
option(BB_LTO "Link-time optimization of bbgpu" ON)
set(BB_PGO "off" CACHE STRING "Profile-guided optimization: off, generate, use")
set(BB_PGO_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../pgo" CACHE PATH "Profile directory")
if (BB_LTO)
    include(CheckIPOSupported)
    check_ipo_supported(RESULT bb_ipo_ok OUTPUT bb_ipo_error)
    if (bb_ipo_ok)
        set(CMAKE_INTERPROCEDURAL_OPTIMIZATION ON)
    else()
        message(WARNING "LTO unavailable: ${bb_ipo_error}")
    endif()
endif()
if (BB_PGO STREQUAL "generate")
    # Atomic counters: the GPU, recording, preparation and copy threads run the same code.
    add_compile_options(-fprofile-generate=${BB_PGO_DIR} -fprofile-update=atomic)
    add_link_options(-fprofile-generate=${BB_PGO_DIR})
    add_compile_definitions(BB_PGO_GENERATE)
elseif (BB_PGO STREQUAL "use")
    # Partial training keeps unprofiled code optimized normally; counters from concurrent
    # threads can be slightly inconsistent (correction). Functions changed since the profile
    # (or built differently for it, bbgpu_init) are compiled without it.
    add_compile_options(-fprofile-use=${BB_PGO_DIR} -fprofile-partial-training
                        -fprofile-correction -Wno-missing-profile -Wno-coverage-mismatch)
endif()

find_package(Vulkan REQUIRED)
find_package(fmt REQUIRED)
find_package(Boost REQUIRED)
# bbport (Windows): MSYS2 has no magic_enum/miniz packages; the submodules are used instead.
find_package(magic_enum QUIET)
if (NOT magic_enum_FOUND)
    add_library(magic_enum INTERFACE)
    add_library(magic_enum::magic_enum ALIAS magic_enum)
    target_include_directories(magic_enum INTERFACE third_party/magic_enum/include
                                                    third_party/magic_enum/include/magic_enum)
endif()
find_package(tsl-robin-map REQUIRED)
find_package(VulkanMemoryAllocator CONFIG QUIET)
if (NOT VulkanMemoryAllocator_FOUND)
    # MSYS2 ships the header (include/vma/vk_mem_alloc.h) without a CMake package.
    find_path(VMA_INCLUDE_DIR vk_mem_alloc.h PATH_SUFFIXES vma REQUIRED)
    add_library(VulkanMemoryAllocator INTERFACE)
    add_library(GPUOpen::VulkanMemoryAllocator ALIAS VulkanMemoryAllocator)
    target_include_directories(VulkanMemoryAllocator INTERFACE ${VMA_INCLUDE_DIR})
endif()
find_package(PkgConfig REQUIRED)
pkg_check_modules(XXHASH REQUIRED IMPORTED_TARGET libxxhash)
pkg_check_modules(SDL3 REQUIRED IMPORTED_TARGET sdl3)
if (NOT WIN32)
    pkg_check_modules(X11 REQUIRED IMPORTED_TARGET x11)
endif()
find_package(miniz QUIET)
if (NOT miniz_FOUND)
    set(BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
    set(BUILD_TESTS OFF CACHE BOOL "" FORCE)
    set(BUILD_FUZZERS OFF CACHE BOOL "" FORCE)
    set(BUILD_SHARED_LIBS OFF)
    set(CMAKE_POLICY_VERSION_MINIMUM 3.5)
    add_subdirectory(third_party/miniz EXCLUDE_FROM_ALL)
    unset(CMAKE_POLICY_VERSION_MINIMUM)
    add_library(miniz::miniz ALIAS miniz)
endif()
find_package(Zydis REQUIRED)
find_program(GLSLANG_COMPILER NAMES glslang glslangValidator REQUIRED)

set(SIRIT_USE_SYSTEM_SPIRV_HEADERS OFF CACHE BOOL "" FORCE)
add_subdirectory(third_party/sirit EXCLUDE_FROM_ALL)

# bbport: FSR 3.1 temporal upscaling / frame generation, native Vulkan (MIT, FireBurn/FSR-Vulkan).
set(FFX_VK_PORTABLE_BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(FFX_VK_PORTABLE_BUILD_PROBE OFF CACHE BOOL "" FORCE)
add_subdirectory(third_party/fsr-vulkan EXCLUDE_FROM_ALL)

# Host shaders -> headers (same scheme as shadPS4's host_shaders/CMakeLists.txt).
set(SHADER_SRC ${CMAKE_CURRENT_SOURCE_DIR}/shadps4/video_core/host_shaders)
set(SHADER_INCLUDE ${CMAKE_CURRENT_BINARY_DIR}/include)
set(SHADER_DIR ${SHADER_INCLUDE}/video_core/host_shaders)
set(SHADER_HEADERS "")
function(add_host_shader FILENAME SHADER_NAME)
    set(OUT ${SHADER_DIR}/${SHADER_NAME}.h)
    string(TOUPPER ${SHADER_NAME} SYMBOL)
    set(DEFINES ${ARGN})
    list(TRANSFORM DEFINES PREPEND "-D")
    add_custom_command(OUTPUT ${OUT}
        COMMAND ${CMAKE_COMMAND} -E make_directory ${SHADER_DIR}
        COMMAND ${GLSLANG_COMPILER} --target-env vulkan1.3 -o ${OUT} --vn ${SYMBOL} ${DEFINES} ${SHADER_SRC}/${FILENAME}
        COMMAND ${CMAKE_COMMAND} "-DHEADER_FILE=${OUT}" -P ${SHADER_SRC}/AddShaderHeaderInclude.cmake
        DEPENDS ${SHADER_SRC}/${FILENAME} VERBATIM)
    set(SHADER_HEADERS ${SHADER_HEADERS} ${OUT} PARENT_SCOPE)
endfunction()
add_host_shader(color_to_ms_depth.frag color_to_ms_depth_frag)
add_host_shader(ms_image_blit.frag ms_image_blit_frag)
add_host_shader(ms_image_blit.frag ms_image_blit_msaa_frag SRC_MSAA=1)
add_host_shader(fault_buffer_process.comp fault_buffer_process_comp)
add_host_shader(indirect_guard.comp indirect_guard_comp)
add_host_shader(fs_tri.vert fs_tri_vert)
add_host_shader(fsr.comp fsr_easu_comp SAMPLE_EASU=1)
add_host_shader(fsr.comp fsr_rcas_comp SAMPLE_RCAS=1)
add_host_shader(post_process.frag post_process_frag)
add_host_shader(camera_motion.comp camera_motion_comp)
add_host_shader(upscale_merge.comp upscale_merge_comp)
add_host_shader(upscale_reactive.comp upscale_reactive_comp)
add_host_shader(taa.comp taa_comp)
add_host_shader(taa_sharpen.comp taa_sharpen_comp)
add_host_shader(taa_sharpen.comp taa_sharpen_ldr_comp LDR_OUTPUT=1)
add_host_shader(buffer_multi_copy.comp buffer_multi_copy_comp)
add_host_shader(depth_resample.frag depth_resample_frag)
add_host_shader(depth_resample.frag depth_stencil_resample_frag HAS_STENCIL=1)
add_host_shader(depth_resample.frag depth_stencil_bits_frag STENCIL_BITS=1)
add_host_shader(camera_motion.comp camera_motion_debug_comp DEBUG_OVERLAY=1)
# Frame generation (vk_frame_generation.cpp): its depth input and the UI over generated frames.
add_host_shader(frame_gen_inputs.comp frame_gen_inputs_comp)
add_host_shader(frame_gen_ui.comp frame_gen_ui_comp)
foreach(BPP IN ITEMS 8 16 32 64 96 128)
    add_host_shader(tiling.comp tiling_micro_${BPP}_comp BITS_PER_PIXEL=${BPP} IS_MACRO_TILED=0)
    add_host_shader(tiling.comp tiling_macro_${BPP}_comp BITS_PER_PIXEL=${BPP} IS_MACRO_TILED=1)
endforeach()
add_custom_target(host_shaders DEPENDS ${SHADER_HEADERS})

file(GLOB_RECURSE VIDEO_CORE CONFIGURE_DEPENDS shadps4/video_core/*.cpp)
file(GLOB_RECURSE RECOMPILER CONFIGURE_DEPENDS shadps4/shader_recompiler/*.cpp)
list(FILTER VIDEO_CORE EXCLUDE REGEX "renderdoc\\.cpp$")
set(COMMON
    shadps4/common/decoder.cpp shadps4/common/error.cpp
    shadps4/common/io_file.cpp shadps4/common/native_clock.cpp shadps4/common/number_utils.cpp
    shadps4/common/path_util.cpp shadps4/common/rdtsc.cpp shadps4/common/spin_lock.cpp shadps4/common/recursive_lock.cpp
    shadps4/common/string_util.cpp shadps4/common/thread.cpp shadps4/common/signal_context.cpp
    shim/common/logging/log.cpp)
file(GLOB AVPLAYER CONFIGURE_DEPENDS shadps4/core/libraries/avplayer/*.cpp)
pkg_check_modules(FFMPEG REQUIRED IMPORTED_TARGET libavformat libavcodec libavutil libswscale libswresample)
file(GLOB SHIM_SOURCES CONFIGURE_DEPENDS shim/*.cpp shim/*/*.cpp)
# Windows: a DLL cannot leave the runtime_* symbols for bb-probe.exe to resolve, so the
# library is static there and linked into the executable.
if (WIN32)
    set(BBGPU_KIND STATIC)
else()
    set(BBGPU_KIND SHARED)
endif()
add_library(bbgpu ${BBGPU_KIND} ${VIDEO_CORE} ${RECOMPILER} ${COMMON} ${SHIM_SOURCES}
    shadps4/core/libraries/gnmdriver/gnmdriver.cpp
    shadps4/core/libraries/videoout/driver.cpp shadps4/core/libraries/videoout/video_out.cpp
    shadps4/core/libraries/kernel/equeue.cpp ${AVPLAYER}
    shadps4/core/libraries/videodec/video_utils.cpp)
add_dependencies(bbgpu host_shaders)
# bbport online: shadPS4 v.0.20.0's network, NP and shadNet sources (bbnet/vendor/shadps4,
# 529ceb3, with bbnet/vendor-changes.diff) and The Hunter's Dream backend (bbnet/thd, from
# droogie's bbhost), as Awaken (Awakenchan/BloodBorneButPc) put them together.
# See bbnet/SHADNET-PORT.md.
find_package(Protobuf CONFIG REQUIRED)
set(BBNET_VENDOR "${CMAKE_CURRENT_SOURCE_DIR}/bbnet/vendor/shadps4")
set(SHADNET_PROTO_OUT "${CMAKE_CURRENT_BINARY_DIR}/shadnet_proto_gen")
file(MAKE_DIRECTORY "${SHADNET_PROTO_OUT}")
add_custom_command(
    OUTPUT "${SHADNET_PROTO_OUT}/shadnet.pb.cc" "${SHADNET_PROTO_OUT}/shadnet.pb.h"
    COMMAND protobuf::protoc "--proto_path=${BBNET_VENDOR}/shadnet"
            "--cpp_out=${SHADNET_PROTO_OUT}" "${BBNET_VENDOR}/shadnet/shadnet.proto"
    DEPENDS "${BBNET_VENDOR}/shadnet/shadnet.proto")
file(GLOB_RECURSE BBNET_SOURCES CONFIGURE_DEPENDS
    bbnet/vendor/shadps4/core/libraries/net/*.cpp bbnet/vendor/shadps4/core/libraries/network/*.cpp
    bbnet/vendor/shadps4/core/libraries/np/*.cpp bbnet/vendor/shadps4/core/net/*.cpp
    bbnet/vendor/shadps4/shadnet/*.cpp)
# Trophies, commerce and the profile and Facebook dialogs stay in the C runtime.
list(FILTER BBNET_SOURCES EXCLUDE REGEX
    "np_trophy|trophy_ui|np_sns_facebook_dialog|np_profile_dialog/|np_commerce/")
file(GLOB BBNET_THD_SOURCES CONFIGURE_DEPENDS bbnet/thd/*.cpp)
find_package(nlohmann_json CONFIG REQUIRED)
add_library(bbnet STATIC ${BBNET_SOURCES} ${BBNET_THD_SOURCES} "${SHADNET_PROTO_OUT}/shadnet.pb.cc"
    bbnet/bbnet_glue.cpp)
target_include_directories(bbnet PRIVATE bbnet/include bbnet shim "${BBNET_VENDOR}"
    "${BBNET_VENDOR}/shadnet" shadps4 "${SHADNET_PROTO_OUT}" third_party/imgui third_party/httplib)
target_link_libraries(bbnet PRIVATE nlohmann_json::nlohmann_json)
# HTTPS (the community game server only speaks TLS) and gzip replies in cpp-httplib.
find_package(OpenSSL REQUIRED)
find_package(ZLIB REQUIRED)
target_compile_definitions(bbnet PRIVATE CPPHTTPLIB_OPENSSL_SUPPORT CPPHTTPLIB_ZLIB_SUPPORT)
# OpenSSL verifies the server's chain (with the Windows ROOT and CA stores) and the host name.
# cpp-httplib's second check on Windows rebuilt the chain from the leaf alone and could pick an
# expired cross-signed "ISRG Root X2" from the user's intermediate store: "SSL server
# verification failed" (error 10) for The Hunter's Dream on some PCs.
target_compile_definitions(bbnet PRIVATE CPPHTTPLIB_DISABLE_WINDOWS_AUTOMATIC_ROOT_CERTIFICATES_UPDATE)
target_link_libraries(bbnet PRIVATE OpenSSL::SSL OpenSSL::Crypto ZLIB::ZLIB)
if (WIN32)
    target_sources(bbnet PRIVATE third_party/wepoll/wepoll.c)
    target_include_directories(bbnet PRIVATE third_party/wepoll)
    find_path(MINIUPNPC_INCLUDE miniupnpc.h PATH_SUFFIXES miniupnpc REQUIRED)
    find_library(MINIUPNPC_LIBRARY NAMES libminiupnpc.a miniupnpc REQUIRED)
    target_include_directories(bbnet PRIVATE "${MINIUPNPC_INCLUDE}")
    target_compile_definitions(bbnet PRIVATE MINIUPNP_STATICLIB)
    target_link_libraries(bbnet PRIVATE "${MINIUPNPC_LIBRARY}")
endif()
target_compile_definitions(bbnet PRIVATE BOOST_ASIO_STANDALONE NDEBUG)
target_compile_options(bbnet PRIVATE -Wno-deprecated-declarations -Wno-missing-field-initializers)
target_link_libraries(bbnet PUBLIC Vulkan::Headers fmt::fmt Boost::headers magic_enum::magic_enum
    protobuf::libprotobuf)
if (WIN32)
    target_compile_definitions(bbnet PUBLIC NOMINMAX WIN32_LEAN_AND_MEAN)
    target_compile_options(bbnet PRIVATE
        "$<$<COMPILE_LANGUAGE:CXX>:SHELL:-include \"${CMAKE_CURRENT_SOURCE_DIR}/bbnet/include/bb_win_compat.h\">")
    target_link_libraries(bbnet PUBLIC ws2_32 iphlpapi bcrypt crypt32)
endif()
target_link_libraries(bbgpu PUBLIC bbnet)
# In-game settings menu: Dear ImGui (third_party/imgui, MIT) with its Vulkan backend, and an
# embedded Cyrillic font (third_party/fonts).
target_sources(bbgpu PRIVATE third_party/imgui/imgui.cpp third_party/imgui/imgui_draw.cpp
    third_party/imgui/imgui_tables.cpp third_party/imgui/imgui_widgets.cpp
    third_party/imgui/backends/imgui_impl_vulkan.cpp)
target_include_directories(bbgpu PRIVATE third_party/imgui third_party/imgui/backends)
target_compile_definitions(bbgpu PRIVATE IMGUI_IMPL_VULKAN_NO_PROTOTYPES
    BB_FONT_PATH="${CMAKE_CURRENT_SOURCE_DIR}/third_party/fonts/DejaVuSans.ttf")
set_source_files_properties(shim/bbport_overlay.cpp PROPERTIES
    OBJECT_DEPENDS ${CMAKE_CURRENT_SOURCE_DIR}/third_party/fonts/DejaVuSans.ttf)
target_include_directories(bbgpu PRIVATE shim shadps4 ${SHADER_INCLUDE} third_party/gcn/include third_party/half/include)
target_compile_definitions(bbgpu PRIVATE BOOST_ASIO_STANDALONE NDEBUG)
target_compile_options(bbgpu PRIVATE -Wno-deprecated-declarations -Wno-missing-field-initializers)
# Runtime symbols (runtime_memory_*, runtime_process_*) resolve against bb-probe.
if (NOT WIN32)
    target_link_options(bbgpu PRIVATE -Wl,--allow-shlib-undefined)
endif()
target_link_libraries(bbgpu PRIVATE ffx-vulkan::portable ffx-vulkan::fsr4-v07-vulkan
    ffx-vulkan::fsr3-vk-framegeneration-3.1.6)
target_link_libraries(bbgpu PUBLIC Vulkan::Headers fmt::fmt Boost::headers magic_enum::magic_enum
    tsl::robin_map GPUOpen::VulkanMemoryAllocator PkgConfig::XXHASH PkgConfig::SDL3 PkgConfig::FFMPEG miniz::miniz Zydis::Zydis sirit)
if (WIN32)
    # Guest code is entered with the System V ABI; NOMINMAX/WIN32_LEAN_AND_MEAN keep
    # <windows.h> out of the way of std::min/max and the Vulkan/SDL headers.
    target_compile_definitions(bbgpu PUBLIC NOMINMAX WIN32_LEAN_AND_MEAN)
    # Quoted: the build works from a folder with spaces in its path (after PR #72).
    target_compile_options(bbgpu PRIVATE
        "SHELL:-include \"${CMAKE_CURRENT_SOURCE_DIR}/shim/bb_win_compat.h\"")
    target_include_directories(bbgpu PRIVATE third_party/xbyak)
    target_link_libraries(bbgpu PUBLIC Vulkan::Vulkan ws2_32 bcrypt ntdll synchronization winmm)
else()
    target_link_libraries(bbgpu PUBLIC PkgConfig::X11)
endif()

# bbport (Windows): bbgpu is a static library there, so the loader and the HLE runtime are
# linked here, where CMake knows its dependencies (build.sh builds them with ninja).
if (WIN32)
    enable_language(RC)
    file(GLOB BB_RUNTIME CONFIGURE_DEPENDS ../src/runtime*.c)
    file(GLOB BB_ATRAC9 CONFIGURE_DEPENDS ../third_party/LibAtrac9/C/src/*.c)
    add_library(atrac9 STATIC ${BB_ATRAC9})
    target_compile_options(atrac9 PRIVATE -w)
    set_target_properties(atrac9 PROPERTIES C_STANDARD 99 INTERPROCEDURAL_OPTIMIZATION OFF)
    add_executable(bb-probe ../src/probe.c ${BB_RUNTIME} ../src/compat_win.c ../src/vulkan_smoke.c ../src/cloth_rate.c
        ../src/engine_hooks.c ../src/engine_features.c ../src/pc_menu.c ../src/rebirth.c ../src/input_bindings.c ../src/mouse_camera.c ../src/key_prompts.c ../src/menu_pointer.c
        ../src/occlusion_queries.c ../src/wind_pace.c ../src/frame_time.c ../packaging/windows/bb-probe.rc)
    target_sources(bb-probe PRIVATE ../src/aspect_ratio.cpp)
    target_compile_definitions(bb-probe PRIVATE NOMINMAX WIN32_LEAN_AND_MEAN)
    set_target_properties(bb-probe PROPERTIES C_STANDARD 11 C_EXTENSIONS OFF)
    target_compile_options(bb-probe PRIVATE $<$<COMPILE_LANGUAGE:C>:-Wall -Wextra -Werror>)
    target_include_directories(bb-probe PRIVATE .. ../src)
    target_link_libraries(bb-probe PRIVATE bbgpu atrac9 onecore bcrypt ws2_32 -pthread)
    # The PS4 range (64 GiB - 1 TiB) must stay free: no high-entropy ASLR for heaps and stacks.
    # The guest main thread runs on the process stack: 16 MiB, committed (no stack probes).
    target_link_options(bb-probe PRIVATE -Wl,--disable-high-entropy-va "SHELL:-Xlinker --stack -Xlinker 16777216,16777216")
    add_executable(bb-gpu-capabilities ../tools/gpu_capabilities.c ../packaging/windows/bb-gpu-capabilities.rc)
    target_link_libraries(bb-gpu-capabilities PRIVATE Vulkan::Vulkan)
    # "Play Bloodborne.exe": the game with the launcher's saved settings, no launcher window.
    add_executable(bb-play WIN32 ../packaging/windows/play.c ../packaging/windows/play.rc)
    target_compile_options(bb-play PRIVATE -municode)
    target_link_options(bb-play PRIVATE -municode)
endif()

# Explicit test targets; neither launches the game nor needs a Vulkan device.
add_executable(trophy-data-test EXCLUDE_FROM_ALL ../tests/test_trophy_data.cpp
    shim/bbport_trophies.cpp)
target_include_directories(trophy-data-test PRIVATE shadps4 shim)
target_compile_options(trophy-data-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
add_executable(trophy-toast-test EXCLUDE_FROM_ALL ../tests/test_trophy_toast.cpp
    shim/bbport_trophy_toast_model.cpp shim/bbport_trophy_media.cpp)
target_include_directories(trophy-toast-test PRIVATE shim)
target_compile_options(trophy-toast-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_link_libraries(trophy-toast-test PRIVATE PkgConfig::FFMPEG)
if (WIN32)
    add_executable(trophy-history-test EXCLUDE_FROM_ALL ../tests/test_runtime_trophies.c
        ../src/runtime_trophies.c)
    target_include_directories(trophy-history-test PRIVATE .. ../src)
    target_compile_options(trophy-history-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
    target_link_libraries(trophy-history-test PRIVATE -pthread)
    add_executable(cloth-rate-test EXCLUDE_FROM_ALL ../tests/test_cloth_rate.c ../src/engine_hooks.c)
    target_include_directories(cloth-rate-test PRIVATE ../src)
    target_compile_options(cloth-rate-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
    add_executable(respawn-patch-test EXCLUDE_FROM_ALL ../tests/test_respawn_patch.c)
    target_include_directories(respawn-patch-test PRIVATE ../src)
    target_compile_options(respawn-patch-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
    add_executable(input-bindings-test EXCLUDE_FROM_ALL ../tests/test_input_bindings.c ../src/input_bindings.c)
    target_include_directories(input-bindings-test PRIVATE ../src)
    target_compile_options(input-bindings-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
    target_link_libraries(input-bindings-test PRIVATE PkgConfig::SDL3)
    add_executable(pad-test EXCLUDE_FROM_ALL ../tests/test_pad.c ../src/input_bindings.c)
    target_include_directories(pad-test PRIVATE .. ../src)
    target_compile_options(pad-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
    target_link_libraries(pad-test PRIVATE PkgConfig::SDL3 -pthread)
    add_executable(engine-hooks-test EXCLUDE_FROM_ALL ../tests/test_engine_hooks.c ../src/engine_hooks.c)
    target_include_directories(engine-hooks-test PRIVATE ../src)
    target_compile_options(engine-hooks-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
    add_executable(wind-pace-test EXCLUDE_FROM_ALL ../tests/test_wind_pace.c ../src/engine_hooks.c)
    target_include_directories(wind-pace-test PRIVATE ../src)
    target_compile_options(wind-pace-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
    add_executable(frame-time-test EXCLUDE_FROM_ALL ../tests/test_frame_time.c ../src/frame_time.c ../src/wind_pace.c
        ../src/cloth_rate.c ../src/engine_hooks.c)
    target_include_directories(frame-time-test PRIVATE ../src)
    target_compile_options(frame-time-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
    # Issue #6: pread from one thread, lseek + read from another, on one descriptor.
    add_executable(file-offsets-test EXCLUDE_FROM_ALL ../tests/test_file_offsets.c ../src/compat_win.c)
    target_include_directories(file-offsets-test PRIVATE ../src)
    target_compile_options(file-offsets-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
    target_link_libraries(file-offsets-test PRIVATE -pthread bcrypt)
endif()

add_executable(shader-user-data-test EXCLUDE_FROM_ALL ../tests/test_shader_user_data.cpp)
target_compile_options(shader-user-data-test PRIVATE -UNDEBUG)
target_include_directories(shader-user-data-test PRIVATE shim shadps4 third_party/gcn/include)
target_link_libraries(shader-user-data-test PRIVATE fmt::fmt Boost::headers)

# The in-game guide drawn offscreen (tools/overlay_preview.cpp): its own code through ImGui's SDL
# software renderer, for working on its look without the game.
add_executable(overlay-preview EXCLUDE_FROM_ALL tools/overlay_preview.cpp
    third_party/imgui/backends/imgui_impl_sdlrenderer3.cpp)
# The guide's source is compiled here as in the library: same definitions, includes and options.
target_include_directories(overlay-preview PRIVATE $<TARGET_PROPERTY:bbgpu,INCLUDE_DIRECTORIES>)
target_compile_definitions(overlay-preview PRIVATE $<TARGET_PROPERTY:bbgpu,COMPILE_DEFINITIONS>)
target_compile_options(overlay-preview PRIVATE $<TARGET_PROPERTY:bbgpu,COMPILE_OPTIONS>)
target_link_libraries(overlay-preview PRIVATE bbgpu)
if(WIN32)
    target_sources(overlay-preview PRIVATE ../src/compat_win.c)
    target_link_libraries(overlay-preview PRIVATE bcrypt onecore ws2_32 -pthread)
endif()
add_executable(stage-point-test EXCLUDE_FROM_ALL ../tests/test_stage_point.cpp)
target_compile_options(stage-point-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(stage-point-test PRIVATE shim)

add_executable(srt-walker-test EXCLUDE_FROM_ALL ../tests/test_srt_walker.cpp)
target_compile_options(srt-walker-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(srt-walker-test PRIVATE $<TARGET_PROPERTY:bbgpu,INCLUDE_DIRECTORIES>)

add_executable(motion-history-test EXCLUDE_FROM_ALL ../tests/test_motion_history.cpp)
target_compile_options(motion-history-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(motion-history-test PRIVATE ..)
add_executable(motion-shader-test EXCLUDE_FROM_ALL ../tests/test_motion_shaders.cpp ../tests/test_gpu_runtime_stubs.cpp)
target_include_directories(motion-shader-test PRIVATE shim shadps4 third_party/gcn/include)
target_link_libraries(motion-shader-test PRIVATE bbgpu)
add_executable(ui-composition-test EXCLUDE_FROM_ALL ../tests/test_ui_composition.cpp)
target_compile_options(ui-composition-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(ui-composition-test PRIVATE ..)

add_executable(scene-resolution-test EXCLUDE_FROM_ALL ../tests/test_scene_resolution.cpp ../tests/test_gpu_runtime_stubs.cpp)
target_include_directories(scene-resolution-test PRIVATE shim shadps4 third_party/gcn/include)
# The test's Vulkan-Hpp inline methods have a different set of platform extensions
# from vk_platform.cpp. Keep them local and use an explicit dispatcher in the test.
target_compile_options(scene-resolution-test PRIVATE -UNDEBUG -fPIC)
set_source_files_properties(../tests/test_scene_resolution.cpp PROPERTIES
    COMPILE_OPTIONS "-fvisibility=hidden;-fvisibility-inlines-hidden")
target_link_libraries(scene-resolution-test PRIVATE bbgpu)
add_executable(taa-shader-test EXCLUDE_FROM_ALL ../tests/test_taa_shader.cpp ../tests/test_gpu_runtime_stubs.cpp)
target_include_directories(taa-shader-test PRIVATE shim shadps4 ${SHADER_INCLUDE} third_party/gcn/include)
target_compile_options(taa-shader-test PRIVATE -UNDEBUG -fPIC)
set_source_files_properties(../tests/test_taa_shader.cpp PROPERTIES
    COMPILE_OPTIONS "-fvisibility=hidden;-fvisibility-inlines-hidden")
target_link_libraries(taa-shader-test PRIVATE bbgpu)
add_dependencies(taa-shader-test host_shaders)

add_executable(camera-motion-test EXCLUDE_FROM_ALL ../tests/test_camera_motion.cpp ../tests/test_gpu_runtime_stubs.cpp)
target_include_directories(camera-motion-test PRIVATE shim shadps4 ${SHADER_INCLUDE} third_party/gcn/include)
target_compile_options(camera-motion-test PRIVATE -UNDEBUG -fPIC)
target_link_libraries(camera-motion-test PRIVATE bbgpu)
add_dependencies(camera-motion-test host_shaders)

# bbport: FSR 4 benchmark outside the game (tools/fsr4_bench.cpp): ninja -C out/gpu fsr4-bench.
add_executable(upscaler-support-test EXCLUDE_FROM_ALL ../tests/test_upscaler_support.cpp
    shim/bbport_settings.cpp)
target_include_directories(upscaler-support-test PRIVATE shim)
target_compile_options(upscaler-support-test PRIVATE -UNDEBUG)

add_executable(fsr4-bench EXCLUDE_FROM_ALL tools/fsr4_bench.cpp
    shadps4/video_core/renderer_vulkan/fsr411/fsr411.cpp)
target_include_directories(fsr4-bench PRIVATE shadps4/video_core/renderer_vulkan/fsr411)
target_link_libraries(fsr4-bench PRIVATE ffx-vulkan::fsr4-v07-vulkan ffx-vulkan::fsr4-v07-assets Vulkan::Vulkan)

add_executable(output-settings-test EXCLUDE_FROM_ALL ../tests/test_output_settings.cpp
    shim/bbport_settings.cpp)
target_include_directories(output-settings-test PRIVATE shim)
target_compile_options(output-settings-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)

if (WIN32)
    add_executable(aspect-thunk-test EXCLUDE_FROM_ALL ../tests/test_aspect_thunk.cpp)
    target_compile_options(aspect-thunk-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
    target_include_directories(aspect-thunk-test PRIVATE ..)
endif()

# bbport shader pre-build, offline check: translates the shader permutations of a pipeline cache
# from the program code in the player's own game files (scripts/shader_code.py) and compares.
add_executable(bb-shader-prebuild EXCLUDE_FROM_ALL tools/shader_prebuild.cpp ../tests/test_gpu_runtime_stubs.cpp)
target_include_directories(bb-shader-prebuild PRIVATE shim shadps4 third_party/gcn/include)
target_link_libraries(bb-shader-prebuild PRIVATE bbgpu $<$<BOOL:${WIN32}>:onecore>)
