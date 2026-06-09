# ==============================================================================
# Acoustics System
# ==============================================================================

corona_add_system(acoustics
    SOURCES acoustics_system.cpp
    DEPENDENCIES SDL3::SDL3-static corona::resource::manager
)
