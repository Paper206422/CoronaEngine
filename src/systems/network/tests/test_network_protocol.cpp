#include <corona/systems/network/file_transfer.h>
#include <corona/systems/network/network_identity.h>
#include <corona/systems/network/network_system.h>
#include <corona/systems/network/protocol.h>
#include <corona/systems/network/sync_engine.h>
#include <corona/shared_data_hub.h>

#include <cstring>
#include <filesystem>
#include <iostream>
#include <optional>
#include <string>
#include <vector>

namespace {

int g_failed = 0;

void expect_true(bool condition, const char* message) {
    if (!condition) {
        std::cerr << "FAIL: " << message << '\n';
        ++g_failed;
    }
}

void test_file_request_carries_transfer_id() {
    constexpr uint64_t transfer_id = 0x1122334455667788ull;
    auto packet = Corona::Network::build_file_request(transfer_id, "Resource/mesh.obj");

    Corona::Network::BufferReader reader(packet.data(), packet.size());
    expect_true(static_cast<Corona::Network::MessageType>(reader.read_u8()) ==
                    Corona::Network::MessageType::FILE_REQUEST,
                "file request message type");
    expect_true(reader.read_u64() == transfer_id, "file request transfer id");
    const auto path_len = reader.read_u16();
    expect_true(reader.read_string(path_len) == "Resource/mesh.obj",
                "file request path payload");
}

void test_actor_create_carries_actor_guid() {
    float transform[9] = {1, 2, 3, 4, 5, 6, 7, 8, 9};
    Corona::Network::ActorCreatePacked optics{};
    const std::string actor_guid = "actor-1234";

    auto packet = Corona::Network::build_actor_create(
        actor_guid, "Scene/main.scene", "Resource/mesh.obj",
        transform, &optics, sizeof(optics));

    Corona::Network::BufferReader reader(packet.data(), packet.size());
    expect_true(static_cast<Corona::Network::MessageType>(reader.read_u8()) ==
                    Corona::Network::MessageType::ACTOR_CREATE,
                "actor create message type");

    const auto guid_len = reader.read_u16();
    expect_true(reader.read_string(guid_len) == actor_guid,
                "actor create actor guid payload");

    const auto scene_len = reader.read_u16();
    expect_true(reader.read_string(scene_len) == "Scene/main.scene",
                "actor create scene payload");

    const auto path_len = reader.read_u16();
    expect_true(reader.read_string(path_len) == "Resource/mesh.obj",
                "actor create model path payload");
}

void test_actor_create_unpack_preserves_wire_transform() {
    float transform[9] = {10, 20, 30, 1, 2, 3, 4, 5, 6};
    Corona::Network::ActorCreatePacked optics{};
    optics.visible = true;
    optics.bEnableLighting = true;

    auto packet = Corona::Network::build_actor_create(
        "actor-xform", "Scene/main.scene", "Resource/mesh.obj",
        transform, &optics, sizeof(optics));

    Corona::Network::BufferReader reader(packet.data(), packet.size());
    (void)reader.read_u8();
    reader.read_string(reader.read_u16());  // actor_guid
    reader.read_string(reader.read_u16());  // scene_name
    reader.read_string(reader.read_u16());  // model_path

    const float* wire_transform = reinterpret_cast<const float*>(reader.data + reader.pos);
    reader.pos += 36;

    Corona::Network::ActorCreatePacked unpacked{};
    std::memcpy(&unpacked, reader.data + reader.pos, sizeof(unpacked));
    std::memcpy(unpacked.transform, wire_transform, 36);

    for (int i = 0; i < 9; ++i) {
        expect_true(unpacked.transform[i] == transform[i],
                    "actor create unpack preserves transform");
    }
    expect_true(unpacked.visible, "actor create unpack preserves optics visible");
    expect_true(unpacked.bEnableLighting,
                "actor create unpack preserves optics lighting flag");
}

void test_actor_create_carries_dependency_paths() {
    float transform[9] = {};
    Corona::Network::ActorCreatePacked optics{};
    const std::vector<std::string> deps{
        "Resource/mesh.mtl",
        "Resource/texture.png",
    };

    auto packet = Corona::Network::build_actor_create(
        "actor-deps", "Scene/main.scene", "Resource/mesh.obj",
        transform, &optics, sizeof(optics), deps);

    Corona::Network::BufferReader reader(packet.data(), packet.size());
    expect_true(static_cast<Corona::Network::MessageType>(reader.read_u8()) ==
                    Corona::Network::MessageType::ACTOR_CREATE,
                "actor create dependency message type");
    reader.read_string(reader.read_u16());  // actor_guid
    reader.read_string(reader.read_u16());  // scene_name
    reader.read_string(reader.read_u16());  // model_path
    reader.pos += 36 + sizeof(optics);

    expect_true(reader.read_u16() == deps.size(), "actor create dependency count");
    expect_true(reader.read_string(reader.read_u16()) == deps[0],
                "actor create first dependency path");
    expect_true(reader.read_string(reader.read_u16()) == deps[1],
                "actor create second dependency path");
}

void test_file_chunk_carries_transfer_id_and_offset() {
    constexpr uint64_t transfer_id = 0x8877665544332211ull;
    constexpr uint32_t total_size = 4096;
    constexpr uint32_t offset = 1024;
    constexpr uint32_t chunk_index = 2;
    constexpr uint32_t chunk_count = 4;
    const std::vector<uint8_t> bytes{1, 2, 3, 4};

    auto packet = Corona::Network::build_file_chunk(
        transfer_id, "Resource/mesh.obj", total_size, offset, chunk_index,
        chunk_count, bytes.data(), static_cast<uint32_t>(bytes.size()));

    Corona::Network::BufferReader reader(packet.data(), packet.size());
    expect_true(static_cast<Corona::Network::MessageType>(reader.read_u8()) ==
                    Corona::Network::MessageType::FILE_CHUNK,
                "file chunk message type");
    expect_true(reader.read_u64() == transfer_id, "file chunk transfer id");
    const auto path_len = reader.read_u16();
    expect_true(reader.read_string(path_len) == "Resource/mesh.obj",
                "file chunk path payload");
    expect_true(reader.read_u32() == total_size, "file chunk total size");
    expect_true(reader.read_u32() == offset, "file chunk offset");
    expect_true(reader.read_u32() == chunk_index, "file chunk index");
    expect_true(reader.read_u32() == chunk_count, "file chunk count");
    expect_true(reader.read_u32() == bytes.size(), "file chunk data length");
}

void test_ownership_claim_carries_actor_guid() {
    auto packet = Corona::Network::build_ownership_claim("actor-owner");

    Corona::Network::BufferReader reader(packet.data(), packet.size());
    expect_true(static_cast<Corona::Network::MessageType>(reader.read_u8()) ==
                    Corona::Network::MessageType::OWNERSHIP_CLAIM,
                "ownership claim message type");
    expect_true(reader.read_string(reader.read_u16()) == "actor-owner",
                "ownership claim actor guid payload");
}

void test_project_relative_path_validation() {
    const std::filesystem::path root = "D:/project/root";

    auto valid = Corona::Network::resolve_project_relative_path(root, "Resource/mesh.obj");
    expect_true(valid.has_value(), "valid project relative path accepted");
    expect_true(valid->filename() == "mesh.obj", "valid path resolved");

    expect_true(!Corona::Network::resolve_project_relative_path(root, "../escape.obj").has_value(),
                "parent traversal rejected");
    expect_true(!Corona::Network::resolve_project_relative_path(root, "D:/tmp/escape.obj").has_value(),
                "absolute path rejected");
    expect_true(!Corona::Network::resolve_project_relative_path(root, "").has_value(),
                "empty path rejected");
}

void test_network_system_session_role_defaults_to_none() {
    Corona::Systems::NetworkSystem sys;

    expect_true(sys.session_role() == Corona::Systems::NetworkSystem::SessionRole::None,
                "network system default session role is none");
    expect_true(sys.session_role_name() == "none",
                "network system default session role label");
}

void test_actor_device_follow_camera_defaults_false_and_round_trips() {
    auto& hub = Corona::SharedDataHub::instance();

    auto actor = hub.actor_storage().allocate();

    {
        auto a = hub.actor_storage().acquire_read(actor);
        expect_true(!a->follow_camera, "actor follow-camera flag defaults to false");
    }
    {
        auto a = hub.actor_storage().acquire_write(actor);
        a->follow_camera = true;
    }
    {
        auto a = hub.actor_storage().acquire_read(actor);
        expect_true(a->follow_camera, "actor follow-camera flag round trips");
    }

    hub.actor_storage().deallocate(actor);
}

void test_network_identity_registry_resolves_actor_components() {
    auto& hub = Corona::SharedDataHub::instance();

    auto transform = hub.model_transform_storage().allocate();
    auto geometry = hub.geometry_storage().allocate();
    auto optics = hub.optics_storage().allocate();
    auto profile = hub.profile_storage().allocate();
    auto actor = hub.actor_storage().allocate();

    {
        auto g = hub.geometry_storage().acquire_write(geometry);
        g->transform_handle = transform;
    }
    {
        auto o = hub.optics_storage().acquire_write(optics);
        o->geometry_handle = geometry;
    }
    {
        auto p = hub.profile_storage().acquire_write(profile);
        p->optics_handle = optics;
    }
    {
        auto a = hub.actor_storage().acquire_write(actor);
        a->profile_handles.push_back(profile);
    }

    Corona::Network::NetworkIdentityRegistry registry(hub);
    expect_true(registry.register_actor("actor-guid", actor),
                "actor guid registration succeeds");

    auto resolved = registry.resolve_actor("actor-guid");
    expect_true(resolved.has_value(), "actor guid resolves");
    expect_true(resolved->actor_handle == actor, "actor handle resolved");
    expect_true(resolved->profile_handle == profile, "profile handle resolved");
    expect_true(resolved->geometry_handle == geometry, "geometry handle resolved through optics");
    expect_true(resolved->transform_handle == transform, "transform handle resolved");
    expect_true(resolved->optics_handle == optics, "optics handle resolved");
    expect_true(resolved->transform_seq == hub.model_transform_storage().seq_id(transform),
                "transform seq resolved");

    hub.actor_storage().deallocate(actor);
    hub.profile_storage().deallocate(profile);
    hub.optics_storage().deallocate(optics);
    hub.geometry_storage().deallocate(geometry);
    hub.model_transform_storage().deallocate(transform);
}

void test_network_identity_registry_tracks_local_ownership() {
    auto& hub = Corona::SharedDataHub::instance();

    auto transform = hub.model_transform_storage().allocate();
    auto geometry = hub.geometry_storage().allocate();
    auto profile = hub.profile_storage().allocate();
    auto actor = hub.actor_storage().allocate();

    {
        auto g = hub.geometry_storage().acquire_write(geometry);
        g->transform_handle = transform;
    }
    {
        auto p = hub.profile_storage().acquire_write(profile);
        p->geometry_handle = geometry;
    }
    {
        auto a = hub.actor_storage().acquire_write(actor);
        a->profile_handles.push_back(profile);
    }

    Corona::Network::NetworkIdentityRegistry registry(hub);
    expect_true(registry.register_actor("actor-remote-owner", actor, false),
                "remote-owned actor guid registration succeeds");
    const auto transform_seq = hub.model_transform_storage().seq_id(transform);
    auto ownership = registry.local_ownership_for_storage_seq(
        Corona::Network::StorageID::ST_MODEL_TRANSFORM, transform_seq);
    expect_true(ownership.has_value(), "registered actor ownership resolves");
    expect_true(ownership && !*ownership, "registered actor can be remote-owned");

    hub.actor_storage().deallocate(actor);
    hub.profile_storage().deallocate(profile);
    hub.geometry_storage().deallocate(geometry);
    hub.model_transform_storage().deallocate(transform);
}

void test_network_identity_registry_applies_pending_ownership_override() {
    auto& hub = Corona::SharedDataHub::instance();

    auto transform = hub.model_transform_storage().allocate();
    auto geometry = hub.geometry_storage().allocate();
    auto profile = hub.profile_storage().allocate();
    auto actor = hub.actor_storage().allocate();

    {
        auto g = hub.geometry_storage().acquire_write(geometry);
        g->transform_handle = transform;
    }
    {
        auto p = hub.profile_storage().acquire_write(profile);
        p->geometry_handle = geometry;
    }
    {
        auto a = hub.actor_storage().acquire_write(actor);
        a->profile_handles.push_back(profile);
    }

    Corona::Network::NetworkIdentityRegistry registry(hub);
    registry.set_actor_ownership("actor-pending-owner", false);
    expect_true(registry.register_actor("actor-pending-owner", actor, true),
                "actor registration succeeds with pending ownership override");
    auto resolved = registry.resolve_actor("actor-pending-owner");
    expect_true(resolved.has_value(), "actor with pending ownership resolves");
    expect_true(resolved && !resolved->locally_owned,
                "pending remote ownership overrides registration default");

    hub.actor_storage().deallocate(actor);
    hub.profile_storage().deallocate(profile);
    hub.geometry_storage().deallocate(geometry);
    hub.model_transform_storage().deallocate(transform);
}

void test_sync_engine_marks_actor_dirty_entries_with_guid() {
    auto& hub = Corona::SharedDataHub::instance();

    auto transform = hub.model_transform_storage().allocate();
    auto geometry = hub.geometry_storage().allocate();
    auto profile = hub.profile_storage().allocate();
    auto actor = hub.actor_storage().allocate();

    {
        auto t = hub.model_transform_storage().acquire_write(transform);
        t->position.x = 42.0f;
    }
    {
        auto g = hub.geometry_storage().acquire_write(geometry);
        g->transform_handle = transform;
    }
    {
        auto p = hub.profile_storage().acquire_write(profile);
        p->geometry_handle = geometry;
    }
    {
        auto a = hub.actor_storage().acquire_write(actor);
        a->profile_handles.push_back(profile);
    }

    Corona::Network::NetworkIdentityRegistry registry(hub);
    expect_true(registry.register_actor("actor-guid-sync", actor),
                "actor guid registration for sync succeeds");

    Corona::Network::SyncEngine sync;
    std::vector<uint8_t> outgoing;
    sync.initialize("local-peer");
    sync.set_identity_mapping_callbacks(
        [&](Corona::Network::StorageID sid, uint64_t seq) {
            return registry.actor_guid_for_storage_seq(sid, seq);
        },
        [&](Corona::Network::StorageID sid, const std::string& guid)
            -> std::optional<uint64_t> {
            return registry.storage_seq_for_actor_guid(sid, guid);
        });
    sync.set_on_outgoing([&](const std::vector<uint8_t>& packet) {
        outgoing = packet;
    });
    sync.poll_and_sync();

    expect_true(!outgoing.empty(), "sync dirty packet exists");
    if (outgoing.empty()) {
        sync.shutdown();
        hub.actor_storage().deallocate(actor);
        hub.profile_storage().deallocate(profile);
        hub.geometry_storage().deallocate(geometry);
        hub.model_transform_storage().deallocate(transform);
        return;
    }

    bool found_actor_key = false;
    Corona::Network::BufferReader reader(outgoing.data(), outgoing.size());
    expect_true(static_cast<Corona::Network::MessageType>(reader.read_u8()) ==
                    Corona::Network::MessageType::SYNC_DIRTY,
                "sync dirty packet emitted");
    (void)reader.read_u32();
    (void)reader.read_u64();
    uint32_t count = reader.read_u32();
    for (uint32_t i = 0; i < count; ++i) {
        auto sid = static_cast<Corona::Network::StorageID>(reader.read_u16());
        (void)reader.read_u64();
        uint16_t key_len = reader.read_u16();
        uint16_t value_len = reader.read_u16();
        std::string key = reader.read_string(key_len);
        reader.pos += value_len;
        if (sid == Corona::Network::StorageID::ST_MODEL_TRANSFORM &&
            key == "actor:actor-guid-sync:xform") {
            found_actor_key = true;
        }
    }
    expect_true(found_actor_key, "sync dirty transform key carries actor guid");

    sync.shutdown();
    hub.actor_storage().deallocate(actor);
    hub.profile_storage().deallocate(profile);
    hub.geometry_storage().deallocate(geometry);
    hub.model_transform_storage().deallocate(transform);
}

void test_sync_engine_does_not_emit_geometry_resource_or_optics_entries() {
    auto& hub = Corona::SharedDataHub::instance();

    auto transform = hub.model_transform_storage().allocate();
    auto model_resource = hub.model_resource_storage().allocate();
    auto geometry = hub.geometry_storage().allocate();
    auto optics = hub.optics_storage().allocate();
    auto profile = hub.profile_storage().allocate();
    auto actor = hub.actor_storage().allocate();

    {
        auto mr = hub.model_resource_storage().acquire_write(model_resource);
        mr->model_id = 7;
    }
    {
        auto g = hub.geometry_storage().acquire_write(geometry);
        g->transform_handle = transform;
        g->model_resource_handle = model_resource;
    }
    {
        auto o = hub.optics_storage().acquire_write(optics);
        o->geometry_handle = geometry;
    }
    {
        auto p = hub.profile_storage().acquire_write(profile);
        p->geometry_handle = geometry;
        p->optics_handle = optics;
    }
    {
        auto a = hub.actor_storage().acquire_write(actor);
        a->profile_handles.push_back(profile);
    }

    Corona::Network::NetworkIdentityRegistry registry(hub);
    expect_true(registry.register_actor("actor-transform-only", actor),
                "actor guid registration for transform-only sync succeeds");

    Corona::Network::SyncEngine sync;
    std::vector<uint8_t> outgoing;
    sync.initialize("local-peer");
    sync.set_identity_mapping_callbacks(
        [&](Corona::Network::StorageID sid, uint64_t seq) {
            return registry.actor_guid_for_storage_seq(sid, seq);
        },
        [&](Corona::Network::StorageID sid, const std::string& guid)
            -> std::optional<uint64_t> {
            return registry.storage_seq_for_actor_guid(sid, guid);
        });
    sync.set_on_outgoing([&](const std::vector<uint8_t>& packet) {
        outgoing = packet;
    });
    sync.poll_and_sync();

    expect_true(!outgoing.empty(), "transform-only sync dirty packet exists");
    if (!outgoing.empty()) {
        Corona::Network::BufferReader reader(outgoing.data(), outgoing.size());
        (void)reader.read_u8();
        (void)reader.read_u32();
        (void)reader.read_u64();
        uint32_t count = reader.read_u32();
        for (uint32_t i = 0; i < count; ++i) {
            auto sid = static_cast<Corona::Network::StorageID>(reader.read_u16());
            (void)reader.read_u64();
            uint16_t key_len = reader.read_u16();
            uint16_t value_len = reader.read_u16();
            reader.pos += key_len + value_len;
            expect_true(sid != Corona::Network::StorageID::ST_GEOMETRY,
                        "sync dirty does not emit geometry entries");
            expect_true(sid != Corona::Network::StorageID::ST_MODEL_RESOURCE,
                        "sync dirty does not emit model resource entries");
            expect_true(sid != Corona::Network::StorageID::ST_OPTICS,
                        "sync dirty does not emit optics entries");
        }
    }

    sync.shutdown();
    hub.actor_storage().deallocate(actor);
    hub.profile_storage().deallocate(profile);
    hub.optics_storage().deallocate(optics);
    hub.geometry_storage().deallocate(geometry);
    hub.model_resource_storage().deallocate(model_resource);
    hub.model_transform_storage().deallocate(transform);
}

void test_sync_engine_does_not_emit_remote_owned_transform() {
    auto& hub = Corona::SharedDataHub::instance();

    auto transform = hub.model_transform_storage().allocate();
    auto geometry = hub.geometry_storage().allocate();
    auto profile = hub.profile_storage().allocate();
    auto actor = hub.actor_storage().allocate();

    {
        auto t = hub.model_transform_storage().acquire_write(transform);
        t->position.x = 7.0f;
    }
    {
        auto g = hub.geometry_storage().acquire_write(geometry);
        g->transform_handle = transform;
    }
    {
        auto p = hub.profile_storage().acquire_write(profile);
        p->geometry_handle = geometry;
    }
    {
        auto a = hub.actor_storage().acquire_write(actor);
        a->profile_handles.push_back(profile);
    }

    Corona::Network::NetworkIdentityRegistry registry(hub);
    expect_true(registry.register_actor("actor-remote-transform", actor, false),
                "remote-owned actor registration for sync succeeds");

    Corona::Network::SyncEngine sync;
    std::vector<uint8_t> outgoing;
    sync.initialize("local-peer");
    sync.set_identity_mapping_callbacks(
        [&](Corona::Network::StorageID sid, uint64_t seq) {
            return registry.actor_guid_for_storage_seq(sid, seq);
        },
        [&](Corona::Network::StorageID sid, const std::string& guid)
            -> std::optional<uint64_t> {
            return registry.storage_seq_for_actor_guid(sid, guid);
        },
        [&](Corona::Network::StorageID sid, uint64_t seq)
            -> std::optional<bool> {
            return registry.local_ownership_for_storage_seq(sid, seq);
        });
    sync.set_on_outgoing([&](const std::vector<uint8_t>& packet) {
        outgoing = packet;
    });
    sync.poll_and_sync();

    bool found_remote_owned_transform = false;
    if (!outgoing.empty()) {
        Corona::Network::BufferReader reader(outgoing.data(), outgoing.size());
        (void)reader.read_u8();
        (void)reader.read_u32();
        (void)reader.read_u64();
        uint32_t count = reader.read_u32();
        for (uint32_t i = 0; i < count; ++i) {
            auto sid = static_cast<Corona::Network::StorageID>(reader.read_u16());
            (void)reader.read_u64();
            uint16_t key_len = reader.read_u16();
            uint16_t value_len = reader.read_u16();
            std::string key = reader.read_string(key_len);
            reader.pos += value_len;
            if (sid == Corona::Network::StorageID::ST_MODEL_TRANSFORM &&
                key == "actor:actor-remote-transform:xform") {
                found_remote_owned_transform = true;
            }
        }
    }
    expect_true(!found_remote_owned_transform,
                "sync dirty does not emit remote-owned actor transform");

    sync.shutdown();
    hub.actor_storage().deallocate(actor);
    hub.profile_storage().deallocate(profile);
    hub.geometry_storage().deallocate(geometry);
    hub.model_transform_storage().deallocate(transform);
}

void test_sync_engine_does_not_emit_unregistered_transform_when_mapping_enabled() {
    auto& hub = Corona::SharedDataHub::instance();

    auto transform = hub.model_transform_storage().allocate();
    {
        auto t = hub.model_transform_storage().acquire_write(transform);
        t->position.x = 11.0f;
    }

    Corona::Network::SyncEngine sync;
    std::vector<uint8_t> outgoing;
    sync.initialize("local-peer");
    sync.set_identity_mapping_callbacks(
        [](Corona::Network::StorageID, uint64_t) {
            return std::string{};
        },
        [](Corona::Network::StorageID, const std::string&)
            -> std::optional<uint64_t> {
            return std::nullopt;
        },
        [](Corona::Network::StorageID, uint64_t)
            -> std::optional<bool> {
            return std::nullopt;
        });
    sync.set_on_outgoing([&](const std::vector<uint8_t>& packet) {
        outgoing = packet;
    });
    sync.poll_and_sync();

    bool found_unregistered_transform = false;
    if (!outgoing.empty()) {
        Corona::Network::BufferReader reader(outgoing.data(), outgoing.size());
        (void)reader.read_u8();
        (void)reader.read_u32();
        (void)reader.read_u64();
        uint32_t count = reader.read_u32();
        for (uint32_t i = 0; i < count; ++i) {
            auto sid = static_cast<Corona::Network::StorageID>(reader.read_u16());
            (void)reader.read_u64();
            uint16_t key_len = reader.read_u16();
            uint16_t value_len = reader.read_u16();
            std::string key = reader.read_string(key_len);
            reader.pos += value_len;
            if (sid == Corona::Network::StorageID::ST_MODEL_TRANSFORM &&
                key == "xform") {
                found_unregistered_transform = true;
            }
        }
    }
    expect_true(!found_unregistered_transform,
                "sync dirty does not emit unregistered transform when mapping is enabled");

    sync.shutdown();
    hub.model_transform_storage().deallocate(transform);
}

void test_sync_engine_drops_unresolved_actor_transform() {
    auto& hub = Corona::SharedDataHub::instance();

    auto transform = hub.model_transform_storage().allocate();
    {
        auto t = hub.model_transform_storage().acquire_write(transform);
        t->position.x = 1.0f;
        t->position.y = 2.0f;
        t->position.z = 3.0f;
        t->scale.x = 1.0f;
        t->scale.y = 1.0f;
        t->scale.z = 1.0f;
    }
    const auto local_seq = hub.model_transform_storage().seq_id(transform);

    Corona::Network::SyncEngine sync;
    sync.initialize("local-peer");
    sync.set_identity_mapping_callbacks(
        [](Corona::Network::StorageID, uint64_t) {
            return std::string{};
        },
        [](Corona::Network::StorageID, const std::string&)
            -> std::optional<uint64_t> {
            return std::nullopt;
        },
        [](Corona::Network::StorageID, uint64_t)
            -> std::optional<bool> {
            return std::nullopt;
        });

    const float remote_transform[9] = {
        99.0f, 98.0f, 97.0f,
        0.0f, 0.0f, 0.0f,
        1.0f, 1.0f, 1.0f,
    };
    const std::string key = "actor:missing-actor:xform";
    auto entry = Corona::Network::build_dirty_entries(
        Corona::Network::StorageID::ST_MODEL_TRANSFORM,
        local_seq,
        key.c_str(),
        static_cast<uint16_t>(key.size()),
        remote_transform,
        sizeof(remote_transform));
    auto packet = Corona::Network::build_sync_dirty(1, 1, entry, 1);
    sync.handle_incoming("remote-peer", packet.data(), packet.size());

    {
        auto t = hub.model_transform_storage().acquire_read(transform);
        expect_true(t->position.x == 1.0f &&
                        t->position.y == 2.0f &&
                        t->position.z == 3.0f,
                    "sync dirty drops unresolved actor transform");
    }

    sync.shutdown();
    hub.model_transform_storage().deallocate(transform);
}

}  // namespace

int main() {
    test_actor_create_carries_actor_guid();
    test_actor_create_unpack_preserves_wire_transform();
    test_actor_create_carries_dependency_paths();
    test_file_request_carries_transfer_id();
    test_file_chunk_carries_transfer_id_and_offset();
    test_ownership_claim_carries_actor_guid();
    test_project_relative_path_validation();
    test_network_system_session_role_defaults_to_none();
    test_actor_device_follow_camera_defaults_false_and_round_trips();
    test_network_identity_registry_resolves_actor_components();
    test_network_identity_registry_tracks_local_ownership();
    test_network_identity_registry_applies_pending_ownership_override();
    test_sync_engine_marks_actor_dirty_entries_with_guid();
    test_sync_engine_does_not_emit_geometry_resource_or_optics_entries();
    test_sync_engine_does_not_emit_remote_owned_transform();
    test_sync_engine_does_not_emit_unregistered_transform_when_mapping_enabled();
    test_sync_engine_drops_unresolved_actor_transform();

    if (g_failed != 0) {
        std::cerr << g_failed << " network protocol test(s) failed\n";
        return 1;
    }
    return 0;
}
