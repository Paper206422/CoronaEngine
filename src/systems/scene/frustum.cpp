#include <corona/math/frustum.h>
#include <corona/shared_data_hub.h>

#include <cmath>

namespace Corona::Math {

namespace {

inline ktm::fvec4 normalize_plane(const ktm::fvec4& p) noexcept {
    const float len = std::sqrt(p.x * p.x + p.y * p.y + p.z * p.z);
    if (len <= 0.0f) {
        return p;
    }
    const float inv = 1.0f / len;
    return ktm::fvec4{p.x * inv, p.y * inv, p.z * inv, p.w * inv};
}

}  // namespace

Frustum Frustum::from_view_proj(const ktm::fmat4x4& m) noexcept {
    // ktm 默认列主序：m[col][row]。row(i) = (m[0][i], m[1][i], m[2][i], m[3][i])
    const auto row = [&](int i) {
        return ktm::fvec4{m[0][i], m[1][i], m[2][i], m[3][i]};
    };

    const ktm::fvec4 r0 = row(0);
    const ktm::fvec4 r1 = row(1);
    const ktm::fvec4 r2 = row(2);
    const ktm::fvec4 r3 = row(3);

    Frustum f;
    f.planes_[0] = normalize_plane(ktm::fvec4{r3.x + r0.x, r3.y + r0.y, r3.z + r0.z, r3.w + r0.w});  // Left
    f.planes_[1] = normalize_plane(ktm::fvec4{r3.x - r0.x, r3.y - r0.y, r3.z - r0.z, r3.w - r0.w});  // Right
    f.planes_[2] = normalize_plane(ktm::fvec4{r3.x + r1.x, r3.y + r1.y, r3.z + r1.z, r3.w + r1.w});  // Bottom
    f.planes_[3] = normalize_plane(ktm::fvec4{r3.x - r1.x, r3.y - r1.y, r3.z - r1.z, r3.w - r1.w});  // Top
    f.planes_[4] = normalize_plane(r2);                                                              // Near (Vulkan: z∈[0,1])
    f.planes_[5] = normalize_plane(ktm::fvec4{r3.x - r2.x, r3.y - r2.y, r3.z - r2.z, r3.w - r2.w});  // Far
    return f;
}

Frustum Frustum::from_camera(const CameraDevice& cam) noexcept {
    return from_view_proj(cam.compute_view_proj_matrix());
}

Containment Frustum::test(const Spatial::AABB& box) const noexcept {
    int inside_count = 0;
    for (const ktm::fvec4& p : planes_) {
        // p-vertex（最远点）和 n-vertex（最近点）
        ktm::fvec3 pv;
        pv.x = p.x >= 0.0f ? box.max.x : box.min.x;
        pv.y = p.y >= 0.0f ? box.max.y : box.min.y;
        pv.z = p.z >= 0.0f ? box.max.z : box.min.z;

        if (p.x * pv.x + p.y * pv.y + p.z * pv.z + p.w < 0.0f) {
            return Containment::Outside;  // 最远点都在外 → 整个盒在外
        }

        ktm::fvec3 nv;
        nv.x = p.x >= 0.0f ? box.min.x : box.max.x;
        nv.y = p.y >= 0.0f ? box.min.y : box.max.y;
        nv.z = p.z >= 0.0f ? box.min.z : box.max.z;
        if (p.x * nv.x + p.y * nv.y + p.z * nv.z + p.w >= 0.0f) {
            ++inside_count;  // 最近点也在内 → 该平面通过
        }
    }
    return inside_count == 6 ? Containment::Inside : Containment::Intersect;
}

}  // namespace Corona::Math
