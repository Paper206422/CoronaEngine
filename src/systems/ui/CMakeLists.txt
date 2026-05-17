# Create a library target for ImGui backend files
add_library(imgui_backends STATIC
        "${imgui_SOURCE_DIR}/backends/imgui_impl_sdl3.cpp"
)
target_include_directories(imgui_backends PUBLIC
        "${imgui_SOURCE_DIR}"
        "${imgui_SOURCE_DIR}/backends"
)
target_link_libraries(imgui_backends PUBLIC imgui SDL3::SDL3-static)


# ImGui System 配置
file(GLOB IMGUI_SYSTEM_SOURCES
    imgui_system.cpp
    vulk/vulkan_backend.cpp
    vulk/browser_manager_vulkan.cpp
    imgui/imgui_ui.cpp
    imgui/editor_settings.cpp
    cef/browser_manager.cpp
    cef/browser_ui.cpp
    cef/cef_client.cpp
    cef/cef_query_bridge.cpp
    cef/cef_realtime_bridge.cpp
    cef/cef_py_bind.cpp
    sdl/sdl_utils.cpp
)

list(APPEND IMGUI_SYSTEM_SOURCES
    ${PROJECT_SOURCE_DIR}/include/corona/systems/ui/vulkan_backend.h
)


corona_add_system(imgui
    SOURCES ${IMGUI_SYSTEM_SOURCES}
    DEPENDENCIES
        Horizon
        libcef_dll_wrapper
        debug "${CEF_LIBCEF_DEBUG}"
        optimized "${CEF_LIBCEF_RELEASE}"
        SDL3::SDL3-static
        imgui
        imgui_backends
        ws2_32
        shlwapi
        dbghelp
        psapi
        version
        winmm
        Python::Python
        nanobind-static
        ktm
        corona::resource::manager
    INCLUDE_DIRS
        ${CMAKE_CURRENT_SOURCE_DIR}
        ${CMAKE_SOURCE_DIR}/build_deps/imgui-src
        ${CEF_INCLUDE_DIR}
        ${CEF_ROOT}
)

target_compile_definitions(corona_imgui_system PUBLIC VK_NO_PROTOTYPES)
target_compile_options(corona_imgui_system PRIVATE "$<$<CXX_COMPILER_ID:MSVC>:/source-charset:utf-8>")

# 嵌入编辑器设置页面的源文件路径（CEF 通过 file:// 直接加载）
corona_to_backslash("${CMAKE_CURRENT_SOURCE_DIR}/vue_settings/editor_settings.html" _SETTINGS_HTML_PATH ESCAPE_FOR_CSTRING)
target_compile_definitions(corona_imgui_system PRIVATE
    CORONA_SETTINGS_HTML_PATH=\"${_SETTINGS_HTML_PATH}\"
)

helicon_compile_shaders(corona_imgui_system
    OUTPUT_DIR "${CMAKE_CURRENT_BINARY_DIR}/generated_shaders"
)
