#pragma once

#include <corona/systems/optics/vision_pipeline_key.h>

#include <array>
#include <cstddef>
#include <cstdint>
#include <functional>
#include <memory>
#include <string>
#include <string_view>
#include <unordered_map>
#include <utility>
#include <vector>

namespace vision {
class GeometryGpuResource;
class SceneData;
}

namespace Corona::Systems::Vision {

enum class VisionResourceOwnership {
    SharedLogicalScene,
    SharedSceneGpu,
    PerPipelineRenderState,
    LegacyPipelineOwned,
};

struct VisionOwnershipAuditEntry {
    std::string_view name;
    VisionResourceOwnership target_ownership;
    std::string_view current_owner;
    std::string_view phase4_action;
};

inline constexpr VisionOwnershipAuditEntry kVisionPhase4OwnershipAudit[] = {
    {"Pipeline::scene_",
     VisionResourceOwnership::SharedLogicalScene,
     "vision::Pipeline",
     "Replaced by per-pipeline Scene view bound to shared VisionSceneResource SceneData in Phase 4D."},
    {"SceneData logical objects",
     VisionResourceOwnership::SharedLogicalScene,
     "VisionSceneResource",
     "Own parsed logical scene identity once per external source."},
    {"Scene::geometry_",
     VisionResourceOwnership::SharedSceneGpu,
     "vision::Scene",
     "Move scene-correlated GPU geometry state into shared scene GPU resource in Phase 4C."},
    {"Geometry::gpu_resource_",
     VisionResourceOwnership::SharedSceneGpu,
     "vision::Geometry",
     "Bind Geometry to the VisionSceneResource scene GPU resource instead of storing Pipeline*."},
    {"GeometryData mesh buffers",
     VisionResourceOwnership::SharedSceneGpu,
     "vision::GeometryData via GeometryGpuResource BindlessArray",
     "Share mesh buffers and mesh handle buffers per logical scene, not per render mode."},
    {"Geometry instance buffers",
     VisionResourceOwnership::SharedSceneGpu,
     "vision::GeometryData via GeometryGpuResource BindlessArray",
     "Update instance buffers and TLAS once per shared logical transform version."},
    {"Accel / BLAS / TLAS",
     VisionResourceOwnership::SharedSceneGpu,
     "vision::GeometryGpuResource with caller-supplied Stream",
     "Move acceleration structures under shared scene GPU resource."},
    {"Material and medium registries",
     VisionResourceOwnership::SharedSceneGpu,
     "vision::SceneData prepared through VisionSceneResource scene GPU bindless",
     "Prepare scene material/medium tables through explicit scene GPU bindless when available."},
    {"Light tables",
     VisionResourceOwnership::SharedSceneGpu,
     "vision::LightManager prepared through VisionSceneResource scene GPU bindless",
     "Prepare scene light tables through explicit scene GPU bindless when available."},
    {"ImagePool textures",
     VisionResourceOwnership::SharedSceneGpu,
     "vision::SceneData ImagePool with VisionSceneResource scene GPU bindless",
     "Keep image textures in the shared logical scene's image pool and bind them through shared scene GPU resources."},
    {"FrameBuffer and denoiser state",
     VisionResourceOwnership::PerPipelineRenderState,
     "vision::Pipeline renderer/framebuffer",
     "Keep per PT/SVGF/SSAT runtime."},
    {"Global::pipeline() and Global::bindless_array() users",
     VisionResourceOwnership::LegacyPipelineOwned,
     "vision::Global / Toolkit helpers",
     "Replace usages that bind scene data to one active pipeline before Phase 5."},
};

struct VisionSceneResourceKey {
    std::string source_path_key;
    VisionPipelineSource source{VisionPipelineSource::EngineBuilt};

    friend bool operator==(const VisionSceneResourceKey& lhs,
                           const VisionSceneResourceKey& rhs) noexcept {
        return lhs.source_path_key == rhs.source_path_key && lhs.source == rhs.source;
    }
};

struct VisionSceneResourceKeyHash {
    [[nodiscard]] std::size_t operator()(
        const VisionSceneResourceKey& key) const noexcept {
        std::size_t seed = std::hash<std::string>{}(key.source_path_key);
        seed ^= std::hash<int>{}(static_cast<int>(key.source)) +
                0x9e3779b97f4a7c15ull + (seed << 6u) + (seed >> 2u);
        return seed;
    }
};

struct VisionLogicalInstanceKey {
    int shape_index{-1};
    int instance_index{-1};

