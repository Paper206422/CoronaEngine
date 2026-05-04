#pragma once

#include <CabbageHardware.h>
#include <corona/events/display_system_events.h>
#include <corona/kernel/event/i_event_bus.h>
#include <corona/kernel/event/i_event_stream.h>
#include <corona/kernel/system/system_base.h>
#include <corona/shader_include.h>
// clang-format off
#include GLSL(../../../../assets/shaders/composite.comp.glsl)
// clang-format on

#include <cstdint>
#include <memory>
#include <mutex>
#include <unordered_map>
#include <vector>

namespace Corona::Systems {
/**
 * @brief Display system
 *
 * Manages windows, input events, and display devices.
 * Runs on a dedicated thread at 120 FPS for responsive input handling.
 * Receives Optics and UI layers, composites them before presenting.
 */
class DisplaySystem : public Kernel::SystemBase {
   public:
    DisplaySystem() {
        set_target_fps(120);
    }

    ~DisplaySystem() override = default;

    // ========================================
    // ISystem interface
    // ========================================

    std::string_view get_name() const override {
        return "Display";
    }

    int get_priority() const override {
        return 100;
    }

    bool initialize(Kernel::ISystemContext* ctx) override;
    void update() override;
    void shutdown() override;

   private:
    struct PendingLayer {
        std::uintptr_t image_handle = 0;
        uint64_t frame_index = 0;
        uint32_t width = 0;
        uint32_t height = 0;
    };

    struct SurfaceState {
        PendingLayer optics;
        PendingLayer ui;
    };

    void compose_and_present(HardwareDisplayer& displayer,
                             SurfaceState& state,
                             HardwareImage& optics_image,
                             HardwareExecutor* optics_executor,
                             HardwareImage& ui_image,
                             HardwareExecutor* ui_executor);
    bool ensure_composite_resources(uint32_t width, uint32_t height);

    Kernel::EventId surface_changed_sub_id_ = 0;
    Kernel::EventId optics_frame_sub_id_ = 0;
    Kernel::EventId ui_frame_sub_id_ = 0;

    // Protects displayers_ and surface_states_ against concurrent access
    // from EventBus handlers (Optics thread, main thread) and update() (Display thread)
    std::mutex frame_mutex_;

    std::unordered_map<uint64_t, HardwareDisplayer> displayers_;
    std::unordered_map<uint64_t, SurfaceState> surface_states_;
    std::vector<void*> pending_surfaces_;  ///< Surfaces awaiting displayer creation (deferred to update thread)

    // Compositing resources
    ComputePipeline<composite_comp_glsl> composite_pipeline_;
    HardwareExecutor compositor_executor_;
    HardwareImage composite_output_;
    HardwareImage transparent_storage_;  ///< 1x1 transparent StorageImage fallback (missing Optics bg)
    HardwareImage transparent_sampled_;  ///< 1x1 transparent SampledImage fallback (missing UI fg)
    uint32_t composite_width_ = 0;
    uint32_t composite_height_ = 0;
    bool composite_pipeline_ready_ = false;
};
}  // namespace Corona::Systems
