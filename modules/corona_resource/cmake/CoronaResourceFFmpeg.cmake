# =============================================================================
# CoronaResource FFmpeg Integration
#
# FFmpeg uses an autotools build and cannot be compiled from source via CMake's
# FetchContent. Instead we consume prebuilt LGPL shared libraries:
#
#   * Windows : download the BtbN prebuilt "win64-lgpl-shared" package and wrap
#               the resulting DLL/import-lib pairs in IMPORTED SHARED targets so
#               the existing runtime-DLL copy machinery distributes them.
#   * Other   : locate a system / user-provided FFmpeg dev package.
#
# Override the auto-download by pointing CORONA_RESOURCE_FFMPEG_ROOT at a
# directory that contains include/, lib/ and (on Windows) bin/ subdirectories.
# =============================================================================

include_guard(GLOBAL)

include(FetchContent)

set(CORONA_RESOURCE_FFMPEG_ROOT "" CACHE PATH
    "Path to a prebuilt FFmpeg dev package (include/ + lib/ [+ bin/]). Leave empty to auto-fetch on Windows.")

set(_CORONA_RESOURCE_FFMPEG_DEFAULT_DOWNLOAD_DIR "${CMAKE_SOURCE_DIR}/third_party/ffmpeg/download")
set(_CORONA_RESOURCE_FFMPEG_DEFAULT_SOURCE_DIR "${CMAKE_SOURCE_DIR}/third_party/ffmpeg/src")

set(CORONA_RESOURCE_FFMPEG_DOWNLOAD_DIR "${_CORONA_RESOURCE_FFMPEG_DEFAULT_DOWNLOAD_DIR}" CACHE PATH
    "Directory used to cache the downloaded FFmpeg archive.")

set(CORONA_RESOURCE_FFMPEG_SOURCE_DIR "${_CORONA_RESOURCE_FFMPEG_DEFAULT_SOURCE_DIR}" CACHE PATH
    "Directory used to cache the extracted FFmpeg package.")

set(_CORONA_RESOURCE_FFMPEG_LEGACY_DOWNLOAD_DIR "${PROJECT_SOURCE_DIR}/third_party/ffmpeg/download")
set(_CORONA_RESOURCE_FFMPEG_LEGACY_SOURCE_DIR "${PROJECT_SOURCE_DIR}/third_party/ffmpeg/src")
if(NOT _CORONA_RESOURCE_FFMPEG_LEGACY_SOURCE_DIR STREQUAL _CORONA_RESOURCE_FFMPEG_DEFAULT_SOURCE_DIR
        AND CORONA_RESOURCE_FFMPEG_SOURCE_DIR STREQUAL _CORONA_RESOURCE_FFMPEG_LEGACY_SOURCE_DIR
        AND EXISTS "${_CORONA_RESOURCE_FFMPEG_DEFAULT_SOURCE_DIR}")
    set(CORONA_RESOURCE_FFMPEG_DOWNLOAD_DIR "${_CORONA_RESOURCE_FFMPEG_DEFAULT_DOWNLOAD_DIR}" CACHE PATH
        "Directory used to cache the downloaded FFmpeg archive." FORCE)
    set(CORONA_RESOURCE_FFMPEG_SOURCE_DIR "${_CORONA_RESOURCE_FFMPEG_DEFAULT_SOURCE_DIR}" CACHE PATH
        "Directory used to cache the extracted FFmpeg package." FORCE)
endif()

# BtbN rolling LGPL shared build. Pin to a different asset/URL if reproducibility
# across machines matters more than tracking upstream.
set(CORONA_RESOURCE_FFMPEG_URL
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-lgpl-shared.zip"
    CACHE STRING "URL of the prebuilt FFmpeg package to download on Windows")

# The five libraries we actually link against.
set(_CORONA_FFMPEG_COMPONENTS avutil avcodec avformat swscale swresample)

# -----------------------------------------------------------------------------
# Resolve the FFmpeg root directory (the folder holding include/ lib/ [bin/]).
# -----------------------------------------------------------------------------
set(_corona_ffmpeg_root "")

