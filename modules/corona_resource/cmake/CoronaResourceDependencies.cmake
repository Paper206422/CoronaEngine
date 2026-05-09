# =============================================================================
# CoronaResource External Dependencies
# =============================================================================

include(FetchContent)
include(CoronaResourceUSD)

# Fetch ktm math library
message(STATUS "Fetching ktm math library...")
FetchContent_Declare(
    ktm
    GIT_REPOSITORY https://github.com/YGXXD/ktm.git
    GIT_TAG main
    EXCLUDE_FROM_ALL
)

# Fetch Assimp 3D model import library
message(STATUS "Fetching Assimp library...")
FetchContent_Declare(
    assimp
    GIT_REPOSITORY https://github.com/assimp/assimp.git
    GIT_TAG master
    GIT_SHALLOW TRUE
    EXCLUDE_FROM_ALL
)

# Fetch stb single-file public domain libraries
message(STATUS "Fetching stb library...")
FetchContent_Declare(
    stb
    GIT_REPOSITORY https://github.com/nothings/stb.git
    GIT_TAG master
    GIT_SHALLOW TRUE
    EXCLUDE_FROM_ALL
)

# Fetch nlohmann/json single-header JSON library
message(STATUS "Fetching nlohmann/json library...")
FetchContent_Declare(
    nlohmann_json
    GIT_REPOSITORY https://github.com/nlohmann/json.git
    GIT_TAG v3.12.0
    GIT_SHALLOW TRUE
    EXCLUDE_FROM_ALL
)

if(TARGET corona::kernel)
    message(STATUS "Using Corona framework provided by parent project")
else()
    message(STATUS "Fetching CoronaFramework library...")
    FetchContent_Declare(
        CoronaFramework
        GIT_REPOSITORY https://github.com/CoronaEngine/CoronaFramework.git
        GIT_TAG main
        GIT_SHALLOW TRUE
        EXCLUDE_FROM_ALL
    )
endif()

# Fetch OpenUSD library
message(STATUS "Fetching OpenUSD library...")
FetchContent_Declare(
    OpenUSD
    GIT_REPOSITORY https://github.com/PixarAnimationStudios/OpenUSD.git
    GIT_TAG release
    GIT_SHALLOW TRUE
    EXCLUDE_FROM_ALL
)

# Fetch tinyexr library
message(STATUS "Fetching tinyexr library...")
FetchContent_Declare(
    tinyexr
    GIT_REPOSITORY https://github.com/syoyo/tinyexr.git
    GIT_TAG release
    GIT_SHALLOW TRUE
    EXCLUDE_FROM_ALL
)

message(STATUS "Fetching meshoptimizer library...")
FetchContent_Declare(
    meshoptimizer
    GIT_REPOSITORY https://github.com/zeux/meshoptimizer.git
    GIT_TAG v0.25  # Recommend specifying a specific version tag or commit hash, avoid using master
)

message(STATUS "Fetching astc-encoder library...")
FetchContent_Declare(
    astc-encoder
    GIT_REPOSITORY https://github.com/ARM-software/astc-encoder.git
    GIT_TAG 5.3.0  # Recommend locking to a specific commit hash or release tag (e.g., 4.6.0)
)

# Configure OpenUSD cache flags ahead of population so imaging stays disabled
set(NO_DX TRUE CACHE BOOL "" FORCE)
set(PXR_BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(PXR_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
set(PXR_BUILD_TUTORIALS OFF CACHE BOOL "" FORCE)
set(PXR_BUILD_IMAGING OFF CACHE BOOL "" FORCE)
set(PXR_ENABLE_PYTHON_SUPPORT OFF CACHE BOOL "" FORCE)
set(PXR_ENABLE_PRECOMPILED_HEADERS OFF CACHE BOOL "" FORCE)

# Configure SDL2 options before making it available
set(SDL_SHARED ON CACHE BOOL "" FORCE)

# Configure Assimp options before making it available
set(ASSIMP_BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(ASSIMP_BUILD_ASSIMP_TOOLS OFF CACHE BOOL "" FORCE)
set(ASSIMP_BUILD_SAMPLES OFF CACHE BOOL "" FORCE)
set(ASSIMP_INSTALL OFF CACHE BOOL "" FORCE)
set(ASSIMP_INJECT_DEBUG_POSTFIX OFF CACHE BOOL "" FORCE)
set(ASSIMP_NO_EXPORT ON CACHE BOOL "" FORCE)
set(ASSIMP_WARNINGS_AS_ERRORS OFF CACHE BOOL "" FORCE)
set(ASSIMP_BUILD_USD_IMPORTER OFF CACHE BOOL "" FORCE)   # Temp enable USD importer

# Configure tinyexr options before making it available
set(TINYEXR_BUILD_SAMPLE OFF CACHE BOOL "" FORCE)

# Configure astc-encoder options before making it available
set(ASTCENC_CLI OFF CACHE BOOL "Disable ASTC CLI tools" FORCE)
set(ASTCENC_UNITTEST OFF CACHE BOOL "Disable ASTC Unit Tests" FORCE)
set(ASTCENC_SHAREDLIB OFF CACHE BOOL "Build shared library" FORCE)

# Make dependencies available
set(_CORONA_RESOURCE_FETCH_DEPS
    ktm
    assimp
    stb
    nlohmann_json
    OpenUSD
    tinyexr
    meshoptimizer
    astc-encoder
)

if(NOT TARGET corona::kernel)
    list(APPEND _CORONA_RESOURCE_FETCH_DEPS CoronaFramework)
endif()

FetchContent_MakeAvailable(${_CORONA_RESOURCE_FETCH_DEPS})

# Create interface library for stb (header-only)
FetchContent_GetProperties(stb)

if (NOT stb_POPULATED)
    FetchContent_Populate(stb)
endif ()

add_library(stb_headers INTERFACE)
target_include_directories(stb_headers INTERFACE ${stb_SOURCE_DIR})

corona_install_usd(usdGeom)
