cmake_minimum_required(VERSION 4.0)

# Project definition
project(CoronaResource
    VERSION 0.5.0
    DESCRIPTION "CoronaResource: Multi-format 3D scene parsing and import library"
    LANGUAGES CXX
)

message(STATUS "Install prefix: ${CMAKE_INSTALL_PREFIX}")
# Add CMake modules path
list(APPEND CMAKE_MODULE_PATH "${CMAKE_CURRENT_SOURCE_DIR}/cmake")

# Include configuration modules
include(CoronaResourceOptions)
include(CoronaResourceCompiler)
include(CoronaResourceDependencies)
include(CoronaResourceUSD)
include(CoronaResourceExamples)

# Add subdirectories
add_subdirectory(src)

if(CORONA_RESOURCE_BUILD_EXAMPLES)
    add_subdirectory(examples)
endif()

if(CORONA_RESOURCE_BUILD_TESTS)
    enable_testing()
    add_subdirectory(tests)
endif()