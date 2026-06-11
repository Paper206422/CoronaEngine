#include <corona/events/network_system_events.h>
#include <corona/kernel/core/i_logger.h>
#include <corona/kernel/event/i_event_bus.h>
#include <corona/kernel/event/i_event_stream.h>
#include <corona/systems/network/file_transfer.h>
#include <corona/systems/network/network_identity.h>
#include <corona/systems/network/network_system.h>
#include <corona/shared_data_hub.h>

#include <chrono>
#include <filesystem>
#include <fstream>
#include <unordered_map>

namespace Corona::Systems {

// ============================================================================
// Impl
// ============================================================================

struct NetworkSystem::Impl {
    Kernel::ISystemContext* ctx = nullptr;

    // Subsystems
    Network::PeerManager peer_manager;
    Network::SyncEngine sync_engine;
    Network::NetworkIdentityRegistry identity_registry{SharedDataHub::instance()};

    // State
    SessionState session_state{SessionState::Idle};
    SessionRole session_role{SessionRole::None};
    std::string instance_name;
    std::string host_address;
    uint16_t host_port = 0;
    uint64_t project_id = 0;
    uint16_t port = Network::kDefaultPort;

    // Timing for sync ticks
    using Clock = std::chrono::steady_clock;
    Clock::time_point last_sync_time;

    // Event subscription IDs
    std::vector<Kernel::EventId> event_subscriptions;

    // File transfer state
    struct IncomingTransfer {
        uint64_t transfer_id = 0;
        std::string model_path;
        std::string sender_peer_id;  // isolate chunks from multi-sender
        uint32_t total_size = 0;
        uint32_t chunk_count = 0;
        std::vector<bool> received_chunks;
        std::vector<uint8_t> buffer;
        Clock::time_point last_chunk_time;
        bool complete = false;
    };
    // key = sender_peer_id + "/" + transfer_id (first responder wins per transfer)
    std::unordered_map<std::string, IncomingTransfer> incoming_transfers;

    // Outgoing transfer: for each model_path, cache the file data
    // so we don't re-read on every FILE_REQUEST
    struct CachedFileData {
        std::vector<uint8_t> data;
        Clock::time_point load_time;
    };
    std::unordered_map<std::string, CachedFileData> outgoing_cache;

    // Project root for file write destination
    std::string project_root;

    // Sync pause (suppress poll_and_sync during incoming actor creation)
    bool sync_paused = false;

    // Deferred actions to execute in update() (avoid GIL in network thread)
    struct PendingAction {
        std::string actor_guid;
        std::string scene_name;
        std::string model_path;
        std::vector<std::string> dependency_paths;
        Network::ActorCreatePacked actor_packed;
    };
    std::vector<PendingAction> pending_actor_creates;

    // Pending file transfers: model_path → actor data from the original
    // ACTOR_CREATE that triggered the transfer.  When the file arrives,
    // we reconstruct the PendingAction without requiring a re-send.
    struct PendingFileTransfer {
        std::string actor_guid;
        std::string scene_name;
        std::string model_path;
        std::vector<std::string> dependency_paths;
        std::vector<uint64_t> transfer_ids;
        uint32_t remaining_files = 0;
        Clock::time_point create_time;
        Network::ActorCreatePacked actor_packed;
    };
    std::unordered_map<uint64_t, PendingFileTransfer> pending_file_transfer_groups;
    std::unordered_map<uint64_t, uint64_t> transfer_to_group;
    uint64_t next_transfer_id = 1;
};

namespace {
constexpr auto kTransferTimeout = std::chrono::seconds(30);
constexpr auto kOutgoingCacheTtl = std::chrono::minutes(2);

std::string_view session_role_label(NetworkSystem::SessionRole role) {
    switch (role) {
    case NetworkSystem::SessionRole::Host:
        return "host";
    case NetworkSystem::SessionRole::Client:
        return "client";
    case NetworkSystem::SessionRole::None:
    default:
        return "none";
    }
}
}  // namespace

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
    impl_->sync_engine.set_identity_mapping_callbacks(
        [this](Network::StorageID storage_id, uint64_t entity_seq) {
            return impl_->identity_registry.actor_guid_for_storage_seq(storage_id, entity_seq);
        },
        [this](Network::StorageID storage_id, const std::string& actor_guid)
            -> std::optional<uint64_t> {
            return impl_->identity_registry.storage_seq_for_actor_guid(storage_id, actor_guid);
        },
        [this](Network::StorageID storage_id, uint64_t entity_seq)
            -> std::optional<bool> {
            return impl_->identity_registry.local_ownership_for_storage_seq(
                storage_id, entity_seq);
        });

