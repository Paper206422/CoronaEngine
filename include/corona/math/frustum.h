#pragma once

#include <corona/spatial/aabb.h>
#include <ktm/ktm.h>

#include <array>
#include <cmath>

namespace Corona {
struct CameraDevice;
}

namespace Corona::Math {

enum class Containment : std::uint8_t {
    Outside,
    Intersect,
    Inside,
};

/**
 * @brief 视锥体（六平面）
 *
 * 平面方程：ax + by + cz + d = 0，法线指向视锥**内**侧。
 * 提取自 view_proj 矩阵（Hartmann–Gribb），适配 Vulkan NDC（z ∈ [0,1]，Y 向下）。
 *
 * 本头文件保持轻量：from_camera 的实现放在 .cpp 里，避免在此 include
 * `<corona/shared_data_hub.h>`（带来 CabbageHardware 依赖）。
 */
class Frustum {
   public:
    Frustum() = default;

    /// 从 view_proj 矩阵提取六平面
    static Frustum from_view_proj(const ktm::fmat4x4& view_proj) noexcept;

    /// 从 CameraDevice 直接构造（实现见 frustum.cpp）
    static Frustum from_camera(const CameraDevice& cam) noexcept;

    /// 三态相交测试（Outside / Intersect / Inside）
    [[nodiscard]] Containment test(const Spatial::AABB& box) const noexcept;

    /// 简化二态：!= Outside
    [[nodiscard]] bool intersects(const Spatial::AABB& box) const noexcept {
        return test(box) != Containment::Outside;
    }

    [[nodiscard]] const std::array<ktm::fvec4, 6>& planes() const noexcept { return planes_; }

   private:
    std::array<ktm::fvec4, 6> planes_{};
};

}  // namespace Corona::Math
