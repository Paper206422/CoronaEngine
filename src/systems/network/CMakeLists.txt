# ==============================================================================
# Network System
# ==============================================================================

corona_add_system(network
    SOURCES
        network_system.cpp
        peer_manager.cpp
        sync_engine.cpp
        discovery.cpp
    DEPENDENCIES
        Horizon
        enet
)

if(BUILD_CORONA_TESTING OR BUILD_TESTING)
    add_executable(corona_network_protocol_tests
        tests/test_network_protocol.cpp
        ${PROJECT_SOURCE_DIR}/src/shared_data_hub.cpp
    )

    target_link_libraries(corona_network_protocol_tests
        PRIVATE
            corona::system::network
    )

    add_test(NAME NetworkProtocolTests COMMAND corona_network_protocol_tests)
endif()
