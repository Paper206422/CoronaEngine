# ==============================================================================
# Optics System
# ==============================================================================

corona_add_system(optics
    SOURCES
        optics_system.cpp
        hardware.h
        $<$<BOOL:${CORONA_BUILD_VISION}>:vision/vision_material_adapter.cpp>
        $<$<BOOL:${CORONA_BUILD_VISION}>:vision/vision_material_adapter.h>
        $<$<BOOL:${CORONA_BUILD_VISION}>:vision/vision_geometry_adapter.cpp>
        $<$<BOOL:${CORONA_BUILD_VISION}>:vision/vision_geometry_adapter.h>
        $<$<BOOL:${CORONA_BUILD_VISION}>:vision/vision_camera_adapter.cpp>
        $<$<BOOL:${CORONA_BUILD_VISION}>:vision/vision_camera_adapter.h>
        $<$<BOOL:${CORONA_BUILD_VISION}>:vision/vision_light_adapter.cpp>
        $<$<BOOL:${CORONA_BUILD_VISION}>:vision/vision_light_adapter.h>
        $<$<BOOL:${CORONA_BUILD_VISION}>:vision/vision_render_mode_config.cpp>
        $<$<BOOL:${CORONA_BUILD_VISION}>:vision/vision_render_mode_config.h>
        $<$<BOOL:${CORONA_BUILD_VISION}>:vision/vision_zero_copy_bridge.cpp>
        $<$<BOOL:${CORONA_BUILD_VISION}>:vision/vision_zero_copy_bridge.h>
    DEPENDENCIES
        Horizon
        corona::resource::manager
    INCLUDE_DIRS
    	$<$<BOOL:${CORONA_BUILD_VISION}>:${CMAKE_SOURCE_DIR}/vision/src>
)

# vision-all_libs is linked PRIVATEly here on purpose: vision bundles its own
# copy of Dear ImGui v1.80 under vision/src/ext/window/imgui and exposes it via
# PUBLIC include directories on vision-window-imgui. If propagated transitively
# to CoronaEngine, that include path is searched before build/_deps/imgui-src
# (v1.92.5), causing <imgui.h> to resolve to the old bundled copy and breaking
# headers that depend on newer types such as ImGuiViewport (C2061). The optics
# system's public headers do not use any vision symbols, so PRIVATE linkage is
# sufficient.
if(CORONA_BUILD_VISION)
    target_link_libraries(corona_optics_system PRIVATE vision-all_libs)
endif()

if((BUILD_CORONA_TESTING OR BUILD_TESTING) AND CORONA_BUILD_VISION)
    add_executable(corona_vision_render_mode_config_tests
        tests/test_vision_render_mode_config.cpp
    )
    target_include_directories(corona_vision_render_mode_config_tests
        PRIVATE
            ${PROJECT_SOURCE_DIR}/include
            ${CMAKE_CURRENT_SOURCE_DIR}
            ${CMAKE_SOURCE_DIR}/vision/src
    )
    target_link_libraries(corona_vision_render_mode_config_tests
        PRIVATE
            corona::system::optics
            vision-all_libs
    )
    add_test(NAME VisionRenderModeConfigTests
             COMMAND corona_vision_render_mode_config_tests)
    set_tests_properties(VisionRenderModeConfigTests PROPERTIES
        WORKING_DIRECTORY "${CMAKE_BINARY_DIR}/bin/$<CONFIG>")
endif()

# ------------------------------------------------------------------------------
# Vision import-scene verification demo (OFF by default)
# When enabled (and Vision is built), the optics system loads a known-good scene
# straight from disk via vision::Importer::import_scene to verify that the Vision
# backend can produce a picture in isolation, bypassing the CoronaEngine->Vision
# scene-building adapters. Edit kVisionDemoScenePath in optics_system.cpp to point
# at a local *.json scene.
# ------------------------------------------------------------------------------
option(CORONA_VISION_IMPORT_DEMO "Enable the Vision import-scene verification demo in OpticsSystem" OFF)
if(CORONA_BUILD_VISION AND CORONA_VISION_IMPORT_DEMO)
    target_compile_definitions(corona_optics_system PRIVATE CORONA_VISION_IMPORT_DEMO)
endif()


helicon_compile_shaders(corona_optics_system
    OUTPUT_DIR "${CMAKE_CURRENT_BINARY_DIR}/generated_shaders"
)
