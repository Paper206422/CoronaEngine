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
#include <cmath>
#include <cstdint>
#include <cstring>
#include <exception>
#include <filesystem>
#include <functional>
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
#include "base/sensor/sensor.h"
#include "rhi/context.h"
#include "vision/vision_geometry_adapter.h"
#include "vision/vision_camera_adapter.h"
#include "vision/vision_light_adapter.h"
#include "vision/vision_zero_copy_bridge.h"
#endif

namespace {
#ifdef CORONA_ENABLE_VISION
ocarina::SP<vision::Pipeline> renderPipeline;
vision::Device* visionDevicePtr = nullptr;

// ============================================================================
// Vision 集成差分诊断实验（详见 docs/vision_integration.md「差分诊断实验」一节）
//
//   CORONA_VISION_EXP_PROBE          只读状态探针，默认开启（开销极小，可常开）。
//                                    在关键生命周期点 dump 几何(host/device)/光源/
//                                    相机/累积帧，用于对比 DEMO 与非 DEMO 路径。
//   CORONA_VISION_EXP_SKIP_GEOMETRY  Stage 1.5：非 DEMO 下跳过 build_vision_geometry，
//                                    做「空几何天光测试」——若能看见灰色天空，说明
//                                    输出/光照/相机链路正常，黑屏根因在几何导入。
//   CORONA_VISION_EXP_GRAFT_GEOMETRY Stage 2：DEMO 下渲染若干帧确认台子正常后，调用
//                                    rebuild_vision_scene() 把 demo 几何「嫁接」成
//                                    Corona 几何，直接验证 mesh 导入是否成功。
//
// 后两个是行为性开关，默认关闭；需要时取消注释或用 -D 传入。
// ============================================================================
#define CORONA_VISION_EXP_PROBE 1
// #define CORONA_VISION_EXP_SKIP_GEOMETRY 1
// #define CORONA_VISION_EXP_GRAFT_GEOMETRY 1

#if CORONA_VISION_EXP_PROBE
// 只读：把一个 Vision pipeline 的几何/光源/相机/累积状态打到日志。
// HOST 段为主机侧（shape/instance/mesh 注册表），DEV 段为设备侧（accel/BVH）。
// 「mesh 导入成功」当且仅当 HOST(inst>0,mesh_reg>0) 且 DEV(tri>0,mesh>0) 同时成立；
// 若 HOST 非零而 DEV 为零 => 上传/BVH 失败或 transform 把几何甩飞（看 world r）。
void dump_vision_state(const char* tag, ::vision::Pipeline& pl) {
    auto& scene = pl.scene();

    // 设备侧：accel/BVH（仅在 prepare / prepare_geometry 之后才非零）
    const auto gs = pl.geometry_stats();  // {mesh_num, triangle_num, vertex_num}

    // 主机侧：shape group / instance / mesh 注册表
    const size_t groups = scene.groups().size();
    const size_t inst = scene.instances().size();
    size_t mesh_reg = 0;
    scene.geometry().data()->for_each_mesh(
        [&mesh_reg](const ::vision::Mesh*, auto) { ++mesh_reg; });

    // 世界包围盒：transform 是否正常的关键信号（退化 0 / 天文数字 => transform bug）
    const auto center = scene.world_center();
    const float radius = scene.world_radius();

    // 光源：env_light_ 是否被正确赋值（全黑常见根因之一）
    auto& lm = scene.light_manager();
    size_t light_n = 0;
    for (auto& l : lm.lights()) { (void)l; ++light_n; }
    const void* env = static_cast<const void*>(lm.env_light());

    // 相机 + 累积帧（frame_idx 每帧归 0 => invalidate 误触发，永不收敛）
    auto& sensor = scene.sensor();
    const auto cam_pos = sensor->position();

    CFW_LOG_INFO(
        "[VPROBE {}] HOST(groups={} inst={} mesh_reg={}) "
        "DEV(accel mesh={} tri={} vert={}) "
        "world(center=({},{},{}) r={}) light(n={} env={}) "
        "cam(pos=({},{},{}) yaw={} pitch={} fov={}) frame_idx={}",
        tag, groups, inst, mesh_reg,
        gs.mesh_num, gs.triangle_num, gs.vertex_num,
        center.x, center.y, center.z, radius,
        light_n, env,
        cam_pos.x, cam_pos.y, cam_pos.z,
        sensor->yaw(), sensor->pitch(), sensor->fov_y(),
        pl.frame_index());
}
#define CORONA_VPROBE(tag_, pl_) dump_vision_state((tag_), (pl_))
#else
#define CORONA_VPROBE(tag_, pl_) ((void)0)
#endif  // CORONA_VISION_EXP_PROBE

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

#ifdef CORONA_VISION_IMPORT_DEMO
// Absolute path to a known-good Vision scene used purely to verify that the
// Vision backend can produce a picture in isolation (i.e. without the
// CoronaEngine->Vision scene-building adapters). Change this to point at any
// local *.json scene. Kept as a constant so it is trivial to edit/relocate.
constexpr const char* kVisionDemoScenePath =
    R"(E:\CoronaExample\test_vision\render_scene\cbox\vision_scene.json)";

// Loads the demo scene from disk and brings it to a renderable state, mirroring
// the reference snippet (import_scene -> init -> prepare -> prepare_view_texture).
// Returns an empty pointer if the file is missing or import fails so the caller
// can skip the demo without crashing.
[[nodiscard]] auto import_vision_demo_pipeline() -> ocarina::SP<vision::Pipeline> {
    const std::filesystem::path scene_path{kVisionDemoScenePath};
    std::error_code ec;
    if (!std::filesystem::exists(scene_path, ec)) {
        CFW_LOG_ERROR("OpticsSystem: Vision demo scene not found: {}", scene_path.string());
        return {};
    }
    // Resolve relative texture/mesh references against the scene's own folder.
    vision::Global::instance().set_scene_path(scene_path.parent_path());
    auto pipeline = vision::Importer::import_scene(scene_path);
    if (!pipeline) {
        CFW_LOG_ERROR("OpticsSystem: Vision demo import_scene returned null for {}",
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
#endif
#endif
}  // namespace

namespace Corona::Systems {
OpticsSystem::OpticsSystem() {
    set_target_fps(60);
}

OpticsSystem::~OpticsSystem() = default;

bool OpticsSystem::initialize_vision_backend_if_enabled() {
    // Vision backend is lazily initialized on first switch to Vision mode.
    CFW_LOG_INFO("OpticsSystem: Vision backend ready for lazy init");
    return true;
}

bool OpticsSystem::initialize_hardware_resources() {
    try {
        hardware_ = std::make_unique<Hardware>();
        image_handle_ = SharedDataHub::instance().image_storage().allocate();
        if (auto accessor = SharedDataHub::instance().image_storage().acquire_write(image_handle_)) {
            // Keep storage entry alive; per-frame image/executor values are updated after render submit.
        } else {
            CFW_LOG_ERROR("[OpticsSystem] Failed to acquire write access to image storage");
            SharedDataHub::instance().image_storage().deallocate(image_handle_);
            image_handle_ = 0;
            return false;
        }

        hardware_->gbufferSize.x = 1920;
        hardware_->gbufferSize.y = 1080;

        const auto w = hardware_->gbufferSize.x;
        const auto h = hardware_->gbufferSize.y;

        // --- Visibility Buffer ---
        hardware_->visibilityImage = HardwareImage(w, h, ImageFormat::RGBA32_UINT, ImageUsage::StorageImage);
        hardware_->depthImage = HardwareImage(w, h, ImageFormat::D32_FLOAT, ImageUsage::DepthImage);

        // --- Uniform buffers ---
        hardware_->uniformBuffer =
            HardwareBuffer(sizeof(Hardware::UniformBufferObject), BufferUsage::StorageBuffer);
        hardware_->vpUniformBuffer = HardwareBuffer(sizeof(Hardware::VPUniformBufferObject),
                                                    BufferUsage::StorageBuffer);

        // --- Instance & Material table buffers (pre-allocate reasonable capacity) ---
        constexpr uint32_t kMaxInstances = 4096;
        constexpr uint32_t kMaxMaterials = 1024;
        hardware_->instanceInfoBuffer = HardwareBuffer(
            kMaxInstances * static_cast<uint32_t>(sizeof(Hardware::InstanceInfo)),
            BufferUsage::StorageBuffer);
        hardware_->materialTableBuffer = HardwareBuffer(
            kMaxMaterials * static_cast<uint32_t>(sizeof(Hardware::MaterialInfo)),
            BufferUsage::StorageBuffer);
        hardware_->actorPickBuffer = HardwareBuffer(sizeof(std::uint32_t), BufferUsage::StorageBuffer);

        hardware_->finalOutputImage = HardwareImage(w, h, ImageFormat::RGBA16_FLOAT, ImageUsage::StorageImage);
    } catch (const std::exception&) {
        CFW_LOG_CRITICAL("OpticsSystem: Failed to initialize hardware resources");
        return false;
    }

    return true;
}

bool OpticsSystem::initialize_render_pipelines() {
    try {
        hardware_->visibilityPipeline.emplace();
        hardware_->lightingPipeline.emplace();
        hardware_->skyPipeline.emplace();
        hardware_->tonemapPipeline.emplace();
        hardware_->debugResolvePipeline.emplace();
        hardware_->actorPickPipeline.emplace();
#ifdef CORONA_ENABLE_VISION
        hardware_->visionResolvePipeline.emplace();
#endif
        hardware_->shaderHasInit = true;
        CFW_LOG_INFO(
            "OpticsSystem: VBuffer pipelines created successfully "
            "(visibility + lighting + sky + tonemap + debugResolve)");
    } catch (const std::exception& e) {
        CFW_LOG_CRITICAL("OpticsSystem: Failed to initialize typed pipelines: {}", e.what());
        return false;
    }

    return true;
}

void OpticsSystem::ensure_camera_render_resources(uint32_t width, uint32_t height) {
    width = std::max(width, 1u);
    height = std::max(height, 1u);

    if (hardware_->gbufferSize.x == width && hardware_->gbufferSize.y == height &&
        hardware_->visibilityImage && hardware_->depthImage && hardware_->finalOutputImage) {
        return;
    }

    hardware_->gbufferSize.x = width;
    hardware_->gbufferSize.y = height;
    hardware_->visibilityImage = HardwareImage(width, height, ImageFormat::RGBA32_UINT,
                                               ImageUsage::StorageImage);
    hardware_->depthImage = HardwareImage(width, height, ImageFormat::D32_FLOAT,
                                          ImageUsage::DepthImage);
    hardware_->finalOutputImage = HardwareImage(width, height, ImageFormat::RGBA16_FLOAT,
                                                ImageUsage::StorageImage);

    CFW_LOG_INFO("OpticsSystem: Render targets resized to camera resolution {}x{}", width, height);
}

bool OpticsSystem::initialize(Kernel::ISystemContext* ctx) {
    (void)ctx;

    if (!initialize_vision_backend_if_enabled()) {
        return false;
    }

    CFW_LOG_NOTICE("OpticsSystem: Initializing...");

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
#ifdef CORONA_ENABLE_VISION
                RenderBackend requested = (event.backend == static_cast<int>(RenderBackend::Vision))
                                              ? RenderBackend::Vision
                                              : RenderBackend::Native;
                pending_backend_.store(static_cast<int>(requested), std::memory_order_relaxed);
                CFW_LOG_INFO("OpticsSystem: Backend switch requested -> {}",
                             requested == RenderBackend::Vision ? "Vision" : "Native");
#else
                (void)event;
                CFW_LOG_WARNING("OpticsSystem: Backend switch ignored (CORONA_ENABLE_VISION not defined)");
#endif
            });
    }

    return true;
}

void OpticsSystem::update() {
    // Check for pending backend switch request before executing either render path.
    int pending = pending_backend_.load(std::memory_order_relaxed);
    RenderBackend requested = static_cast<RenderBackend>(pending);
    if (requested != current_backend_) {
#ifdef CORONA_ENABLE_VISION
        if (requested == RenderBackend::Vision) {
            if (!init_vision_lazy()) {
                CFW_LOG_WARNING("OpticsSystem: Vision init failed, staying on Native");
                pending_backend_.store(static_cast<int>(RenderBackend::Native), std::memory_order_relaxed);
            } else {
                current_backend_ = RenderBackend::Vision;
                CFW_LOG_INFO("OpticsSystem: Switched to Vision backend");
            }
        } else {
            // 切回 Native：不要销毁 Vision pipeline / CUDA 资源。
            // 之前在这里调用 renderPipeline.reset() 并将 vision_initialized_ 置为
            // false，导致再次切回 Vision 时 init_vision_lazy() 重新执行
            // create_vision_pipeline()/scene.prepare() 等重建逻辑。由于底层 CUDA
            // device 是 function-local static（只创建一次），在残留状态上重建
            // 会造成 CUDA 资源冲突并崩溃。改为“挂起”Vision：保留 pipeline 与
            // vision_initialized_，仅停止渲染 Vision 帧；切回 Vision 时直接复用。
            consecutive_vision_failures_ = 0;
            current_backend_ = RenderBackend::Native;
            CFW_LOG_INFO("OpticsSystem: Switched to Native backend (Vision suspended)");
        }
#else
        current_backend_ = RenderBackend::Native;
        CFW_LOG_INFO("OpticsSystem: Switched to Native backend");
#endif
    }

#ifdef CORONA_ENABLE_VISION
    // Vision 模式不依赖 Native 管线资源，提前进入渲染
    if (current_backend_ == RenderBackend::Vision) {
        static float vc = 0.f; static uint64_t vi = 0;
        vc += delta_time(); ++vi;
        optics_pipeline(vc, vi);
        return;
    }
#endif
    if (!hardware_->shaderHasInit || !hardware_->visibilityPipeline ||
        !hardware_->lightingPipeline || !hardware_->skyPipeline || !hardware_->tonemapPipeline ||
        !hardware_->debugResolvePipeline) {
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
#ifdef CORONA_ENABLE_VISION
    if (current_backend_ == RenderBackend::Vision) {
        if (vision_initialized_) {
            run_vision_frame(frame_count, frame_index);
        } else {
            CFW_LOG_WARNING("OpticsSystem: Vision backend not initialized, falling back to Native");
        }
        return;
    }
#endif
    auto& visibility = *hardware_->visibilityPipeline;
    auto& lighting = *hardware_->lightingPipeline;
    auto& sky = *hardware_->skyPipeline;
    auto& tonemap = *hardware_->tonemapPipeline;

    for (auto scene_it = SharedDataHub::instance().scene_storage().cbegin();
         scene_it != SharedDataHub::instance().scene_storage().cend(); ++scene_it) {
        const auto& scene = *scene_it;
        if (!scene.enabled)
            continue;

        for (auto cam_handle : scene.camera_handles) {
            if (auto camera = SharedDataHub::instance().camera_storage().try_acquire_read(cam_handle)) {
                if (image_handle_ != 0) {
                    if (auto consumed_device = SharedDataHub::instance().image_storage().acquire_write(image_handle_)) {
                        hardware_->executor.wait(consumed_device->consumed_executor);
                    }
                }
                ensure_camera_render_resources(camera->width, camera->height);

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

                // ================================================================
                // 2. Build per-frame Instance Table & Material Table
                //    仅遍历本场景 actor → profile → optics，隔离多场景数据
                // ================================================================
                hardware_->instanceInfoData.clear();
                hardware_->instanceActorHandles.clear();
                hardware_->materialTableData.clear();

                // Configure visibility pipeline render targets
                visibility.visibilityData = hardware_->visibilityImage;
                visibility.setDepthImage(hardware_->depthImage);

                auto& actor_storage = SharedDataHub::instance().actor_storage();
                auto& profile_storage = SharedDataHub::instance().profile_storage();
                auto& optics_storage = SharedDataHub::instance().optics_storage();
                auto& geom_storage = SharedDataHub::instance().geometry_storage();
                auto& transform_storage = SharedDataHub::instance().model_transform_storage();

                uint32_t object_id = 1;
                for (auto actor_handle : scene.actor_handles) {
                    auto actor = actor_storage.try_acquire_read(actor_handle);
                    if (!actor) {
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
                            }

                            for (auto& m : geom->mesh_handles) {
                                // --- Collect material info ---
                                auto materialID = static_cast<uint32_t>(hardware_->materialTableData.size());
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
                                    hardware_->materialTableData.push_back(mat_info);
                                }

                                // --- Collect instance info ---
                                auto instanceID = static_cast<uint32_t>(hardware_->instanceInfoData.size());
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
                                    hardware_->instanceInfoData.push_back(inst);
                                    hardware_->instanceActorHandles.push_back(actor_handle);
                                }

                                // --- Record visibility draw call ---
                                visibility.pushConsts.modelMatrix = model_matrix;
                                visibility.pushConsts.uniformBufferIndex =
                                    hardware_->vpUniformBuffer.storeDescriptor();
                                // VBuffer uses 1-based instanceID (0 = background sentinel after clear)
                                visibility.pushConsts.instanceID = instanceID + 1;
                                // Alpha-cutout: pass texture descriptor for discard test
                                if (m.textureBuffer) {
                                    visibility[visibility_frag_glsl::pushConsts::textureIndex] =
                                        m.textureBuffer.storeDescriptor();
                                } else {
                                    visibility[visibility_frag_glsl::pushConsts::textureIndex] =
                                        static_cast<uint32_t>(0);
                                }
                                visibility.record(m.indexBuffer, m.vertexBuffer);
                            }
                        }
                        ++object_id;
                    }
                }

                // ================================================================
                // 3. Upload instance & material tables to GPU
                // ================================================================
                if (!hardware_->instanceInfoData.empty()) {
                    hardware_->instanceInfoBuffer.copyFromData(
                        hardware_->instanceInfoData.data(),
                        hardware_->instanceInfoData.size() * sizeof(Hardware::InstanceInfo));
                }
                if (!hardware_->materialTableData.empty()) {
                    hardware_->materialTableBuffer.copyFromData(
                        hardware_->materialTableData.data(),
                        hardware_->materialTableData.size() * sizeof(Hardware::MaterialInfo));
                }

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

                // Offscreen cameras (no surface) render to a dedicated image so
                // they never overwrite the display pipeline's finalOutputImage.
                const bool is_offscreen = (camera->surface == nullptr);
                if (is_offscreen) {
                    if (!offscreen_image_ ||
                        offscreen_w_ != hardware_->gbufferSize.x ||
                        offscreen_h_ != hardware_->gbufferSize.y) {
                        offscreen_image_ = HardwareImage(
                            hardware_->gbufferSize.x, hardware_->gbufferSize.y,
                            ImageFormat::RGBA16_FLOAT, ImageUsage::StorageImage);
                        offscreen_w_ = hardware_->gbufferSize.x;
                        offscreen_h_ = hardware_->gbufferSize.y;
                    }
                }
                HardwareImage& render_target = is_offscreen
                                                   ? offscreen_image_
                                                   : hardware_->finalOutputImage;
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

                if (actor_pick_request) {
                    complete_actor_pick(*actor_pick_request);
                }

                if (image_handle_ != 0) {
                    process_pending_screenshots(cam_handle, render_target);

                    if (camera->surface != nullptr) {
                        if (auto image_device = SharedDataHub::instance().image_storage().acquire_write(image_handle_)) {
                            image_device->image = hardware_->finalOutputImage;
                            image_device->executor = hardware_->executor;
                        }

                        if (auto* event_bus = context()->event_bus()) {
                            event_bus->publish<Events::OpticsFrameReadyEvent>({camera->surface,
                                                                               image_handle_,
                                                                               frame_index,
                                                                               hardware_->gbufferSize.x,
                                                                               hardware_->gbufferSize.y});
                        }
                    }
                }

#ifdef CORONA_ENABLE_VISION
                // (Vision render path runs in run_vision_frame below)
#endif
            }
        }
    }
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
    if (auto camera = SharedDataHub::instance().camera_storage().try_acquire_read(camera_handle)) {
        pick_handle = camera->actor_pick_handle;
    }
    if (pick_handle == 0) {
        return std::nullopt;
    }

    auto pick = SharedDataHub::instance().actor_pick_storage().try_acquire_write(pick_handle);
    if (!pick || !pick->pending) {
        return std::nullopt;
    }

    ActorPickRequest request;
    request.pick_handle = pick_handle;
    request.x = pick->x;
    request.y = pick->y;
    pick->pending = false;

    if (request.x >= hardware_->gbufferSize.x || request.y >= hardware_->gbufferSize.y) {
        pick->actor_handle = 0;
        pick->result_x = request.x;
        pick->result_y = request.y;
        pick->result_ready = true;
        return std::nullopt;
    }

    pick->result_ready = false;
    return request;
}

