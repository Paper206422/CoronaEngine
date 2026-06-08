#include <corona/events/network_system_events.h>
#include <corona/kernel/core/i_logger.h>
#include <corona/kernel/event/i_event_bus.h>
#include <corona/kernel/event/i_event_stream.h>
#include <corona/systems/network/network_system.h>

#include <chrono>

namespace Corona::Systems {

// ============================================================================
// Impl
// ============================================================================

struct NetworkSystem::Impl {
    Kernel::ISystemContext* ctx = nullptr;

    // Subsystems
    Network::Discovery discovery;
    Network::PeerManager peer_manager;
    Network::SyncEngine sync_engine;

    // State
    SessionState session_state{SessionState::Idle};
    std::string instance_name;
    uint64_t project_id = 0;
    uint16_t port = Network::kDefaultPort;

    // Timing for sync ticks
    using Clock = std::chrono::steady_clock;
    Clock::time_point last_sync_time;
    Clock::time_point last_discovery_poll;

    // Event subscription IDs
    std::vector<Kernel::EventId> event_subscriptions;
};

// ============================================================================
// Lifecycle
// ============================================================================

NetworkSystem::NetworkSystem() : impl_(std::make_unique<Impl>()) {
    set_target_fps(60);
}

NetworkSystem::~NetworkSystem() = default;

bool NetworkSystem::initialize(Kernel::ISystemContext* ctx) {
    impl_->ctx = ctx;
    CFW_LOG_NOTICE("NetworkSystem: Initializing (ENet LAN collaborative editing)");

    // Wire up SyncEngine → PeerManager outbound path
    impl_->sync_engine.set_on_outgoing([this](const std::vector<uint8_t>& packet) {
        impl_->peer_manager.broadcast(
            Network::kChannelReliable,
            packet.data(), packet.size(),
            true);
    });

    // Wire up PeerManager → SyncEngine inbound path
    impl_->peer_manager.set_on_data_received(
        [this](const std::string& peer_id, const uint8_t* data, size_t len) {
            on_data_received(peer_id, data, len);
        });

    // Wire up PeerManager connect/disconnect → events
    impl_->peer_manager.set_on_peer_connected(
        [this](const Network::PeerManager::PeerInfo& info) {
            on_peer_connected(info);
        });

    impl_->peer_manager.set_on_peer_disconnected(
        [this](const Network::PeerManager::PeerInfo& info) {
            on_peer_disconnected(info);
        });

    // Wire up Discovery → PeerManager connect path
    impl_->discovery.set_on_peer_discovered(
        [this](const std::string& ip, const std::string& name, uint64_t proj_id) {
            on_peer_discovered(ip, name, proj_id);
        });

    return true;
}

void NetworkSystem::update() {
    if (impl_->session_state != SessionState::Active) return;

    auto now = Impl::Clock::now();

    // Poll ENet events every tick
    impl_->peer_manager.poll();

    // Poll Discovery broadcasts
    if (now - impl_->last_discovery_poll >=
        std::chrono::milliseconds(Network::kDiscoveryIntervalMs)) {
        impl_->discovery.poll();
        impl_->last_discovery_poll = now;
    }

    // Sync engine tick (~60 Hz)
    if (now - impl_->last_sync_time >=
        std::chrono::milliseconds(Network::kSyncIntervalMs)) {
        impl_->sync_engine.poll_and_sync();
        impl_->last_sync_time = now;
    }
}

void NetworkSystem::shutdown() {
    CFW_LOG_NOTICE("NetworkSystem: Shutting down...");
    stop_session();

    // Unsubscribe events
    if (impl_->ctx && impl_->ctx->event_bus()) {
        for (auto id : impl_->event_subscriptions) {
            impl_->ctx->event_bus()->unsubscribe(id);
        }
    }
    impl_->event_subscriptions.clear();
}

// ============================================================================
// Public API
// ============================================================================

bool NetworkSystem::start_session(const std::string& instance_name,
                                  uint64_t project_id, uint16_t port) {
    if (impl_->session_state == SessionState::Active) {
        CFW_LOG_WARNING("NetworkSystem: Session already active");
        return true;
    }

    impl_->session_state = SessionState::Starting;
    impl_->instance_name = instance_name;
    impl_->project_id = project_id;
    impl_->port = port;

    CFW_LOG_INFO("NetworkSystem: Starting session '{}' on port {} (project={:x})",
                 instance_name, port, project_id);

    // 1. PeerManager
    if (!impl_->peer_manager.start(port, instance_name)) {
        impl_->session_state = SessionState::Error;
        CFW_LOG_ERROR("NetworkSystem: Failed to start PeerManager");
        return false;
    }

    // 2. SyncEngine
    impl_->sync_engine.initialize(impl_->peer_manager.local_peer_id());

    // 3. Discovery (use port + 1 to avoid bind conflict with ENet)
    if (!impl_->discovery.start(port + Network::kDiscoveryPortOffset, instance_name, project_id)) {
        impl_->peer_manager.stop();
        impl_->session_state = SessionState::Error;
        CFW_LOG_ERROR("NetworkSystem: Failed to start Discovery");
        return false;
    }

    impl_->session_state = SessionState::Active;
    impl_->last_sync_time = Impl::Clock::now();
    impl_->last_discovery_poll = Impl::Clock::now();

    // Publish event
    if (impl_->ctx && impl_->ctx->event_bus()) {
        Events::NetworkHostStartedEvent ev{port};
        impl_->ctx->event_bus()->publish(ev);
    }

    CFW_LOG_INFO("NetworkSystem: Session active — listening on port {}", port);
    return true;
}

void NetworkSystem::stop_session() {
    if (impl_->session_state != SessionState::Active &&
        impl_->session_state != SessionState::Error) return;

    impl_->discovery.stop();
    impl_->sync_engine.shutdown();
    impl_->peer_manager.stop();

    impl_->session_state = SessionState::Idle;

    // Publish event
    if (impl_->ctx && impl_->ctx->event_bus()) {
        Events::NetworkHostStoppedEvent ev;
        impl_->ctx->event_bus()->publish(ev);
    }

    CFW_LOG_INFO("NetworkSystem: Session stopped");
}

NetworkSystem::SessionState NetworkSystem::session_state() const {
    return impl_->session_state;
}

size_t NetworkSystem::peer_count() const {
    return impl_->peer_manager.peer_count();
}

// ============================================================================
// Callbacks
// ============================================================================

void NetworkSystem::on_peer_discovered(const std::string& ip,
                                       const std::string& name,
                                       uint64_t /*project_id*/) {
    CFW_LOG_DEBUG("NetworkSystem: Discovered peer {} at {}", name, ip);
    impl_->peer_manager.connect_to_peer(ip, impl_->port, name);
}

void NetworkSystem::on_peer_connected(const Network::PeerManager::PeerInfo& info) {
    CFW_LOG_INFO("NetworkSystem: Peer connected — {} ({})", info.id, info.name);

    if (impl_->ctx && impl_->ctx->event_bus()) {
        Events::PeerConnectedEvent ev{info.id, info.name};
        impl_->ctx->event_bus()->publish(ev);
    }
}

void NetworkSystem::on_peer_disconnected(const Network::PeerManager::PeerInfo& info) {
    CFW_LOG_INFO("NetworkSystem: Peer disconnected — {} ({})", info.id, info.name);

    if (impl_->ctx && impl_->ctx->event_bus()) {
        Events::PeerDisconnectedEvent ev{info.id};
        impl_->ctx->event_bus()->publish(ev);
    }
}

void NetworkSystem::on_data_received(const std::string& peer_id,
                                     const uint8_t* data, size_t len) {
    impl_->sync_engine.handle_incoming(peer_id, data, len);

    if (impl_->ctx && impl_->ctx->event_bus()) {
        Events::RemoteSyncReceivedEvent ev{peer_id};
        impl_->ctx->event_bus()->publish(ev);
    }
}

}  // namespace Corona::Systems
