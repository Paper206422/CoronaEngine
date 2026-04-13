# ============================================================================== 
# CoronaEngine - Root CMake Configuration
#
# Responsibilities:
#   - Coordinate the build using modular helper scripts located in misc/cmake.
#   - Register project-wide options, toolchains, third-party dependencies, and
#     runtime asset staging helpers.
#   - Add subdirectories in module order: src -> engine -> examples.
# ============================================================================== 

cmake_minimum_required(VERSION 4.0)

list(APPEND CMAKE_MODULE_PATH "${CMAKE_CURRENT_SOURCE_DIR}/misc/cmake")

set_property(GLOBAL PROPERTY USE_FOLDERS ON)

# ------------------------------------------------------------------------------
# Project Declaration
# ------------------------------------------------------------------------------
project(
    CoronaEngine
    VERSION      0.5.0
    HOMEPAGE_URL "https://github.com/CoronaEngine/CoronaEngine"
    LANGUAGES    C CXX
)

# ------------------------------------------------------------------------------
# Modular Configuration Includes
# ------------------------------------------------------------------------------
include(corona_options)             # Global build options (editor/examples/runtime switches)
include(corona_python)              # Embedded Python discovery and dependency checks
include(corona_third_party)         # FetchContent declarations for external dependencies
include(corona_compile_config)      # Compiler settings, standards, and shared definitions
include(corona_add_system)          # Helper for adding system modules
include(corona_runtime_deps)        # Runtime dependency collection and copy helpers
include(corona_editor)              # Editor asset packaging helpers
include(corona_cef)

# ------------------------------------------------------------------------------
# Testing Support
# ------------------------------------------------------------------------------
include(CTest)

# ------------------------------------------------------------------------------
# Subdirectories
# ------------------------------------------------------------------------------
add_subdirectory(src)               # Core engine static library

if(BUILD_CORONA_EXAMPLES)
    add_subdirectory(examples)      # Example applications
endif()

# ------------------------------------------------------------------------------
# Copy sync-deps.bat to _deps directory
# ------------------------------------------------------------------------------
# Use FETCHCONTENT_BASE_DIR if set, otherwise fall back to ${CMAKE_BINARY_DIR}/_deps
if(FETCHCONTENT_BASE_DIR)
    set(_DEPS_DIR "${FETCHCONTENT_BASE_DIR}")
else()
    set(_DEPS_DIR "${CMAKE_BINARY_DIR}/_deps")
endif()

if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/sync-deps.bat")
    file(COPY "${CMAKE_CURRENT_SOURCE_DIR}/sync-deps.bat"
         DESTINATION "${_DEPS_DIR}")
    message(STATUS "Copied sync-deps.bat to ${_DEPS_DIR}")
endif()

# ------------------------------------------------------------------------------
# Configuration Summary
# ------------------------------------------------------------------------------
message(STATUS "")
message(STATUS "================================================================================")
message(STATUS "  CoronaEngine Configuration Summary")
message(STATUS "================================================================================")
message(STATUS "  Python executable     : ${Python_EXECUTABLE}")

if(Python_VERSION)
    message(STATUS "  Python version        : ${Python_VERSION}")
endif()

message(STATUS "  Build runtime         : ${BUILD_CORONA_RUNTIME}")
message(STATUS "  Build examples        : ${BUILD_CORONA_EXAMPLES}")
message(STATUS "  Build editor          : ${BUILD_CORONA_EDITOR}")
message(STATUS "  Auto install deps     : ${CORONA_AUTO_INSTALL_PY_DEPS}")
message(STATUS "================================================================================")
message(STATUS "")