void OpticsSystem::complete_actor_pick(const ActorPickRequest& request) {
    std::uint32_t instance_id = 0;
    if (!hardware_->actorPickBuffer.copyToData(&instance_id, sizeof(instance_id))) {
        CFW_LOG_ERROR("OpticsSystem: Failed to read actor pick result from GPU");
    }

    std::uintptr_t actor_handle = 0;
    if (instance_id > 0) {
        const auto instance_index = static_cast<std::size_t>(instance_id - 1);
        if (instance_index < hardware_->instanceActorHandles.size()) {
            actor_handle = hardware_->instanceActorHandles[instance_index];
        }
    }

    if (auto pick = SharedDataHub::instance().actor_pick_storage().try_acquire_write(request.pick_handle)) {
        pick->actor_handle = actor_handle;
        pick->result_x = request.x;
        pick->result_y = request.y;
        pick->result_ready = true;
    }
}

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
            CFW_LOG_INFO("OpticsSystem: Screenshot saved to {}", req.file_path);
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
    CFW_LOG_NOTICE("OpticsSystem: Shutting down...");

    if (auto* event_bus = context()->event_bus()) {
        if (screenshot_request_sub_id_ != 0) {
            event_bus->unsubscribe(screenshot_request_sub_id_);
        }
        if (backend_switch_sub_id_ != 0) {
            event_bus->unsubscribe(backend_switch_sub_id_);
        }
    }

    if (image_handle_ != 0) {
        SharedDataHub::instance().image_storage().deallocate(image_handle_);
        image_handle_ = 0;
    }

    offscreen_image_ = HardwareImage();
