# ==============================================================================
# Geometry System
# ==============================================================================

corona_add_system(geometry
    SOURCES
        geometry_system.cpp
        geometry_queries.cpp
        geometry_lod.cpp
        geometry_internal.h
        frustum.cpp
    DEPENDENCIES
        Horizon
        corona::resource::manager
)

if(BUILD_CORONA_TESTING OR BUILD_TESTING)
    add_executable(corona_geometry_editor_temporary_tests
        tests/test_editor_temporary_actor_bounds.cpp
        ${PROJECT_SOURCE_DIR}/src/shared_data_hub.cpp
    )

    target_link_libraries(corona_geometry_editor_temporary_tests
        PRIVATE
            corona::system::geometry
    )

    add_test(NAME GeometryEditorTemporaryActorTests COMMAND corona_geometry_editor_temporary_tests)
endif()
