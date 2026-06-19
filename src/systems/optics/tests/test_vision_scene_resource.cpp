#include <corona/systems/optics/vision_scene_resource.h>

#include <algorithm>
#include <cstdlib>
#include <iostream>
#include <memory>
#include <string_view>
#include <unordered_map>

namespace {

using Corona::Systems::Vision::VisionOwnershipAuditEntry;
using Corona::Systems::Vision::VisionPipelineSource;
using Corona::Systems::Vision::VisionLogicalInstanceKey;
using Corona::Systems::Vision::VisionLogicalInstanceRecord;
using Corona::Systems::Vision::VisionResourceOwnership;
using Corona::Systems::Vision::VisionSceneResource;
using Corona::Systems::Vision::VisionSceneResourceKey;
using Corona::Systems::Vision::VisionSceneResourceKeyHash;
using Corona::Systems::Vision::kVisionPhase4OwnershipAudit;

[[noreturn]] void fail(std::string_view message) {
    std::cerr << "FAIL: " << message << '\n';
    std::exit(1);
}

void expect(bool condition, std::string_view message) {
    if (!condition) {
        fail(message);
    }
}

bool audit_contains(std::string_view name, VisionResourceOwnership ownership) {
    return std::any_of(std::begin(kVisionPhase4OwnershipAudit),
                       std::end(kVisionPhase4OwnershipAudit),
                       [&](const VisionOwnershipAuditEntry& entry) {
                           return entry.name == name &&
                                  entry.target_ownership == ownership;
                       });
}

void ownership_audit_covers_phase4_required_dependencies() {
    expect(audit_contains("Pipeline::scene_",
                          VisionResourceOwnership::SharedLogicalScene),
           "Phase 4 audit should cover Pipeline::scene_ as shared logical scene");
    expect(audit_contains("SceneData logical objects",
                          VisionResourceOwnership::SharedLogicalScene),
           "Phase 4D audit should cover SceneData as shared logical scene");
    expect(audit_contains("Scene::geometry_",
                          VisionResourceOwnership::SharedSceneGpu),
           "Phase 4 audit should cover Scene::geometry_ as shared scene GPU");
    expect(audit_contains("Geometry::gpu_resource_",
                          VisionResourceOwnership::SharedSceneGpu),
           "Phase 4 audit should cover Geometry::gpu_resource_ as shared scene GPU");
    expect(audit_contains("FrameBuffer and denoiser state",
                          VisionResourceOwnership::PerPipelineRenderState),
           "Phase 4 audit should keep framebuffer and denoiser per pipeline");
    expect(audit_contains("Material and medium registries",
                          VisionResourceOwnership::SharedSceneGpu),
           "Phase 4 audit should classify material/medium tables as shared scene GPU data");
    expect(audit_contains("Light tables",
                          VisionResourceOwnership::SharedSceneGpu),
           "Phase 4 audit should classify light tables as shared scene GPU data");
    expect(audit_contains("ImagePool textures",
                          VisionResourceOwnership::SharedSceneGpu),
           "Phase 4 audit should classify image textures as shared scene GPU data");
    expect(audit_contains("Global::pipeline() and Global::bindless_array() users",
                          VisionResourceOwnership::LegacyPipelineOwned),
           "Phase 4 audit should cover Global pipeline/bindless callers");
}

void scene_resource_key_is_mode_independent() {
    const VisionSceneResourceKey external_file{"d:/scene/vision_scene.json",
                                               VisionPipelineSource::ExternalFile};
    const VisionSceneResourceKey external_live{"d:/scene/vision_scene.json",
                                               VisionPipelineSource::ExternalLive};

    std::unordered_map<VisionSceneResourceKey,
                       int,
                       VisionSceneResourceKeyHash>
        resources;
    resources.emplace(external_file, 1);
    resources[external_file] = 2;
    resources.emplace(external_live, 3);

    expect(resources.size() == 2,
           "shared scene resources should be keyed by scene identity/source, not render mode");
    expect(resources[external_file] == 2,
           "same scene resource key should reuse the existing resource slot");
}

void transform_state_lives_on_scene_resource() {
    VisionSceneResource resource;
    resource.key = VisionSceneResourceKey{"d:/scene/vision_scene.json",
                                          VisionPipelineSource::ExternalLive};
    expect(resource.is_external_live(),
           "external_live source should be visible from scene resource");

    resource.external_live_transform_signatures.emplace(42u, 100u);
    expect(!resource.scene_gpu_needs_transform_upload(),
           "fresh scene resource should not need a transform upload");
    resource.mark_transforms_changed();

    expect(resource.logical_transform_version == 1u,
           "scene resource transform version should increment on shared transform update");
    expect(resource.scene_gpu_needs_transform_upload(),
           "scene GPU resource should lag after a shared transform update");
    resource.mark_scene_gpu_transforms_uploaded();
    expect(!resource.scene_gpu_needs_transform_upload(),
           "scene GPU resource should be marked current after upload");
    expect(resource.scene_gpu_transform_version == resource.logical_transform_version,
           "scene GPU transform version should match logical version after upload");
    expect(resource.external_live_transform_signatures.at(42u) == 100u,
           "external_live transform signature cache should live on scene resource");
}

void scene_gpu_resource_lives_on_scene_resource() {
    VisionSceneResource resource;
    expect(!resource.has_scene_gpu_resource(),
           "fresh scene resource should not own a scene GPU resource");
    expect(resource.scene_gpu_resource_identity() == 0u,
           "fresh scene resource GPU resource identity should be empty");

    auto* fake_gpu_resource =
        reinterpret_cast<::vision::GeometryGpuResource*>(0x1000);
    std::shared_ptr<::vision::GeometryGpuResource> shared_gpu_resource(
        fake_gpu_resource,
        [](::vision::GeometryGpuResource*) {});
    resource.set_scene_gpu_resource(shared_gpu_resource);

    expect(resource.has_scene_gpu_resource(),
           "scene GPU resource should be stored on VisionSceneResource");
    expect(resource.scene_gpu_resource_identity() ==
               reinterpret_cast<std::uintptr_t>(fake_gpu_resource),
           "scene GPU resource identity should be the shared resource pointer");
    expect(resource.scene_gpu_resource == shared_gpu_resource,
           "scene GPU resource should reuse the supplied shared pointer");

    resource.set_scene_gpu_resource({});
    expect(!resource.has_scene_gpu_resource(),
           "scene GPU resource should be clearable when the scene resource is released");
}

void logical_scene_lives_on_scene_resource() {
    VisionSceneResource resource;
    expect(!resource.has_logical_scene(),
           "fresh scene resource should not own a logical scene");
    expect(resource.logical_scene_identity() == 0u,
           "fresh logical scene identity should be empty");

    auto* fake_scene = reinterpret_cast<::vision::SceneData*>(0x1800);
    std::shared_ptr<::vision::SceneData> shared_scene(
        fake_scene,
        [](::vision::SceneData*) {});
    resource.set_logical_scene(shared_scene);

    expect(resource.has_logical_scene(),
           "logical scene should be stored on VisionSceneResource");
    expect(resource.logical_scene_identity() ==
               reinterpret_cast<std::uintptr_t>(fake_scene),
           "logical scene identity should be the shared SceneData pointer");
    expect(resource.logical_scene == shared_scene,
           "VisionSceneResource should reuse the supplied logical scene pointer");
}

void logical_scene_is_created_once_per_scene_resource() {
    VisionSceneResource resource;
    int factory_calls = 0;
    auto* fake_scene = reinterpret_cast<::vision::SceneData*>(0x2800);
    auto factory = [&]() {
        ++factory_calls;
        return std::shared_ptr<::vision::SceneData>(
            fake_scene,
            [](::vision::SceneData*) {});
    };

    auto first = resource.ensure_logical_scene(factory);
    auto second = resource.ensure_logical_scene(factory);

    expect(factory_calls == 1,
           "logical scene factory should run only once per VisionSceneResource");
    expect(first == second,
           "same VisionSceneResource should return the same logical scene");
    expect(resource.logical_scene == first,
           "VisionSceneResource should retain the shared logical scene");
}

void scene_gpu_resource_is_created_once_per_scene_resource() {
    VisionSceneResource resource;
    int factory_calls = 0;
    auto* fake_gpu_resource =
        reinterpret_cast<::vision::GeometryGpuResource*>(0x2000);
    auto factory = [&]() {
        ++factory_calls;
        return std::shared_ptr<::vision::GeometryGpuResource>(
            fake_gpu_resource,
            [](::vision::GeometryGpuResource*) {});
    };

    auto first = resource.ensure_scene_gpu_resource(factory);
    auto second = resource.ensure_scene_gpu_resource(factory);

    expect(factory_calls == 1,
           "scene GPU resource factory should run only once per VisionSceneResource");
    expect(first == second,
           "same VisionSceneResource should return the same scene GPU resource");
    expect(resource.scene_gpu_resource == first,
           "VisionSceneResource should retain the shared scene GPU resource");
}

void explicit_reload_resets_loaded_scene_state() {
    VisionSceneResource resource;
    resource.key = VisionSceneResourceKey{"d:/scene/vision_scene.json",
                                          VisionPipelineSource::ExternalLive};
    auto* fake_scene = reinterpret_cast<::vision::SceneData*>(0x3000);
    auto* fake_gpu_resource =
        reinterpret_cast<::vision::GeometryGpuResource*>(0x4000);
    resource.set_logical_scene(std::shared_ptr<::vision::SceneData>(
        fake_scene,
        [](::vision::SceneData*) {}));
    resource.set_scene_gpu_resource(std::shared_ptr<::vision::GeometryGpuResource>(
        fake_gpu_resource,
        [](::vision::GeometryGpuResource*) {}));
    resource.external_live_transform_signatures.emplace(42u, 100u);
    resource.mark_transforms_changed();
    resource.mark_scene_gpu_transforms_uploaded();
    resource.upsert_logical_instance({
        .key = VisionLogicalInstanceKey{.shape_index = 2, .instance_index = 0},
        .actor_handle = 11u,
        .transform_signature = 100u,
        .object_to_world = {1.f, 0.f, 0.f, 0.f,
                            0.f, 1.f, 0.f, 0.f,
                            0.f, 0.f, 1.f, 0.f,
                            0.f, 0.f, 0.f, 1.f},
    });

    resource.reset_loaded_scene();

    expect(!resource.has_logical_scene(),
           "explicit external scene reload should discard the previous logical scene");
    expect(!resource.has_scene_gpu_resource(),
           "explicit external scene reload should discard previous scene GPU resources");
    expect(resource.external_live_transform_signatures.empty(),
           "explicit external scene reload should clear external_live transform cache");
    expect(resource.logical_instance_count() == 0u,
           "explicit external scene reload should clear cached logical instances");
    expect(resource.logical_transform_version == 0u &&
               resource.scene_gpu_transform_version == 0u,
           "explicit external scene reload should reset transform versions");
}

void logical_instance_identity_is_shared_per_scene_resource() {
    VisionSceneResource resource;
    VisionLogicalInstanceRecord first{
        .key = VisionLogicalInstanceKey{.shape_index = 2, .instance_index = 0},
        .actor_handle = 11u,
        .transform_signature = 100u,
        .object_to_world = {1.f, 0.f, 0.f, 0.f,
                            0.f, 1.f, 0.f, 0.f,
                            0.f, 0.f, 1.f, 0.f,
                            0.f, 0.f, 0.f, 1.f},
    };
    VisionLogicalInstanceRecord updated = first;
    updated.actor_handle = 12u;
    updated.transform_signature = 200u;
    updated.object_to_world[12] = 4.f;

    expect(resource.upsert_logical_instance(first),
           "first logical instance insert should report a change");
    expect(resource.logical_instance_count() == 1u,
           "logical instance list should contain one identity after insert");
    expect(resource.upsert_logical_instance(updated),
           "same logical instance key with changed data should update in place");
    expect(resource.logical_instance_count() == 1u,
           "same shape/instance key must not create duplicate logical identity");

    const auto* record = resource.find_logical_instance(first.key);
    expect(record != nullptr,
           "updated logical instance should be findable by stable key");
    expect(record->actor_handle == 12u,
           "logical instance update should replace actor binding data");
    expect(record->transform_signature == 200u,
           "logical instance update should replace transform signature");
    expect(record->object_to_world[12] == 4.f,
           "logical instance update should replace CPU transform data");
    expect(!resource.upsert_logical_instance(updated),
           "upserting identical logical instance data should report no change");
}

void ownership_names_are_stable() {
    expect(Corona::Systems::Vision::vision_resource_ownership_name(
               VisionResourceOwnership::SharedLogicalScene) == "shared_logical_scene",
           "shared logical scene ownership name should be stable");
    expect(Corona::Systems::Vision::vision_resource_ownership_name(
               VisionResourceOwnership::SharedSceneGpu) == "shared_scene_gpu",
           "shared scene GPU ownership name should be stable");
    expect(Corona::Systems::Vision::vision_resource_ownership_name(
               VisionResourceOwnership::PerPipelineRenderState) ==
               "per_pipeline_render_state",
           "per-pipeline ownership name should be stable");
}

}  // namespace

int main() {
    ownership_audit_covers_phase4_required_dependencies();
    scene_resource_key_is_mode_independent();
    transform_state_lives_on_scene_resource();
    logical_scene_lives_on_scene_resource();
    logical_scene_is_created_once_per_scene_resource();
    scene_gpu_resource_lives_on_scene_resource();
    scene_gpu_resource_is_created_once_per_scene_resource();
    explicit_reload_resets_loaded_scene_state();
    logical_instance_identity_is_shared_per_scene_resource();
    ownership_names_are_stable();
    return 0;
}
