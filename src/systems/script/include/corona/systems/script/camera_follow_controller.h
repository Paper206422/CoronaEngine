#pragma once

#include <ktm/ktm.h>

#include <cstdint>

namespace Corona::Systems {

class CameraFollowController {
   public:
    static CameraFollowController& instance();

    CameraFollowController(const CameraFollowController&) = delete;
    CameraFollowController& operator=(const CameraFollowController&) = delete;
    CameraFollowController(CameraFollowController&&) = delete;
    CameraFollowController& operator=(CameraFollowController&&) = delete;

    void set_target(std::uintptr_t actor_handle, std::uintptr_t camera_handle,
                    float offset_x, float offset_y, float offset_z);
    void clear_target();
    bool is_active() const;

    void update(float delta_time);

    void inject_key(int vk_code, bool down);
    void inject_rmb(bool down, int screen_x, int screen_y);

   private:
    CameraFollowController() = default;

    void update_wasd(ktm::fvec3& obj_pos, const ktm::fvec3& offset);
    void update_rmb_orbit(ktm::fvec3& obj_pos, const ktm::fvec3& offset);
    void update_camera(const ktm::fvec3& obj_pos, const ktm::fvec3& offset);

    static ktm::fvec3 normalize(const ktm::fvec3& v);
    static ktm::fvec3 cross(const ktm::fvec3& a, const ktm::fvec3& b);

    bool active_{false};
    std::uintptr_t actor_handle_{0};
    std::uintptr_t camera_handle_{0};
    ktm::fvec3 offset_{0.0f, 0.0f, 2.0f};
    bool camera_look_at_{true};

    bool rmb_down_{false};
    int prev_mouse_x_{0};
    int prev_mouse_y_{0};

    float elapsed_since_last_log_{0.0f};
};

}  // namespace Corona::Systems
