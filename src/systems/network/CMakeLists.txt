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
