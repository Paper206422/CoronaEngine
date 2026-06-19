#include <corona/events/display_system_events.h>
#include <corona/events/optics_system_events.h>
#include <corona/kernel/core/i_logger.h>
#include <corona/kernel/event/i_event_bus.h>
#include <corona/kernel/event/i_event_stream.h>
#include <corona/resource/resource_manager.h>
#include <corona/resource/types/image.h>
#include <corona/shared_data_hub.h>
#include <corona/systems/optics/optics_system.h>

#include <algorithm>
#include <cctype>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <exception>
#include <filesystem>
#include <functional>
#include <system_error>
#include <string>
#include <string_view>
#include <unordered_set>
#include <vector>

#include "hardware.h"

// CORONA_ENABLE_VISION is controlled by CMake (-DCORONA_ENABLE_VISION).

//#define CORONA_VISION_IMPORT_DEMO

#ifdef CORONA_ENABLE_VISION
#include "base/import/importer.h"
#include "base/import/parameter_set.h"
#include "base/import/project_desc.h"
#include "base/mgr/global.h"
#include "base/mgr/pipeline.h"
#include "base/mgr/scene.h"
#include "base/sensor/frame_buffer.h"
#include "base/sensor/light_field_types.h"
#include "base/sensor/sensor.h"
#include "rhi/context.h"
#include "vision/vision_geometry_adapter.h"
#include "vision/vision_camera_adapter.h"
#include "vision/vision_light_adapter.h"
#include "vision/vision_zero_copy_bridge.h"
#endif

namespace {

struct RenderInstanceBatch {
    std::vector<Hardware::InstanceInfo> instances;
    std::vector<Hardware::MaterialInfo> materials;
    std::vector<std::uintptr_t> actorHandles;

    void clear() {
        instances.clear();
        materials.clear();
        actorHandles.clear();
    }
};

[[nodiscard]] std::string normalize_scene_path_key(const std::string& raw_path) {
    if (raw_path.empty()) {
        return {};
    }

    std::error_code ec;
    std::filesystem::path path = std::filesystem::u8path(raw_path);
    auto normalized = std::filesystem::weakly_canonical(path, ec);
    if (ec) {
        ec.clear();
        normalized = path.is_absolute() ? path : std::filesystem::absolute(path, ec);
        if (ec) {
            normalized = path;
        }
    }
    auto key = normalized.lexically_normal().generic_string();
#ifdef _WIN32
    std::transform(key.begin(), key.end(), key.begin(), [](unsigned char ch) {
        return static_cast<char>(std::tolower(ch));
    });
#endif
    return key;
}

[[nodiscard]] bool has_external_live_bindings_for_scene(const std::string& scene_path) {
    const auto target_key = normalize_scene_path_key(scene_path);
    if (target_key.empty()) {
        return false;
    }

    auto& hub = Corona::SharedDataHub::instance();
    for (auto scene_it = hub.scene_storage().cbegin(); scene_it != hub.scene_storage().cend(); ++scene_it) {
        const auto& scene_dev = *scene_it;
        if (!scene_dev.enabled) {
            continue;
        }
        for (auto actor_handle : scene_dev.actor_handles) {
            const auto binding = hub.external_vision_binding(actor_handle);
            if (!binding) {
                continue;
            }
            if (normalize_scene_path_key(binding->source_path) == target_key) {
                return true;
            }
        }
    }
    return false;
}

#ifdef CORONA_ENABLE_VISION
[[nodiscard]] ::vision::float4x4 corona_transform_to_vision_o2w(
    const Corona::ModelTransform& transform) {
    const ktm::fmat4x4 corona_mat = transform.compute_matrix();
    ::vision::float4x4 o2w = ::vision::make_float4x4(1.f);
    // Corona/Native uses +Z-forward left-handed coordinates. Vision uses
    // -Z-forward coordinates, so convert object transforms by F * M * F where
    // F = diag(1, 1, -1, 1), matching the built-in Vision geometry adapter.
    for (int col = 0; col < 4; ++col) {
        for (int row = 0; row < 4; ++row) {
            float value = corona_mat[col][row];
            if (row == 2) value = -value;
            if (col == 2) value = -value;
            o2w[col][row] = value;
        }
    }
    return o2w;
}

void mix_hash(std::size_t& sig, std::size_t value) {
    sig ^= value + 0x9e3779b97f4a7c15ULL + (sig << 6) + (sig >> 2);
}

void mix_hash_float(std::size_t& sig, float value) {
    std::uint32_t bits = 0;
    static_assert(sizeof(bits) == sizeof(value), "float must be 32-bit");
    std::memcpy(&bits, &value, sizeof(bits));
    mix_hash(sig, static_cast<std::size_t>(bits));
}

[[nodiscard]] std::size_t external_live_transform_signature(
    const Corona::ModelTransform& transform,
    int shape_index) {
    std::size_t sig = 0;
    mix_hash(sig, static_cast<std::size_t>(shape_index));
    mix_hash_float(sig, transform.position.x);
    mix_hash_float(sig, transform.position.y);
    mix_hash_float(sig, transform.position.z);
    mix_hash_float(sig, transform.euler_rotation.x);
    mix_hash_float(sig, transform.euler_rotation.y);
    mix_hash_float(sig, transform.euler_rotation.z);
    mix_hash_float(sig, transform.scale.x);
    mix_hash_float(sig, transform.scale.y);
    mix_hash_float(sig, transform.scale.z);
    return sig;
}

[[nodiscard]] int external_live_shape_index(const Corona::ExternalVisionBindingDevice& binding) {
    if (binding.shape_index >= 0) {
        return binding.shape_index;
    }

    constexpr std::string_view prefix = "/scene/shapes/";
    if (binding.json_path.rfind(prefix, 0) != 0) {
        return -1;
    }
    try {
        return std::stoi(binding.json_path.substr(prefix.size()));
    } catch (...) {
        return -1;
    }
}

struct ExternalLiveResolvedTransform {
    int shape_index{-1};
    std::size_t signature{0};
    ::vision::float4x4 o2w{};
};

[[nodiscard]] std::optional<ExternalLiveResolvedTransform> resolve_external_live_transform(
    std::uintptr_t actor_handle,
    const Corona::ExternalVisionBindingDevice& binding) {
    const int shape_index = external_live_shape_index(binding);
    if (actor_handle == 0 || shape_index < 0) {
        return std::nullopt;
    }

    auto& hub = Corona::SharedDataHub::instance();
    auto actor = hub.actor_storage().try_acquire_read(actor_handle);
    if (!actor) {
        return std::nullopt;
    }

    for (auto profile_handle : actor->profile_handles) {
        auto profile = hub.profile_storage().try_acquire_read(profile_handle);
        if (!profile) {
            continue;
        }

        std::uintptr_t geometry_handle = profile->geometry_handle;
        if (geometry_handle == 0 && profile->optics_handle != 0) {
            if (auto optics = hub.optics_storage().try_acquire_read(profile->optics_handle)) {
                geometry_handle = optics->geometry_handle;
            }
        }
        if (geometry_handle == 0) {
            continue;
        }

        auto geometry = hub.geometry_storage().try_acquire_read(geometry_handle);
        if (!geometry || geometry->transform_handle == 0) {
            continue;
        }

        auto transform = hub.model_transform_storage().try_acquire_read(geometry->transform_handle);
        if (!transform) {
            continue;
        }

        ExternalLiveResolvedTransform result;
        result.shape_index = shape_index;
        result.signature = external_live_transform_signature(*transform, shape_index);
        result.o2w = corona_transform_to_vision_o2w(*transform);
        return result;
    }

    return std::nullopt;
}
#endif

void apply_pending_camera_moves() {
    auto& hub = Corona::SharedDataHub::instance();
    auto moves = hub.drain_camera_moves();
    if (moves.empty()) {
        return;
    }

    auto& camera_storage = hub.camera_storage();
    for (const auto& move : moves) {
        if (auto camera = camera_storage.try_acquire_write(move.camera_handle)) {
            camera->position = move.position;
            camera->forward = move.forward;
            camera->world_up = move.world_up;
            camera->fov = move.fov;
        }
    }
}

void apply_pending_camera_viewport_updates() {
    auto& hub = Corona::SharedDataHub::instance();
    auto updates = hub.drain_camera_viewport_updates();
    if (updates.empty()) {
        return;
    }

    auto& camera_storage = hub.camera_storage();
    for (const auto& update : updates) {
        if (auto camera = camera_storage.acquire_write(update.camera_handle)) {
            camera->surface = update.surface;
            camera->follows_default_surface = false;
            camera->view_open = update.view_open;
            camera->view_x = update.x;
            camera->view_y = update.y;
            camera->view_width = update.width;
            camera->view_height = update.height;
            const auto render_width =
                static_cast<std::uint32_t>(std::max(update.render_width, 1));
            const auto render_height =
                static_cast<std::uint32_t>(std::max(update.render_height, 1));
            camera->width = render_width;
            camera->height = render_height;
            camera->aspect = static_cast<float>(render_width) /
                             static_cast<float>(render_height);
        }
    }
}

void apply_pending_camera_state_updates() {
    auto& hub = Corona::SharedDataHub::instance();
    auto updates = hub.drain_camera_state_updates();
    if (updates.empty()) {
        return;
    }

    auto& camera_storage = hub.camera_storage();
    for (const auto& update : updates) {
        if (auto camera = camera_storage.acquire_write(update.camera_handle)) {
            if (Corona::has_camera_state_field(
                    update.fields, Corona::CameraStateUpdateField::Surface)) {
                camera->surface = update.surface;
                camera->follows_default_surface = false;
            }
            if (Corona::has_camera_state_field(
                    update.fields, Corona::CameraStateUpdateField::Size)) {
                camera->width = update.width;
                camera->height = update.height;
                camera->aspect = static_cast<float>(update.width) /
                                 static_cast<float>(update.height);
            }
            if (Corona::has_camera_state_field(
                    update.fields, Corona::CameraStateUpdateField::OutputMode)) {
                camera->output_mode = update.output_mode;
            }
            if (Corona::has_camera_state_field(
                    update.fields, Corona::CameraStateUpdateField::RenderBackend)) {
                camera->render_backend = update.render_backend;
            }
            if (Corona::has_camera_state_field(
                    update.fields, Corona::CameraStateUpdateField::ViewState)) {
                camera->view_open = update.view_open;
                camera->view_x = update.view_x;
                camera->view_y = update.view_y;
                camera->view_width = update.view_width;
                camera->view_height = update.view_height;
                camera->move_speed = update.move_speed;
            }
        }
    }
}

void apply_pending_camera_releases() {
    auto& hub = Corona::SharedDataHub::instance();
    for (const auto& release : hub.drain_camera_releases()) {
        if (release.actor_pick_handle != 0) {
            hub.actor_pick_storage().deallocate(release.actor_pick_handle);
        }
        hub.camera_storage().deallocate(release.camera_handle);
    }
}

[[nodiscard]] ktm::fmat4x4 make_orthographic_lh(float width,
                                                float height,
                                                float near_plane,
                                                float far_plane) {
    ktm::fmat4x4 proj = ktm::fmat4x4::from_eye();
    const float depth = std::max(far_plane - near_plane, 1e-4f);

    proj[0][0] = 2.0f / std::max(width, 1e-4f);
    proj[1][1] = -2.0f / std::max(height, 1e-4f);
    proj[2][2] = 1.0f / depth;
    proj[3][2] = -near_plane / depth;
    return proj;
}

[[nodiscard]] ktm::fmat4x4 make_camera_basis_matrix(const Corona::CameraDevice& camera) {
    const ktm::fvec3 forward = ktm::normalize(camera.forward);
    ktm::fvec3 right = ktm::cross(camera.world_up, forward);
    if (ktm::length(right) < 1e-5f) {
        right = ktm::fvec3{1.0f, 0.0f, 0.0f};
    } else {
        right = ktm::normalize(right);
    }
    const ktm::fvec3 up = ktm::normalize(ktm::cross(forward, right));

    ktm::fmat4x4 basis = ktm::fmat4x4::from_eye();
    basis[0][0] = right.x;
    basis[0][1] = right.y;
    basis[0][2] = right.z;
    basis[1][0] = up.x;
    basis[1][1] = up.y;
    basis[1][2] = up.z;
    basis[2][0] = forward.x;
    basis[2][1] = forward.y;
    basis[2][2] = forward.z;
    basis[3][0] = camera.position.x;
    basis[3][1] = camera.position.y;
    basis[3][2] = camera.position.z;
    return basis;
}

[[nodiscard]] ktm::fmat4x4 multiply_ktm_mat4(const ktm::fmat4x4& lhs,
                                             const ktm::fmat4x4& rhs) {
    ktm::fmat4x4 out{};
    for (std::size_t col = 0; col < 4; ++col) {
        for (std::size_t row = 0; row < 4; ++row) {
            out[col][row] = lhs[0][row] * rhs[col][0] +
                            lhs[1][row] * rhs[col][1] +
                            lhs[2][row] * rhs[col][2] +
                            lhs[3][row] * rhs[col][3];
        }
    }
    return out;
}

bool collect_actor_instances_for_visibility(
    const Corona::SceneDevice& scene,
    RasterizerPipeline<visibility_vert_glsl, visibility_frag_glsl>& target_visibility,
    uint32_t target_vp_descriptor,
    bool follow_camera_pass,
    const ktm::fmat4x4* camera_basis,
    RenderInstanceBatch& batch) {
    batch.clear();

    auto& hub = Corona::SharedDataHub::instance();
    auto& actor_storage = hub.actor_storage();
    auto& profile_storage = hub.profile_storage();
    auto& optics_storage = hub.optics_storage();
    auto& geom_storage = hub.geometry_storage();
    auto& transform_storage = hub.model_transform_storage();

    bool has_instances = false;
    uint32_t object_id = 1;
    for (auto actor_handle : scene.actor_handles) {
        auto actor = actor_storage.try_acquire_read(actor_handle);
        if (!actor) {
            ++object_id;
            continue;
        }

        if (actor->follow_camera != follow_camera_pass) {
            ++object_id;
            continue;
        }

        for (auto profile_handle : actor->profile_handles) {
            auto profile = profile_storage.try_acquire_read(profile_handle);
            if (!profile || profile->optics_handle == 0) continue;

            auto optics_acc = optics_storage.try_acquire_read(profile->optics_handle);
            if (!optics_acc) continue;
            const auto& optics = *optics_acc;

            if (!optics.visible) {
                ++object_id;
                continue;
            }
            // Mesh texture descriptors are non-const, so the geometry storage must be
            // write-acquired here. Skipping on transient lock contention causes flicker.
            if (auto geom = geom_storage.try_acquire_write(optics.geometry_handle)) {
                ktm::fmat4x4 model_matrix{ktm::fmat4x4::from_eye()};
                if (auto transform = transform_storage.try_acquire_read(geom->transform_handle)) {
                    model_matrix = transform->compute_matrix();
                    if (camera_basis != nullptr) {
                        model_matrix = multiply_ktm_mat4(*camera_basis, model_matrix);
                    }
                }

                for (auto& m : geom->mesh_handles) {
                    auto material_id = static_cast<uint32_t>(batch.materials.size());
                    {
                        Hardware::MaterialInfo mat_info{};

                        const float lighting_enabled = optics.bEnableLighting ? 1.0f : 0.0f;
                        mat_info.textureDescriptor = m.textureBuffer ? m.textureBuffer.storeDescriptor() : 0;

                        if (optics.bEnableLighting) {
                            mat_info.metallic = optics.metallic;
                            mat_info.roughness = optics.roughness;
                            mat_info.subsurface = optics.subsurface;
                            mat_info.specular = optics.specular;
                            mat_info.specularTint = optics.specularTint;
                            mat_info.anisotropic = optics.anisotropic;
                            mat_info.sheen = optics.sheen;
                            mat_info.sheenTint = optics.sheenTint;
                            mat_info.clearcoat = optics.clearcoat;
                            mat_info.clearcoatGloss = optics.clearcoatGloss;
                        } else {
                            mat_info.metallic = 0.0f;
                            mat_info.roughness = 1.0f;
                            mat_info.subsurface = 0.0f;
                            mat_info.specular = 0.0f;
                            mat_info.specularTint = 0.0f;
                            mat_info.anisotropic = 0.0f;
                            mat_info.sheen = 0.0f;
                            mat_info.sheenTint = 0.0f;
                            mat_info.clearcoat = 0.0f;
                            mat_info.clearcoatGloss = 0.0f;
                        }

                        mat_info.lightingEnabled = lighting_enabled;
                        mat_info.materialColor = ktm::fvec4{
                            m.materialColor[0], m.materialColor[1],
                            m.materialColor[2], m.materialColor[3]};
                        batch.materials.push_back(mat_info);
                    }

                    auto instance_id = static_cast<uint32_t>(batch.instances.size());
                    {
                        Hardware::InstanceInfo inst{};
                        inst.modelMatrix = model_matrix;
                        inst.vertexBufferIndex =
                            m.vertexStorageBuffer ? m.vertexStorageBuffer.storeDescriptor() : 0;
                        inst.indexBufferIndex =
                            m.indexStorageBuffer ? m.indexStorageBuffer.storeDescriptor() : 0;
                        inst.materialID = material_id;
                        inst.objectID = object_id;
                        batch.instances.push_back(inst);
                        batch.actorHandles.push_back(actor_handle);
                        has_instances = true;
                    }

                    target_visibility.pushConsts.modelMatrix = model_matrix;
                    target_visibility.pushConsts.uniformBufferIndex = target_vp_descriptor;
                    target_visibility.pushConsts.instanceID = instance_id + 1;
                    target_visibility[visibility_frag_glsl::pushConsts::textureIndex] =
                        m.textureBuffer ? m.textureBuffer.storeDescriptor() : static_cast<uint32_t>(0);
                    target_visibility.record(m.indexBuffer, m.vertexBuffer);
                }
            }
            ++object_id;
        }
    }
    return has_instances;
}

void upload_instance_tables(const RenderInstanceBatch& batch,
                            HardwareBuffer& instance_buffer,
                            HardwareBuffer& material_buffer) {
    if (!batch.instances.empty()) {
        instance_buffer.copyFromData(
            batch.instances.data(),
            batch.instances.size() * sizeof(Hardware::InstanceInfo));
    }
    if (!batch.materials.empty()) {
        material_buffer.copyFromData(
            batch.materials.data(),
            batch.materials.size() * sizeof(Hardware::MaterialInfo));
    }
}

#ifdef CORONA_ENABLE_VISION
ocarina::SP<vision::Pipeline> renderPipeline;
vision::Device* visionDevicePtr = nullptr;
std::unordered_set<std::uintptr_t> retainedVisionContexts;

[[nodiscard]] auto make_default_vision_project_desc() -> vision::ProjectDesc {
    // Each *Desc has in-class default initializers; the overridden
    // init(const ParameterSet&) is only used for JSON-driven configuration.
    // The ParameterSet MUST wrap an empty JSON *object* (not a default-
    // constructed null): NodeDesc::set_parameter() asserts is_object() and the
    // various init() helpers call ps.value("param", ...)/set_parameter(), which
    // raise nlohmann type_errors on a null payload. Because nlohmann is built
    // with JSON_NOEXCEPTION here, that surfaces as abort()/SIGABRT instead of a
    // catchable std::exception, crashing before any pipeline plugin is created.
    const vision::ParameterSet empty_ps{vision::DataWrap::object()};
    vision::ProjectDesc project_desc;
    project_desc.pipeline_desc.init(empty_ps);
    project_desc.renderer_desc.sampler_desc.init(empty_ps);
    project_desc.renderer_desc.spectrum_desc.init(empty_ps);
    project_desc.renderer_desc.light_sampler_desc.init(empty_ps);
    project_desc.renderer_desc.integrator_desc.init(empty_ps);
    project_desc.renderer_desc.warper_desc.init(empty_ps);
    project_desc.renderer_desc.render_setting.init(empty_ps);
    project_desc.scene_desc.sensor_desc.init(empty_ps);
    project_desc.output_desc.init(empty_ps);
    return project_desc;
}

[[nodiscard]] auto create_vision_pipeline() -> ocarina::SP<vision::Pipeline> {
    auto project_desc = make_default_vision_project_desc();
    auto pipeline = vision::Node::create_shared<vision::Pipeline>(project_desc.pipeline_desc);
    if (!pipeline) {
        return {};
    }
    pipeline->init_project(project_desc);
    pipeline->init_postprocessor(project_desc.renderer_desc.denoiser_desc);
    pipeline->init();
    return pipeline;
}

[[nodiscard]] auto select_scene_camera_handle(const Corona::SceneDevice& scene) -> std::uintptr_t {
    if (scene.active_camera_handle != 0 &&
        std::find(scene.camera_handles.begin(),
                  scene.camera_handles.end(),
                  scene.active_camera_handle) != scene.camera_handles.end()) {
        return scene.active_camera_handle;
    }
    return scene.camera_handles.empty() ? 0 : scene.camera_handles.front();
}

void log_vision_pipeline_diagnostics(vision::Pipeline& pipeline,
                                     const std::string& label) {
    auto* fb = pipeline.frame_buffer();
    if (fb == nullptr) {
        CFW_LOG_WARNING("OpticsSystem: Vision pipeline {} has no framebuffer", label);
        return;
    }

    const auto pixel_res = fb->resolution();
    const auto raytracing_res = fb->raytracing_resolution();
    const bool lightfield =
        dynamic_cast<const vision::ILightFieldFrameBuffer*>(fb) != nullptr;
    const bool output_denoise = pipeline.output_desc().denoise;

    std::string denoiser_type = "none";
    bool denoiser_enabled = false;
    bool denoiser_supports_lightfield = false;
    if (auto* integrator = pipeline.renderer().integrator().get()) {
        if (auto* illum = dynamic_cast<vision::IlluminationIntegrator*>(integrator)) {
            if (auto* denoiser = illum->denoiser()) {
                denoiser_type = std::string(denoiser->impl_type());
                denoiser_enabled = denoiser->enabled();
                denoiser_supports_lightfield = denoiser->supports_lightfield();
            }
        }
    }

    const bool ssat_active = lightfield &&
                             denoiser_type == "SSAT" &&
                             denoiser_enabled &&
                             output_denoise &&
                             denoiser_supports_lightfield;

    CFW_LOG_INFO(
        "OpticsSystem: Vision pipeline {} framebuffer={}, pixel_res=({}, {}), "
        "raytracing_res=({}, {}), lightfield={}, denoiser={}, "
        "denoiser_enabled={}, output_denoise={}, SSAT active={}",
        label,
        std::string(fb->impl_type()),
        pixel_res.x,
        pixel_res.y,
        raytracing_res.x,
        raytracing_res.y,
        lightfield,
        denoiser_type,
        denoiser_enabled,
        output_denoise,
        ssat_active);
}

// Loads a Vision scene from disk and brings it to a renderable state, mirroring
// the reference snippet (import_scene -> init -> prepare -> prepare_view_texture).
// Resolves relative texture/mesh references against the scene's own folder.
// Returns an empty pointer if the file is missing or import fails so the caller
// can skip without crashing.
[[nodiscard]] auto import_vision_scene_from_file(const std::filesystem::path& scene_path)
    -> ocarina::SP<vision::Pipeline> {
    std::error_code ec;
    if (!std::filesystem::exists(scene_path, ec)) {
        CFW_LOG_ERROR("OpticsSystem: Vision scene not found: {}", scene_path.string());
        return {};
    }
    // Resolve relative texture/mesh references against the scene's own folder.
    vision::Global::instance().set_scene_path(scene_path.parent_path());
    auto pipeline = vision::Importer::import_scene(scene_path);
    if (!pipeline) {
        CFW_LOG_ERROR("OpticsSystem: Vision import_scene returned null for {}",
                      scene_path.string());
        return {};
    }
    pipeline->init();
    pipeline->prepare();
    // prepare() does not create FrameBuffer::view_texture_; the render path tone
    // maps into it and we later read it back, so create it explicitly here.
    pipeline->frame_buffer()->prepare_view_texture();
    return pipeline;
}

#ifdef CORONA_VISION_IMPORT_DEMO
// Absolute path to a known-good Vision scene used purely to verify that the
// Vision backend can produce a picture in isolation (i.e. without the
// CoronaEngine->Vision scene-building adapters). Change this to point at any
// local *.json scene. Kept as a constant so it is trivial to edit/relocate.
constexpr const char* kVisionDemoScenePath =
    R"(E:\CoronaExample\test_vision\render_scene\cbox\vision_scene.json)";
#endif
#endif  // CORONA_ENABLE_VISION
}  // namespace

