#pragma once

#include <CabbageHardware.h>
#include <SDL3/SDL.h>
#include <imgui.h>
#include <include/internal/cef_types.h>

#include <memory>
#include <mutex>
#include <string>
#include <unordered_map>
#include <vector>

namespace Corona::Systems {
class VulkanBackend;
}

namespace Corona::Systems::UI {
class OffscreenCefClient;

inline constexpr ImTextureID k_invalid_texture_id = static_cast<ImTextureID>(0);

inline bool is_valid_texture_id(const ImTextureID texture_id) {
    return texture_id != k_invalid_texture_id;
}

struct DragRegion {
    float x, y, width, height;
};

// ============================================================================
// 浏览器标签页数据结构
// ============================================================================

struct BrowserTab {
    std::string name;
    std::string url;

    OffscreenCefClient* client = nullptr;
    // VkDescriptorSet texture_id = VK_NULL_HANDLE;
    ImTextureID texture_id = k_invalid_texture_id;

    int width = 800;
    int height = 600;

    // Docking 相关属性
    std::string docking_pos;        // 位置: "left", "right", "top", "bottom", "center"
    int dock_width = 0;             // 指定宽度，0 表示自动
    int dock_height = 0;            // 指定高度，0 表示自动
    bool dock_fixed = false;        // 是否固定位置
    bool dock_initialized = false;  // 是否已初始化 docking

    bool open = true;
    bool minimized = false;  // 新增：是否最小化
    bool needs_resize = false;
    bool buffer_dirty = false;
    bool has_focus = false;

    char url_buffer[1024] = "";
    std::vector<uint8_t> pixel_buffer;
    std::mutex mutex;  // 保护 pixel_buffer 和 buffer_dirty

    std::vector<DragRegion> drag_regions;
    bool drag_pending = false;
    ImVec2 drag_pending_start_pos;
    bool dragging_window = false;
    std::mutex drag_mutex;  // 确保线程安全
};

// ============================================================================
// 浏览器标签管理器
// ============================================================================

class BrowserManager {
   public:
    static BrowserManager& instance();

    int create_tab(const std::string& url, const std::string& path = "",
                   const std::string& docking_pos = "",
                   int dock_width = 0, int dock_height = 0,
                   bool dock_fixed = false);
    BrowserTab* get_tab(int tab_id);
    void remove_tab(int tab_id);
    void update_texture(int tab_id);
    void resize_tab(int tab_id, int width, int height);

    // 隐藏标签页（最小化）
    bool hide_tab(int tab_id, bool if_close = false);
    // 显示标签页（恢复）
    bool show_tab(int tab_id);

    // void set_vulkan_backend(VulkanBackend* backend);
    // VulkanBackend* get_vulkan_backend() const;

    [[nodiscard]] const std::unordered_map<int, std::unique_ptr<BrowserTab>>& get_tabs() const;
    std::unordered_map<int, std::unique_ptr<BrowserTab>>& get_tabs();

    void update();
    void close_all_tabs();

    // 设置主窗口指针
    void set_main_window(SDL_Window* window) { main_window_ = window; }
    void set_tab_drag_regions(int tab_id, const std::vector<DragRegion>& regions);

   private:
    BrowserManager() = default;
    SDL_Window* main_window_ = nullptr;
    ImTextureID create_browser_texture(int width, int height);
    void destroy_tab_texture(BrowserTab* tab);

    struct OwnedImage {
        HardwareImage image;
        uint32_t width = 0;
        uint32_t height = 0;
    };

    std::unordered_map<int, std::unique_ptr<BrowserTab>> tabs_;
    std::vector<int> tabs_to_close_;
    std::unordered_map<ImTextureID, OwnedImage> owned_images_;
    int tab_counter_ = 0;

    HardwareExecutor texture_executor_;
};

}  // namespace Corona::Systems::UI