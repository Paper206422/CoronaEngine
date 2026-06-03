# ==============================================================================
# Geometry System
# ==============================================================================

corona_add_system(geometry
    SOURCES
        geometry_system.cpp
        frustum.cpp
    DEPENDENCIES
        Horizon
        corona::resource::manager
)