#ifdef CORONA_ENABLE_VISION
    // Release the zero-copy bridge (imported Vulkan buffer + exported CUDA buffer)
    // before the Vision pipeline/device is torn down, so the import never outlives
    // its backing allocation.
    vision_zero_copy_bridge_.reset();
#endif
    hardware_.reset();

    CFW_LOG_INFO("OpticsSystem: Hardware resources released");
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
        renderPipeline->invalidate();

        CFW_LOG_INFO(
            "OpticsSystem: Vision scene rebuilt ({} geometry instances, {} candidates, {} skipped)",
            result.instance_count, result.candidate_count, result.skipped_no_data);
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
        renderPipeline = import_vision_demo_pipeline();
        if (!renderPipeline) {
            CFW_LOG_ERROR("OpticsSystem: Vision demo pipeline import failed");
            return false;
        }
        vision_initialized_ = true;
        CORONA_VPROBE("demo.after_prepare", *renderPipeline);
        CFW_LOG_INFO("OpticsSystem: Vision import-scene demo initialized successfully");
        return true;
#else
        renderPipeline = create_vision_pipeline();
        if (!renderPipeline) {
            CFW_LOG_ERROR("OpticsSystem: Failed to create Vision pipeline without external scene import");
            return false;
        }

        // Populate Vision scene directly from CoronaEngine scene data.
        auto& scene = renderPipeline->scene();
