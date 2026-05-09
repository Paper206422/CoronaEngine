# =============================================================================
# Image Example
# =============================================================================

corona_add_example(
    NAME ImageExample
    SOURCES image_example.cpp
    LIBRARIES corona::resource::manager
    USD_MODULES gf
    NEEDS_TBB ON
    NEEDS_ASSIMP ON
    NEEDS_USD_COPY ON
)

