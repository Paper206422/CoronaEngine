#pragma once

#include <cstdint>
#include <cstring>
#include <string>
#include <vector>

namespace Corona::Network {

// ============================================================================
// Protocol version — increment when binary format changes
// ============================================================================
constexpr uint8_t kProtocolVersion = 1;

// ============================================================================
// Default port for discovery and ENet communication
// ============================================================================
constexpr uint16_t kDefaultPort = 27960;

// ============================================================================
// Discovery uses a separate port to avoid bind conflict with ENet host.
// Discovery port = main_port + 1 (e.g. 27960 → 27961)
// ============================================================================
constexpr uint16_t kDiscoveryPortOffset = 1;

// ============================================================================
// Discovery broadcast interval (ms)
// ============================================================================
constexpr int kDiscoveryIntervalMs = 500;

// ============================================================================
// Peer heartbeat interval (ms) and timeout (ms)
// ============================================================================
constexpr int kHeartbeatIntervalMs = 1000;
constexpr int kPeerTimeoutMs = 3000;

// ============================================================================
// Sync tick interval (ms) — ~60 Hz dirty polling
// ============================================================================
constexpr int kSyncIntervalMs = 16;

// ============================================================================
// ENet channel allocation
// ============================================================================
constexpr int kChannelReliable = 0;    // SYNC_DIRTY, SYNC_FULL
constexpr int kChannelUnreliable = 1;  // HEARTBEAT

// ============================================================================
// Message types (single byte prefix on every packet)
// ============================================================================
enum class MessageType : uint8_t {
    SYNC_DIRTY    = 0x01,  // Incremental dirty sync
    SYNC_FULL     = 0x02,  // Full state snapshot (new peer joins)
    HEARTBEAT     = 0x03,  // Keep-alive
    HELLO         = 0x04,  // Post-connect handshake: exchange stable identity
    ACTOR_CREATE  = 0x10,  // Actor creation event (scene_name + model_path + transform + optics)
    FILE_REQUEST  = 0x11,  // Request model file from peer
    FILE_CHUNK    = 0x12,  // File chunk transfer
};

// ============================================================================
// Storage ID — maps to a SharedDataHub Storage type
// ============================================================================
enum class StorageID : uint16_t {
    ST_MODEL_TRANSFORM = 0,
    ST_GEOMETRY        = 1,
    ST_OPTICS          = 2,
    ST_MECHANICS       = 3,
    ST_ACOUSTICS       = 4,
    ST_SCENE           = 5,
    ST_CAMERA          = 6,
    ST_ACTOR           = 7,
    ST_ENVIRONMENT     = 8,
    ST_MODEL_RESOURCE  = 9,
};

// ============================================================================
// Discovery broadcast packet (UDP, plain struct, fixed layout)
// ============================================================================
struct DiscoveryPacket {
    char magic[6] = {'C','O','R','O','N','A'};  // Magic identifier
    uint8_t protocol_version = kProtocolVersion;
    char instance_name[32] = {};
    uint64_t project_id = 0;
};

// ============================================================================
// SYNC_DIRTY header (binary, after MessageType byte)
// ============================================================================
struct SyncDirtyHeader {
    uint32_t seq = 0;
    uint64_t timestamp_ms = 0;
    uint32_t count = 0;
};

// ============================================================================
// A single dirty entry header (followed by key/value payload)
// ============================================================================
struct SyncDirtyEntryHeader {
    uint16_t storage_id = 0;
    uint64_t entity_id = 0;
    uint16_t key_len = 0;
    uint16_t value_len = 0;
    // Followed by: char[key_len] key, char[value_len] value
};

// ============================================================================
// SYNC_FULL header — full state snapshot
// ============================================================================
struct SyncFullHeader {
    uint32_t seq = 0;
    uint32_t count = 0;
    // Followed by count entries in same format as SYNC_DIRTY
};

// ============================================================================
// Peer ID helper — unique per instance, used for LWW tiebreaking
// ============================================================================
inline std::string make_peer_id(const char* ip, uint16_t port) {
    return std::string(ip) + ":" + std::to_string(port);
}

// ============================================================================
// Compact binary serialization helpers
// ============================================================================

inline void write_u8(std::vector<uint8_t>& buf, uint8_t v) { buf.push_back(v); }
inline void write_u16(std::vector<uint8_t>& buf, uint16_t v) {
    buf.push_back(static_cast<uint8_t>(v & 0xFF));
    buf.push_back(static_cast<uint8_t>((v >> 8) & 0xFF));
}
inline void write_u32(std::vector<uint8_t>& buf, uint32_t v) {
    buf.push_back(static_cast<uint8_t>(v & 0xFF));
    buf.push_back(static_cast<uint8_t>((v >> 8) & 0xFF));
    buf.push_back(static_cast<uint8_t>((v >> 16) & 0xFF));
    buf.push_back(static_cast<uint8_t>((v >> 24) & 0xFF));
}
inline void write_u64(std::vector<uint8_t>& buf, uint64_t v) {
    for (int i = 0; i < 8; ++i) {
        buf.push_back(static_cast<uint8_t>((v >> (i * 8)) & 0xFF));
    }
}
inline void write_bytes(std::vector<uint8_t>& buf, const void* data, size_t len) {
    const auto* p = static_cast<const uint8_t*>(data);
    buf.insert(buf.end(), p, p + len);
}
inline void write_string(std::vector<uint8_t>& buf, const std::string& s) {
    write_u16(buf, static_cast<uint16_t>(s.size()));
    write_bytes(buf, s.data(), s.size());
}

struct BufferReader {
    const uint8_t* data;
    size_t size;
    size_t pos = 0;

