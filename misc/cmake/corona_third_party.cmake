# ============================================================================== 
# corona_third_party.cmake
#
# Purpose:
#   Declare and fetch external dependencies using `FetchContent`.
#
# Notes:
#   - Centralizes source-level dependencies required by the engine and examples.
#   - Uses parallel capable FetchContent at configure time.
#
# Tips:
#   - Pin `GIT_TAG` values to specific commits or release versions to lock
#     dependency versions where stability is preferred.
# ============================================================================== 

include_guard(GLOBAL)

include(FetchContent)

# ------------------------------------------------------------------------------
# Core dependency declarations
# ------------------------------------------------------------------------------
FetchContent_Declare(Horizon
    GIT_REPOSITORY https://github.com/CoronaEngine/Horizon.git
    GIT_TAG 2a1b7f1113aaf675e9dcebbb51cf0c042ea36644
    EXCLUDE_FROM_ALL
)

FetchContent_Declare(assimp
    GIT_REPOSITORY https://github.com/assimp/assimp.git
    GIT_TAG master
    GIT_SHALLOW TRUE
    EXCLUDE_FROM_ALL
)

FetchContent_Declare(stb
    GIT_REPOSITORY https://github.com/nothings/stb.git
    GIT_TAG master
    GIT_SHALLOW TRUE
    EXCLUDE_FROM_ALL
)

FetchContent_Declare(nanobind
    GIT_REPOSITORY https://github.com/wjakob/nanobind.git
    GIT_TAG v2.9.2
    GIT_SHALLOW TRUE
    EXCLUDE_FROM_ALL
)

FetchContent_Declare(Vision
    GIT_REPOSITORY https://github.com/CoronaEngine/Vision.git
    GIT_TAG master
    GIT_SHALLOW TRUE
    EXCLUDE_FROM_ALL
)


FetchContent_Declare(
        glfw
        GIT_REPOSITORY https://github.com/glfw/glfw.git
        GIT_TAG master
        EXCLUDE_FROM_ALL
)

FetchContent_Declare(
        volk
        GIT_REPOSITORY https://github.com/zeux/volk.git
        GIT_TAG master
        EXCLUDE_FROM_ALL
)

FetchContent_Declare(
        Vulkan-Headers
        GIT_REPOSITORY https://github.com/KhronosGroup/Vulkan-Headers.git
        GIT_TAG main
        EXCLUDE_FROM_ALL
)

FetchContent_Declare(
        VulkanMemoryAllocator
        GIT_REPOSITORY https://github.com/GPUOpen-LibrariesAndSDKs/VulkanMemoryAllocator.git
        GIT_TAG master
        EXCLUDE_FROM_ALL
)

FetchContent_Declare(
        SDL
        GIT_REPOSITORY https://github.com/libsdl-org/SDL.git
        GIT_TAG release-3.4.0
        GIT_SHALLOW ON
)

FetchContent_Declare(
        imgui
        GIT_REPOSITORY https://github.com/ocornut/imgui.git
        GIT_TAG v1.92.5-docking
        EXCLUDE_FROM_ALL
)

# ------------------------------------------------------------------------------
# Fetch and enable dependencies
# ------------------------------------------------------------------------------

set(BUILD_TESTING OFF CACHE BOOL "Disable building tests for 3rd party dependencies" FORCE)

FetchContent_MakeAvailable(assimp)
message(STATUS "[3rdparty] assimp module enabled")

FetchContent_MakeAvailable(stb)
message(STATUS "[3rdparty] stb module enabled")

FetchContent_MakeAvailable(nanobind)
message(STATUS "[3rdparty] nanobind module enabled")

FetchContent_MakeAvailable(Horizon)
message(STATUS "[3rdparty] Horizon module enabled")

FetchContent_MakeAvailable(glfw)
message(STATUS "[3rdparty] glfw module enabled")

FetchContent_MakeAvailable(volk)
message(STATUS "[3rdparty] volk module enabled")

FetchContent_MakeAvailable(Vulkan-Headers)
message(STATUS "[3rdparty] Vulkan-Headers module enabled")

FetchContent_MakeAvailable(VulkanMemoryAllocator)
message(STATUS "[3rdparty] VulkanMemoryAllocator module enabled")

FetchContent_MakeAvailable(SDL)
message(STATUS "[3rdparty] SDL module enabled")

FetchContent_MakeAvailable(imgui)
message(STATUS "[3rdparty] imgui module enabled")

# Manually define imgui target since it has no CMakeLists.txt
if(NOT TARGET imgui)
    add_library(imgui STATIC
            "${imgui_SOURCE_DIR}/imgui.cpp"
            "${imgui_SOURCE_DIR}/imgui_demo.cpp"
            "${imgui_SOURCE_DIR}/imgui_draw.cpp"
            "${imgui_SOURCE_DIR}/imgui_tables.cpp"
            "${imgui_SOURCE_DIR}/imgui_widgets.cpp"
    )
    target_include_directories(imgui PUBLIC "${imgui_SOURCE_DIR}")

    # Manually define imgui target since it has no CMakeLists.txt
    if(MSVC)
        # Allow imgui to inherit global runtime settings (MD/MDd)
    endif()
endif()

if(CORONA_BUILD_VISION)
    set(SDL_SHARED ON CACHE BOOL "" FORCE)
    set(VISION_BUILD_VULKAN OFF CACHE BOOL "" FORCE)
    FetchContent_MakeAvailable(Vision)
    message(STATUS "[3rdparty] Vision module enabled")
endif()