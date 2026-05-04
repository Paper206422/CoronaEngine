
# ==============================================================================
# Animation System
# ==============================================================================


corona_add_system(kinematics
    SOURCES kinematics_system.cpp
    DEPENDENCIES
        corona::resource::manager
        Horizon
)