namespace Corona::Systems {

struct OpticsSystem::NativeViewResources {
    HardwareImage visibility;
    HardwareImage depth;
    std::optional<RasterizerPipeline<visibility_vert_glsl, visibility_frag_glsl>>
        visibility_pipeline;
    uint32_t width = 0;
    uint32_t height = 0;
    uint64_t last_used_frame = 0;
};

// per-camera UI overlay 中间产物（Native 与 Vision 共用，单一分配来源）。
struct OpticsSystem::UiViewResources {
    HardwareImage ui_visibility;  ///< RGBA32_UINT StorageImage
    HardwareImage ui_depth;       ///< D32_FLOAT DepthImage
    uint32_t width = 0;
    uint32_t height = 0;
    uint64_t last_used_frame = 0;
};

OpticsSystem::OpticsSystem() {
    set_target_fps(60);
}

OpticsSystem::~OpticsSystem() = default;

bool OpticsSystem::initialize_vision_backend_if_enabled() {
    // Vision backend is lazily initialized on first switch to Vision mode.
    return true;
}

bool OpticsSystem::initialize_hardware_resources() {
    try {
        hardware_ = std::make_unique<Hardware>();

        hardware_->gbufferSize.x = 1920;
        hardware_->gbufferSize.y = 1080;

        // --- Uniform buffers ---
        hardware_->uniformBuffer =
            HardwareBuffer(sizeof(Hardware::UniformBufferObject), BufferUsage::StorageBuffer);
        hardware_->vpUniformBuffer = HardwareBuffer(sizeof(Hardware::VPUniformBufferObject),
                                                    BufferUsage::StorageBuffer);
        hardware_->uiVpUniformBuffer = HardwareBuffer(sizeof(Hardware::VPUniformBufferObject),
                                                      BufferUsage::StorageBuffer);

        // --- Instance & Material table buffers (pre-allocate reasonable capacity) ---
        constexpr uint32_t kMaxInstances = 4096;
        constexpr uint32_t kMaxMaterials = 1024;
        hardware_->instanceInfoBuffer = HardwareBuffer(
            kMaxInstances * static_cast<uint32_t>(sizeof(Hardware::InstanceInfo)),
            BufferUsage::StorageBuffer);
        hardware_->uiInstanceInfoBuffer = HardwareBuffer(
            kMaxInstances * static_cast<uint32_t>(sizeof(Hardware::InstanceInfo)),
            BufferUsage::StorageBuffer);
        hardware_->materialTableBuffer = HardwareBuffer(
            kMaxMaterials * static_cast<uint32_t>(sizeof(Hardware::MaterialInfo)),
            BufferUsage::StorageBuffer);
        hardware_->uiMaterialTableBuffer = HardwareBuffer(
            kMaxMaterials * static_cast<uint32_t>(sizeof(Hardware::MaterialInfo)),
            BufferUsage::StorageBuffer);
        hardware_->actorPickBuffer = HardwareBuffer(sizeof(std::uint32_t), BufferUsage::StorageBuffer);

        // finalOutputImage 不再在此创建：每个 surface 的最终输出由
        // acquire_surface_target() 按需创建（改造1: per-surface 输出）。
    } catch (const std::exception&) {
        CFW_LOG_CRITICAL("OpticsSystem: Failed to initialize hardware resources");
        return false;
    }

    return true;
}

bool OpticsSystem::initialize_render_pipelines() {
    try {
        hardware_->visibilityPipeline.emplace();
        hardware_->uiVisibilityPipeline.emplace();
        hardware_->lightingPipeline.emplace();
        hardware_->skyPipeline.emplace();
        hardware_->tonemapPipeline.emplace();
        hardware_->debugResolvePipeline.emplace();
        hardware_->actorPickPipeline.emplace();
        hardware_->opticsOverlayPipeline.emplace();
        hardware_->opticsCursorPipeline.emplace();
        hardware_->opticsUiWarpPipeline.emplace();
        hardware_->opticsCompositePipeline.emplace();
#ifdef CORONA_ENABLE_VISION
        hardware_->visionResolvePipeline.emplace();
#endif
        hardware_->shaderHasInit = true;
    } catch (const std::exception& e) {
        CFW_LOG_CRITICAL("OpticsSystem: Failed to initialize typed pipelines: {}", e.what());
        return false;
    }

    return true;
}

void OpticsSystem::bind_native_view_resources(std::uintptr_t camera_handle,
                                              uint32_t width,
                                              uint32_t height,
                                              uint64_t frame_index) {
    width = std::max(width, 1u);
    height = std::max(height, 1u);

    auto& resources_ptr = native_view_resources_[camera_handle];
    if (!resources_ptr) {
        resources_ptr = std::make_unique<NativeViewResources>();
    }
    auto& resources = *resources_ptr;
    if (resources.width != width || resources.height != height ||
        !resources.visibility || !resources.depth || !resources.visibility_pipeline) {
        hardware_->executor.waitForDeferredResources();
        resources.visibility = HardwareImage(width, height, ImageFormat::RGBA32_UINT,
                                             ImageUsage::StorageImage);
        resources.depth = HardwareImage(width, height, ImageFormat::D32_FLOAT,
                                        ImageUsage::DepthImage);
        resources.visibility_pipeline.emplace();
        resources.visibility_pipeline->visibilityData = resources.visibility;
        resources.visibility_pipeline->setDepthImage(resources.depth);
        resources.width = width;
        resources.height = height;
    }
    resources.last_used_frame = frame_index;

    hardware_->gbufferSize.x = width;
    hardware_->gbufferSize.y = height;
    hardware_->visibilityImage = resources.visibility;
    hardware_->depthImage = resources.depth;

    // UI visibility/depth 由共享 helper 统一分配并绑定（Native 与 Vision 同源）。
    ensure_ui_view_resources(camera_handle, width, height, frame_index);
}

void OpticsSystem::ensure_ui_view_resources(std::uintptr_t camera_handle,
                                            uint32_t width,
                                            uint32_t height,
                                            uint64_t frame_index) {
    width = std::max(width, 1u);
    height = std::max(height, 1u);

    auto& resources_ptr = ui_view_resources_[camera_handle];
    if (!resources_ptr) {
        resources_ptr = std::make_unique<UiViewResources>();
    }
    auto& resources = *resources_ptr;
    if (resources.width != width || resources.height != height ||
        !resources.ui_visibility || !resources.ui_depth) {
        hardware_->executor.waitForDeferredResources();
        resources.ui_visibility = HardwareImage(width, height, ImageFormat::RGBA32_UINT,
                                                ImageUsage::StorageImage);
        resources.ui_depth = HardwareImage(width, height, ImageFormat::D32_FLOAT,
                                           ImageUsage::DepthImage);
        resources.width = width;
        resources.height = height;
    }
    resources.last_used_frame = frame_index;

    // 不修改 gbufferSize（调用方负责）。仅绑定共享句柄到本相机的 UI 图。
    hardware_->uiVisibilityImage = resources.ui_visibility;
    hardware_->uiDepthImage = resources.ui_depth;
}

void OpticsSystem::evict_idle_native_view_resources(uint64_t frame_index) {
    for (auto it = native_view_resources_.begin(); it != native_view_resources_.end();) {
        const auto& resources = *it->second;
        const bool idle =
            frame_index > resources.last_used_frame &&
            (frame_index - resources.last_used_frame) > kNativeViewIdleEvictFrames;
        if (idle) {
            it = native_view_resources_.erase(it);
        } else {
            ++it;
        }
    }
}

void OpticsSystem::evict_idle_ui_view_resources(uint64_t frame_index) {
    for (auto it = ui_view_resources_.begin(); it != ui_view_resources_.end();) {
        const auto& resources = *it->second;
        const bool idle =
            frame_index > resources.last_used_frame &&
            (frame_index - resources.last_used_frame) > kUiViewIdleEvictFrames;
        if (idle) {
            it = ui_view_resources_.erase(it);
        } else {
            ++it;
        }
    }
}

OpticsSystem::SurfaceRenderTarget& OpticsSystem::acquire_surface_target(void* surface,
                                                                        uint32_t width,
                                                                        uint32_t height,
                                                                        uint64_t frame_index) {
    width = std::max(width, 1u);
    height = std::max(height, 1u);

    auto& target = surface_targets_[surface];

    // 首次出现该 surface：分配独立的 image_storage 句柄。
    if (target.image_handle == 0) {
        target.image_handle = SharedDataHub::instance().image_storage().allocate();
        // 触碰一次写句柄以保活存储项；逐帧的 image/executor 在渲染提交后更新。
        if (auto accessor =
                SharedDataHub::instance().image_storage().acquire_write(target.image_handle)) {
            // keep-alive only
        }
    }

    // 分辨率变化或首次：创建/重建该 surface 的 Optics 输出图。
    if (!target.final_output || !target.ui_overlay || !target.ui_warped_overlay ||
        !target.composite_output ||
        target.width != width || target.height != height) {
        if (target.image_handle != 0) {
            if (auto image_device =
                    SharedDataHub::instance().image_storage().acquire_write(target.image_handle)) {
                hardware_->executor.wait(image_device->consumed_executor);
            }
        }
        hardware_->executor.waitForDeferredResources();
        target.final_output =
            HardwareImage(width, height, ImageFormat::RGBA16_FLOAT, ImageUsage::StorageImage);
        target.ui_overlay =
            HardwareImage(width, height, ImageFormat::RGBA16_FLOAT, ImageUsage::StorageImage);
        target.ui_warped_overlay =
            HardwareImage(width, height, ImageFormat::RGBA16_FLOAT, ImageUsage::StorageImage);
        target.composite_output =
            HardwareImage(width, height, ImageFormat::RGBA16_FLOAT, ImageUsage::StorageImage);
        target.width = width;
        target.height = height;
    }

    target.last_used_frame = frame_index;
    return target;
}

void OpticsSystem::evict_idle_surface_targets(uint64_t frame_index) {
    for (auto it = surface_targets_.begin(); it != surface_targets_.end();) {
        const auto& target = it->second;
        const bool idle =
            frame_index > target.last_used_frame &&
            (frame_index - target.last_used_frame) > kSurfaceTargetIdleEvictFrames;
        if (idle) {
            if (target.image_handle != 0) {
                SharedDataHub::instance().image_storage().deallocate(target.image_handle);
            }
            it = surface_targets_.erase(it);
        } else {
            ++it;
        }
    }
}

bool OpticsSystem::initialize(Kernel::ISystemContext* ctx) {
    (void)ctx;

    if (!initialize_vision_backend_if_enabled()) {
        return false;
    }

    if (!initialize_hardware_resources()) {
        return false;
    }

    if (!initialize_render_pipelines()) {
        return false;
    }

    if (auto* event_bus = ctx->event_bus()) {
        screenshot_request_sub_id_ = event_bus->subscribe<Events::ScreenshotRequestEvent>(
            [this](const Events::ScreenshotRequestEvent& event) {
                if (event.camera_handle == 0 || event.file_path.empty()) {
                    return;
                }
                std::lock_guard<std::mutex> lock(screenshot_mutex_);
                pending_screenshots_.push_back({event.camera_handle, event.file_path, event.completion_promise});
            });

        backend_switch_sub_id_ = event_bus->subscribe<Events::RenderBackendSwitchEvent>(
            [this](const Events::RenderBackendSwitchEvent& event) {
                if (event.camera_handle == 0) {
                    return;
                }
                if (auto camera = SharedDataHub::instance().camera_storage().acquire_write(
                        event.camera_handle)) {
#ifdef CORONA_ENABLE_VISION
                    camera->render_backend =
                        event.backend == static_cast<int>(RenderBackend::Vision)
                            ? CameraRenderBackend::Vision
                            : CameraRenderBackend::Native;
#else
                    camera->render_backend = CameraRenderBackend::Native;
#endif
                }
            });

#ifdef CORONA_ENABLE_VISION
        vision_scene_load_sub_id_ = event_bus->subscribe<Events::VisionSceneLoadEvent>(
            [this](const Events::VisionSceneLoadEvent& event) {
                // Only stash the path here (any thread). The actual import touches
                // the CUDA pipeline and MUST run on the render thread, so it is
                // deferred to apply_pending_vision_scene_load() in update().
                std::lock_guard<std::mutex> lock(vision_scene_load_mutex_);
                pending_vision_scene_load_ = event.scene_path;
            });
#endif
    }

    return true;
}

void OpticsSystem::update() {
    apply_pending_camera_moves();
    apply_pending_camera_viewport_updates();
    apply_pending_camera_state_updates();
    apply_pending_camera_releases();

#ifdef CORONA_ENABLE_VISION
    std::vector<std::uintptr_t> requested_vision_cameras;
    bool camera_views_ready = true;
    for (const auto& scene : SharedDataHub::instance().scene_storage()) {
        if (!scene.enabled) {
            continue;
        }
        for (const auto camera_handle : scene.camera_handles) {
            if (auto camera =
                    SharedDataHub::instance().camera_storage().try_acquire_read(camera_handle);
                camera) {
                if (camera->view_open && camera->surface == nullptr) {
                    camera_views_ready = false;
                }
                if (camera->render_backend == CameraRenderBackend::Vision &&
                    camera->surface != nullptr) {
                    requested_vision_cameras.push_back(camera_handle);
                }
            }
        }
    }

    if (camera_views_ready && !requested_vision_cameras.empty() &&
        !vision_initialized_ && !init_vision_lazy()) {
        CFW_LOG_WARNING("OpticsSystem: Vision init failed, falling back affected cameras to Native");
        for (const auto camera_handle : requested_vision_cameras) {
            if (auto camera =
                    SharedDataHub::instance().camera_storage().acquire_write(camera_handle)) {
                camera->render_backend = CameraRenderBackend::Native;
            }
        }
    }
#endif

    if (!hardware_->shaderHasInit || !hardware_->lightingPipeline ||
        !hardware_->skyPipeline || !hardware_->tonemapPipeline ||
        !hardware_->debugResolvePipeline || !hardware_->opticsOverlayPipeline ||
        !hardware_->opticsCursorPipeline || !hardware_->opticsUiWarpPipeline ||
        !hardware_->opticsCompositePipeline) {
        return;
    }

    static float frame_count = 0.0f;
    static uint64_t frame_index = 0;

    float dt = delta_time();
    frame_count += dt;
    ++frame_index;

    optics_pipeline(frame_count, frame_index);
}

void OpticsSystem::optics_pipeline(float frame_count, uint64_t frame_index) {
    drain_viewport_ui_pointer_commands();

    auto& lighting = *hardware_->lightingPipeline;
    auto& sky = *hardware_->skyPipeline;
    auto& tonemap = *hardware_->tonemapPipeline;
    // UI overlay/warp/composite 管线现由 compose_surface_ui_overlay() 内部使用。

    for (auto scene_it = SharedDataHub::instance().scene_storage().cbegin();
         scene_it != SharedDataHub::instance().scene_storage().cend(); ++scene_it) {
        const auto& scene = *scene_it;
        if (!scene.enabled)
            continue;

        for (auto cam_handle : scene.camera_handles) {
            if (auto camera = SharedDataHub::instance().camera_storage().try_acquire_read(cam_handle)) {
                if (camera->render_backend == CameraRenderBackend::Vision) {
                    continue;
                }
                void* surface = camera->surface;
                if (surface == nullptr) {
                    continue;
                }

                // 显示相机：在覆写其 surface 专属输出前，等待上一帧合成器消费完成。
                auto& target = acquire_surface_target(surface, camera->width,
                                                      camera->height, frame_index);
                if (auto consumed_device =
                        SharedDataHub::instance().image_storage().acquire_write(target.image_handle)) {
                    hardware_->executor.wait(consumed_device->consumed_executor);
                }
                bind_native_view_resources(cam_handle, camera->width, camera->height,
                                           frame_index);
                auto& visibility =
                    *native_view_resources_.at(cam_handle)->visibility_pipeline;

                // ================================================================
                // 1. Update camera uniform buffers
                // ================================================================
                hardware_->uniformBufferObjects.eyePosition = camera->position;
                hardware_->uniformBufferObjects.eyeDir = camera->forward;
                hardware_->uniformBufferObjects.eyeViewMatrix = camera->compute_view_matrix();
                hardware_->uniformBufferObjects.eyeProjMatrix = camera->compute_projection_matrix();
                hardware_->vpUniformBufferObjects.viewProjMatrix = camera->compute_view_proj_matrix();
                hardware_->vpUniformBuffer.copyFromData(&hardware_->vpUniformBufferObjects,
                                                        sizeof(hardware_->vpUniformBufferObjects));

                // Configure visibility pipeline render targets
                auto& actor_storage = SharedDataHub::instance().actor_storage();
                auto& profile_storage = SharedDataHub::instance().profile_storage();
                auto& optics_storage = SharedDataHub::instance().optics_storage();
                auto& geom_storage = SharedDataHub::instance().geometry_storage();
                auto& transform_storage = SharedDataHub::instance().model_transform_storage();

                RenderInstanceBatch sceneBatch;

                auto collect_actor_instances_for_pass =
                    [&](auto& target_visibility,
                        uint32_t target_vp_descriptor,
                        bool follow_camera_pass,
                        const ktm::fmat4x4* camera_basis,
                        RenderInstanceBatch& batch) -> bool {
                    batch.clear();

                    bool has_instances = false;
                    uint32_t object_id = 1;
                    for (auto actor_handle : scene.actor_handles) {
                        auto actor = actor_storage.try_acquire_read(actor_handle);
                        if (!actor) {
                            ++object_id;
                            continue;
                        }

                        if (actor->follow_camera != follow_camera_pass) {
                            ++object_id;
                            continue;
                        }

                        for (auto profile_handle : actor->profile_handles) {
                            auto profile = profile_storage.try_acquire_read(profile_handle);
                            if (!profile || profile->optics_handle == 0) continue;

                            auto optics_acc = optics_storage.try_acquire_read(profile->optics_handle);
                            if (!optics_acc) continue;
                            const auto& optics = *optics_acc;

                            if (!optics.visible) {
                                ++object_id;
                                continue;
                            }
                            // 阻塞写锁：mesh 的 textureBuffer.storeDescriptor() 是非 const，
                            // 必须持写句柄。此处绝不能用 _nowait——拿不到锁就跳过会导致该物体
                            // 本帧不进 instance/material 表（模型没上 GPU），表现为闪烁。用阻塞
                            // 版 try_acquire_write 等锁（不漏帧），槽位失效时返回无效句柄而非抛异常。
                            if (auto geom = geom_storage.try_acquire_write(optics.geometry_handle)) {
                                ktm::fmat4x4 model_matrix{ktm::fmat4x4::from_eye()};
                                if (auto transform = transform_storage.try_acquire_read(geom->transform_handle)) {
                                    model_matrix = transform->compute_matrix();
                                    if (camera_basis != nullptr) {
                                        model_matrix = multiply_ktm_mat4(*camera_basis, model_matrix);
                                    }
                                }

                                for (auto& m : geom->mesh_handles) {
                                    // --- Collect material info ---
                                    auto materialID = static_cast<uint32_t>(batch.materials.size());
                                    {
                                        Hardware::MaterialInfo mat_info{};

                                        // 光照开关：bEnableLighting 为 true 时物体接收光照，false 时不接收光照
                                        float lighting_enabled = optics.bEnableLighting ? 1.0f : 0.0f;

                                        mat_info.textureDescriptor = m.textureBuffer
                                                                         ? m.textureBuffer.storeDescriptor()
                                                                         : 0;

                                        // 当光照关闭时，将 BRDF 参数设为中性值，使物体不受方向光影响
                                        if (optics.bEnableLighting) {
                                            mat_info.metallic = optics.metallic;
                                            mat_info.roughness = optics.roughness;
                                            mat_info.subsurface = optics.subsurface;
                                            mat_info.specular = optics.specular;
                                            mat_info.specularTint = optics.specularTint;
                                            mat_info.anisotropic = optics.anisotropic;
                                            mat_info.sheen = optics.sheen;
                                            mat_info.sheenTint = optics.sheenTint;
                                            mat_info.clearcoat = optics.clearcoat;
                                            mat_info.clearcoatGloss = optics.clearcoatGloss;
                                        } else {
                                            // 关闭光照：使用中性BRDF参数（完全漫反射，无高光，无清漆等）
                                            mat_info.metallic = 0.0f;
                                            mat_info.roughness = 1.0f;
                                            mat_info.subsurface = 0.0f;
                                            mat_info.specular = 0.0f;
                                            mat_info.specularTint = 0.0f;
                                            mat_info.anisotropic = 0.0f;
                                            mat_info.sheen = 0.0f;
                                            mat_info.sheenTint = 0.0f;
                                            mat_info.clearcoat = 0.0f;
                                            mat_info.clearcoatGloss = 0.0f;
                                        }

                                        mat_info.lightingEnabled = lighting_enabled;
                                        mat_info.materialColor = ktm::fvec4{
                                            m.materialColor[0], m.materialColor[1],
                                            m.materialColor[2], m.materialColor[3]};
                                        batch.materials.push_back(mat_info);
                                    }

                                    // --- Collect instance info ---
                                    auto instanceID = static_cast<uint32_t>(batch.instances.size());
                                    {
                                        Hardware::InstanceInfo inst{};
                                        inst.modelMatrix = model_matrix;
                                        inst.vertexBufferIndex = m.vertexStorageBuffer
                                                                     ? m.vertexStorageBuffer.storeDescriptor()
                                                                     : 0;
                                        inst.indexBufferIndex = m.indexStorageBuffer
                                                                    ? m.indexStorageBuffer.storeDescriptor()
                                                                    : 0;
                                        inst.materialID = materialID;
                                        inst.objectID = object_id;
                                        batch.instances.push_back(inst);
                                        batch.actorHandles.push_back(actor_handle);
                                        has_instances = true;
                                    }

                                    // --- Record visibility draw call ---
                                    target_visibility.pushConsts.modelMatrix = model_matrix;
                                    target_visibility.pushConsts.uniformBufferIndex =
                                        target_vp_descriptor;
                                    // VBuffer uses 1-based instanceID (0 = background sentinel after clear)
                                    target_visibility.pushConsts.instanceID = instanceID + 1;
                                    // Alpha-cutout: pass texture descriptor for discard test
                                    if (m.textureBuffer) {
                                        target_visibility[visibility_frag_glsl::pushConsts::textureIndex] =
                                            m.textureBuffer.storeDescriptor();
                                    } else {
                                        target_visibility[visibility_frag_glsl::pushConsts::textureIndex] =
                                            static_cast<uint32_t>(0);
                                    }
                                    target_visibility.record(m.indexBuffer, m.vertexBuffer);
                                }
                            }
                            ++object_id;
                        }
                    }
                    return has_instances;
                };

                auto upload_instance_tables = [&](const RenderInstanceBatch& batch,
                                                  HardwareBuffer& instance_buffer,
                                                  HardwareBuffer& material_buffer) {
                    if (!batch.instances.empty()) {
                        instance_buffer.copyFromData(
                            batch.instances.data(),
                            batch.instances.size() * sizeof(Hardware::InstanceInfo));
                    }
                    if (!batch.materials.empty()) {
                        material_buffer.copyFromData(
                            batch.materials.data(),
                            batch.materials.size() * sizeof(Hardware::MaterialInfo));
                    }
                };

                const uint32_t sceneVpDescriptor = hardware_->vpUniformBuffer.storeDescriptor();
                collect_actor_instances_for_pass(visibility,
                                                 sceneVpDescriptor,
                                                 false,
                                                 nullptr,
                                                 sceneBatch);
                upload_instance_tables(sceneBatch,
                                       hardware_->instanceInfoBuffer,
                                       hardware_->materialTableBuffer);

                // ================================================================
                // 4. Environment parameters
                // ================================================================
                ktm::fvec3 sun_dir;
                sun_dir.x = 1.0f;
                sun_dir.y = 1.0f;
                sun_dir.z = 1.0f;
                std::uint32_t floor_grid_enabled = 1;
                ktm::fvec3 sun_color{1.0f, 0.949f, 0.853f};
                float sun_intensity = 10.0f;
                float sky_intensity = 20.0f;
                float exposure = 1.0f;
                if (scene.environment != 0) {
                    if (auto env = SharedDataHub::instance().environment_storage().try_acquire_read(
                            scene.environment)) {
                        sun_dir = env->sun_position;
                        floor_grid_enabled = env->floor_grid_enabled;
                        sun_color = env->sun_color;
                        sun_intensity = env->sun_intensity;
                        sky_intensity = env->sky_intensity;
                        exposure = env->exposure;
                    }
                }
                sun_dir = ktm::normalize(sun_dir);

                hardware_->uniformBuffer.copyFromData(&hardware_->uniformBufferObjects,
                                                      sizeof(hardware_->uniformBufferObjects));
                const uint32_t uboDescriptor = hardware_->uniformBuffer.storeDescriptor();
                const uint32_t depthDescriptor = visibility.getDepthImage().storeDescriptor();

                HardwareImage& render_target = target.final_output;
                HardwareImage* presented_target = &render_target;
                const uint32_t finalOutputDescriptor = render_target.storeDescriptor();

                // ================================================================
                // 5. Lighting pass: VBuffer decode + PBR direct illumination
                // ================================================================
                lighting.pushConsts.gbufferSize = hardware_->gbufferSize;
                lighting.pushConsts.visibilityImageIndex =
                    hardware_->visibilityImage.storeDescriptor();
                lighting.pushConsts.depthImageIndex = depthDescriptor;
                lighting.pushConsts.instanceInfoBufferIndex =
                    hardware_->instanceInfoBuffer.storeDescriptor();
                lighting.pushConsts.materialTableBufferIndex =
                    hardware_->materialTableBuffer.storeDescriptor();
                lighting.pushConsts.vpBufferIndex =
                    hardware_->vpUniformBuffer.storeDescriptor();
                lighting.pushConsts.finalOutputImage = finalOutputDescriptor;
                lighting.pushConsts.uniformBufferIndex = uboDescriptor;
                lighting.pushConsts.sun_dir = sun_dir;
                {
                    ktm::fvec3 lightColor;
                    lightColor.x = sun_color.x * sun_intensity;
                    lightColor.y = sun_color.y * sun_intensity;
                    lightColor.z = sun_color.z * sun_intensity;
                    lighting.pushConsts.lightColor = lightColor;
                }
                lighting.pushConsts.ambientIntensity = sun_intensity * 0.02f;

                // ================================================================
                // 6. Sky pass: atmospheric scattering + floor grid
                // ================================================================
                sky.pushConsts.gbufferSize = hardware_->gbufferSize;
                sky.pushConsts.gbufferDepthImage = depthDescriptor;
                sky.pushConsts.finalOutputImage = finalOutputDescriptor;
                sky.pushConsts.uniformBufferIndex = uboDescriptor;
                sky.pushConsts.sun_dir = sun_dir;
                sky.pushConsts.floor_grid_enabled = floor_grid_enabled;
                sky.pushConsts.cameraFov = camera->fov;
                sky.pushConsts.sky_intensity = sky_intensity;

                // ================================================================
                // 7. Tonemap pass: ACES filmic HDR → LDR
                // ================================================================
                tonemap.pushConsts.gbufferSize = hardware_->gbufferSize;
                tonemap.pushConsts.inputImage = finalOutputDescriptor;
                tonemap.pushConsts.outputImage = finalOutputDescriptor;
                tonemap.pushConsts.exposure = exposure;

                // ================================================================
                // 8. GPU sync & dispatch
                // ================================================================
                const uint32_t dispatchX = (hardware_->gbufferSize.x + 7u) / 8u;
                const uint32_t dispatchY = (hardware_->gbufferSize.y + 7u) / 8u;

                const bool is_debug_mode = camera->output_mode != CameraOutputMode::FinalColor;
                const auto actor_pick_request = take_pending_actor_pick(cam_handle);

                if (actor_pick_request) {
                    auto& actorPick = *hardware_->actorPickPipeline;
                    actorPick.pushConsts.pixel = ktm::uvec2{actor_pick_request->x, actor_pick_request->y};
                    actorPick.pushConsts.visibilityImageIndex =
                        hardware_->visibilityImage.storeDescriptor();
                    actorPick.pushConsts.outputBufferIndex =
                        hardware_->actorPickBuffer.storeDescriptor();
                }

                if (is_debug_mode) {
                    // ============================================================
                    // Debug path: visibility + debug_resolve only (skip lighting/sky/tonemap)
                    // ============================================================
                    auto& debugResolve = *hardware_->debugResolvePipeline;

                    debugResolve.pushConsts.gbufferSize = hardware_->gbufferSize;
                    debugResolve.pushConsts.visibilityImageIndex =
                        hardware_->visibilityImage.storeDescriptor();
                    debugResolve.pushConsts.depthImageIndex = depthDescriptor;
                    debugResolve.pushConsts.instanceInfoBufferIndex =
                        hardware_->instanceInfoBuffer.storeDescriptor();
                    debugResolve.pushConsts.materialTableBufferIndex =
                        hardware_->materialTableBuffer.storeDescriptor();
                    debugResolve.pushConsts.vpBufferIndex =
                        hardware_->vpUniformBuffer.storeDescriptor();
                    debugResolve.pushConsts.outputImageIndex = finalOutputDescriptor;

                    // Map CameraOutputMode to debugMode uint
                    uint32_t debugMode = 0;
                    switch (camera->output_mode) {
                        case CameraOutputMode::BaseColor:
                            debugMode = 0;
                            break;
                        case CameraOutputMode::Normal:
                            debugMode = 1;
                            break;
                        case CameraOutputMode::WorldPosition:
                            debugMode = 2;
                            break;
                        case CameraOutputMode::ObjectID:
                            debugMode = 3;
                            break;
                        case CameraOutputMode::VisibilityBuffer:
                            debugMode = 4;
                            break;
                        default:
                            debugMode = 0;
                            break;
                    }
                    debugResolve.pushConsts.debugMode = debugMode;

                    hardware_->executor << visibility(hardware_->gbufferSize.x, hardware_->gbufferSize.y)
                                        << debugResolve(dispatchX, dispatchY, 1);
                } else {
                    // ============================================================
                    // Normal rendering path: full pipeline
                    // ============================================================
                    hardware_->executor << visibility(hardware_->gbufferSize.x, hardware_->gbufferSize.y)
                                        << lighting(dispatchX, dispatchY, 1)
                                        << sky(dispatchX, dispatchY, 1)
                                        << tonemap(dispatchX, dispatchY, 1);
                }

                if (actor_pick_request) {
                    hardware_->executor << (*hardware_->actorPickPipeline)(1, 1, 1);
                }

                hardware_->executor << hardware_->executor.commit();
                // Camera UBO/VP/instance/material buffers are shared by the Native
                // pipelines. Finish this camera before the CPU overwrites those
                // buffers for the next visible camera, otherwise surfaces can
                // alternate between camera poses.
                hardware_->executor.waitForDeferredResources();

                if (actor_pick_request) {
                    complete_actor_pick(*actor_pick_request, sceneBatch.actorHandles);
                }

                if (!is_debug_mode) {
                    const auto ui_state =
                        SharedDataHub::instance().viewport_ui_state(cam_handle);
                    presented_target = compose_surface_ui_overlay(
                        cam_handle, *camera, scene, target, render_target,
                        ui_state.mode, ui_state.calibration, frame_index);
                    // 仅在真正发生合成时 commit，保持无 follow-actor 时的原有行为
                    // （此时 render_target 已在上方 scene pass 提交）。
                    if (presented_target == &target.composite_output) {
                        hardware_->executor << hardware_->executor.commit();
                    }
                }

                // 截图对任意相机（显示/离屏）都适用，从最终 Optics 输出读取。
                process_pending_screenshots(cam_handle, *presented_target);

                // 显示相机把自己 surface 的输出发布给 DisplaySystem（按 surface 区分）。
                if (auto image_device =
                        SharedDataHub::instance().image_storage().acquire_write(target.image_handle)) {
                    image_device->image = *presented_target;
                    image_device->executor = hardware_->executor;
                }

                if (auto* event_bus = context()->event_bus()) {
                    event_bus->publish<Events::OpticsFrameReadyEvent>({surface,
                                                                       target.image_handle,
                                                                       frame_index,
                                                                       hardware_->gbufferSize.x,
                                                                       hardware_->gbufferSize.y});
                }

#ifdef CORONA_ENABLE_VISION
                // (Vision render path runs in run_vision_frame below)
#endif
            }
        }
    }

#ifdef CORONA_ENABLE_VISION
    if (vision_initialized_) {
        run_vision_frame(frame_count, frame_index);
    }
#endif

    // 回收长期空闲（相机解绑 / 视口关闭）的 surface 目标，约束动态开关下的显存占用。
    evict_idle_surface_targets(frame_index);
    evict_idle_native_view_resources(frame_index);
    evict_idle_ui_view_resources(frame_index);
}

void OpticsSystem::drain_viewport_ui_pointer_commands() {
    auto commands = SharedDataHub::instance().drain_viewport_ui_pointer_commands();
    for (const auto& command : commands) {
        if (command.camera_handle == 0) {
            continue;
        }

        auto& state = viewport_cursor_states_[command.camera_handle];
        if (command.sequence < state.sequence) {
            continue;
        }

        std::string event_type = command.event_type;
        std::transform(event_type.begin(), event_type.end(), event_type.begin(), [](unsigned char ch) {
            return static_cast<char>(std::tolower(ch));
        });
        const bool hide_event =
            event_type == "leave" || event_type == "mouseout" ||
            event_type == "pointerleave" || event_type == "cancel" ||
            event_type == "pointercancel" || event_type == "blur";

        state.x = command.x;
        state.y = command.y;
        state.buttons = command.buttons;
        state.modifiers = command.modifiers;
        state.cursor_shape = command.cursor_shape;
        state.sequence = command.sequence;
        state.visible = !hide_event && command.cursor_shape != ViewportUiCursorShape::Hidden;
    }
}

HardwareImage* OpticsSystem::compose_surface_ui_overlay(
    std::uintptr_t camera_handle,
    const CameraDevice& camera,
    const SceneDevice& scene,
    SurfaceRenderTarget& target,
    HardwareImage& background,
    ViewportUiMode mode,
    const ViewportUiCalibration& calibration,
    uint64_t frame_index) {
    (void)frame_index;

    auto& uiVisibility = *hardware_->uiVisibilityPipeline;
    auto& opticsOverlay = *hardware_->opticsOverlayPipeline;
    auto& opticsCursor = *hardware_->opticsCursorPipeline;
    auto& opticsUiWarp = *hardware_->opticsUiWarpPipeline;
    auto& opticsComposite = *hardware_->opticsCompositePipeline;

    const uint32_t dispatchX = (hardware_->gbufferSize.x + 7u) / 8u;
    const uint32_t dispatchY = (hardware_->gbufferSize.y + 7u) / 8u;
    uint32_t cursorDispatchX = dispatchX;
    uint32_t cursorDispatchY = dispatchY;

    // follow-camera UI 使用正交投影：把跟随相机的 actor 以屏幕贴合方式光栅化。
    const ktm::fmat4x4 camera_basis = make_camera_basis_matrix(camera);
    constexpr float kFollowCameraOrthoHeight = 2.0f;
    constexpr float kFollowCameraNear = -1000.0f;
    constexpr float kFollowCameraFar = 1000.0f;
    const float ortho_width = kFollowCameraOrthoHeight * camera.aspect;
    const ktm::fmat4x4 ortho_proj =
        make_orthographic_lh(ortho_width, kFollowCameraOrthoHeight,
                             kFollowCameraNear, kFollowCameraFar);

    hardware_->vpUniformBufferObjects.viewProjMatrix =
        multiply_ktm_mat4(ortho_proj, camera.compute_view_matrix());
    hardware_->uiVpUniformBuffer.copyFromData(&hardware_->vpUniformBufferObjects,
                                              sizeof(hardware_->vpUniformBufferObjects));
    const uint32_t uiVpDescriptor = hardware_->uiVpUniformBuffer.storeDescriptor();

    uiVisibility.visibilityData = hardware_->uiVisibilityImage;
    uiVisibility.setDepthImage(hardware_->uiDepthImage);

    RenderInstanceBatch uiBatch;
    const bool has_follow_camera_instances =
        collect_actor_instances_for_visibility(scene, uiVisibility, uiVpDescriptor,
                                               /*follow_camera_pass=*/true,
                                               &camera_basis, uiBatch);

    const bool stereo_ui = mode == ViewportUiMode::Stereo3D;
    const auto cursor_it = viewport_cursor_states_.find(camera_handle);
    const bool cursor_visible =
        stereo_ui && cursor_it != viewport_cursor_states_.end() && cursor_it->second.visible &&
        cursor_it->second.cursor_shape != ViewportUiCursorShape::Hidden &&
        std::isfinite(cursor_it->second.x) && std::isfinite(cursor_it->second.y);
    const ViewportCursorState* cursor_state =
        cursor_visible ? &cursor_it->second : nullptr;

    const auto ui_instance_count = static_cast<std::uint32_t>(uiBatch.instances.size());
    auto& ui_log_state = ui_pass_log_states_[camera_handle];
    if (!ui_log_state.has_state ||
        ui_log_state.has_follow_camera_instances != has_follow_camera_instances ||
        ui_log_state.stereo_ui != stereo_ui ||
        ui_log_state.cursor_visible != cursor_visible ||
        ui_log_state.instance_count != ui_instance_count ||
        ui_log_state.width != hardware_->gbufferSize.x ||
        ui_log_state.height != hardware_->gbufferSize.y) {
        ui_log_state = UiPassLogState{
            .has_state = true,
            .has_follow_camera_instances = has_follow_camera_instances,
            .stereo_ui = stereo_ui,
            .cursor_visible = cursor_visible,
            .instance_count = ui_instance_count,
            .width = hardware_->gbufferSize.x,
            .height = hardware_->gbufferSize.y,
        };
        CFW_LOG_INFO("Optics UI pass: camera={} mode={} follow_camera_instances={} cursor={} output={}x{} warp={}",
                     camera_handle,
                     stereo_ui ? "stereo3d" : "flat2d",
                     ui_instance_count,
                     cursor_visible ? "visible" : "hidden",
                     hardware_->gbufferSize.x,
                     hardware_->gbufferSize.y,
                     (stereo_ui && (has_follow_camera_instances || cursor_visible)) ? "submitted" : "skipped");
    }

    if (!has_follow_camera_instances && !cursor_visible) {
        return &background;
    }

    const uint32_t overlayDescriptor = target.ui_overlay.storeDescriptor();
    if (has_follow_camera_instances) {
        upload_instance_tables(uiBatch,
                               hardware_->uiInstanceInfoBuffer,
                               hardware_->uiMaterialTableBuffer);

        opticsOverlay.pushConsts.gbufferSize = hardware_->gbufferSize;
        opticsOverlay.pushConsts.visibilityImageIndex =
            hardware_->uiVisibilityImage.storeDescriptor();
        opticsOverlay.pushConsts.instanceInfoBufferIndex =
            hardware_->uiInstanceInfoBuffer.storeDescriptor();
        opticsOverlay.pushConsts.materialTableBufferIndex =
            hardware_->uiMaterialTableBuffer.storeDescriptor();
        opticsOverlay.pushConsts.vpBufferIndex = uiVpDescriptor;
        opticsOverlay.pushConsts.outputImage = overlayDescriptor;
    }

    if (cursor_visible && cursor_state != nullptr) {
        const bool preserve_existing_overlay = has_follow_camera_instances;
        uint32_t cursor_origin_x = 0;
        uint32_t cursor_origin_y = 0;
        uint32_t cursor_width = hardware_->gbufferSize.x;
        uint32_t cursor_height = hardware_->gbufferSize.y;
        if (preserve_existing_overlay && hardware_->gbufferSize.x > 0u &&
            hardware_->gbufferSize.y > 0u) {
            constexpr int32_t kCursorPadding = 4;
            constexpr uint32_t kCursorExtent = 32;
            const auto cursor_x = static_cast<int32_t>(std::floor(cursor_state->x));
            const auto cursor_y = static_cast<int32_t>(std::floor(cursor_state->y));
            cursor_origin_x = static_cast<uint32_t>(std::max(cursor_x - kCursorPadding, 0));
            cursor_origin_y = static_cast<uint32_t>(std::max(cursor_y - kCursorPadding, 0));
            cursor_origin_x = std::min(cursor_origin_x, hardware_->gbufferSize.x - 1u);
            cursor_origin_y = std::min(cursor_origin_y, hardware_->gbufferSize.y - 1u);
            cursor_width = std::min(kCursorExtent, hardware_->gbufferSize.x - cursor_origin_x);
            cursor_height = std::min(kCursorExtent, hardware_->gbufferSize.y - cursor_origin_y);
        }

        opticsCursor.pushConsts.outputImage = overlayDescriptor;
        opticsCursor.pushConsts.outputWidth = hardware_->gbufferSize.x;
        opticsCursor.pushConsts.outputHeight = hardware_->gbufferSize.y;
        opticsCursor.pushConsts.originX = cursor_origin_x;
        opticsCursor.pushConsts.originY = cursor_origin_y;
        opticsCursor.pushConsts.cursorX = cursor_state->x;
        opticsCursor.pushConsts.cursorY = cursor_state->y;
        opticsCursor.pushConsts.cursorShape =
            static_cast<std::uint32_t>(cursor_state->cursor_shape);
        opticsCursor.pushConsts.preserveExisting = preserve_existing_overlay ? 1u : 0u;
        cursorDispatchX = (cursor_width + 7u) / 8u;
        cursorDispatchY = (cursor_height + 7u) / 8u;
    }

    uint32_t compositeOverlayDescriptor = overlayDescriptor;
    if (stereo_ui) {
        opticsUiWarp.pushConsts.inputImage = overlayDescriptor;
        opticsUiWarp.pushConsts.outputImage =
            target.ui_warped_overlay.storeDescriptor();
        opticsUiWarp.pushConsts.outputWidth = hardware_->gbufferSize.x;
        opticsUiWarp.pushConsts.outputHeight = hardware_->gbufferSize.y;
        opticsUiWarp.pushConsts.lenticularPitch = calibration.lenticular_pitch;
        opticsUiWarp.pushConsts.slant = std::tan(calibration.slant_angle_radians);
        opticsUiWarp.pushConsts.phaseOffset = calibration.phase_offset;
        opticsUiWarp.pushConsts.parallaxScale = calibration.parallax_scale;
        opticsUiWarp.pushConsts.rgbSubpixelOffsets = ktm::fvec4(
            calibration.rgb_subpixel_offsets[0],
            calibration.rgb_subpixel_offsets[1],
            calibration.rgb_subpixel_offsets[2],
            0.0f);
        compositeOverlayDescriptor = target.ui_warped_overlay.storeDescriptor();
    }

    opticsComposite.pushConsts.bgImage = background.storeDescriptor();
    opticsComposite.pushConsts.fgImage = compositeOverlayDescriptor;
    opticsComposite.pushConsts.outputImage = target.composite_output.storeDescriptor();
    opticsComposite.pushConsts.outputWidth = hardware_->gbufferSize.x;
    opticsComposite.pushConsts.outputHeight = hardware_->gbufferSize.y;

    if (has_follow_camera_instances) {
        hardware_->executor << uiVisibility(hardware_->gbufferSize.x, hardware_->gbufferSize.y)
                            << opticsOverlay(dispatchX, dispatchY, 1);
    }
    if (cursor_visible) {
        hardware_->executor << opticsCursor(cursorDispatchX, cursorDispatchY, 1);
    }
    if (stereo_ui) {
        hardware_->executor << opticsUiWarp(dispatchX, dispatchY, 1);
    }
    hardware_->executor << opticsComposite(dispatchX, dispatchY, 1);
    // 注意：此处不 commit，由调用方在合适时机统一提交。

    return &target.composite_output;
}

namespace {

// Convert IEEE 754 half-precision float (16-bit) to single-precision float.
float half_to_float(uint16_t h) {
    const uint32_t sign = (h >> 15) & 0x1;
    const uint32_t exponent = (h >> 10) & 0x1F;
    const uint32_t mantissa = h & 0x3FF;

    float result;
    if (exponent == 0) {
        result = std::ldexp(static_cast<float>(mantissa), -24);  // denorm or zero
    } else if (exponent == 31) {
        result = (mantissa == 0) ? INFINITY : NAN;
    } else {
        result = std::ldexp(static_cast<float>(mantissa | 0x400), static_cast<int>(exponent) - 25);
    }
    return sign ? -result : result;
}

}  // namespace

std::optional<OpticsSystem::ActorPickRequest> OpticsSystem::take_pending_actor_pick(std::uintptr_t camera_handle) {
    std::uintptr_t pick_handle = 0;
    std::uint32_t camera_width = 0;
    std::uint32_t camera_height = 0;
    if (auto camera = SharedDataHub::instance().camera_storage().try_acquire_read(camera_handle)) {
        pick_handle = camera->actor_pick_handle;
        camera_width = camera->width;
        camera_height = camera->height;
    }
    if (pick_handle == 0 || camera_width == 0 || camera_height == 0) {
        return std::nullopt;
    }

    auto pick = SharedDataHub::instance().actor_pick_storage().try_acquire_write(pick_handle);
    if (!pick || !pick->pending) {
        return std::nullopt;
    }

    ActorPickRequest request;
    request.pick_handle = pick_handle;
    request.request_id = pick->request_id;
    request.x = pick->x;
    request.y = pick->y;
    pick->pending = false;

    if (request.x >= camera_width || request.y >= camera_height) {
        pick->actor_handle = 0;
        pick->result_x = request.x;
        pick->result_y = request.y;
        pick->result_request_id = request.request_id;
        pick->result_ready = true;
        return std::nullopt;
    }

    pick->result_ready = false;
    return request;
}

void OpticsSystem::complete_actor_pick(const ActorPickRequest& request,
                                       const std::vector<std::uintptr_t>& scene_actor_handles) {
    std::uint32_t instance_id = 0;
    if (!hardware_->actorPickBuffer.copyToData(&instance_id, sizeof(instance_id))) {
        CFW_LOG_ERROR("OpticsSystem: Failed to read actor pick result from GPU");
    }

    std::uintptr_t actor_handle = 0;
    if (instance_id > 0) {
        const auto instance_index = static_cast<std::size_t>(instance_id - 1);
        if (instance_index < scene_actor_handles.size()) {
            actor_handle = scene_actor_handles[instance_index];
        }
    }

    if (auto pick = SharedDataHub::instance().actor_pick_storage().try_acquire_write(request.pick_handle)) {
        if (pick->request_id != request.request_id) {
            return;
        }
        pick->actor_handle = actor_handle;
        pick->result_x = request.x;
        pick->result_y = request.y;
        pick->result_request_id = request.request_id;
        pick->result_ready = true;
    }
}

#ifdef CORONA_ENABLE_VISION
void OpticsSystem::process_vision_actor_pick(std::uintptr_t camera_handle,
                                             const CameraDevice& camera,
                                             const SceneDevice& scene,
                                             uint64_t frame_index) {
    const auto actor_pick_request = take_pending_actor_pick(camera_handle);
    if (!actor_pick_request) {
        return;
    }

    bind_native_view_resources(camera_handle, camera.width, camera.height, frame_index);
    auto& visibility = *native_view_resources_.at(camera_handle)->visibility_pipeline;

    hardware_->vpUniformBufferObjects.viewProjMatrix = camera.compute_view_proj_matrix();
    hardware_->vpUniformBuffer.copyFromData(&hardware_->vpUniformBufferObjects,
                                            sizeof(hardware_->vpUniformBufferObjects));
    const uint32_t scene_vp_descriptor = hardware_->vpUniformBuffer.storeDescriptor();

    RenderInstanceBatch scene_batch;
    collect_actor_instances_for_visibility(scene,
                                           visibility,
                                           scene_vp_descriptor,
                                           false,
                                           nullptr,
                                           scene_batch);
    upload_instance_tables(scene_batch,
                           hardware_->instanceInfoBuffer,
                           hardware_->materialTableBuffer);

    auto& actor_pick = *hardware_->actorPickPipeline;
    actor_pick.pushConsts.pixel = ktm::uvec2{actor_pick_request->x, actor_pick_request->y};
    actor_pick.pushConsts.visibilityImageIndex = hardware_->visibilityImage.storeDescriptor();
    actor_pick.pushConsts.outputBufferIndex = hardware_->actorPickBuffer.storeDescriptor();

    hardware_->executor << visibility(hardware_->gbufferSize.x, hardware_->gbufferSize.y)
                        << actor_pick(1, 1, 1)
                        << hardware_->executor.commit();
    hardware_->executor.waitForDeferredResources();

    complete_actor_pick(*actor_pick_request, scene_batch.actorHandles);
}
#endif

void OpticsSystem::process_pending_screenshots(std::uintptr_t camera_handle, HardwareImage& render_target) {
    std::vector<PendingScreenshot> matched;
    {
        std::lock_guard<std::mutex> lock(screenshot_mutex_);
        auto it = std::remove_if(pending_screenshots_.begin(), pending_screenshots_.end(),
                                 [camera_handle](const PendingScreenshot& req) { return req.camera_handle == camera_handle; });
        matched.assign(std::make_move_iterator(it), std::make_move_iterator(pending_screenshots_.end()));
        pending_screenshots_.erase(it, pending_screenshots_.end());
    }

    if (matched.empty()) {
        return;
    }

    const uint32_t w = hardware_->gbufferSize.x;
    const uint32_t h = hardware_->gbufferSize.y;
    if (w == 0 || h == 0) {
        CFW_LOG_WARNING("OpticsSystem: Cannot take screenshot - zero render dimensions");
        for (auto& req : matched) {
            if (req.completion_promise) req.completion_promise->set_value(false);
        }
        return;
    }

    const uint64_t pixel_count = static_cast<uint64_t>(w) * h;
    const uint64_t buffer_size = pixel_count * 8;  // RGBA16F = 4 channels * 2 bytes
    HardwareBuffer staging_buffer(static_cast<uint32_t>(buffer_size), BufferUsage::StorageBuffer);
    if (!staging_buffer) {
        CFW_LOG_ERROR("OpticsSystem: Failed to create staging buffer for screenshot");
        for (auto& req : matched) {
            if (req.completion_promise) req.completion_promise->set_value(false);
        }
        return;
    }

    hardware_->executor << render_target.copyTo(staging_buffer)
                        << hardware_->executor.commit();

    std::vector<uint16_t> half_data(pixel_count * 4);
    if (!staging_buffer.copyToData(half_data.data(), buffer_size)) {
        CFW_LOG_ERROR("OpticsSystem: Failed to read screenshot data from GPU");
        for (auto& req : matched) {
            if (req.completion_promise) req.completion_promise->set_value(false);
        }
        return;
    }

    // Convert RGBA16F to RGBA8
    std::vector<uint8_t> rgba8(pixel_count * 4);
    for (uint64_t i = 0; i < pixel_count * 4; ++i) {
        float v = half_to_float(half_data[i]);
        v = std::fmax(0.0f, std::fmin(1.0f, v));
        rgba8[i] = static_cast<uint8_t>(v * 255.0f + 0.5f);
    }

    for (const auto& req : matched) {
        std::filesystem::path file_path(req.file_path);
        auto image = std::make_shared<Resource::Image>(file_path);
        image->set_data(rgba8.data(), static_cast<int>(w), static_cast<int>(h), 4);

        auto rid = Resource::IResource::generate_uid(file_path);
        auto& manager = Resource::ResourceManager::get_instance();
        manager.add_resource(rid, image);

        if (manager.export_sync(rid, file_path)) {
            if (req.completion_promise) {
                req.completion_promise->set_value(true);
            }
        } else {
            CFW_LOG_ERROR("OpticsSystem: Failed to save screenshot to {}", req.file_path);
            if (req.completion_promise) {
                req.completion_promise->set_value(false);
            }
        }
    }
}

void OpticsSystem::shutdown() {
    if (auto* event_bus = context()->event_bus()) {
        if (screenshot_request_sub_id_ != 0) {
            event_bus->unsubscribe(screenshot_request_sub_id_);
        }
        if (backend_switch_sub_id_ != 0) {
            event_bus->unsubscribe(backend_switch_sub_id_);
        }
#ifdef CORONA_ENABLE_VISION
        if (vision_scene_load_sub_id_ != 0) {
            event_bus->unsubscribe(vision_scene_load_sub_id_);
        }
#endif
    }

    // 释放所有 per-surface 渲染目标的存储句柄与 GPU 图（改造1）。
    for (auto& [surface, target] : surface_targets_) {
        if (target.image_handle != 0) {
            SharedDataHub::instance().image_storage().deallocate(target.image_handle);
        }
    }
    surface_targets_.clear();
    native_view_resources_.clear();
#ifdef CORONA_ENABLE_VISION
    if (renderPipeline) {
        renderPipeline->commit_command();
    }
    // Imported Vulkan buffers must be released before their CUDA allocations.
    vision_zero_copy_bridges_.clear();
    if (renderPipeline) {
        renderPipeline->clear_view_contexts();
    }
#endif
    hardware_.reset();
}
#ifdef CORONA_ENABLE_VISION
std::size_t OpticsSystem::compute_vision_scene_signature() const {
    // Lightweight per-frame change detector. Traverses the same hierarchy as
    // build_vision_geometry (enabled scene → actor → profile → optics → geometry)
    // and folds the topology/transform/material-relevant fields into one hash.
    // Any meaningful change to imported/removed geometry, transforms, material
    // params or per-mesh color flips this signature, triggering a rebuild.
    std::size_t sig = 0;
    auto mix = [&sig](std::size_t v) {
        // 64-bit hash_combine (boost-style golden ratio constant).
        sig ^= v + 0x9e3779b97f4a7c15ULL + (sig << 6) + (sig >> 2);
    };
    auto mix_float = [&mix](float f) {
        // Hash the raw bit pattern so small value changes are detected.
        std::uint32_t bits = 0;
        static_assert(sizeof(bits) == sizeof(f), "float must be 32-bit");
        std::memcpy(&bits, &f, sizeof(bits));
        mix(static_cast<std::size_t>(bits));
    };

    auto& hub = SharedDataHub::instance();
    auto& actor_storage = hub.actor_storage();
    auto& profile_storage = hub.profile_storage();
    auto& optics_storage = hub.optics_storage();
    auto& geom_storage = hub.geometry_storage();
    auto& transform_storage = hub.model_transform_storage();

    for (auto scene_it = hub.scene_storage().cbegin(); scene_it != hub.scene_storage().cend(); ++scene_it) {
        const auto& scene_dev = *scene_it;
        if (!scene_dev.enabled) continue;
        for (auto actor_handle : scene_dev.actor_handles) {
            auto actor = actor_storage.try_acquire_read(actor_handle);
            if (!actor) continue;
            mix(static_cast<std::size_t>(actor_handle));
            for (auto profile_handle : actor->profile_handles) {
                auto profile = profile_storage.try_acquire_read(profile_handle);
                if (!profile || profile->optics_handle == 0 || profile->geometry_handle == 0) continue;

                auto optics = optics_storage.try_acquire_read(profile->optics_handle);
                if (!optics) continue;

                // visible toggle changes topology of the Vision scene.
                mix(optics->visible ? 0x1u : 0x2u);
                if (!optics->visible) continue;

                // Material parameters bridged into the Vision principled BSDF.
                mix_float(optics->metallic);
                mix_float(optics->roughness);

                auto geom = geom_storage.try_acquire_read(optics->geometry_handle);
                if (!geom) continue;
                mix(static_cast<std::size_t>(optics->geometry_handle));
                mix(static_cast<std::size_t>(geom->model_resource_handle));
                mix(geom->mesh_handles.size());

                // Per-mesh material color (texture-color replacement detection).
                for (const auto& mesh_dev : geom->mesh_handles) {
                    mix_float(mesh_dev.materialColor[0]);
                    mix_float(mesh_dev.materialColor[1]);
                    mix_float(mesh_dev.materialColor[2]);
                    mix_float(mesh_dev.materialColor[3]);

                    // Mesh data readiness: for procedurally-generated geometry the
                    // vertex/index buffers are uploaded asynchronously, so the
                    // element count flips 0 -> N once the GPU upload completes.
                    // Folding it into the signature makes that transition trigger
                    // one more rebuild even though no logical field changed.
                    const auto& vbuf = mesh_dev.vertexBuffer
                                           ? mesh_dev.vertexBuffer
                                           : mesh_dev.vertexStorageBuffer;
                    mix(static_cast<std::size_t>(vbuf.getElementCount()));
                }

                // Object-to-world transform (position / rotation / scale).
                if (auto transform = transform_storage.try_acquire_read(geom->transform_handle)) {
                    mix_float(transform->position.x);
                    mix_float(transform->position.y);
                    mix_float(transform->position.z);
                    mix_float(transform->euler_rotation.x);
                    mix_float(transform->euler_rotation.y);
                    mix_float(transform->euler_rotation.z);
                    mix_float(transform->scale.x);
                    mix_float(transform->scale.y);
                    mix_float(transform->scale.z);
                }
            }
        }
    }
    return sig;
}

Vision::VisionBuildResult OpticsSystem::rebuild_vision_scene() {
    Vision::VisionBuildResult result;
    if (!renderPipeline) return result;
    try {
        renderPipeline->activate_view_context(0u);
        auto& scene = renderPipeline->scene();
        result = Vision::build_vision_geometry(scene);

        // build_vision_geometry() clears and rebuilds the scene's meshes/shapes,
        // which also tears down the light manager state established during
        // init_vision_lazy(). If we don't re-register the lights here, the
        // following scene.prepare() reinitialises the light sampler with a missing
        // (or geometry-introduced area-light only) env_light_, corrupting the
        // light sampler's env index / PMF bookkeeping and crashing the CUDA device
        // (observed: process exit code -1 right after "Vision scene rebuilt").
        // Mirror the initialization path: always re-inject a single Infinite sky
        // light (+ optional point sun) from the current Corona environment so the
        // env_light_ assignment stays valid across rebuilds.
        Corona::EnvironmentDevice env{};
        for (auto sd_it = SharedDataHub::instance().scene_storage().cbegin();
             sd_it != SharedDataHub::instance().scene_storage().cend(); ++sd_it) {
            const auto& sd = *sd_it;
            if (!sd.enabled) continue;
            if (sd.environment != 0) {
                if (auto e = SharedDataHub::instance().environment_storage().try_acquire_read(sd.environment)) {
                    env = *e;
                    break;
                }
            }
        }
        Vision::setup_vision_lights(scene, env);

        // A scene rebuild changes topology: new meshes, materials (and therefore
        // new bindless texture handles) and a freshly rebuilt light manager.
        //
        // We must NOT call the full renderPipeline->prepare() here. That method is
        // a one-shot initialisation path (FixedRenderPipeline::prepare() runs
        // Pipeline::prepare() -> scene_.prepare() -> renderer_.prepare(scene_) ->
        // image_pool().prepare() -> ...). Re-running it on an already-initialised
        // pipeline reallocates the framebuffer / sensor / image-pool device buffers
        // that the render loop is already holding references to, which crashes the
        // CUDA device (observed: crash on the following prepare_view_texture()).
        //
        // The correct runtime update is an INCREMENTAL sequence that only refreshes
        // the parts affected by the topology change, while leaving the framebuffer,
        // view texture and sensor (resolution unchanged) untouched:
        //   scene.prepare()         -> re-encode materials/sensor for the new scene
        //   prepare_geometry()      -> rebuild geometry device buffers + accel
        //   prepare_lights()        -> rebuild the light sampler's device buffers
        //   upload_bindless_array() -> publish the new material texture handles
        //   compile()               -> recompile the integrator for the new
        //                              light/material/instance counts
        //   invalidate()            -> reset accumulation
        //
        // prepare_lights() is CRITICAL: setup_vision_lights() above changed the light
        // set, but Scene::prepare() does NOT touch the light sampler. The official init
        // path runs renderer_.prepare(scene_) -> prepare_lights() ->
        // light_sampler_->prepare(), which rebuilds the on-device light count / PMF /
        // env-index buffers. Skipping it leaves the UniformLightSampler indexing a stale
        // light buffer with the new (different) light_num(), so the very first render()
        // after the rebuild performs an out-of-bounds GPU read and crashes the CUDA
        // device (observed: process exit -1 right after "Vision scene rebuilt", with no
        // "This scene contains N light types" log emitted during the rebuild).
        // It must run AFTER prepare_geometry() because area lights reference shapes.
        scene.prepare();
        renderPipeline->prepare_geometry();
        renderPipeline->renderer().prepare_lights();
        renderPipeline->upload_bindless_array();
        renderPipeline->compile();
        renderPipeline->rebuild_view_context_renderers();
        renderPipeline->invalidate_all_view_contexts();
    } catch (const std::exception& e) {
        CFW_LOG_ERROR("OpticsSystem: Vision scene rebuild failed: {}", e.what());
    }
    return result;
}

void OpticsSystem::sync_vision_dynamic_scene() {
    if (!vision_initialized_) return;

    const std::size_t sig = compute_vision_scene_signature();

    // Debounce: only rebuild after the signature has stayed stable for a few frames,
    // batching bursts of edits (e.g. importing several objects) into one rebuild.
    if (sig != vision_pending_signature_) {
        vision_pending_signature_ = sig;
        vision_stable_frames_ = 0;
        vision_rebuild_retries_ = 0;  // 内容发生变化，清零重试计数
        return;
    }

    if (sig == vision_applied_signature_) {
        return;  // nothing changed since the last applied rebuild
    }

    if (++vision_stable_frames_ < kVisionRebuildDebounceFrames) {
        return;  // still settling
    }
    vision_stable_frames_ = 0;

    const Vision::VisionBuildResult result = rebuild_vision_scene();

    if (result.instance_count > 0 || result.candidate_count == 0) {
        // 重建成功，或场景本就为空（candidate_count==0 是合法的 0）：接受签名，
        // 停止重试，避免对空场景每帧空转重建。
        vision_applied_signature_ = sig;
        vision_rebuild_retries_ = 0;
    } else {
        // 有候选物体但 0 实例 → 网格数据尚未就绪：不锁定签名，下一帧继续重试。
        if (++vision_rebuild_retries_ >= kVisionRebuildMaxRetries) {
            CFW_LOG_ERROR(
                "OpticsSystem: Vision rebuild produced 0 instances from {} candidates after {} "
                "retries; accepting empty result to avoid busy-loop",
                result.candidate_count, vision_rebuild_retries_);
            vision_applied_signature_ = sig;  // 兜底：达到上限后接受，停止重试
            vision_rebuild_retries_ = 0;
        }
        // 否则保持 vision_applied_signature_ 不变；由于签名未变，下一帧去抖立即满足，
        // 会再次触发 rebuild，直到数据就绪或达到上限。
    }
}

void OpticsSystem::sync_external_live_vision_transforms() {
    if (!vision_initialized_ || !renderPipeline || current_vision_scene_path_.empty()) {
        return;
    }

    const auto current_scene_key = normalize_scene_path_key(current_vision_scene_path_);
    if (current_scene_key.empty()) {
        return;
    }

    auto& hub = SharedDataHub::instance();
    auto& vision_scene = renderPipeline->scene();
    auto& groups = vision_scene.groups();

    bool changed = false;
    std::size_t updated_actors = 0;
    std::unordered_set<std::uintptr_t> active_bound_actors;

    for (auto scene_it = hub.scene_storage().cbegin(); scene_it != hub.scene_storage().cend(); ++scene_it) {
        const auto& scene_dev = *scene_it;
        if (!scene_dev.enabled) {
            continue;
        }

        for (auto actor_handle : scene_dev.actor_handles) {
            const auto binding = hub.external_vision_binding(actor_handle);
            if (!binding) {
                continue;
            }
            if (normalize_scene_path_key(binding->source_path) != current_scene_key) {
                continue;
            }

            const auto resolved = resolve_external_live_transform(actor_handle, *binding);
            if (!resolved) {
                continue;
            }

            active_bound_actors.insert(actor_handle);
            const auto cached = external_live_transform_signatures_.find(actor_handle);
            if (cached != external_live_transform_signatures_.end() &&
                cached->second == resolved->signature) {
                continue;
            }

            const auto group_index = static_cast<std::size_t>(resolved->shape_index);
            if (group_index >= groups.size() || !groups[group_index]) {
                continue;
            }

            auto& group = groups[group_index];
            group->aabb = ::vision::Box3f{};
            group->for_each([&](::vision::SP<::vision::ShapeInstance> instance, uint) {
                if (!instance) {
                    return;
                }
                instance->set_o2w(resolved->o2w);
                instance->init_aabb();
                group->aabb.extend(instance->aabb);
            });

            external_live_transform_signatures_[actor_handle] = resolved->signature;
            changed = true;
            ++updated_actors;
        }
    }

    for (auto it = external_live_transform_signatures_.begin();
         it != external_live_transform_signatures_.end();) {
        if (active_bound_actors.contains(it->first)) {
            ++it;
        } else {
            it = external_live_transform_signatures_.erase(it);
        }
    }

    if (!changed) {
        return;
    }

    try {
        renderPipeline->activate_view_context(0u);
        renderPipeline->update_geometry();
        renderPipeline->invalidate_all_view_contexts();
        CFW_LOG_DEBUG("OpticsSystem: external_live updated {} proxy actor transform(s)",
                      updated_actors);
    } catch (const std::exception& e) {
        CFW_LOG_ERROR("OpticsSystem: external_live transform sync failed: {}", e.what());
    }
}

bool OpticsSystem::init_vision_lazy() {
    if (vision_initialized_) return true;
    try {
        // ocarina::Device is non-default-constructible; use auto so the type is
        // deduced from create_device(). Function-local static ensures single init.
        static auto s_device = ocarina::RHIContext::instance().create_device("cuda");
        visionDevicePtr = &s_device;
        visionDevicePtr->init_rtx();
        vision::Global::instance().set_device(visionDevicePtr);
        vision::Global::instance().set_scene_path(std::filesystem::current_path());

#ifdef CORONA_VISION_IMPORT_DEMO
        // Verification demo: load a known-good scene straight from disk instead of
        // building the Vision scene from CoronaEngine data. This isolates the
        // Vision render path so we can confirm it produces a picture at all.
        renderPipeline = import_vision_scene_from_file(std::filesystem::path{kVisionDemoScenePath});
        if (!renderPipeline) {
            CFW_LOG_ERROR("OpticsSystem: Vision demo pipeline import failed");
            return false;
        }
        vision_initialized_ = true;
        vision_scene_source_ = VisionSceneSource::ExternalFile;
        current_vision_scene_path_ = kVisionDemoScenePath;
        external_live_transform_signatures_.clear();
        return true;
#else
        std::optional<std::string> pending_external_scene;
        {
            std::lock_guard<std::mutex> lock(vision_scene_load_mutex_);
            if (pending_vision_scene_load_ && !pending_vision_scene_load_->empty()) {
                pending_external_scene.swap(pending_vision_scene_load_);
            }
        }
        if (pending_external_scene) {
            if (!load_external_vision_scene(*pending_external_scene)) {
                CFW_LOG_ERROR("OpticsSystem: failed to initialize Vision from external scene: {}",
                              *pending_external_scene);
                return false;
            }
            vision_initialized_ = true;
            const bool external_live = has_external_live_bindings_for_scene(*pending_external_scene);
            vision_scene_source_ =
                external_live ? VisionSceneSource::ExternalLive : VisionSceneSource::ExternalFile;
            vision_applied_signature_ = 0;
            vision_pending_signature_ = 0;
            vision_stable_frames_ = 0;
            vision_rebuild_retries_ = 0;
            CFW_LOG_INFO("OpticsSystem: initialized Vision from {} scene: {}",
                         external_live ? "external_live" : "external",
                         *pending_external_scene);
            return true;
        }

        renderPipeline = create_vision_pipeline();
        if (!renderPipeline) {
            CFW_LOG_ERROR("OpticsSystem: Failed to create Vision pipeline without external scene import");
            return false;
        }

        // Populate Vision scene directly from CoronaEngine scene data.
        auto& scene = renderPipeline->scene();
        Vision::build_vision_geometry(scene);

        // Always inject lights. Vision's UniformLightSampler divides by light_num()
        // and indexes the light buffer; an empty light set (no environment in the
        // Corona scene) causes a 1/0 PMF and an out-of-bounds GPU read -> device crash.
        // When no environment is found we fall back to a default EnvironmentDevice so
        // the scene still receives a directional sun + sky light.
        Corona::EnvironmentDevice env{};
        for (auto sd_it = SharedDataHub::instance().scene_storage().cbegin();
             sd_it != SharedDataHub::instance().scene_storage().cend(); ++sd_it) {
            const auto& sd = *sd_it;
            if (!sd.enabled) continue;
            if (sd.environment != 0) {
                if (auto e = SharedDataHub::instance().environment_storage().try_acquire_read(sd.environment)) {
                    env = *e;
                    break;
                }
            }
        }
        Vision::setup_vision_lights(scene, env);

        renderPipeline->prepare();

        // Pipeline::prepare() allocates the internal per-pixel device buffers but
        // does NOT create FrameBuffer::view_texture_ (only prepare_view_texture()
        // does). The render path tone-maps into view_texture_ and we later read it
        // via fill_window_buffer(view_texture()). Without this the first frame uses
        // an uninitialized texture. The official vision-gui/vision-eval apps also
        // call prepare_view_texture() right after prepare().
        renderPipeline->frame_buffer()->prepare_view_texture();

        // sync_vision_camera uploads to GPU device buffers. Those device buffers are
        // only allocated during Pipeline::prepare() (Scene::prepare -> Sensor::prepare
        // -> EncodedObject::prepare_data -> reset_device_buffer). Running it
        // before prepare() uploads into unallocated device memory and crashes the
        // CUDA device deterministically.
        for (auto sd_it = SharedDataHub::instance().scene_storage().cbegin();
             sd_it != SharedDataHub::instance().scene_storage().cend(); ++sd_it) {
            const auto& sd = *sd_it;
            if (!sd.enabled) continue;
            const auto camera_handle = select_scene_camera_handle(sd);
            if (camera_handle == 0) continue;
            auto camera = SharedDataHub::instance().camera_storage().try_acquire_read(camera_handle);
            if (!camera) continue;
            Vision::sync_vision_camera(*renderPipeline, *camera);
            break;
        }

        vision_initialized_ = true;
        current_vision_scene_path_.clear();
        external_live_transform_signatures_.clear();

        // Establish the dynamic-scene signature baseline so subsequent edits are
        // detected as changes against the initially-built scene.
        vision_applied_signature_ = compute_vision_scene_signature();
        vision_pending_signature_ = vision_applied_signature_;
        vision_stable_frames_ = 0;

        return true;
#endif  // CORONA_VISION_IMPORT_DEMO
    } catch (const std::exception& e) {
        CFW_LOG_ERROR("OpticsSystem: Vision init failed: {}", e.what());
        return false;
    }
}

void OpticsSystem::run_vision_frame(float frame_count, uint64_t frame_index) {
    (void)frame_count;
    apply_pending_vision_scene_load();
    if (!renderPipeline) return;

#ifndef CORONA_VISION_IMPORT_DEMO
    bool has_visible_vision_camera = false;
    for (const auto& scene : SharedDataHub::instance().scene_storage()) {
        if (!scene.enabled) continue;
        for (const auto camera_handle : scene.camera_handles) {
            auto camera =
                SharedDataHub::instance().camera_storage().try_acquire_read(camera_handle);
            if (camera && camera->render_backend == CameraRenderBackend::Vision &&
                camera->surface != nullptr) {
                has_visible_vision_camera = true;
                break;
            }
        }
        if (has_visible_vision_camera) break;
    }
    if (has_visible_vision_camera && vision_scene_source_ == VisionSceneSource::EngineBuilt) {
        sync_vision_dynamic_scene();
    } else if (has_visible_vision_camera &&
               vision_scene_source_ == VisionSceneSource::ExternalLive) {
        sync_external_live_vision_transforms();
    }
#endif

    std::unordered_set<std::uintptr_t> active_contexts;
    for (auto scene_it = SharedDataHub::instance().scene_storage().cbegin();
         scene_it != SharedDataHub::instance().scene_storage().cend(); ++scene_it) {
        const auto& scene = *scene_it;
        if (!scene.enabled) continue;

        for (auto cam_handle : scene.camera_handles) {
            auto camera = SharedDataHub::instance().camera_storage().try_acquire_read(cam_handle);
            if (!camera || camera->render_backend != CameraRenderBackend::Vision ||
                camera->surface == nullptr) {
                continue;
            }

            active_contexts.insert(cam_handle);
            retainedVisionContexts.erase(cam_handle);
            process_vision_actor_pick(cam_handle, *camera, scene, frame_index);
            try {
                const auto resolution =
                    ocarina::make_uint2(std::max(camera->width, 1u),
                                       std::max(camera->height, 1u));
                if (!renderPipeline->has_view_context(cam_handle) &&
                    !renderPipeline->create_view_context(cam_handle, resolution)) {
                    CFW_LOG_ERROR(
                        "OpticsSystem: unable to allocate Vision view context for camera {}",
                        cam_handle);
                    continue;
                }
                if (!renderPipeline->activate_view_context(cam_handle)) {
                    continue;
                }

                Vision::sync_vision_camera(*renderPipeline, *camera);
                renderPipeline->upload_data();
                renderPipeline->display(1.0 / 60.0);

                auto* fb = renderPipeline->frame_buffer();
                const auto res = fb->resolution();
                const uint32_t w = res.x;
                const uint32_t h = res.y;

                auto& bridge = vision_zero_copy_bridges_[cam_handle];
                if (!bridge) {
                    bridge = std::make_unique<Vision::VisionZeroCopyBridge>();
                }
                if (!bridge->ensure(*renderPipeline, w, h) ||
                    !bridge->copy_from_framebuffer(*renderPipeline)) {
                    CFW_LOG_WARNING(
                        "OpticsSystem: Vision bridge unavailable for camera {} ({}x{})",
                        cam_handle, w, h);
                    continue;
                }

                void* surface = camera->surface;
                hardware_->gbufferSize = ktm::uvec2{w, h};
                auto& target = acquire_surface_target(surface, w, h, frame_index);
                if (auto consumed_device =
                        SharedDataHub::instance().image_storage().acquire_write(
                            target.image_handle)) {
                    hardware_->executor.wait(consumed_device->consumed_executor);
                }

                {
                    auto& visionResolve = *hardware_->visionResolvePipeline;
                    visionResolve.pushConsts.gbufferSize = hardware_->gbufferSize;
                    visionResolve.pushConsts.srcBufferIndex = bridge->imported().storeDescriptor();
                    visionResolve.pushConsts.outputImage = target.final_output.storeDescriptor();
                    visionResolve.pushConsts.exposure = 1.0f;

                    const uint32_t dispatchX = (w + 7u) / 8u;
                    const uint32_t dispatchY = (h + 7u) / 8u;
                    // 不在此 commit：UI overlay pass 紧随其后读 final_output 作为背景，
                    // 整帧在同一 executor 上按程序序记录、末尾统一提交一次。
                    hardware_->executor << visionResolve(dispatchX, dispatchY, 1);
                }

                // 与 Native 共用的 UI overlay 层：gbufferSize 已在上方设为 {w,h}。
                ensure_ui_view_resources(cam_handle, w, h, frame_index);
                const auto ui_state =
                    SharedDataHub::instance().viewport_ui_state(cam_handle);
                HardwareImage* presented = compose_surface_ui_overlay(
                    cam_handle, *camera, scene, target, target.final_output,
                    ui_state.mode, ui_state.calibration, frame_index);

                hardware_->executor << hardware_->executor.commit();

                process_pending_screenshots(cam_handle, *presented);

                if (auto image_device =
                        SharedDataHub::instance().image_storage().acquire_write(
                            target.image_handle)) {
                    image_device->image = *presented;
                    image_device->executor = hardware_->executor;
                }

                if (auto* event_bus = context()->event_bus()) {
                    event_bus->publish<Events::OpticsFrameReadyEvent>(
                        {surface, target.image_handle, frame_index, w, h});
                }
            } catch (const std::exception& error) {
                CFW_LOG_ERROR("OpticsSystem: Vision camera {} failed: {}",
                              cam_handle, error.what());
            }
        }
    }

    for (auto it = vision_zero_copy_bridges_.begin();
         it != vision_zero_copy_bridges_.end();) {
        if (active_contexts.contains(it->first)) {
            ++it;
            continue;
        }
        const auto camera_handle = it->first;
        bool camera_exists = false;
        bool retain_bridge = false;
        if (auto camera =
                SharedDataHub::instance().camera_storage().try_acquire_read(camera_handle)) {
            camera_exists = true;
            retain_bridge = camera->surface != nullptr;
        }

        // A visible camera may switch back to Vision at any time. Keep its imported
        // bridge alive while the surface exists; recreating the CUDA/Vulkan import on
        // a surface that is still being presented can stall both renderers. Closing
        // or suspending the view clears the surface and still releases the bridge.
        if (retain_bridge) {
            if (!retainedVisionContexts.contains(camera_handle)) {
                renderPipeline->commit_command();
                renderPipeline->invalidate_view_context(camera_handle);
                retainedVisionContexts.insert(camera_handle);
            }
            ++it;
            continue;
        }

        renderPipeline->commit_command();
        it = vision_zero_copy_bridges_.erase(it);
        if (camera_exists) {
            renderPipeline->invalidate_view_context(camera_handle);
            retainedVisionContexts.insert(camera_handle);
        } else {
            renderPipeline->remove_view_context(camera_handle);
        }
    }
    for (auto it = retainedVisionContexts.begin();
         it != retainedVisionContexts.end();) {
        if (SharedDataHub::instance().camera_storage().try_acquire_read(*it)) {
            ++it;
            continue;
        }
        renderPipeline->remove_view_context(*it);
        it = retainedVisionContexts.erase(it);
    }
    renderPipeline->activate_view_context(0u);
}

void OpticsSystem::apply_pending_vision_scene_load() {
    std::optional<std::string> request;
    {
        std::lock_guard<std::mutex> lock(vision_scene_load_mutex_);
        if (!pending_vision_scene_load_) return;
        request.swap(pending_vision_scene_load_);
    }

    const std::string& path = *request;
    if (!path.empty()) {
        if (load_external_vision_scene(path)) {
            const bool external_live = has_external_live_bindings_for_scene(path);
            vision_scene_source_ =
                external_live ? VisionSceneSource::ExternalLive : VisionSceneSource::ExternalFile;
            vision_applied_signature_ = 0;
            vision_pending_signature_ = 0;
            vision_stable_frames_ = 0;
            vision_rebuild_retries_ = 0;
            CFW_LOG_INFO("OpticsSystem: {} Vision scene loaded: {}",
                         external_live ? "external_live" : "external",
                         path);
        }
        return;
    }

    try {
        auto pipeline = create_vision_pipeline();
        if (!pipeline) {
            CFW_LOG_ERROR("OpticsSystem: failed to recreate engine-built Vision pipeline");
            return;
        }
        auto& scene = pipeline->scene();
        Vision::build_vision_geometry(scene);

        Corona::EnvironmentDevice env{};
        for (auto sd_it = SharedDataHub::instance().scene_storage().cbegin();
             sd_it != SharedDataHub::instance().scene_storage().cend(); ++sd_it) {
            const auto& sd = *sd_it;
            if (!sd.enabled) continue;
            if (sd.environment != 0) {
                if (auto e = SharedDataHub::instance().environment_storage().try_acquire_read(sd.environment)) {
                    env = *e;
                    break;
                }
            }
        }
        Vision::setup_vision_lights(scene, env);
        pipeline->prepare();
        pipeline->frame_buffer()->prepare_view_texture();

        for (auto sd_it = SharedDataHub::instance().scene_storage().cbegin();
             sd_it != SharedDataHub::instance().scene_storage().cend(); ++sd_it) {
            const auto& sd = *sd_it;
            if (!sd.enabled) continue;
            const auto camera_handle = select_scene_camera_handle(sd);
            if (camera_handle == 0) continue;
            auto camera = SharedDataHub::instance().camera_storage().try_acquire_read(camera_handle);
            if (!camera) continue;
            Vision::sync_vision_camera(*pipeline, *camera);
            break;
        }

        if (renderPipeline) {
            renderPipeline->commit_command();
            renderPipeline->clear_view_contexts();
        }
        vision_zero_copy_bridges_.clear();
        retainedVisionContexts.clear();
        renderPipeline = std::move(pipeline);
        vision_scene_source_ = VisionSceneSource::EngineBuilt;
        current_vision_scene_path_.clear();
        external_live_transform_signatures_.clear();
        vision_applied_signature_ = compute_vision_scene_signature();
        vision_pending_signature_ = vision_applied_signature_;
        vision_stable_frames_ = 0;
        vision_rebuild_retries_ = 0;
        CFW_LOG_INFO("OpticsSystem: restored engine-built Vision scene");
    } catch (const std::exception& e) {
        CFW_LOG_ERROR("OpticsSystem: restoring engine-built Vision scene failed: {}", e.what());
    }
}

bool OpticsSystem::load_external_vision_scene(const std::string& scene_path) {
    try {
        auto pipeline = import_vision_scene_from_file(std::filesystem::u8path(scene_path));
        if (!pipeline) {
            CFW_LOG_ERROR("OpticsSystem: External Vision scene import failed: {}", scene_path);
            return false;
        }
        log_vision_pipeline_diagnostics(*pipeline, "external import");
        // Replace only after a successful import so a bad path leaves the current
        // scene intact.
        if (renderPipeline) {
            renderPipeline->commit_command();
            renderPipeline->clear_view_contexts();
        }
        vision_zero_copy_bridges_.clear();
        retainedVisionContexts.clear();
        renderPipeline = std::move(pipeline);
        current_vision_scene_path_ = scene_path;
        external_live_transform_signatures_.clear();
        return true;
    } catch (const std::exception& e) {
        CFW_LOG_ERROR("OpticsSystem: External Vision scene import threw: {}", e.what());
        return false;
    }
}
#endif  // CORONA_ENABLE_VISION

}  // namespace Corona::Systems
