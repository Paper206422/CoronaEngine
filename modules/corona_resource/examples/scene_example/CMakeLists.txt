# =============================================================================
# Scene Example
# =============================================================================

corona_add_example(
    NAME SceneExample
    SOURCES scene_example.cpp
    LIBRARIES corona::resource::manager corona::resource::scene
    USD_MODULES usdLux
    NEEDS_TBB ON
    NEEDS_ASSIMP ON
    NEEDS_USD_COPY ON
)