    BufferReader(const void* d, size_t s)
        : data(static_cast<const uint8_t*>(d)), size(s) {}

    bool has_remaining(size_t n) const { return pos + n <= size; }

    uint8_t read_u8() {
        return data[pos++];
    }
    uint16_t read_u16() {
        uint16_t v = data[pos] | (static_cast<uint16_t>(data[pos + 1]) << 8);
        pos += 2;
        return v;
    }
    uint32_t read_u32() {
        uint32_t v = 0;
        for (int i = 0; i < 4; ++i) v |= static_cast<uint32_t>(data[pos + i]) << (i * 8);
        pos += 4;
        return v;
    }
    uint64_t read_u64() {
        uint64_t v = 0;
        for (int i = 0; i < 8; ++i) v |= static_cast<uint64_t>(data[pos + i]) << (i * 8);
        pos += 8;
        return v;
    }
    std::string read_string(uint16_t len) {
        std::string s(reinterpret_cast<const char*>(data + pos), len);
        pos += len;
        return s;
    }
};

// ============================================================================
// SYNC_DIRTY message builder
// ============================================================================
inline std::vector<uint8_t> build_sync_dirty(
    uint32_t seq,
    uint64_t timestamp_ms,
    const std::vector<uint8_t>& entries_payload,
    uint32_t entry_count)
{
    std::vector<uint8_t> buf;
    buf.reserve(1 + 16 + entries_payload.size());

    write_u8(buf, static_cast<uint8_t>(MessageType::SYNC_DIRTY));
    write_u32(buf, seq);
    write_u64(buf, timestamp_ms);
    write_u32(buf, entry_count);
    write_bytes(buf, entries_payload.data(), entries_payload.size());

    return buf;
}

// ============================================================================
// SYNC_DIRTY entry builder helper
// ============================================================================
inline std::vector<uint8_t> build_dirty_entries(
    StorageID storage_id,
    uint64_t entity_id,
    const char* key, uint16_t key_len,
    const void* value, uint16_t value_len)
{
    std::vector<uint8_t> buf;
    buf.reserve(4 + 8 + 2 + 2 + key_len + value_len);

    write_u16(buf, static_cast<uint16_t>(storage_id));
    write_u64(buf, entity_id);
    write_u16(buf, key_len);
    write_u16(buf, value_len);
    write_bytes(buf, key, key_len);
    write_bytes(buf, value, value_len);

    return buf;
}

// ============================================================================
// SYNC_FULL message builder
// ============================================================================
inline std::vector<uint8_t> build_sync_full(
    uint32_t seq,
    const std::vector<uint8_t>& entries_payload,
    uint32_t entry_count)
{
    std::vector<uint8_t> buf;
    buf.reserve(1 + 4 + 4 + entries_payload.size());

    write_u8(buf, static_cast<uint8_t>(MessageType::SYNC_FULL));
    write_u32(buf, seq);
    write_u32(buf, entry_count);
    write_bytes(buf, entries_payload.data(), entries_payload.size());

    return buf;
}

// ============================================================================
// Heartbeat packet
// ============================================================================
inline std::vector<uint8_t> build_heartbeat(uint32_t seq) {
    std::vector<uint8_t> buf;
    buf.reserve(1 + 4);
    write_u8(buf, static_cast<uint8_t>(MessageType::HEARTBEAT));
    write_u32(buf, seq);
    return buf;
}

// ============================================================================
// HELLO handshake packet
// ============================================================================
// Sent immediately after an ENet connection is established, in both directions.
// Carries the sender's stable identity so the receiver can rekey the peer:
// ENet's inbound CONNECT event only exposes the remote's ephemeral source port,
// not its listen port, so peer ids would otherwise be asymmetric between the
// two ends. After HELLO, both ends agree on stable_id = "name@listen_port".
//   [1B type=0x04] [2B name_len] [instance_name] [2B listen_port]
// ============================================================================
inline std::vector<uint8_t> build_hello(const std::string& instance_name,
                                        uint16_t listen_port) {
    std::vector<uint8_t> buf;
    buf.reserve(1 + 2 + instance_name.size() + 2);
    write_u8(buf, static_cast<uint8_t>(MessageType::HELLO));
    write_string(buf, instance_name);
    write_u16(buf, listen_port);
    return buf;
}

// ============================================================================
// ACTOR_CREATE message builder
// ============================================================================
// Wire format:
//   [1B type] [2B scene_name_len] [scene_name] [2B model_path_len] [model_path]
//   [36B transform (9 floats)] [72B optics (OpticsPacked)]
// ============================================================================
struct ActorCreatePacked {
    float transform[9];  // pos(3) + rot(3) + scale(3)
    // OpticsPacked — see sync_engine.cpp
    bool visible;
    bool bEnableLighting;
    float metallic;
    float roughness;
    float subsurface;
    float specular;
    float specularTint;
    float anisotropic;
    float sheen;
    float sheenTint;
    float clearcoat;
    float clearcoatGloss;
    float ambient[3];
    float diffuse[3];
    float specular_color[3];
    float shininess;
};

inline std::vector<uint8_t> build_actor_create(
    const std::string& scene_name,
    const std::string& model_path,
    const float* transform,  // 9 floats
    const void* optics_packed, size_t optics_size)
{
    std::vector<uint8_t> buf;
    buf.reserve(1 + 2 + scene_name.size() + 2 + model_path.size() + 36 + optics_size);

    write_u8(buf, static_cast<uint8_t>(MessageType::ACTOR_CREATE));
    write_string(buf, scene_name);
    write_string(buf, model_path);
    write_bytes(buf, transform, 36);
    write_bytes(buf, optics_packed, optics_size);

    return buf;
}

// ============================================================================
// FILE_REQUEST message builder
// ============================================================================
inline std::vector<uint8_t> build_file_request(const std::string& model_path) {
    std::vector<uint8_t> buf;
    buf.reserve(1 + 2 + model_path.size());
    write_u8(buf, static_cast<uint8_t>(MessageType::FILE_REQUEST));
    write_string(buf, model_path);
    return buf;
}

// ============================================================================
// FILE_CHUNK message builder
// ============================================================================
// Wire format:
//   [1B type] [2B model_path_len] [model_path]
//   [4B total_size] [4B chunk_index] [4B chunk_count]
//   [4B chunk_data_len] [chunk_data]
// ============================================================================
inline std::vector<uint8_t> build_file_chunk(
    const std::string& model_path,
    uint32_t total_size,
    uint32_t chunk_index,
    uint32_t chunk_count,
    const void* chunk_data, uint32_t chunk_data_len)
{
    std::vector<uint8_t> buf;
    buf.reserve(1 + 2 + model_path.size() + 4 + 4 + 4 + 4 + chunk_data_len);

    write_u8(buf, static_cast<uint8_t>(MessageType::FILE_CHUNK));
    write_string(buf, model_path);
    write_u32(buf, total_size);
    write_u32(buf, chunk_index);
    write_u32(buf, chunk_count);
    write_u32(buf, chunk_data_len);
    write_bytes(buf, chunk_data, chunk_data_len);

    return buf;
}

}  // namespace Corona::Network