#if defined(CORONA_VISION_EXP_SKIP_GEOMETRY)
        // Stage 1.5「空几何天光测试」：刻意跳过几何导入，只留天光。若此后能看见
        // 灰色天空，说明输出/光照/相机链路在非 DEMO 路径同样正常，黑屏根因 100%
        // 在几何导入；若仍全黑，则问题在 env_light_/输出/相机，而非几何。
        Vision::VisionBuildResult build_result{};
        CFW_LOG_WARNING(
            "OpticsSystem: [EXP] CORONA_VISION_EXP_SKIP_GEOMETRY enabled — skipping "
            "build_vision_geometry (empty-geometry sky test)");
#else
        Vision::VisionBuildResult build_result = Vision::build_vision_geometry(scene);
#endif
        int geom_count = build_result.instance_count;

        // 主机侧探针：build_vision_geometry 之后、prepare 之前。此时 accel/BVH 尚未
        // 构建，DEV 段应为 0，但 HOST 段（inst/mesh_reg）已应反映导入结果。
        CORONA_VPROBE("prod.host_built", *renderPipeline);

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

        CFW_LOG_INFO("OpticsSystem: Vision adapters finished ({} geometry instances)", geom_count);

        renderPipeline->prepare();

        // Pipeline::prepare() allocates the internal per-pixel device buffers but
        // does NOT create FrameBuffer::view_texture_ (only prepare_view_texture()
        // does). The render path tone-maps into view_texture_ and we later read it
        // via fill_window_buffer(view_texture()). Without this the first frame uses
        // an uninitialized texture. The official vision-gui/vision-eval apps also
        // call prepare_view_texture() right after prepare().
        renderPipeline->frame_buffer()->prepare_view_texture();

        // 设备侧探针：prepare() 之后 accel/BVH 已构建。把这条与上面 prod.host_built、
        // 以及 DEMO 路径的 demo.after_prepare 三方对比，即可判定 mesh 导入是否成功：
        //   - DEV tri==0 而 HOST inst>0  => 设备侧上传/BVH 失败（或 transform 致 AABB 退化）
        //   - DEV 数字与 demo.after_prepare 同量级 => mesh 导入成功，黑屏在下游
        CORONA_VPROBE("prod.after_prepare", *renderPipeline);


        // which upload to GPU device buffers. Those device buffers are only
        // allocated during Pipeline::prepare() (Scene::prepare -> Sensor::prepare
        // -> EncodedObject::prepare_data -> reset_device_buffer). Running it
        // before prepare() uploads into unallocated device memory and crashes the
        // CUDA device deterministically.
        for (auto sd_it = SharedDataHub::instance().scene_storage().cbegin();
             sd_it != SharedDataHub::instance().scene_storage().cend(); ++sd_it) {
            const auto& sd = *sd_it;
            if (!sd.enabled) continue;
            if (sd.camera_handles.empty()) continue;
            auto camera = SharedDataHub::instance().camera_storage().try_acquire_read(sd.camera_handles.front());
            if (!camera) continue;
            Vision::sync_vision_camera(*renderPipeline, *camera);
            break;
        }

        vision_initialized_ = true;

        // Establish the dynamic-scene signature baseline so subsequent edits are
        // detected as changes against the initially-built scene.
        vision_applied_signature_ = compute_vision_scene_signature();
        vision_pending_signature_ = vision_applied_signature_;
        vision_stable_frames_ = 0;

        CFW_LOG_INFO("OpticsSystem: Vision backend initialized successfully");
        return true;
