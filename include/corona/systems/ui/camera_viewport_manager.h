#pragma once

#include <cstdint>
#include <mutex>
#include <optional>
#include <string>
#include <unordered_map>
#include <vector>

namespace Corona::Systems::UI {

struct CameraViewportRecord {
    std::string scene_id;
    std::string camera_id;
    std::uintptr_t camera_handle{};
    int tab_id{-1};
    void* surface{};
    int x{120};
    int y{120};
    int width{960};
    int height{540};
    int render_width{960};
    int render_height{540};
};

class CameraViewportManager {
   public:
    static CameraViewportManager& instance();

    bool register_view(std::string scene_id, std::string camera_id,
                       std::uintptr_t camera_handle, int tab_id);
    bool bind_surface(int tab_id, void* surface, int x, int y, int width, int height);
    bool update_layout(int tab_id, int x, int y, int width, int height);
    bool unregister_view(int tab_id, bool preserve_open);

    [[nodiscard]] bool is_camera_view(int tab_id) const;
    [[nodiscard]] std::optional<CameraViewportRecord> find_by_tab(int tab_id) const;
    [[nodiscard]] std::optional<CameraViewportRecord> find_by_camera(
        const std::string& scene_id, const std::string& camera_id) const;
    [[nodiscard]] std::vector<int> tabs_for_scene(const std::string& scene_id) const;

   private:
    CameraViewportManager() = default;

    mutable std::mutex mutex_;
    std::unordered_map<int, CameraViewportRecord> views_;
};

}  // namespace Corona::Systems::UI