if(CORONA_RESOURCE_FFMPEG_ROOT)
    set(_corona_ffmpeg_root "${CORONA_RESOURCE_FFMPEG_ROOT}")
    message(STATUS "[FFmpeg] Using user-provided root: ${_corona_ffmpeg_root}")
elseif(WIN32)
    file(GLOB_RECURSE _corona_ffmpeg_cached_avcodec_hdr
        "${CORONA_RESOURCE_FFMPEG_SOURCE_DIR}/*/include/libavcodec/avcodec.h"
        "${CORONA_RESOURCE_FFMPEG_SOURCE_DIR}/include/libavcodec/avcodec.h")

    if(_corona_ffmpeg_cached_avcodec_hdr)
        list(GET _corona_ffmpeg_cached_avcodec_hdr 0 _corona_ffmpeg_hdr)
        get_filename_component(_corona_ffmpeg_inc "${_corona_ffmpeg_hdr}" DIRECTORY)
        get_filename_component(_corona_ffmpeg_inc "${_corona_ffmpeg_inc}" DIRECTORY)
        get_filename_component(_corona_ffmpeg_root "${_corona_ffmpeg_inc}" DIRECTORY)
        message(STATUS "[FFmpeg] Using cached prebuilt root: ${_corona_ffmpeg_root}")
    else()
        message(STATUS "[FFmpeg] Fetching prebuilt package: ${CORONA_RESOURCE_FFMPEG_URL}")
        FetchContent_Declare(
            ffmpeg_prebuilt
            URL "${CORONA_RESOURCE_FFMPEG_URL}"
            DOWNLOAD_DIR "${CORONA_RESOURCE_FFMPEG_DOWNLOAD_DIR}"
            SOURCE_DIR "${CORONA_RESOURCE_FFMPEG_SOURCE_DIR}"
            DOWNLOAD_EXTRACT_TIMESTAMP TRUE
        )
        FetchContent_MakeAvailable(ffmpeg_prebuilt)

        # BtbN archives wrap everything in a single top-level directory; locate the
        # actual root by searching for a known header.
        file(GLOB_RECURSE _corona_ffmpeg_avcodec_hdr
            "${ffmpeg_prebuilt_SOURCE_DIR}/*/include/libavcodec/avcodec.h"
            "${ffmpeg_prebuilt_SOURCE_DIR}/include/libavcodec/avcodec.h")
        if(_corona_ffmpeg_avcodec_hdr)
            list(GET _corona_ffmpeg_avcodec_hdr 0 _corona_ffmpeg_hdr)
            # .../<root>/include/libavcodec/avcodec.h -> <root>
            get_filename_component(_corona_ffmpeg_inc "${_corona_ffmpeg_hdr}" DIRECTORY)
            get_filename_component(_corona_ffmpeg_inc "${_corona_ffmpeg_inc}" DIRECTORY)
            get_filename_component(_corona_ffmpeg_root "${_corona_ffmpeg_inc}" DIRECTORY)
        endif()
    endif()
    message(STATUS "[FFmpeg] Prebuilt root: ${_corona_ffmpeg_root}")
endif()

