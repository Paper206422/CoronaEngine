# ==============================================================================
# Mechanics System
# ==============================================================================

corona_add_system(mechanics
    SOURCES mechanics_system.cpp
    DEPENDENCIES
        Horizon
        corona::resource::manager
)