    friend bool operator==(const VisionLogicalInstanceKey& lhs,
                           const VisionLogicalInstanceKey& rhs) noexcept {
        return lhs.shape_index == rhs.shape_index &&
               lhs.instance_index == rhs.instance_index;
    }
};

struct VisionLogicalInstanceKeyHash {
    [[nodiscard]] std::size_t operator()(
        const VisionLogicalInstanceKey& key) const noexcept {
        std::size_t seed = std::hash<int>{}(key.shape_index);
        seed ^= std::hash<int>{}(key.instance_index) +
                0x9e3779b97f4a7c15ull + (seed << 6u) + (seed >> 2u);
        return seed;
    }
};

struct VisionLogicalInstanceRecord {
    VisionLogicalInstanceKey key;
    std::uintptr_t actor_handle{0};
    std::size_t transform_signature{0};
    std::array<float, 16> object_to_world{};
};

struct VisionSceneResource {
    VisionSceneResourceKey key;
    std::string display_source_path;
    std::string overlay_path;
    std::string overlay_guid;
    std::shared_ptr<::vision::SceneData> logical_scene;
    std::shared_ptr<::vision::GeometryGpuResource> scene_gpu_resource;
    std::uint64_t logical_transform_version{0};
    std::uint64_t scene_gpu_transform_version{0};
    std::unordered_map<std::uintptr_t, std::size_t> external_live_transform_signatures;
    std::unordered_map<VisionLogicalInstanceKey,
                       VisionLogicalInstanceRecord,
                       VisionLogicalInstanceKeyHash>
        logical_instances;

    [[nodiscard]] bool is_external_live() const noexcept {
        return key.source == VisionPipelineSource::ExternalLive;
    }

    [[nodiscard]] bool has_scene_gpu_resource() const noexcept {
        return scene_gpu_resource != nullptr;
    }

    [[nodiscard]] bool has_logical_scene() const noexcept {
        return logical_scene != nullptr;
    }

    [[nodiscard]] std::uintptr_t logical_scene_identity() const noexcept {
        return reinterpret_cast<std::uintptr_t>(logical_scene.get());
    }

    [[nodiscard]] std::uintptr_t scene_gpu_resource_identity() const noexcept {
        return reinterpret_cast<std::uintptr_t>(scene_gpu_resource.get());
    }

    void set_logical_scene(std::shared_ptr<::vision::SceneData> scene) noexcept {
        logical_scene = std::move(scene);
    }

    std::shared_ptr<::vision::SceneData> ensure_logical_scene(
        const std::function<std::shared_ptr<::vision::SceneData>()>& factory) {
        if (!logical_scene) {
            logical_scene = factory();
        }
        return logical_scene;
    }

    void set_scene_gpu_resource(
        std::shared_ptr<::vision::GeometryGpuResource> resource) noexcept {
        scene_gpu_resource = std::move(resource);
    }

    void reset_loaded_scene() noexcept {
        logical_scene.reset();
        scene_gpu_resource.reset();
        logical_transform_version = 0;
        scene_gpu_transform_version = 0;
        external_live_transform_signatures.clear();
        logical_instances.clear();
    }

    std::shared_ptr<::vision::GeometryGpuResource> ensure_scene_gpu_resource(
        const std::function<std::shared_ptr<::vision::GeometryGpuResource>()>& factory) {
        if (!scene_gpu_resource) {
            scene_gpu_resource = factory();
        }
        return scene_gpu_resource;
    }

    void mark_transforms_changed() noexcept {
        ++logical_transform_version;
    }

    [[nodiscard]] bool scene_gpu_needs_transform_upload() const noexcept {
        return scene_gpu_transform_version != logical_transform_version;
    }

    void mark_scene_gpu_transforms_uploaded() noexcept {
        scene_gpu_transform_version = logical_transform_version;
    }

    [[nodiscard]] std::size_t logical_instance_count() const noexcept {
        return logical_instances.size();
    }

    [[nodiscard]] const VisionLogicalInstanceRecord* find_logical_instance(
        const VisionLogicalInstanceKey& key) const noexcept {
        const auto iter = logical_instances.find(key);
        return iter == logical_instances.end() ? nullptr : &iter->second;
    }

    bool upsert_logical_instance(VisionLogicalInstanceRecord record) {
        const auto key = record.key;
        auto [iter, inserted] = logical_instances.try_emplace(key, std::move(record));
        if (inserted) {
            return true;
        }
        if (iter->second.actor_handle == record.actor_handle &&
            iter->second.transform_signature == record.transform_signature &&
            iter->second.object_to_world == record.object_to_world) {
            return false;
        }
        iter->second = std::move(record);
        return true;
    }

    void replace_logical_instances(std::vector<VisionLogicalInstanceRecord> records) {
        logical_instances.clear();
        for (auto& record : records) {
            logical_instances.emplace(record.key, std::move(record));
        }
    }
};

[[nodiscard]] inline std::string_view vision_resource_ownership_name(
    VisionResourceOwnership ownership) noexcept {
    switch (ownership) {
        case VisionResourceOwnership::SharedLogicalScene:
            return "shared_logical_scene";
        case VisionResourceOwnership::SharedSceneGpu:
            return "shared_scene_gpu";
        case VisionResourceOwnership::PerPipelineRenderState:
            return "per_pipeline_render_state";
        case VisionResourceOwnership::LegacyPipelineOwned:
            return "legacy_pipeline_owned";
    }
    return "legacy_pipeline_owned";
}

}  // namespace Corona::Systems::Vision
