# =============================================================================
# LOD Example
# =============================================================================

corona_add_example(
    NAME LODExample
    SOURCES lod_example.cpp
    LIBRARIES corona::resource::manager corona::resource::scene
    NEEDS_TBB ON
    NEEDS_ASSIMP ON
)
