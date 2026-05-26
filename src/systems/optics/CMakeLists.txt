# ==============================================================================
# Optics System
# ==============================================================================

corona_add_system(optics
    SOURCES
        optics_system.cpp
        hardware.h
        vision/vision_output_bridge.cpp
        vision/vision_output_bridge.h
        $<$<BOOL:${CORONA_BUILD_VISION}>:vision/vision_geometry_adapter.cpp>
        $<$<BOOL:${CORONA_BUILD_VISION}>:vision/vision_material_adapter.cpp>
        $<$<BOOL:${CORONA_BUILD_VISION}>:vision/vision_light_adapter.cpp>
        $<$<BOOL:${CORONA_BUILD_VISION}>:vision/vision_camera_adapter.cpp>
    DEPENDENCIES
        Horizon
        corona::resource::manager
        $<$<BOOL:${CORONA_BUILD_VISION}>:vision-all_libs>
    INCLUDE_DIRS
    	$<$<BOOL:${CORONA_BUILD_VISION}>:${Vision_SOURCE_DIR}/src>
    COMPILE_DEFINITIONS
        $<$<BOOL:${CORONA_BUILD_VISION}>:CORONA_ENABLE_VISION>
)

helicon_compile_shaders(corona_optics_system
    OUTPUT_DIR "${CMAKE_CURRENT_BINARY_DIR}/generated_shaders"
)
