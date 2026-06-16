#include <corona/shared_data_hub.h>
#include <corona/systems/geometry/geometry_system.h>

#include <cmath>
#include <cstdint>
#include <iostream>
#include <string>

namespace {

ktm::fvec3 v3(float x, float y, float z) {
    ktm::fvec3 value;
    value[0] = x;
    value[1] = y;
    value[2] = z;
    return value;
}

struct ActorFixture {
    std::uintptr_t actor{0};
    std::uintptr_t profile{0};
    std::uintptr_t geometry{0};
    std::uintptr_t mechanics{0};
    std::uintptr_t transform{0};
};

ActorFixture make_actor(Corona::SharedDataHub& hub,
                        ktm::fvec3 position,
                        bool editor_temporary) {
    ActorFixture fixture;
    fixture.transform = hub.model_transform_storage().allocate();
    fixture.geometry = hub.geometry_storage().allocate();
    fixture.mechanics = hub.mechanics_storage().allocate();
    fixture.profile = hub.profile_storage().allocate();
    fixture.actor = hub.actor_storage().allocate();

    {
        auto transform = hub.model_transform_storage().acquire_write(fixture.transform);
        transform->position = position;
        transform->scale = v3(1.0f, 1.0f, 1.0f);
    }
    {
        auto geometry = hub.geometry_storage().acquire_write(fixture.geometry);
        geometry->transform_handle = fixture.transform;
    }
    {
        auto mechanics = hub.mechanics_storage().acquire_write(fixture.mechanics);
        mechanics->geometry_handle = fixture.geometry;
        mechanics->min_xyz = v3(-1.0f, -1.0f, -1.0f);
        mechanics->max_xyz = v3(1.0f, 1.0f, 1.0f);
    }
    {
        auto profile = hub.profile_storage().acquire_write(fixture.profile);
        profile->geometry_handle = fixture.geometry;
        profile->mechanics_handle = fixture.mechanics;
    }
    {
        auto actor = hub.actor_storage().acquire_write(fixture.actor);
        actor->profile_handles.push_back(fixture.profile);
        actor->editor_temporary = editor_temporary;
    }
    return fixture;
}

bool nearly_equal(float actual, float expected, float epsilon = 1.0e-4f) {
    return std::abs(actual - expected) <= epsilon;
}

bool expect_near(const char* label, float actual, float expected) {
    if (nearly_equal(actual, expected)) {
        return true;
    }
    std::cerr << label << ": expected " << expected << ", got " << actual << '\n';
    return false;
}

}  // namespace

int main() {
    auto& hub = Corona::SharedDataHub::instance();
    const auto scene_handle = hub.scene_storage().allocate();
    const auto normal = make_actor(hub, v3(0.0f, 0.0f, 0.0f), false);
    const auto cursor = make_actor(hub, v3(1000.0f, 0.0f, 0.0f), true);

    {
        auto scene = hub.scene_storage().acquire_write(scene_handle);
        scene->actor_handles = {normal.actor, cursor.actor};
    }

    Corona::Systems::GeometrySystem geometry_system;
    geometry_system.update();

    auto scene = hub.scene_storage().acquire_read(scene_handle);
    if (!scene.valid()) {
        std::cerr << "scene handle is invalid after GeometrySystem::update\n";
        return 1;
    }
    bool ok = true;
    ok &= expect_near("min_world.x", scene->min_world[0], -1.1f);
    ok &= expect_near("max_world.x", scene->max_world[0], 1.1f);
    ok &= expect_near("center_world.x", scene->center_world[0], 0.0f);
    return ok ? 0 : 1;
}
