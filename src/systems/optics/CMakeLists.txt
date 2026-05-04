# ==============================================================================
# Optics System
# ==============================================================================

corona_add_system(optics
    SOURCES
        optics_system.cpp
        hardware.h
    DEPENDENCIES 
        Horizon
        corona::resource::manager
        $<$<BOOL:${CORONA_BUILD_VISION}>:vision-all_libs>
    INCLUDE_DIRS
    	$<$<BOOL:${CORONA_BUILD_VISION}>:${Vision_SOURCE_DIR}/src>
)

helicon_compile_shaders(corona_optics_system
    OUTPUT_DIR "${CMAKE_CURRENT_BINARY_DIR}/generated_shaders"
)