# -----------------------------------------------------------------------------
# Build the imported targets.
# -----------------------------------------------------------------------------
if(_corona_ffmpeg_root)
    set(_corona_ffmpeg_inc_dir "${_corona_ffmpeg_root}/include")

    foreach(_comp IN LISTS _CORONA_FFMPEG_COMPONENTS)
        if(WIN32)
            # Windows: DLL in bin/, import library in lib/.
            file(GLOB _impl "${_corona_ffmpeg_root}/lib/${_comp}.lib"
                            "${_corona_ffmpeg_root}/lib/lib${_comp}.dll.a")
            file(GLOB _dll  "${_corona_ffmpeg_root}/bin/${_comp}-*.dll"
                            "${_corona_ffmpeg_root}/bin/lib${_comp}-*.dll"
                            "${_corona_ffmpeg_root}/bin/${_comp}.dll")
            if(NOT _impl)
                message(FATAL_ERROR "[FFmpeg] Import library for '${_comp}' not found under ${_corona_ffmpeg_root}/lib")
            endif()
            list(GET _impl 0 _impl)
            add_library(ffmpeg::${_comp} SHARED IMPORTED GLOBAL)
            set_target_properties(ffmpeg::${_comp} PROPERTIES
                IMPORTED_IMPLIB "${_impl}"
                INTERFACE_INCLUDE_DIRECTORIES "${_corona_ffmpeg_inc_dir}")
            if(_dll)
                list(GET _dll 0 _dll)
                set_target_properties(ffmpeg::${_comp} PROPERTIES IMPORTED_LOCATION "${_dll}")
            endif()
        else()
            # Unix: a single .so/.dylib (or static .a) under lib/.
            file(GLOB _lib "${_corona_ffmpeg_root}/lib/lib${_comp}.so"
                           "${_corona_ffmpeg_root}/lib/lib${_comp}.dylib"
                           "${_corona_ffmpeg_root}/lib/lib${_comp}.a")
            if(NOT _lib)
                message(FATAL_ERROR "[FFmpeg] Library for '${_comp}' not found under ${_corona_ffmpeg_root}/lib")
            endif()
            list(GET _lib 0 _lib)
            add_library(ffmpeg::${_comp} UNKNOWN IMPORTED GLOBAL)
            set_target_properties(ffmpeg::${_comp} PROPERTIES
                IMPORTED_LOCATION "${_lib}"
                INTERFACE_INCLUDE_DIRECTORIES "${_corona_ffmpeg_inc_dir}")
        endif()
    endforeach()

    set(CORONA_RESOURCE_HAVE_FFMPEG TRUE CACHE INTERNAL "FFmpeg targets are available")
else()
    # Last resort: try to discover a system install through pkg-config.
    find_package(PkgConfig QUIET)
    if(PkgConfig_FOUND)
        pkg_check_modules(FFMPEG QUIET IMPORTED_TARGET
            libavformat libavcodec libavutil libswscale libswresample)
    endif()

    if(TARGET PkgConfig::FFMPEG)
        message(STATUS "[FFmpeg] Using system FFmpeg via pkg-config")
        foreach(_comp IN LISTS _CORONA_FFMPEG_COMPONENTS)
            add_library(ffmpeg::${_comp} INTERFACE IMPORTED GLOBAL)
            target_link_libraries(ffmpeg::${_comp} INTERFACE PkgConfig::FFMPEG)
        endforeach()
        set(CORONA_RESOURCE_HAVE_FFMPEG TRUE CACHE INTERNAL "FFmpeg targets are available")
    else()
        message(WARNING
            "[FFmpeg] No FFmpeg found. Set CORONA_RESOURCE_FFMPEG_ROOT to a prebuilt "
            "dev package, or install FFmpeg dev packages discoverable by pkg-config. "
            "Video/Audio import/export will be disabled.")
        set(CORONA_RESOURCE_HAVE_FFMPEG FALSE CACHE INTERNAL "FFmpeg targets are available")
    endif()
endif()

# Convenience aggregate target consumers can link against.
if(CORONA_RESOURCE_HAVE_FFMPEG)
    add_library(corona_ffmpeg INTERFACE)
    foreach(_comp IN LISTS _CORONA_FFMPEG_COMPONENTS)
        target_link_libraries(corona_ffmpeg INTERFACE ffmpeg::${_comp})
    endforeach()
    add_library(corona::ffmpeg ALIAS corona_ffmpeg)
endif()

# -----------------------------------------------------------------------------
# Helper: copy every runtime DLL an executable transitively depends on (FFmpeg,
# TBB, ...) next to the built binary. Relies on CMake's $<TARGET_RUNTIME_DLLS>,
# which resolves IMPORTED SHARED targets reached through INTERFACE link chains —
# something the property-walking copy in CoronaRuntime.cmake misses for our
# IMPORTED FFmpeg targets.
# -----------------------------------------------------------------------------
function(corona_resource_copy_runtime_dlls target_name)
    if(NOT WIN32)
        return()
    endif()
    add_custom_command(TARGET ${target_name} POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E copy_if_different
            "$<TARGET_RUNTIME_DLLS:${target_name}>" "$<TARGET_FILE_DIR:${target_name}>"
        COMMAND_EXPAND_LISTS
        VERBATIM)
endfunction()