    // Wire up PeerManager → SyncEngine inbound path
    impl_->peer_manager.set_on_data_received(
        [this](const std::string& peer_id, const uint8_t* data, size_t len) {
            // Route: SYNC_DIRTY/SYNC_FULL/HEARTBEAT → sync engine
            //         ACTOR_CREATE/FILE_REQUEST/FILE_CHUNK → custom handler
            if (len >= 1) {
                using Network::MessageType;
                auto mt = static_cast<MessageType>(data[0]);
                if (mt == MessageType::SYNC_DIRTY || mt == MessageType::SYNC_FULL ||
                    mt == MessageType::HEARTBEAT) {
                    on_data_received(peer_id, data, len);
                } else {
                    on_custom_message(peer_id, data, len);
                }
            }
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

    return true;
}

void NetworkSystem::update() {
    if (impl_->session_state != SessionState::Active) return;

    auto now = Impl::Clock::now();

    // Poll ENet events every tick
    impl_->peer_manager.poll();

    // Sync engine tick (~60 Hz) — paused during remote actor creation
    // to ensure both peers build identical storage layouts (seq_id alignment).
    if (!impl_->sync_paused && now - impl_->last_sync_time >=
        std::chrono::milliseconds(Network::kSyncIntervalMs)) {
        impl_->sync_engine.poll_and_sync();
        impl_->last_sync_time = now;
    }

    for (auto it = impl_->incoming_transfers.begin();
         it != impl_->incoming_transfers.end(); ) {
        if (now - it->second.last_chunk_time > kTransferTimeout) {
            CFW_LOG_WARNING("NetworkSystem: Incoming transfer timed out — id={} path='{}'",
                            it->second.transfer_id, it->second.model_path);
            it = impl_->incoming_transfers.erase(it);
        } else {
            ++it;
        }
    }

    for (auto it = impl_->pending_file_transfer_groups.begin();
         it != impl_->pending_file_transfer_groups.end(); ) {
        if (now - it->second.create_time > kTransferTimeout) {
            CFW_LOG_WARNING("NetworkSystem: Pending file group timed out — actor='{}' model='{}'",
                            it->second.actor_guid, it->second.model_path);
            for (uint64_t transfer_id : it->second.transfer_ids) {
                impl_->transfer_to_group.erase(transfer_id);
            }
            it = impl_->pending_file_transfer_groups.erase(it);
        } else {
            ++it;
        }
    }

    for (auto it = impl_->outgoing_cache.begin(); it != impl_->outgoing_cache.end(); ) {
        if (now - it->second.load_time > kOutgoingCacheTtl) {
            it = impl_->outgoing_cache.erase(it);
        } else {
            ++it;
        }
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
                                  uint64_t project_id, uint16_t port,
                                  SessionRole role) {
    if (impl_->session_state == SessionState::Active) {
        CFW_LOG_WARNING("NetworkSystem: Session already active");
        if (role != SessionRole::None) {
            impl_->session_role = role;
        }
        return true;
    }

    impl_->session_state = SessionState::Starting;
    impl_->session_role = role == SessionRole::None ? SessionRole::Host : role;
    impl_->instance_name = instance_name;
    impl_->host_address.clear();
    impl_->host_port = 0;
    impl_->project_id = project_id;
    impl_->port = port;

    CFW_LOG_INFO("NetworkSystem: Starting manual-IP session '{}' on port {} role={} (project={:x})",
                 instance_name, port, session_role_label(impl_->session_role), project_id);

    // 1. PeerManager
    if (!impl_->peer_manager.start(port, instance_name)) {
        impl_->session_state = SessionState::Error;
        impl_->session_role = SessionRole::None;
        CFW_LOG_ERROR("NetworkSystem: Failed to start PeerManager");
        return false;
    }

    // 2. SyncEngine
    impl_->sync_engine.initialize(impl_->peer_manager.local_peer_id());

    impl_->session_state = SessionState::Active;
    impl_->last_sync_time = Impl::Clock::now();

    // Publish event
    if (impl_->ctx && impl_->ctx->event_bus()) {
        Events::NetworkHostStartedEvent ev{port};
        impl_->ctx->event_bus()->publish(ev);
    }

    CFW_LOG_INFO("NetworkSystem: Session active — listening on port {} role={}",
                 port, session_role_label(impl_->session_role));
    return true;
}

void NetworkSystem::stop_session() {
    if (impl_->session_state != SessionState::Active &&
        impl_->session_state != SessionState::Error) return;

    impl_->peer_manager.stop();
    impl_->sync_engine.shutdown();
    impl_->identity_registry.clear();
    impl_->incoming_transfers.clear();
    impl_->outgoing_cache.clear();
    impl_->pending_actor_creates.clear();
    impl_->pending_file_transfer_groups.clear();
    impl_->transfer_to_group.clear();

    impl_->session_state = SessionState::Idle;
    impl_->session_role = SessionRole::None;
    impl_->host_address.clear();
    impl_->host_port = 0;

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

NetworkSystem::SessionRole NetworkSystem::session_role() const {
    return impl_->session_role;
}

std::string_view NetworkSystem::session_role_name() const {
    return Corona::Systems::session_role_label(impl_->session_role);
}

const std::string& NetworkSystem::host_address() const {
    return impl_->host_address;
}

uint16_t NetworkSystem::host_port() const {
    return impl_->host_port;
}

size_t NetworkSystem::peer_count() const {
    return impl_->peer_manager.peer_count();
}

bool NetworkSystem::connect_to_peer(const std::string& ip, uint16_t port,
                                    const std::string& peer_name) {
    if (impl_->session_state != SessionState::Active) {
        CFW_LOG_WARNING("NetworkSystem: Cannot connect — session not active");
        return false;
    }
    if (ip.empty()) {
        CFW_LOG_WARNING("NetworkSystem: Cannot connect — host IP is empty");
        return false;
    }
    impl_->peer_manager.connect_to_peer(ip, port, peer_name, /*force=*/true);
    impl_->session_role = SessionRole::Client;
    impl_->host_address = ip;
    impl_->host_port = port;
    return true;
}

void NetworkSystem::broadcast_actor_create(const std::string& actor_guid,
                                           const std::string& scene_name,
                                           const std::string& model_path,
                                           const std::vector<std::string>& dependency_paths,
                                           const float* transform,
                                           const void* optics_packed, size_t optics_size) {
    if (impl_->session_state != SessionState::Active) return;
    if (impl_->peer_manager.peer_count() == 0) {
        CFW_LOG_DEBUG("NetworkSystem: No peers — skipping actor create broadcast");
        return;
    }
    auto pkt = Network::build_actor_create(actor_guid, scene_name, model_path, transform,
                                           optics_packed, optics_size, dependency_paths);
    impl_->peer_manager.broadcast(Network::kChannelReliable, pkt.data(), pkt.size(), true);
    CFW_LOG_INFO("NetworkSystem: Broadcast actor create — actor='{}' scene='{}' model='{}' deps={}",
                 actor_guid, scene_name, model_path, dependency_paths.size());
}

bool NetworkSystem::has_pending_transfers() const {
    return !impl_->pending_actor_creates.empty();
}

void NetworkSystem::set_sync_paused(bool paused) {
    impl_->sync_paused = paused;
}

bool NetworkSystem::pop_pending_actor_create(std::string& actor_guid,
                                              std::string& scene_name,
                                              std::string& model_path,
                                              void* actor_packed_out, size_t packed_size) {
    if (impl_->pending_actor_creates.empty()) return false;
    auto& pa = impl_->pending_actor_creates.front();
    actor_guid = pa.actor_guid;
    scene_name = pa.scene_name;
    model_path = pa.model_path;
    if (actor_packed_out && packed_size <= sizeof(Network::ActorCreatePacked)) {
        std::memcpy(actor_packed_out, &pa.actor_packed, packed_size);
    }
    impl_->pending_actor_creates.erase(impl_->pending_actor_creates.begin());
    return true;
}

bool NetworkSystem::register_actor_identity(const std::string& actor_guid,
                                            std::uintptr_t actor_handle,
                                            bool locally_owned) {
    const bool ok = impl_->identity_registry.register_actor(
        actor_guid, actor_handle, locally_owned);
    if (ok) {
        CFW_LOG_INFO("NetworkSystem: Registered actor identity — actor='{}' handle={} owner={}",
                     actor_guid, actor_handle, locally_owned ? "local" : "remote");
    } else {
        CFW_LOG_WARNING("NetworkSystem: Failed to register actor identity — actor='{}' handle={}",
                        actor_guid, actor_handle);
    }
    return ok;
}

std::optional<Network::ActorNetworkIdentity> NetworkSystem::resolve_actor_identity(
    const std::string& actor_guid) const {
    return impl_->identity_registry.resolve_actor(actor_guid);
}

bool NetworkSystem::claim_actor_ownership(const std::string& actor_guid) {
    if (actor_guid.empty()) return false;
    impl_->identity_registry.set_actor_ownership(actor_guid, true);
    if (impl_->session_state == SessionState::Active && impl_->peer_manager.peer_count() > 0) {
        auto pkt = Network::build_ownership_claim(actor_guid);
        impl_->peer_manager.broadcast(Network::kChannelReliable, pkt.data(), pkt.size(), true);
    }
    CFW_LOG_INFO("NetworkSystem: Claimed actor ownership — actor='{}'", actor_guid);
    return true;
}

void NetworkSystem::set_project_root(const std::string& project_root) {
    impl_->project_root = project_root;
}

// ============================================================================
// Callbacks
// ============================================================================

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

void NetworkSystem::on_custom_message(const std::string& sender_peer_id,
                                        const uint8_t* data, size_t len) {
    if (len < 1) return;
    using Network::MessageType;
    auto mt = static_cast<MessageType>(data[0]);

    if (mt == MessageType::ACTOR_CREATE) {
        Network::BufferReader r(data + 1, len - 1);
        uint16_t guid_len = r.read_u16();
        std::string actor_guid = r.read_string(guid_len);
        uint16_t sn_len = r.read_u16();
        std::string scene_name = r.read_string(sn_len);
        uint16_t mp_len = r.read_u16();
        std::string model_path = r.read_string(mp_len);

        if (r.has_remaining(36 + sizeof(Network::ActorCreatePacked))) {
            const float* transform = reinterpret_cast<const float*>(r.data + r.pos);
            r.pos += 36;
            Network::ActorCreatePacked actor_packed{};
            std::memcpy(&actor_packed, r.data + r.pos, sizeof(actor_packed));
            std::memcpy(actor_packed.transform, transform, 36);
            r.pos += sizeof(Network::ActorCreatePacked);

            std::vector<std::string> dependency_paths;
            if (r.has_remaining(2)) {
                uint16_t dep_count = r.read_u16();
                for (uint16_t i = 0; i < dep_count; ++i) {
                    if (!r.has_remaining(2)) break;
                    uint16_t dep_len = r.read_u16();
                    if (!r.has_remaining(dep_len)) break;
                    dependency_paths.push_back(r.read_string(dep_len));
                }
            }

            CFW_LOG_INFO("NetworkSystem: Received ACTOR_CREATE from {} — actor='{}' scene='{}' model='{}' deps={}",
                         sender_peer_id, actor_guid, scene_name, model_path, dependency_paths.size());

            auto file_exists = [this](const std::string& path) {
                auto full_path = Network::resolve_project_relative_path(
                    impl_->project_root, path);
                return full_path && std::filesystem::exists(*full_path) &&
                       std::filesystem::is_regular_file(*full_path);
            };

            std::vector<std::string> missing_paths;
            if (!file_exists(model_path)) {
                missing_paths.push_back(model_path);
            }
            for (const auto& dep : dependency_paths) {
                if (!file_exists(dep)) {
                    missing_paths.push_back(dep);
                }
            }

            if (missing_paths.empty()) {
                Impl::PendingAction pa;
                pa.actor_guid = actor_guid;
                pa.scene_name = scene_name;
                pa.model_path = model_path;
                pa.dependency_paths = dependency_paths;
                pa.actor_packed = actor_packed;
                impl_->pending_actor_creates.push_back(pa);
            } else {
                uint64_t group_id = impl_->next_transfer_id++;
                Impl::PendingFileTransfer group;
                group.actor_guid = actor_guid;
                group.scene_name = scene_name;
                group.model_path = model_path;
                group.dependency_paths = dependency_paths;
                group.actor_packed = actor_packed;
                group.remaining_files = static_cast<uint32_t>(missing_paths.size());
                group.create_time = Impl::Clock::now();

                auto send_request = [&](uint64_t transfer_id, const std::string& path) {
                    auto pkt = Network::build_file_request(transfer_id, path);
                    const auto* peer_info = impl_->peer_manager.find_peer(sender_peer_id);
                    if (peer_info && peer_info->peer) {
                        impl_->peer_manager.send_to(peer_info->peer, Network::kChannelReliable,
                                                    pkt.data(), pkt.size(), true);
                    } else {
                        impl_->peer_manager.broadcast(Network::kChannelReliable,
                                                      pkt.data(), pkt.size(), true);
                    }
                };

                std::vector<std::pair<uint64_t, std::string>> requests;
                for (const auto& path : missing_paths) {
                    uint64_t transfer_id = impl_->next_transfer_id++;
                    group.transfer_ids.push_back(transfer_id);
                    impl_->transfer_to_group[transfer_id] = group_id;
                    requests.emplace_back(transfer_id, path);
                }
                impl_->pending_file_transfer_groups[group_id] = std::move(group);
                for (const auto& [transfer_id, path] : requests) {
                    send_request(transfer_id, path);
                }
            }
        }
    } else if (mt == MessageType::FILE_REQUEST) {
        handle_file_request(sender_peer_id, data, len);
    } else if (mt == MessageType::FILE_CHUNK) {
        handle_file_chunk(sender_peer_id, data, len);
    } else if (mt == MessageType::OWNERSHIP_CLAIM) {
        Network::BufferReader r(data + 1, len - 1);
        if (!r.has_remaining(2)) return;
        uint16_t guid_len = r.read_u16();
        if (!r.has_remaining(guid_len)) return;
        std::string actor_guid = r.read_string(guid_len);
        impl_->identity_registry.set_actor_ownership(actor_guid, false);
        CFW_LOG_INFO("NetworkSystem: Peer {} claimed actor ownership — actor='{}'",
                     sender_peer_id, actor_guid);
    }
}

void NetworkSystem::handle_file_request(const std::string& sender_peer_id,
                                        const uint8_t* data, size_t len) {
    if (len < 1 + 8 + 2) return;
    Network::BufferReader r(data + 1, len - 1);
    uint64_t transfer_id = r.read_u64();
    uint16_t mp_len = r.read_u16();
    if (!r.has_remaining(mp_len)) return;
    std::string model_path = r.read_string(mp_len);

    auto full_path = Network::resolve_project_relative_path(
        impl_->project_root, model_path);
    if (!full_path) {
        CFW_LOG_ERROR("NetworkSystem: Reject unsafe FILE_REQUEST path '{}'", model_path);
        return;
    }

    auto& cache = impl_->outgoing_cache[model_path];
    if (cache.data.empty()) {
        std::ifstream file(*full_path, std::ios::binary | std::ios::ate);
        if (!file.is_open()) {
            CFW_LOG_ERROR("NetworkSystem: Cannot open file '{}' for FILE_REQUEST", full_path->string());
            impl_->outgoing_cache.erase(model_path);
            return;
        }
        cache.data.resize(static_cast<size_t>(file.tellg()));
        file.seekg(0);
        file.read(reinterpret_cast<char*>(cache.data.data()), cache.data.size());
        cache.load_time = Impl::Clock::now();
    }

    if (cache.data.empty()) return;

    constexpr uint32_t kChunkSize = 512 * 1024; // 512KB
    uint32_t total_size = static_cast<uint32_t>(cache.data.size());
    uint32_t chunk_count = (total_size + kChunkSize - 1) / kChunkSize;

    // Find sender's peer
    const auto* peer_info = impl_->peer_manager.find_peer(sender_peer_id);
    if (!peer_info || !peer_info->peer) {
        CFW_LOG_ERROR("NetworkSystem: Cannot find peer {} for FILE_CHUNK send", sender_peer_id);
        return;
    }

    for (uint32_t i = 0; i < chunk_count; ++i) {
        uint32_t offset = i * kChunkSize;
        uint32_t chunk_len = std::min(kChunkSize, total_size - offset);

        auto pkt = Network::build_file_chunk(
            transfer_id, model_path, total_size, offset, i, chunk_count,
            cache.data.data() + offset, chunk_len);

        impl_->peer_manager.send_to(peer_info->peer, Network::kChannelReliable,
                                    pkt.data(), pkt.size(), true);
    }
}

void NetworkSystem::handle_file_chunk(const std::string& sender_peer_id,
                                      const uint8_t* data, size_t len) {
    if (len < 1 + 8 + 2) return;
    Network::BufferReader r(data + 1, len - 1);

    uint64_t transfer_id = r.read_u64();
    uint16_t mp_len = r.read_u16();
    if (!r.has_remaining(mp_len)) return;
    std::string model_path = r.read_string(mp_len);

    if (!r.has_remaining(4 + 4 + 4 + 4 + 4)) return;
    uint32_t total_size = r.read_u32();
    uint32_t offset = r.read_u32();
    uint32_t chunk_index = r.read_u32();
    uint32_t chunk_count = r.read_u32();
    uint32_t chunk_data_len = r.read_u32();

    if (!r.has_remaining(chunk_data_len)) return;
    const uint8_t* chunk_data = r.data + r.pos;

    if (chunk_index >= chunk_count) return;

    // Get or create transfer state — isolate by sender+transfer_id to prevent
    // chunk interleaving when multiple peers respond to one FILE_REQUEST.
    std::string tx_key = Network::make_transfer_key(sender_peer_id, transfer_id);
    auto& tx = impl_->incoming_transfers[tx_key];
    if (tx.model_path.empty()) {
        tx.transfer_id = transfer_id;
        tx.model_path = model_path;
        tx.sender_peer_id = sender_peer_id;
        tx.total_size = total_size;
        tx.chunk_count = chunk_count;
        tx.received_chunks.resize(chunk_count, false);
        tx.buffer.resize(total_size);
        tx.last_chunk_time = Impl::Clock::now();
    }

    if (tx.model_path != model_path || tx.total_size != total_size ||
        tx.chunk_count != chunk_count) {
        CFW_LOG_ERROR("NetworkSystem: Inconsistent FILE_CHUNK transfer {}", transfer_id);
        impl_->incoming_transfers.erase(tx_key);
        return;
    }

    // Write chunk into buffer
    if (offset + chunk_data_len <= total_size) {
        std::memcpy(tx.buffer.data() + offset, chunk_data, chunk_data_len);
        tx.received_chunks[chunk_index] = true;
        tx.last_chunk_time = Impl::Clock::now();
    }

    // Check if all chunks received
    bool all_received = true;
    for (bool rcvd : tx.received_chunks) {
        if (!rcvd) { all_received = false; break; }
    }

    if (!all_received) {
        return;
    }

    // All chunks received — write to disk
    auto dest = Network::resolve_project_relative_path(impl_->project_root, model_path);
    if (!dest) {
        CFW_LOG_ERROR("NetworkSystem: Reject unsafe FILE_CHUNK path '{}'", model_path);
        impl_->incoming_transfers.erase(tx_key);
        return;
    }

    std::error_code ec;
    std::filesystem::create_directories(dest->parent_path(), ec);

    auto tmp_dest = *dest;
    tmp_dest += ".part";
    std::ofstream out(tmp_dest, std::ios::binary);
    if (out.is_open()) {
        out.write(reinterpret_cast<const char*>(tx.buffer.data()), total_size);
        out.close();
        std::filesystem::rename(tmp_dest, *dest, ec);
        if (ec) {
            std::filesystem::remove(tmp_dest);
            CFW_LOG_ERROR("NetworkSystem: Failed to finalize file '{}'", dest->string());
            impl_->incoming_transfers.erase(tx_key);
            return;
        }
    } else {
        CFW_LOG_ERROR("NetworkSystem: Failed to write file '{}'", dest->string());
        impl_->incoming_transfers.erase(tx_key);
        return;
    }

    impl_->incoming_transfers.erase(tx_key);

    auto group_id_it = impl_->transfer_to_group.find(transfer_id);
    if (group_id_it != impl_->transfer_to_group.end()) {
        uint64_t group_id = group_id_it->second;
        impl_->transfer_to_group.erase(group_id_it);
        auto ft_it = impl_->pending_file_transfer_groups.find(group_id);
        if (ft_it == impl_->pending_file_transfer_groups.end()) {
            return;
        }
        if (ft_it->second.remaining_files > 0) {
            --ft_it->second.remaining_files;
        }
        if (ft_it->second.remaining_files != 0) {
            return;
        }

        Impl::PendingAction pa;
        pa.actor_guid = ft_it->second.actor_guid;
        pa.scene_name = ft_it->second.scene_name;
        pa.model_path = ft_it->second.model_path;
        pa.dependency_paths = ft_it->second.dependency_paths;
        pa.actor_packed = ft_it->second.actor_packed;
        impl_->pending_actor_creates.push_back(pa);
        impl_->pending_file_transfer_groups.erase(ft_it);
    }
}

}  // namespace Corona::Systems
