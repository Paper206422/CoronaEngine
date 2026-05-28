#include <corona/events/display_system_events.h>
#include <corona/events/optics_system_events.h>
#include <corona/kernel/core/i_logger.h>
#include <corona/kernel/event/i_event_bus.h>
#include <corona/kernel/event/i_event_stream.h>
#include <corona/resource/resource_manager.h>
#include <corona/resource/types/image.h>
#include <corona/shared_data_hub.h>
#include <corona/systems/optics/optics_system.h>

#include <cmath>
#include <cstdint>
#include <exception>
#include <filesystem>
#include <vector>

#include "hardware.h"

// CORONA_ENABLE_VISION is controlled by CMake (-DCORONA_ENABLE_VISION).


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
#include "vision/vision_output_bridge.h"
#endif

namespace {
#ifdef CORONA_ENABLE_VISION
ocarina::SP<vision::Pipeline> renderPipeline;
vision::Device* visionDevicePtr = nullptr;

[[nodiscard]] auto make_default_vision_project_desc() -> vision::ProjectDesc {
    // Each *Desc has in-class default initializers; the overridden
    // init(const ParameterSet&) is only used for JSON-driven configuration.
    // An empty ParameterSet keeps the in-class defaults while still letting
    // each Desc run any side-effects it may perform during init().
    const vision::ParameterSet empty_ps{};
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

void OpticsSystem::set_render_backend(RenderBackend backend) {
    pending_backend_.store(static_cast<int>(backend), std::memory_order_relaxed);
}

RenderBackend OpticsSystem::get_render_backend() const {
    return current_backend_;
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
            renderPipeline.reset();
            vision_initialized_ = false;
            consecutive_vision_failures_ = 0;
            has_last_vision_frame_ = false;
            current_backend_ = RenderBackend::Native;
            CFW_LOG_INFO("OpticsSystem: Switched to Native backend");
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

    for (const auto& scene : SharedDataHub::instance().scene_storage()) {
        if (!scene.enabled)
            continue;

        for (auto cam_handle : scene.camera_handles) {
            if (auto camera = SharedDataHub::instance().camera_storage().acquire_read(cam_handle)) {
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
                    auto actor = actor_storage.acquire_read(actor_handle);
                    if (!actor) {
                        ++object_id;
                        continue;
                    }

                    for (auto profile_handle : actor->profile_handles) {
                        auto profile = profile_storage.acquire_read(profile_handle);
                        if (!profile || profile->optics_handle == 0) continue;

                        auto optics_acc = optics_storage.acquire_read(profile->optics_handle);
                        if (!optics_acc) continue;
                        const auto& optics = *optics_acc;

                        if (!optics.visible) {
                            ++object_id;
                            continue;
                        }
                        if (auto geom = geom_storage.acquire_write(optics.geometry_handle)) {
                            ktm::fmat4x4 model_matrix{ktm::fmat4x4::from_eye()};
                            if (auto transform = transform_storage.acquire_read(geom->transform_handle)) {
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
                    if (auto env = SharedDataHub::instance().environment_storage().acquire_read(
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
                if (image_handle_ != 0) {
                    if (auto consumed_device = SharedDataHub::instance().image_storage().acquire_write(image_handle_)) {
                        hardware_->executor.wait(consumed_device->consumed_executor);
                    }
                }

                const uint32_t dispatchX = hardware_->gbufferSize.x / 8;
                const uint32_t dispatchY = hardware_->gbufferSize.y / 8;

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

                    hardware_->executor << visibility(1920, 1080)
                                        << debugResolve(dispatchX, dispatchY, 1);
                } else {
                    // ============================================================
                    // Normal rendering path: full pipeline
                    // ============================================================
                    hardware_->executor << visibility(1920, 1080)
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
    }

    if (image_handle_ != 0) {
        SharedDataHub::instance().image_storage().deallocate(image_handle_);
        image_handle_ = 0;
    }

    offscreen_image_ = HardwareImage();
    hardware_.reset();

    CFW_LOG_INFO("OpticsSystem: Hardware resources released");
}
#ifdef CORONA_ENABLE_VISION
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
        renderPipeline = create_vision_pipeline();
        if (!renderPipeline) {
            CFW_LOG_ERROR("OpticsSystem: Failed to create Vision pipeline without external scene import");
            return false;
        }

        // Populate Vision scene directly from CoronaEngine scene data.
        auto& scene = renderPipeline->scene();
        int geom_count = Vision::build_vision_geometry(scene);

        Corona::EnvironmentDevice env{};
        bool env_found = false;
        for (const auto& sd : SharedDataHub::instance().scene_storage()) {
            if (!sd.enabled) continue;
            if (sd.environment != 0) {
                if (auto e = SharedDataHub::instance().environment_storage().acquire_read(sd.environment)) {
                    env = *e;
                    env_found = true;
                    break;
                }
            }
        }
        if (env_found) {
            Vision::setup_vision_lights(scene, env);
        }

        for (const auto& sd : SharedDataHub::instance().scene_storage()) {
            if (!sd.enabled) continue;
            if (sd.camera_handles.empty()) continue;
            auto camera = SharedDataHub::instance().camera_storage().acquire_read(sd.camera_handles.front());
            if (!camera) continue;
            Vision::sync_vision_camera(*renderPipeline, *camera);
            break;
        }

        CFW_LOG_INFO("OpticsSystem: Vision adapters finished ({} geometry instances)", geom_count);

        renderPipeline->prepare();
        vision_initialized_ = true;
        CFW_LOG_INFO("OpticsSystem: Vision backend initialized successfully");
        return true;
    } catch (const std::exception& e) {
        CFW_LOG_ERROR("OpticsSystem: Vision init failed: {}", e.what());
        return false;
    }
}

void OpticsSystem::run_vision_frame(float frame_count, uint64_t frame_index) {
    if (!renderPipeline) return;
    for (const auto& scene : SharedDataHub::instance().scene_storage()) {
        if (!scene.enabled) continue;
        for (auto cam_handle : scene.camera_handles) {
            auto camera = SharedDataHub::instance().camera_storage().acquire_read(cam_handle);
            if (!camera) continue;
            try {
                Vision::sync_vision_camera(*renderPipeline, *camera);
                renderPipeline->render(1.0 / 60.0);

                auto* fb = renderPipeline->frame_buffer();
                auto res = fb->raytracing_resolution();  // ocarina::uint2
                uint32_t w = res.x;
                uint32_t h = res.y;
                fb->fill_window_buffer(fb->view_texture());
                const auto& wbuf = fb->window_buffer();
                static_assert(sizeof(wbuf[0]) == sizeof(float) * 4,
                    "float4 must be 16 bytes for reinterpret_cast to float* to be valid");
                const float* raw = reinterpret_cast<const float*>(wbuf.data());
                const bool uploaded = Vision::VisionOutputBridge::upload_to_hardware_image(
                    raw, w, h, hardware_->finalOutputImage, hardware_->executor);
                if (!uploaded) {
                    throw std::runtime_error("Vision output upload failed");
                }

                last_render_cam_handle_ = cam_handle;
                consecutive_vision_failures_ = 0;
                has_last_vision_frame_ = true;
                last_vision_frame_width_ = w;
                last_vision_frame_height_ = h;

                if (image_handle_ != 0 && camera->surface != nullptr) {
                    if (auto image_device = SharedDataHub::instance().image_storage().acquire_write(image_handle_)) {
                        image_device->image = hardware_->finalOutputImage;
                        image_device->executor = hardware_->executor;
                    }
                    if (auto* event_bus = context()->event_bus()) {
                        event_bus->publish<Events::OpticsFrameReadyEvent>(
                            {camera->surface, image_handle_, frame_index, w, h});
                    }
                }
            } catch (const std::exception& e) {
                ++consecutive_vision_failures_;
                CFW_LOG_ERROR("OpticsSystem: Vision frame failed: {}", e.what());
                if (consecutive_vision_failures_ >= 3) {
                    CFW_LOG_WARNING("OpticsSystem: Vision backend failed {} consecutive frames; manual fallback to native is recommended",
                                    consecutive_vision_failures_);
                }
                if (has_last_vision_frame_ && image_handle_ != 0 && camera->surface != nullptr) {
                    if (auto* event_bus = context()->event_bus()) {
                        event_bus->publish<Events::OpticsFrameReadyEvent>({
                            camera->surface,
                            image_handle_,
                            frame_index,
                            last_vision_frame_width_,
                            last_vision_frame_height_});
                    }
                }
            }
            break; // process first camera only for Vision
        }
        break; // process first scene only for Vision
    }
}
#endif  // CORONA_ENABLE_VISION

}  // namespace Corona::Systems