#endif  // CORONA_VISION_IMPORT_DEMO
    } catch (const std::exception& e) {
        CFW_LOG_ERROR("OpticsSystem: Vision init failed: {}", e.what());
        return false;
    }
}

void OpticsSystem::run_vision_frame(float frame_count, uint64_t frame_index) {
    if (!renderPipeline) return;

#if defined(CORONA_VISION_IMPORT_DEMO) && defined(CORONA_VISION_EXP_GRAFT_GEOMETRY)
    // Stage 2「几何嫁接」：在已被证明能正常出图、能操控相机的 DEMO 台子上，先渲染
    // 若干帧确认台子正常，再调用 rebuild_vision_scene() 把 demo 几何替换成 Corona
    // 几何（复用现成的「build_vision_geometry + setup_vision_lights + 增量 prepare」
    // 序列）。这是直接验证 mesh 导入是否成功的决定性实验：
    //   - 嫁接后能看见 Corona 物体并可飞行 => mesh 导入 + 几何路径完全正常，
    //     非 DEMO 黑屏的根因在 create_vision_pipeline 或首次 prepare，而非几何；
    //   - 嫁接后变全黑 => Corona 几何派生的场景本身有问题，回看 graft.after 探针的
    //     HOST/DEV 数字定位（主机侧没建出来 vs 设备侧没上传 vs transform 甩飞）。
    {
        static constexpr uint64_t kGraftAtFrame = 120;  // 跑 ~2s 确认 DEMO 正常后再嫁接
        static bool s_grafted = false;
        if (!s_grafted && frame_index >= kGraftAtFrame) {
            s_grafted = true;
            CFW_LOG_WARNING(
                "OpticsSystem: [EXP] Stage2 grafting Corona geometry into demo pipeline at frame {}",
                frame_index);
            CORONA_VPROBE("graft.before", *renderPipeline);
            const Vision::VisionBuildResult graft = rebuild_vision_scene();
            CFW_LOG_WARNING(
                "OpticsSystem: [EXP] Stage2 graft result instances={} candidates={} skipped={}",
                graft.instance_count, graft.candidate_count, graft.skipped_no_data);
            CORONA_VPROBE("graft.after", *renderPipeline);
        }
    }
#endif

#ifndef CORONA_VISION_IMPORT_DEMO
    // Detect and apply dynamic scene changes (object import/export, transform,
    // material params, per-mesh color) before rendering this frame.
    sync_vision_dynamic_scene();
#endif

    // [VDIAG-B0] Entry/loop probe: tells apart "run_vision_frame never iterates a
    // camera" (no enabled scene / empty camera_handles -> nothing rendered -> black)
    // from "renders but is not displayed". Rate-limited to once per 120 frames.
    //bool vdiag_rendered_any = false;

    for (auto scene_it = SharedDataHub::instance().scene_storage().cbegin();
         scene_it != SharedDataHub::instance().scene_storage().cend(); ++scene_it) {
        const auto& scene = *scene_it;
        if (!scene.enabled) continue;
        for (auto cam_handle : scene.camera_handles) {
            auto camera = SharedDataHub::instance().camera_storage().try_acquire_read(cam_handle);
            if (!camera) continue;
            try {
                // [VDIAG-B2] Bracket the CUDA calls so an exit-code crash can be pinned
                // to the exact stage (sync_vision_camera vs render vs readback). The
                // process exited -1 right after "Vision scene rebuilt", so we want to
                // know whether the first render() after a rebuild is the crash site.
                //if ((frame_index % 120) == 0) {
                //    CFW_LOG_INFO("OpticsSystem: [VDIAG-B2] frame={} stage=sync_camera cam={}",
                //                 frame_index, cam_handle);
                //}
                Vision::sync_vision_camera(*renderPipeline, *camera);
                 /*               if ((frame_index % 120) == 0) {
                                    CFW_LOG_INFO("OpticsSystem: [VDIAG-B2] frame={} stage=render begin", frame_index);
                                }*/
                                // IMPORTANT: render() only RECORDS commands into the Vision
                                // stream (the default, non-profiling submit path does NOT
                                // synchronize/commit). Downloading view_texture() right after a
                                // bare render() therefore reads stale (black) GPU memory.
                                // Use the full pipeline lifecycle instead:
                                //   upload_data() -> display(dt)
                                // display() runs before_render -> render -> commit_command
                                // (which performs synchronize() + commit()) -> after_render,
                                // matching the reference apps (vision-gui / vision-eval).
                                renderPipeline->upload_data();
                                renderPipeline->display(1.0 / 60.0);
#if CORONA_VISION_EXP_PROBE
                // 运行时探针（每 120 帧一次）：display() 已 synchronize/commit，读取安全。
                // 重点观察 frame_idx 是否单调增长（累积收敛）还是每帧归 0（invalidate
                // 误触发），以及 accel/light/相机在运行中是否被动态重建意外清空。
                if ((frame_index % 120) == 0) {
                    dump_vision_state("runtime", *renderPipeline);
                }
#endif
                //vdiag_rendered_any = true;
                //if ((frame_index % 120) == 0) {
                //    CFW_LOG_INFO("OpticsSystem: [VDIAG-B2] frame={} stage=render done", frame_index);
                //}

                auto* fb = renderPipeline->frame_buffer();
                auto res = fb->raytracing_resolution();  // ocarina::uint2
                uint32_t w = res.x;
                uint32_t h = res.y;

                // [ZERO-COPY] Share Vision's pre-tonemap linear color buffer with
                // Vulkan instead of the GPU->CPU->half->GPU readback. The bridge
                // copies accumulation_buffer_/rt_buffer_ on-device into a CUDA
                // exportable buffer, exports its Win32 handle, and imports it as a
                // Vulkan HardwareBuffer; the vision_resolve compute pass below
                // applies Vision's exposure+ACES and writes finalOutputImage.
                // NOTE: no cross-API semaphore yet (tearing/flicker possible).
                if (!vision_zero_copy_bridge_) {
                    vision_zero_copy_bridge_ =
                        std::make_unique<Vision::VisionZeroCopyBridge>();
                }
                if (!vision_zero_copy_bridge_->ensure(*renderPipeline, w, h) ||
                    !vision_zero_copy_bridge_->copy_from_framebuffer(*renderPipeline)) {
                    CFW_LOG_WARNING(
                        "OpticsSystem: Vision zero-copy bridge unavailable this frame "
                        "(w={} h={}), skipping frame", w, h);
                    ++consecutive_vision_failures_;
                    break;
                }

                if (image_handle_ != 0) {
                    if (auto consumed_device = SharedDataHub::instance().image_storage().acquire_write(image_handle_)) {
                        hardware_->executor.wait(consumed_device->consumed_executor);
                    }
                }
                ensure_camera_render_resources(w, h);

                // Resolve: imported linear float4 -> exposure+ACES -> finalOutputImage.
                {
                    auto& visionResolve = *hardware_->visionResolvePipeline;
                    visionResolve.pushConsts.gbufferSize = hardware_->gbufferSize;
                    visionResolve.pushConsts.srcBufferIndex =
                        vision_zero_copy_bridge_->imported().storeDescriptor();
                    visionResolve.pushConsts.outputImage =
                        hardware_->finalOutputImage.storeDescriptor();
                    visionResolve.pushConsts.exposure = 1.0f;  // Vision FrameBuffer default

                    const uint32_t dispatchX = (w + 7u) / 8u;
                    const uint32_t dispatchY = (h + 7u) / 8u;
                    hardware_->executor << visionResolve(dispatchX, dispatchY, 1)
                                        << hardware_->executor.commit();
                }

                last_render_cam_handle_ = cam_handle;
                consecutive_vision_failures_ = 0;
                has_last_vision_frame_ = true;
                last_vision_frame_width_ = w;
                last_vision_frame_height_ = h;

                if (image_handle_ != 0) {
                    if (camera->surface != nullptr) {
                        if (auto image_device = SharedDataHub::instance().image_storage().acquire_write(image_handle_)) {
                            image_device->image = hardware_->finalOutputImage;
                            image_device->executor = hardware_->executor;
                        }

                        if (auto* event_bus = context()->event_bus()) {
                            event_bus->publish<Events::OpticsFrameReadyEvent>({camera->surface,
                                                                               image_handle_,
                                                                               frame_index,
                                                                               w,
                                                                               h});
                        }
                    }
                }

                // [VDIAG-B1] Publish-gate probe: an offscreen camera (surface==nullptr)
                // or a zero image_handle silently skips the OpticsFrameReadyEvent and the
                // frame never reaches DisplaySystem -> black screen. Gated the same way as
                // [DIAG] so it keeps reporting after a project/scene is loaded.
                //{
                //    static uint32_t s_b1_count = 0;
                //    static uint32_t s_b1_w = 0, s_b1_h = 0;
                //    const bool b1_dim_changed = (w != s_b1_w || h != s_b1_h);
                //    if (b1_dim_changed) { s_b1_w = w; s_b1_h = h; s_b1_count = 0; }
                //    if (s_b1_count < 5 || (frame_index % 120) == 0) {
                //        ++s_b1_count;
                //        CFW_LOG_INFO(
                //            "OpticsSystem: [VDIAG-B1] publish-gate: image_handle={} surface={} frame={} {}x{}",
                //            image_handle_, static_cast<const void*>(camera->surface), frame_index, w, h);
                //    }
                //}
            } catch (const std::exception& e) {
                //++consecutive_vision_failures_;
                //CFW_LOG_ERROR("OpticsSystem: Vision frame failed: {}", e.what());
                //if (consecutive_vision_failures_ >= 3) {
                //    CFW_LOG_WARNING("OpticsSystem: Vision backend failed {} consecutive frames; manual fallback to native is recommended",
                //                    consecutive_vision_failures_);
                //}
                //if (has_last_vision_frame_ && image_handle_ != 0 && camera->surface != nullptr) {
                //    if (auto* event_bus = context()->event_bus()) {
                //        event_bus->publish<Events::OpticsFrameReadyEvent>({
                //            camera->surface,
                //            image_handle_,
                //            frame_index,
                //            last_vision_frame_width_,
                //            last_vision_frame_height_});
                //    }
                //}
            }
            break; // process first camera only for Vision
        }
        break; // process first scene only for Vision
    }

    // [VDIAG-B0] If no enabled scene/camera was iterated, run_vision_frame produced
    // nothing this frame. A persistent "rendered=false" while in Vision mode means the
    // scene/camera storage is empty or all scenes are disabled -> guaranteed black.
    //if (!vdiag_rendered_any && (frame_index % 120) == 0) {
    //    CFW_LOG_WARNING(
    //        "OpticsSystem: [VDIAG-B0] frame={} rendered NO camera (no enabled scene or empty camera_handles)",
    //        frame_index);
    //}
}
#endif  // CORONA_ENABLE_VISION

}  // namespace Corona::Systems
