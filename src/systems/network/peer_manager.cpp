#include <corona/systems/network/peer_manager.h>

#include <enet/enet.h>
#include <corona/kernel/core/i_logger.h>

#include <algorithm>
#include <mutex>

namespace Corona::Network {

struct PeerManager::Impl {
    ENetHost* host = nullptr;
    std::string local_id;
    std::string instance_name;

    // Peer tracking
    std::vector<PeerInfo> peer_list;
    mutable std::mutex peer_mutex;

    // Sequence counter
    std::atomic<uint32_t> sequence{0};

    // Callbacks
    OnPeerConnected on_connected;
    OnPeerDisconnected on_disconnected;
    OnDataReceived on_data;

    // ------------------------------------------------------------------------
    // Helpers
    // ------------------------------------------------------------------------

    PeerInfo* find_peer_unsafe(_ENetPeer* raw) {
        for (auto& p : peer_list) {
            if (p.peer == raw) return &p;
        }
        return nullptr;
    }

    PeerInfo* find_peer_by_id_unsafe(const std::string& id) {
        for (auto& p : peer_list) {
            if (p.id == id) return &p;
        }
        return nullptr;
    }
};

// ============================================================================
PeerManager::PeerManager() : impl_(std::make_unique<Impl>()) {}

PeerManager::~PeerManager() { stop(); }

// ============================================================================
bool PeerManager::start(uint16_t port, const std::string& instance_name) {
    if (impl_->host) {
        CFW_LOG_WARNING("PeerManager: Already started");
        return true;
    }

    impl_->instance_name = instance_name;

    // Build local ID from a placeholder IP (we don't know our LAN IP yet;
    // it will be populated when we accept or connect to a peer).
    // In practice it's used as a tiebreaker; localhost + port is fine.
    impl_->local_id = "127.0.0.1:" + std::to_string(port);

    // Create the ENet host
    // address.port = port, maxPeers = 64, maxChannels = 2
    ENetAddress addr{};
    addr.host = ENET_HOST_ANY;
    addr.port = port;

    impl_->host = enet_host_create(
        &addr,      // listen address
        64,         // max peers
        2,          // channel count
        0,          // incoming bandwidth (unlimited)
        0           // outgoing bandwidth (unlimited)
    );

    if (!impl_->host) {
        CFW_LOG_ERROR("PeerManager: Failed to create ENet host on port {}", port);
        return false;
    }

    CFW_LOG_INFO("PeerManager: Started on port {} (local_id={})", port,
                 impl_->local_id);
    return true;
}

void PeerManager::stop() {
    if (!impl_->host) return;

    // Disconnect all peers (forceful)
    {
        std::lock_guard lock(impl_->peer_mutex);
        for (auto& p : impl_->peer_list) {
            if (p.peer) enet_peer_disconnect(p.peer, 0);
        }
    }

    // Flush pending disconnects
    enet_host_flush(impl_->host);

    // Destroy host
    enet_host_destroy(impl_->host);
    impl_->host = nullptr;

    {
        std::lock_guard lock(impl_->peer_mutex);
        impl_->peer_list.clear();
    }

    CFW_LOG_INFO("PeerManager: Stopped");
}

// ============================================================================
void PeerManager::connect_to_peer(const std::string& ip, uint16_t port,
                                  const std::string& peer_name) {
    if (!impl_->host) return;

    // ID-based connection ordering: smaller ID waits, larger ID initiates
    std::string remote_id = make_peer_id(ip.c_str(), port);

    if (impl_->local_id < remote_id) {
        // We have the smaller ID — wait for them to connect to us
        CFW_LOG_DEBUG("PeerManager: {} < {} — waiting for inbound connection",
                      impl_->local_id, remote_id);
        return;
    }

    // Check if already connected
    {
        std::lock_guard lock(impl_->peer_mutex);
        if (impl_->find_peer_by_id_unsafe(remote_id)) return;
    }

    ENetAddress addr{};
    enet_address_set_host(&addr, ip.c_str());
    addr.port = port;

    ENetPeer* peer = enet_host_connect(impl_->host, &addr, 2, 0);
    if (!peer) {
        CFW_LOG_ERROR("PeerManager: Failed to initiate connection to {}", remote_id);
        return;
    }

    // Store pending peer info (data is the remote peer ID string so we can
    // match it on the connect event)
    {
        std::lock_guard lock(impl_->peer_mutex);
        PeerInfo info;
        info.id = remote_id;
        info.name = peer_name;
        info.peer = peer;
        info.connected = false;
        impl_->peer_list.push_back(info);
    }

    CFW_LOG_INFO("PeerManager: Connecting to {} ({})", remote_id, peer_name);
}

void PeerManager::disconnect_peer(const std::string& peer_id) {
    std::lock_guard lock(impl_->peer_mutex);
    auto* p = impl_->find_peer_by_id_unsafe(peer_id);
    if (p && p->peer) {
        enet_peer_disconnect(p->peer, 0);
        CFW_LOG_INFO("PeerManager: Disconnecting peer {}", peer_id);
    }
}

// ============================================================================
size_t PeerManager::peer_count() const {
    std::lock_guard lock(impl_->peer_mutex);
    return impl_->peer_list.size();
}

std::vector<PeerManager::PeerInfo> PeerManager::peers() const {
    std::lock_guard lock(impl_->peer_mutex);
    return impl_->peer_list;
}

const PeerManager::PeerInfo* PeerManager::find_peer(
    const std::string& peer_id) const {
    std::lock_guard lock(impl_->peer_mutex);
    return impl_->find_peer_by_id_unsafe(peer_id);
}

const std::string& PeerManager::local_peer_id() const {
    return impl_->local_id;
}

uint32_t PeerManager::next_seq() {
    return impl_->sequence.fetch_add(1);
}

// ============================================================================
void PeerManager::broadcast(int channel, const void* data, size_t len,
                            bool reliable) {
    if (!impl_->host || len == 0) return;

    ENetPacket* pkt = enet_packet_create(
        data, len,
        reliable ? ENET_PACKET_FLAG_RELIABLE : ENET_PACKET_FLAG_UNSEQUENCED);

    enet_host_broadcast(impl_->host, channel, pkt);
    // enet_host_broadcast takes ownership — no need to destroy pkt
}

void PeerManager::send_to(_ENetPeer* peer, int channel,
                          const void* data, size_t len, bool reliable) {
    if (!peer || len == 0) return;

    ENetPacket* pkt = enet_packet_create(
        data, len,
        reliable ? ENET_PACKET_FLAG_RELIABLE : ENET_PACKET_FLAG_UNSEQUENCED);

    enet_peer_send(peer, channel, pkt);
}

// ============================================================================
void PeerManager::poll() {
    if (!impl_->host) return;

    ENetEvent event;
    while (enet_host_service(impl_->host, &event, 0) > 0) {
        switch (event.type) {
        case ENET_EVENT_TYPE_CONNECT: {
            // Build peer ID from the remote address
            char ip[64];
            enet_address_get_host_ip(&event.peer->address, ip, sizeof(ip));
            std::string remote_id = make_peer_id(ip, event.peer->address.port);

            // Find our pending PeerInfo or create one (for inbound connections)
            std::string name;
            {
                std::lock_guard lock(impl_->peer_mutex);
                auto* info = impl_->find_peer_by_id_unsafe(remote_id);
                if (info) {
                    info->connected = true;
                    name = info->name;
                } else {
                    // Inbound connection: store it
                    PeerInfo pinfo;
                    pinfo.id = remote_id;
                    pinfo.name = remote_id; // will be filled when we match discovery
                    pinfo.peer = event.peer;
                    pinfo.connected = true;
                    impl_->peer_list.push_back(pinfo);
                }
            }
            handle_connect(event.peer, remote_id, name);
            break;
        }

        case ENET_EVENT_TYPE_DISCONNECT: {
            std::lock_guard lock(impl_->peer_mutex);
            auto* info = impl_->find_peer_unsafe(event.peer);
            if (info) {
                handle_disconnect(*info);
                // Remove from list
                impl_->peer_list.erase(
                    std::remove_if(impl_->peer_list.begin(), impl_->peer_list.end(),
                        [&](const PeerInfo& p) { return p.id == info->id; }),
                    impl_->peer_list.end());
            }
            break;
        }

        case ENET_EVENT_TYPE_RECEIVE: {
            std::string peer_id;
            {
                std::lock_guard lock(impl_->peer_mutex);
                auto* info = impl_->find_peer_unsafe(event.peer);
                if (info) peer_id = info->id;
            }
            if (!peer_id.empty() && impl_->on_data) {
                impl_->on_data(peer_id, event.packet->data,
                               event.packet->dataLength);
            }
            enet_packet_destroy(event.packet);
            break;
        }

        default:
            break;
        }
    }
}

// ============================================================================
void PeerManager::handle_connect(ENetPeer* /*peer*/,
                                 const std::string& remote_id,
                                 const std::string& name) {
    CFW_LOG_INFO("PeerManager: Peer connected — {} ({})", remote_id, name);
    if (impl_->on_connected) {
        PeerInfo info;
        info.id = remote_id;
        info.name = name;
        info.connected = true;
        impl_->on_connected(info);
    }
}

void PeerManager::handle_disconnect(const PeerInfo& info) {
    CFW_LOG_INFO("PeerManager: Peer disconnected — {} ({})", info.id, info.name);
    if (impl_->on_disconnected) {
        impl_->on_disconnected(info);
    }
}

// ============================================================================
void PeerManager::set_on_peer_connected(OnPeerConnected cb) {
    impl_->on_connected = std::move(cb);
}

void PeerManager::set_on_peer_disconnected(OnPeerDisconnected cb) {
    impl_->on_disconnected = std::move(cb);
}

void PeerManager::set_on_data_received(OnDataReceived cb) {
    impl_->on_data = std::move(cb);
}

}  // namespace Corona::Network
