#include <corona/events/display_system_events.h>
#include <corona/events/engine_events.h>
#include <corona/kernel/core/i_logger.h>
#include <corona/kernel/event/i_event_bus.h>
#include <corona/kernel/event/i_event_stream.h>
#include <corona/shared_data_hub.h>
#include <corona/systems/display/display_system.h>

#include <algorithm>
#include <ranges>

namespace Corona::Systems {

bool DisplaySystem::initialize(Kernel::ISystemContext* ctx) {
    CFW_LOG_NOTICE("DisplaySystem: Initializing...");

    auto* event_bus = ctx->event_bus();
    if (event_bus == nullptr) {
        CFW_LOG_WARNING("DisplaySystem: No event bus available");
        return true;
    }

    surface_changed_sub_id_ = event_bus->subscribe<Events::DisplaySurfaceChangedEvent>(
        [this](const Events::DisplaySurfaceChangedEvent& event) {
            if (event.surface == nullptr) {
                return;
            }

            std::lock_guard<std::mutex> lock(frame_mutex_);
            pending_surfaces_.push_back(event.surface);
        });

    optics_frame_sub_id_ = event_bus->subscribe<Events::OpticsFrameReadyEvent>(
        [this](const Events::OpticsFrameReadyEvent& event) {
            if (event.surface == nullptr ||
                event.image_handle == 0) {
                return;
            }

            const auto surface_id = reinterpret_cast<uint64_t>(event.surface);
            std::lock_guard<std::mutex> lock(frame_mutex_);
            auto& layer = surface_states_[surface_id].optics;
            // [VDIAG-B3] Confirm DisplaySystem actually receives Vision optics frames
            // (and that they are not dropped by the monotonic frame_index guard below).
            // Gated periodically + first few so it keeps reporting after a scene loads
            // (Vision frame_index is already in the hundreds by then).
            {
                static uint32_t s_b3_count = 0;
                if (s_b3_count < 5 || (event.frame_index % 120) == 0) {
                    ++s_b3_count;
                    CFW_LOG_INFO(
                        "DisplaySystem: [VDIAG-B3] recv optics: surface={} (id={}) handle={} frame={} {}x{} (prev_frame={}, accepted={})",
                        static_cast<const void*>(event.surface), surface_id, event.image_handle,
                        event.frame_index, event.width, event.height, layer.frame_index,
                        (event.frame_index >= layer.frame_index));
                }
            }
            if (event.frame_index >= layer.frame_index) {
                layer.image_handle = event.image_handle;
                layer.frame_index = event.frame_index;
                layer.width = event.width;
                layer.height = event.height;
            }
        });

    ui_frame_sub_id_ = event_bus->subscribe<Events::UIFrameReadyEvent>(
        [this](const Events::UIFrameReadyEvent& event) {
            if (event.surface == nullptr ||
                event.image_handle == 0) {
                return;
            }

            const auto surface_id = reinterpret_cast<uint64_t>(event.surface);
            std::lock_guard<std::mutex> lock(frame_mutex_);
            auto& layer = surface_states_[surface_id].ui;
            if (event.frame_index >= layer.frame_index) {
                layer.image_handle = event.image_handle;
                layer.frame_index = event.frame_index;
                layer.width = event.width;
                layer.height = event.height;
            }
        });

    CFW_LOG_DEBUG("DisplaySystem: EventBus subscriptions ready (optics + ui)");

    // Create 1x1 transparent fallback images for single-layer compositing.
    // Porter-Duff Source Over with a transparent layer is an identity operation.
    // Two images needed because Optics outputs StorageImage and UI outputs SampledImage,
    // which live in different descriptor sets.
    transparent_storage_ = HardwareImage(1, 1, ImageFormat::RGBA16_FLOAT, ImageUsage::StorageImage);
    transparent_sampled_ = HardwareImage(1, 1, ImageFormat::RGBA8_SRGB, ImageUsage::SampledImage);
    if (transparent_storage_ && transparent_sampled_) {
        uint8_t zero_pixel[4] = {0, 0, 0, 0};
        compositor_executor_ << transparent_storage_.copyFrom(zero_pixel)
                             << transparent_sampled_.copyFrom(zero_pixel)
                             << compositor_executor_.commit();
    }

    return true;
}

void DisplaySystem::update() {
    // Snapshot shared state and process pending displayer creation under lock,
    // then release before GPU work. displayers_ is only modified here, so
    // iterating it after the lock is safe.
    std::unordered_map<uint64_t, SurfaceState> states_snapshot;
    {
        std::lock_guard<std::mutex> lock(frame_mutex_);
        for (auto* surface : pending_surfaces_) {
            const auto surface_id = reinterpret_cast<uint64_t>(surface);
            if (!displayers_.contains(surface_id)) {
                CFW_LOG_INFO("DisplaySystem: Creating new displayer for surface {}", surface_id);
                displayers_.emplace(surface_id, HardwareDisplayer(surface));
            }
        }
        pending_surfaces_.clear();
        states_snapshot = surface_states_;
    }

    for (auto& [surface_id, displayer] : displayers_) {
        auto it = states_snapshot.find(surface_id);
        if (it == states_snapshot.end()) {
            continue;
        }

        auto& state = it->second;
        const bool has_optics = state.optics.image_handle != 0;
        const bool has_ui = state.ui.image_handle != 0;

        // [VDIAG-B5] Surface-binding probe: confirm whether the surface being composed
        // actually has an optics layer bound. A black screen with bg(optics)=0x0 means
        // this displayer's surface_id never received an OpticsFrameReadyEvent (mismatch
        // between the surface used for display vs. the surface Vision renders to).
        {
            static uint32_t s_b5_count = 0;
            // Log the first few, then every 120 UI frames, AND always log the first
            // 5 iterations where optics actually carries a handle. The previous
            // s_b5_count<8 gate only fired during early frames (before Vision started
            // publishing), so it never captured the loaded-scene compose path.
            static uint32_t s_b5_optics_seen = 0;
            const bool optics_present = state.optics.image_handle != 0;
            const bool optics_edge = optics_present && s_b5_optics_seen < 5;
            if (s_b5_count < 8 || optics_edge || (state.ui.frame_index % 120) == 0) {
                ++s_b5_count;
                if (optics_present) { ++s_b5_optics_seen; }
                CFW_LOG_INFO(
                    "DisplaySystem: [VDIAG-B5] compose-iter surface_id={} optics(handle={} {}x{} frame={}) ui(handle={} {}x{} frame={})",
                    surface_id,
                    state.optics.image_handle, state.optics.width, state.optics.height, state.optics.frame_index,
                    state.ui.image_handle, state.ui.width, state.ui.height, state.ui.frame_index);
            }
        }

        if (!has_optics && !has_ui) {
            continue;
        }

        // Acquire write handles for available layers
        SharedDataHub::ImageStorage::WriteHandle optics_frame;
        SharedDataHub::ImageStorage::WriteHandle ui_frame;
        if (has_optics) {
            optics_frame = SharedDataHub::instance().image_storage().acquire_write(state.optics.image_handle);
        }
        if (has_ui) {
            ui_frame = SharedDataHub::instance().image_storage().acquire_write(state.ui.image_handle);
        }

        // Resolve images: use producer image if available, transparent fallback otherwise.
        HardwareImage* optics_img_ptr = nullptr;
        HardwareExecutor* optics_exec_ptr = nullptr;
        if (has_optics && optics_frame) {
            optics_img_ptr = &optics_frame->image;
            optics_exec_ptr = &optics_frame->executor;
        }

        HardwareImage* ui_img_ptr = nullptr;
        HardwareExecutor* ui_exec_ptr = nullptr;
        if (has_ui && ui_frame) {
            ui_img_ptr = &ui_frame->image;
            ui_exec_ptr = &ui_frame->executor;
        }

        HardwareImage& bg_image = (optics_img_ptr && *optics_img_ptr) ? *optics_img_ptr : transparent_storage_;
        HardwareImage& fg_image = (ui_img_ptr && *ui_img_ptr) ? *ui_img_ptr : transparent_sampled_;

        // [VDIAG-B6] Resolve probe: distinguish "snapshot missing optics" from
        // "image_storage acquire failed" from "stored image invalid". Logged the
        // first few times optics is present so we capture the loaded-scene path.
        if (has_optics) {
            static uint32_t s_b6_count = 0;
            if (s_b6_count < 8) {
                ++s_b6_count;
                CFW_LOG_INFO(
                    "DisplaySystem: [VDIAG-B6] resolve: optics_handle={} acquire_ok={} stored_image_valid={} using_bg_optics={}",
                    state.optics.image_handle,
                    static_cast<bool>(optics_frame),
                    (optics_img_ptr ? static_cast<bool>(*optics_img_ptr) : false),
                    (optics_img_ptr && *optics_img_ptr));
            }
        }

        if (!bg_image || !fg_image) {
            continue;
        }

        compose_and_present(displayer,
                            state,
                            bg_image,
                            (optics_img_ptr && *optics_img_ptr) ? optics_exec_ptr : nullptr,
                            fg_image,
                            (ui_img_ptr && *ui_img_ptr) ? ui_exec_ptr : nullptr);

        // Write back the consumed signal so producers know when to safely reuse their image.
        if (has_optics && optics_frame) {
            optics_frame->consumed_executor = compositor_executor_;
        }
        if (has_ui && ui_frame) {
            ui_frame->consumed_executor = compositor_executor_;
        }
    }
}

bool DisplaySystem::ensure_composite_resources(uint32_t width, uint32_t height) {
    if (!composite_pipeline_ready_) {
        composite_pipeline_ready_ = (composite_pipeline_.getComputePipelineID() != 0);
        if (!composite_pipeline_ready_) {
            CFW_LOG_ERROR("DisplaySystem: Failed to create typed composite pipeline");
            return false;
        }
        CFW_LOG_INFO("DisplaySystem: Typed composite compute pipeline created");
    }

    if (composite_width_ != width || composite_height_ != height || !composite_output_) {
        composite_output_ = HardwareImage(width, height, ImageFormat::RGBA16_FLOAT, ImageUsage::StorageImage);
        if (!composite_output_) {
            CFW_LOG_ERROR("DisplaySystem: Failed to create composite output ({}x{})", width, height);
            return false;
        }
        composite_width_ = width;
        composite_height_ = height;
        CFW_LOG_INFO("DisplaySystem: Composite output image created ({}x{})", width, height);
    }

    return true;
}

void DisplaySystem::compose_and_present(HardwareDisplayer& displayer,
                                        SurfaceState& state,
                                        HardwareImage& optics_image,
                                        HardwareExecutor* optics_executor,
                                        HardwareImage& ui_image,
                                        HardwareExecutor* ui_executor) {
    if (state.ui.width == 0 || state.ui.height == 0) {
        return;
    }

    if (!ensure_composite_resources(state.ui.width, state.ui.height)) {
        return;
    }

    // bgImage & outputImage are StorageImage (set 2); fgImage is SampledImage (set 0).
    composite_pipeline_.pushConsts.bgImage = optics_image.storeDescriptor();
    composite_pipeline_.pushConsts.fgImage = ui_image.storeDescriptor();
    composite_pipeline_.pushConsts.outputImage = composite_output_.storeDescriptor();
    composite_pipeline_.pushConsts.outputWidth = state.ui.width;
    composite_pipeline_.pushConsts.outputHeight = state.ui.height;
    composite_pipeline_.pushConsts.bgWidth = std::max(state.optics.width, 1u);
    composite_pipeline_.pushConsts.bgHeight = std::max(state.optics.height, 1u);

    const uint32_t dispatch_x = (state.ui.width + 7u) / 8u;
    const uint32_t dispatch_y = (state.ui.height + 7u) / 8u;

    // [VDIAG-B4] Composite probe: a mismatch between the optics (bg) resolution and
    // the output resolution forces the shader to rescale. Dispatch is ceil-divided so
    // non-multiple-of-8 UI sizes still cover the right/bottom edge pixels.
    {
        static uint32_t s_vdiag_compose_count = 0;
        static uint32_t s_vdiag_compose_optics = 0;
        const bool b4_optics_present = state.optics.image_handle != 0;
        if (s_vdiag_compose_count < 5 || (b4_optics_present && s_vdiag_compose_optics < 5)) {
            ++s_vdiag_compose_count;
            if (b4_optics_present) { ++s_vdiag_compose_optics; }
            CFW_LOG_INFO(
                "DisplaySystem: [VDIAG-B4] compose: out={}x{} bg(optics)={}x{} dispatch={}x{}",
                state.ui.width, state.ui.height, state.optics.width, state.optics.height,
                dispatch_x, dispatch_y);
        }
    }

    // GPU sync: wait for each producer's rendering to finish before reading their images
    if (optics_executor) {
        compositor_executor_.wait(*optics_executor);
    }
    if (ui_executor) {
        compositor_executor_.wait(*ui_executor);
    }

    compositor_executor_ << composite_pipeline_(dispatch_x, dispatch_y, 1)
                         << compositor_executor_.commit();

    // After commit, producer images are no longer read — displayer only reads composite_output_
    displayer.wait(compositor_executor_) << composite_output_;
}

void DisplaySystem::shutdown() {
    CFW_LOG_NOTICE("DisplaySystem: Shutting down...");

    if (auto* event_bus = context()->event_bus()) {
        if (surface_changed_sub_id_ != 0) {
            event_bus->unsubscribe(surface_changed_sub_id_);
        }
        if (optics_frame_sub_id_ != 0) {
            event_bus->unsubscribe(optics_frame_sub_id_);
        }
        if (ui_frame_sub_id_ != 0) {
            event_bus->unsubscribe(ui_frame_sub_id_);
        }
    }

    composite_pipeline_ready_ = false;
    composite_output_ = HardwareImage();
    composite_pipeline_ = ComputePipeline<composite_comp_glsl>();

    surface_states_.clear();
    displayers_.clear();
    CFW_LOG_DEBUG("DisplaySystem: Shutdown complete");
}

}  // namespace Corona::Systems
