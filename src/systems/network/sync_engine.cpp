#include <corona/systems/network/sync_engine.h>

#include <corona/shared_data_hub.h>
#include <corona/kernel/core/i_logger.h>

#include <chrono>
#include <cstring>
#include <mutex>

namespace Corona::Network {

// ============================================================================
// Per-type serialize / deserialize / hash helpers
// ============================================================================

namespace {

// ---- ModelTransform helpers ----
std::string hash_mt(const ModelTransform& t, uint64_t entity_seq) {
    uint64_t h = entity_seq;
    auto mix = [&](const void* p, size_t n) {
        const auto* b = static_cast<const uint8_t*>(p);
        for (size_t i = 0; i < n; ++i) h = h * 31 + b[i];
    };
    mix(&t.position, sizeof(t.position));
    mix(&t.euler_rotation, sizeof(t.euler_rotation));
    mix(&t.scale, sizeof(t.scale));

    char buf[24];
    std::snprintf(buf, sizeof(buf), "%016llx", static_cast<unsigned long long>(h));
    return {buf};
}

void serialize_mt(const ModelTransform& t, std::vector<uint8_t>& entries) {
    const char* key = "xform";
    uint16_t key_len = 5;
    float xform[9];
    xform[0] = t.position.x; xform[1] = t.position.y; xform[2] = t.position.z;
    xform[3] = t.euler_rotation.x; xform[4] = t.euler_rotation.y; xform[5] = t.euler_rotation.z;
    xform[6] = t.scale.x; xform[7] = t.scale.y; xform[8] = t.scale.z;

    auto entry = build_dirty_entries(StorageID::ST_MODEL_TRANSFORM, 0,
                                     key, key_len, xform, sizeof(xform));
    entries.insert(entries.end(), entry.begin(), entry.end());
}

void deserialize_mt(ModelTransform& t, const uint8_t* value, uint16_t value_len) {
    if (value_len != 36) return;
    const auto* f = reinterpret_cast<const float*>(value);
    t.position.x = f[0]; t.position.y = f[1]; t.position.z = f[2];
    t.euler_rotation.x = f[3]; t.euler_rotation.y = f[4]; t.euler_rotation.z = f[5];
    t.scale.x = f[6]; t.scale.y = f[7]; t.scale.z = f[8];
}

// ---- CameraDevice helpers ----
std::string hash_cam(const CameraDevice& c, uint64_t entity_seq) {
    uint64_t h = entity_seq;
    auto mix = [&](const void* p, size_t n) {
        const auto* b = static_cast<const uint8_t*>(p);
        for (size_t i = 0; i < n; ++i) h = h * 31 + b[i];
    };
    mix(&c.position, sizeof(c.position));
    mix(&c.forward, sizeof(c.forward));
    mix(&c.fov, sizeof(c.fov));
    char buf[24];
    std::snprintf(buf, sizeof(buf), "%016llx", static_cast<unsigned long long>(h));
    return {buf};
}

void serialize_cam(const CameraDevice& c, std::vector<uint8_t>& entries) {
    const char* key = "cam";
    uint16_t key_len = 3;
    float data[7];
    data[0] = c.position.x; data[1] = c.position.y; data[2] = c.position.z;
    data[3] = c.forward.x; data[4] = c.forward.y; data[5] = c.forward.z;
    data[6] = c.fov;

    auto entry = build_dirty_entries(StorageID::ST_CAMERA, 0,
                                     key, key_len, data, sizeof(data));
    entries.insert(entries.end(), entry.begin(), entry.end());
}

void deserialize_cam(CameraDevice& c, const uint8_t* value, uint16_t value_len) {
    if (value_len != 28) return;
    const auto* f = reinterpret_cast<const float*>(value);
    c.position.x = f[0]; c.position.y = f[1]; c.position.z = f[2];
    c.forward.x = f[3]; c.forward.y = f[4]; c.forward.z = f[5];
    c.fov = f[6];
}

// ---- EnvironmentDevice helpers ----
std::string hash_env(const EnvironmentDevice& e, uint64_t entity_seq) {
    uint64_t h = entity_seq;
    auto mix = [&](const void* p, size_t n) {
        const auto* b = static_cast<const uint8_t*>(p);
        for (size_t i = 0; i < n; ++i) h = h * 31 + b[i];
    };
    mix(&e.sun_position, sizeof(e.sun_position));
    mix(&e.sun_intensity, sizeof(e.sun_intensity));
    mix(&e.exposure, sizeof(e.exposure));
    char buf[24];
    std::snprintf(buf, sizeof(buf), "%016llx", static_cast<unsigned long long>(h));
    return {buf};
}

void serialize_env(const EnvironmentDevice& e, std::vector<uint8_t>& entries) {
    const char* key = "env";
    uint16_t key_len = 3;
    float data[5];
    data[0] = e.sun_position.x; data[1] = e.sun_position.y; data[2] = e.sun_position.z;
    data[3] = e.sun_intensity;
    data[4] = e.exposure;

    auto entry = build_dirty_entries(StorageID::ST_ENVIRONMENT, 0,
                                     key, key_len, data, sizeof(data));
    entries.insert(entries.end(), entry.begin(), entry.end());
}

void deserialize_env(EnvironmentDevice& e, const uint8_t* value, uint16_t value_len) {
    if (value_len != 20) return;
    const auto* f = reinterpret_cast<const float*>(value);
    e.sun_position.x = f[0]; e.sun_position.y = f[1]; e.sun_position.z = f[2];
    e.sun_intensity = f[3];
    e.exposure = f[4];
}

}  // anonymous namespace

// ============================================================================
// Impl
// ============================================================================

struct SyncEngine::Impl {
    SharedDataHub& hub;
    std::string local_peer_id;

