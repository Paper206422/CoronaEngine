# CoronaResource Tests

# Test executable
add_executable(corona_resource_tests
    test_resource_manager.cpp
        ../examples/lru_cache_example/lru_cache_example.h
)

target_link_libraries(corona_resource_tests
    PRIVATE
        corona::resource::manager
)

target_include_directories(corona_resource_tests
    PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}
)

corona_copy_tbb_runtime_artifacts(corona_resource_tests)
corona_copy_runtime_files(gf corona_resource_tests)
corona_copy_runtime_files(assimp::assimp corona_resource_tests)

# Add test
add_test(NAME ResourceManagerTests COMMAND corona_resource_tests)

