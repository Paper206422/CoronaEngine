# =============================================================================
# LRU Cache Example
# =============================================================================

corona_add_example(
    NAME LRUCacheExample
    LIBRARIES corona::kernel
    SOURCES
        main.cpp
        lru_cache_example.cpp
        lru_cache_example.h
)