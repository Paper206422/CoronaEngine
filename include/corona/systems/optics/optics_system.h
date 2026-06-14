#pragma once

#include <Horizon.h>
#include <corona/events/optics_system_events.h>
#include <corona/kernel/event/i_event_bus.h>
#include <corona/kernel/event/i_event_stream.h>
#include <corona/kernel/system/system_base.h>

#include <atomic>
#include <cstdint>
#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <unordered_map>
#include <vector>

// 前向声明 Hardware 结构体
struct Hardware;

namespace Corona::Systems {

#ifdef CORONA_ENABLE_VISION
namespace Vision {
struct VisionBuildResult;  // 定义见 vision/vision_geometry_adapter.h
class VisionZeroCopyBridge;  // 定义见 vision/vision_zero_copy_bridge.h
}  // namespace Vision
#endif

/**
 * @brief 光学系统 (Optics System)
 *
 * 负责场景光学渲染、光线追踪、GPU 资源管理和渲染管线控制。
 * 运行在独立线程，以 120 FPS 渲染场景。
 */

/// 渲染后端枚举
enum class RenderBackend : int {
    Native = 0,  ///< 默认 Vulkan/光栅化管线
    Vision = 1,  ///< Vision CUDA 路径追踪后端
};

class OpticsSystem : public Kernel::SystemBase {
   public:
    OpticsSystem();
    ~OpticsSystem() override;

    // ========================================
    // ISystem 接口实现
    // ========================================

    std::string_view get_name() const override {
        return "Optics";
    }

    int get_priority() const override {
        return 90;  // 高优先级，在显示系统之后初始化
    }

    /**
     * @brief 初始化光学系统
     * @param ctx 系统上下文
     * @return 初始化成功返回 true
     */
    bool initialize(Kernel::ISystemContext* ctx) override;

    /**
     * @brief 每帧渲染
     *
     * 在独立线程中调用，执行场景光学渲染
     */
    void update() override;

    /**
     * @brief 关闭光学系统
     *
     * 清理所有 GPU 资源和渲染管线
     */
    void shutdown() override;

   private:
    bool initialize_vision_backend_if_enabled();
    bool initialize_hardware_resources();
    bool initialize_render_pipelines();

    void ensure_camera_render_resources(uint32_t width, uint32_t height);
    void optics_pipeline(float frame_count, uint64_t frame_index);
    void process_pending_screenshots(std::uintptr_t camera_handle, HardwareImage& render_target);
#ifdef CORONA_ENABLE_VISION
    // Vision 相关私有方法（在 CORONA_ENABLE_VISION 宏保护下实现）
    bool init_vision_lazy();  ///< 首次切换到 Vision 时的 lazy 初始化
    void run_vision_frame(float frame_count, uint64_t frame_index);

    /// Vision 场景来源：引擎构建（默认，随 SharedDataHub 动态同步）或外部文件
    /// （独立模式，导入期间禁用动态同步 / 相机对齐，使用场景自带 sensor）。
    enum class VisionSceneSource { EngineBuilt, ExternalFile };
    VisionSceneSource vision_scene_source_{VisionSceneSource::EngineBuilt};

    /// 渲染线程起始处消费：若存在 pending 加载请求则切换 Vision 场景。
    /// 仅在 Vision 已初始化后执行；空路径表示卸载外部场景、回到引擎构建场景。
    void apply_pending_vision_scene_load();

    /// 从磁盘 .json 导入一个 Vision 场景并带到可渲染状态（替换全局
    /// renderPipeline）。失败返回 false 且不改动现有 pipeline。
    bool load_external_vision_scene(const std::string& scene_path);

    /// 计算当前 SharedDataHub 场景的轻量签名，用于检测动态变化
    /// （几何拓扑 / transform / 材质参数 / materialColor / visible）。
    std::size_t compute_vision_scene_signature() const;

    /// 以"全量重建"方式把当前场景数据重新同步到 Vision：
    /// build_vision_geometry → scene.prepare → prepare_geometry → invalidate。
    /// 复用现有 pipeline（材质类型固定，无需重编译着色器），并通过
    /// scene.prepare() 内部的 remove_unused_elements() 回收旧材质，避免累积泄漏。
    /// 返回本次重建的统计结果，供去抖/重试逻辑区分"空场景"与"数据未就绪"。
    Vision::VisionBuildResult rebuild_vision_scene();

    /// 去抖检测：若签名变化则触发（延迟）重建，覆盖导入/导出/参数调整等动态操作。
    void sync_vision_dynamic_scene();
#endif  // CORONA_ENABLE_VISION
    struct ActorPickRequest {
        std::uintptr_t pick_handle{0};
        std::uint32_t x{0};
        std::uint32_t y{0};
    };
    std::optional<ActorPickRequest> take_pending_actor_pick(std::uintptr_t camera_handle);
    void complete_actor_pick(const ActorPickRequest& request,
                             const std::vector<std::uintptr_t>& scene_actor_handles);