    // Snapshot: key → hash of last-synced value
    std::unordered_map<std::string, std::string> last_synced;
    mutable std::mutex snapshot_mutex;

    // Callbacks
    OnSyncOutgoing on_outgoing;
    OnFullSyncRequest on_full_sync_request;

    // Sequence counter for outgoing packets
    uint32_t seq = 0;

    // True while we are applying remote data — suppress outgoing re-broadcast
    bool syncing_from_remote = false;

    Impl(SharedDataHub& h) : hub(h) {}

    std::string make_key(StorageID sid, uint64_t entity_seq, const std::string& field) {
        char buf[96];
        std::snprintf(buf, sizeof(buf), "%u-%016llx-%s",
                      static_cast<unsigned>(sid),
                      static_cast<unsigned long long>(entity_seq),
                      field.c_str());
        return {buf};
    }

    // Returns true if data changed since last poll
    bool check_snapshot(const std::string& snap_key, const std::string& cur_hash) {
        std::lock_guard lock(snapshot_mutex);
        auto it = last_synced.find(snap_key);
        if (it != last_synced.end() && it->second == cur_hash) return false;
        last_synced[snap_key] = cur_hash;
        return true;
    }

    // Retrieve ObjectId from iterator via the Storage's object_id() method.
    // Fallback: use the data address as ObjectId (same as handle in this Storage).
    template <typename StorageT, typename IterT>
    std::uintptr_t get_id(StorageT& store, IterT& it) {
        return reinterpret_cast<std::uintptr_t>(&(*it));
    }
};

// ============================================================================

SyncEngine::SyncEngine() : impl_(std::make_unique<Impl>(SharedDataHub::instance())) {}

SyncEngine::~SyncEngine() = default;

void SyncEngine::initialize(const std::string& local_peer_id) {
    impl_->local_peer_id = local_peer_id;
    impl_->last_synced.clear();
    impl_->seq = 0;
    CFW_LOG_INFO("SyncEngine: Initialized (peer={})", local_peer_id);
}

void SyncEngine::shutdown() {
    impl_->last_synced.clear();
    CFW_LOG_INFO("SyncEngine: Shut down");
}

// ============================================================================
// Outbound
// ============================================================================

void SyncEngine::poll_and_sync() {
    if (impl_->syncing_from_remote) return;

    auto& hub = impl_->hub;
    std::vector<uint8_t> entries_payload;
    uint32_t dirty_count = 0;

    // --- ModelTransform ---
    {
        auto& store = hub.model_transform_storage();
        for (auto it = store.begin(); it != store.end(); ++it) {
            const ModelTransform& data = *it;
            auto obj_id = impl_->get_id(store, it);
            auto ent_seq = store.seq_id(obj_id);

            std::string cur_hash = hash_mt(data, ent_seq);
            std::string snap_key = impl_->make_key(StorageID::ST_MODEL_TRANSFORM, ent_seq, "xform");

            if (impl_->check_snapshot(snap_key, cur_hash)) {
                serialize_mt(data, entries_payload);
                ++dirty_count;
            }
        }
    }

    // --- CameraDevice ---
    {
        auto& store = hub.camera_storage();
        for (auto it = store.begin(); it != store.end(); ++it) {
            const CameraDevice& data = *it;
            auto obj_id = impl_->get_id(store, it);
            auto ent_seq = store.seq_id(obj_id);

            std::string cur_hash = hash_cam(data, ent_seq);
            std::string snap_key = impl_->make_key(StorageID::ST_CAMERA, ent_seq, "cam");

            if (impl_->check_snapshot(snap_key, cur_hash)) {
                serialize_cam(data, entries_payload);
                ++dirty_count;
            }
        }
    }

    // --- EnvironmentDevice ---
    {
        auto& store = hub.environment_storage();
        for (auto it = store.begin(); it != store.end(); ++it) {
            const EnvironmentDevice& data = *it;
            auto obj_id = impl_->get_id(store, it);
            auto ent_seq = store.seq_id(obj_id);

            std::string cur_hash = hash_env(data, ent_seq);
            std::string snap_key = impl_->make_key(StorageID::ST_ENVIRONMENT, ent_seq, "env");

            if (impl_->check_snapshot(snap_key, cur_hash)) {
                serialize_env(data, entries_payload);
                ++dirty_count;
            }
        }
    }

    if (dirty_count == 0) return;

    using namespace std::chrono;
    auto now_ms = duration_cast<milliseconds>(
        steady_clock::now().time_since_epoch()).count();

    auto pkt = build_sync_dirty(impl_->seq++, static_cast<uint64_t>(now_ms),
                                entries_payload, dirty_count);

    if (impl_->on_outgoing) {
        impl_->on_outgoing(pkt);
    }
}

void SyncEngine::sync_full_to(const std::string& /*target_peer_id*/) {
    CFW_LOG_DEBUG("SyncEngine: sync_full_to not yet implemented");
}

// ============================================================================
// Inbound
// ============================================================================

void SyncEngine::handle_incoming(const std::string& sender_peer_id,
                                 const uint8_t* data, size_t len) {
    if (len < 2) return;

    BufferReader r(data, len);
    auto type = static_cast<MessageType>(r.read_u8());

    if (type == MessageType::SYNC_DIRTY) {
        if (!r.has_remaining(16)) return;
        uint32_t /*seq*/ = r.read_u32();
        uint64_t /*remote_ts*/ = r.read_u64();
        uint32_t count = r.read_u32();

        auto& hub = impl_->hub;

        for (uint32_t i = 0; i < count; ++i) {
            if (!r.has_remaining(2 + 8 + 2 + 2)) break;
            auto storage_id = static_cast<StorageID>(r.read_u16());
            uint64_t /*entity_id*/ = r.read_u64();
            uint16_t key_len = r.read_u16();
            uint16_t value_len = r.read_u16();

            if (!r.has_remaining(key_len + value_len)) break;
            /*std::string key =*/ r.read_string(key_len);
            const uint8_t* value_ptr = r.data + r.pos;
            r.read_string(value_len); // advance past value

            impl_->syncing_from_remote = true;

            switch (storage_id) {
            case StorageID::ST_MODEL_TRANSFORM: {
                auto& store = hub.model_transform_storage();
                for (auto it = store.begin(); it != store.end(); ++it) {
                    ModelTransform& cur = const_cast<ModelTransform&>(*it);
                    deserialize_mt(cur, value_ptr, value_len);
                    break; // apply to first entity (placeholder entity mapping)
                }
                break;
            }
            case StorageID::ST_CAMERA: {
                auto& store = hub.camera_storage();
                for (auto it = store.begin(); it != store.end(); ++it) {
                    CameraDevice& cur = const_cast<CameraDevice&>(*it);
                    deserialize_cam(cur, value_ptr, value_len);
                    break;
                }
                break;
            }
            case StorageID::ST_ENVIRONMENT: {
                auto& store = hub.environment_storage();
                for (auto it = store.begin(); it != store.end(); ++it) {
                    EnvironmentDevice& cur = const_cast<EnvironmentDevice&>(*it);
                    deserialize_env(cur, value_ptr, value_len);
                    break;
                }
                break;
            }
            default:
                break;
            }

            impl_->syncing_from_remote = false;
        }
    }
    else if (type == MessageType::SYNC_FULL) {
        if (!r.has_remaining(8)) return;
        uint32_t /*seq*/ = r.read_u32();
        uint32_t count = r.read_u32();
        CFW_LOG_INFO("SyncEngine: Received SYNC_FULL ({} entries) from {}",
                     count, sender_peer_id);
        // Recurse with remaining payload (same entry format)
        handle_incoming(sender_peer_id, data + 1 + 8, len - 1 - 8);
    }
    else if (type == MessageType::HEARTBEAT) {
        // No action needed
    }
}

// ============================================================================
void SyncEngine::set_on_outgoing(OnSyncOutgoing cb) {
    impl_->on_outgoing = std::move(cb);
}

void SyncEngine::set_on_full_sync_request(OnFullSyncRequest cb) {
    impl_->on_full_sync_request = std::move(cb);
}

}  // namespace Corona::Network