    // ========================================================================
    // Per-surface render output (改造1: optics 输出 per-surface 化)
    // ========================================================================
    // 每个被绑定到某个 surface 的相机拥有独立的最终输出图与共享存储句柄，
    // 这样逐相机遍历时不再互相覆盖；DisplaySystem 也已按 surface 独立合成。
    // Pass 1 scene 与 Pass 2 UI 使用各自的 visibility/depth 中间产物。
    struct SurfaceRenderTarget {
        HardwareImage final_output;        ///< 该 surface 专属的 RGBA16F 最终输出
        HardwareImage ui_overlay;          ///< Pass 2 camera-follow actor overlay
        HardwareImage composite_output;    ///< Optics-internal scene+overlay result
        std::uintptr_t image_handle = 0;   ///< 该 surface 专属的 image_storage 句柄
        uint32_t width = 0;                ///< 该输出图当前分辨率
        uint32_t height = 0;
        uint64_t last_used_frame = 0;      ///< 最近一次被渲染的帧号，用于空闲回收
    };

    /// 取得（必要时创建/扩缩）给定 surface 的渲染目标，并刷新 last_used_frame。
    /// width/height 为本次相机分辨率；surface 不可为 nullptr。
    SurfaceRenderTarget& acquire_surface_target(void* surface, uint32_t width,
                                                uint32_t height, uint64_t frame_index);

    /// 回收连续多帧未被任何相机使用的 surface 目标（释放 GPU 图与存储句柄），
    /// 应对“任意多个、自由开关”的视口生命周期，避免长期累积泄漏。
    void evict_idle_surface_targets(uint64_t frame_index);

    std::unordered_map<void*, SurfaceRenderTarget> surface_targets_;
    /// 空闲多少帧后回收一个 surface 目标（约 2s @120fps）。
    static constexpr uint64_t kSurfaceTargetIdleEvictFrames = 240;

    // 无 surface 的离屏相机（仅截图，不显示）继续共用一张离屏图：截图在渲染后
    // 同步处理，逐相机串行，无需 per-surface。
    HardwareImage offscreen_image_;
    uint32_t offscreen_w_{0}, offscreen_h_{0};

    std::unique_ptr<Hardware> hardware_;

    // Vision 后端状态
#ifdef CORONA_ENABLE_VISION
    // Zero-copy path: shares Vision's pre-tonemap linear color buffer with Vulkan
    // (CUDA exported buffer -> imported HardwareBuffer) and resolves it via the
    // vision_resolve compute pass. This is the sole display path for Vision frames;
    // the previous GPU->CPU->GPU readback (download float4 -> float_to_half -> upload)
    // has been removed.
    std::unique_ptr<Vision::VisionZeroCopyBridge> vision_zero_copy_bridge_;

    // 启用 Vision 编译时，首帧 update() 检测到 pending != current 会自动触发
    // init_vision_lazy() 切换到 Vision；若初始化失败仍会回退 Native。
    std::atomic<int> pending_backend_{static_cast<int>(RenderBackend::Vision)};
#else
    std::atomic<int> pending_backend_{static_cast<int>(RenderBackend::Native)};
#endif
    RenderBackend current_backend_{RenderBackend::Native};
    bool vision_initialized_{false};
    std::uintptr_t last_render_cam_handle_{0};
    uint32_t consecutive_vision_failures_{0};
    bool has_last_vision_frame_{false};
    uint32_t last_vision_frame_width_{0};
    uint32_t last_vision_frame_height_{0};

    // ---- Vision 动态场景同步（脏标记 + 去抖全量重建）----
    std::size_t vision_applied_signature_{0};   ///< 已同步到 Vision 的场景签名基线
    std::size_t vision_pending_signature_{0};   ///< 最近一次检测到的（可能仍在变化的）签名
    uint32_t vision_stable_frames_{0};          ///< 签名保持稳定的连续帧数，用于去抖
    static constexpr uint32_t kVisionRebuildDebounceFrames = 3;  ///< 稳定该帧数后才重建

    // 当一次重建检测到"有候选物体但 0 实例"（数据尚未就绪）时，不锁定签名并在
    // 后续帧重试，直到数据就绪或达到上限后兜底接受，避免每帧空转重建。
    uint32_t vision_rebuild_retries_{0};        ///< 数据未就绪导致的连续重试次数
    static constexpr uint32_t kVisionRebuildMaxRetries = 30;  ///< 重试上限（约 0.5s @60fps）

    // ---- Vision 外部场景加载（跨线程：事件写路径，渲染线程消费）----
    // VisionSceneLoadEvent 只携带路径写入此处；实际 import 在 run_vision_frame
    // 起始的渲染线程执行，避免在 Python/CEF 线程触碰 CUDA pipeline。
    std::mutex vision_scene_load_mutex_;
    std::optional<std::string> pending_vision_scene_load_;

    struct PendingScreenshot {
        std::uintptr_t camera_handle = 0;
        std::string file_path;
        std::shared_ptr<std::promise<bool>> completion_promise;
    };
    std::vector<PendingScreenshot> pending_screenshots_;
    std::mutex screenshot_mutex_;
    Kernel::EventId screenshot_request_sub_id_ = 0;
    Kernel::EventId backend_switch_sub_id_ = 0;
    Kernel::EventId vision_scene_load_sub_id_ = 0;
};

}  // namespace Corona::Systems
