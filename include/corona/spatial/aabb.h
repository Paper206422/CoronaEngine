#pragma once

#include <ktm/ktm.h>

#include <algorithm>

namespace Corona::Spatial {

/**
 * @brief 轴对齐包围盒（World/Local 复用）
 *
 * 约定：min <= max（逐分量）。空盒可由 invalid() 表达（min > max）。
 */
struct AABB {
    ktm::fvec3 min{0.0f, 0.0f, 0.0f};
    ktm::fvec3 max{0.0f, 0.0f, 0.0f};

    [[nodiscard]] bool valid() const noexcept {
        return min.x <= max.x && min.y <= max.y && min.z <= max.z;
    }

    [[nodiscard]] ktm::fvec3 center() const noexcept {
        return ktm::fvec3{(min.x + max.x) * 0.5f,
                          (min.y + max.y) * 0.5f,
                          (min.z + max.z) * 0.5f};
    }

    [[nodiscard]] ktm::fvec3 extent() const noexcept {
        return ktm::fvec3{(max.x - min.x) * 0.5f,
                          (max.y - min.y) * 0.5f,
                          (max.z - min.z) * 0.5f};
    }

    [[nodiscard]] bool overlaps(const AABB& o) const noexcept {
        return (min.x <= o.max.x && max.x >= o.min.x) &&
               (min.y <= o.max.y && max.y >= o.min.y) &&
               (min.z <= o.max.z && max.z >= o.min.z);
    }

    [[nodiscard]] bool contains(const ktm::fvec3& p) const noexcept {
        return p.x >= min.x && p.x <= max.x &&
               p.y >= min.y && p.y <= max.y &&
               p.z >= min.z && p.z <= max.z;
    }

    [[nodiscard]] AABB merged(const AABB& o) const noexcept {
        AABB r;
        r.min.x = std::min(min.x, o.min.x);
        r.min.y = std::min(min.y, o.min.y);
        r.min.z = std::min(min.z, o.min.z);
        r.max.x = std::max(max.x, o.max.x);
        r.max.y = std::max(max.y, o.max.y);
        r.max.z = std::max(max.z, o.max.z);
        return r;
    }

    [[nodiscard]] AABB expanded(float pad) const noexcept {
        AABB r;
        r.min = ktm::fvec3{min.x - pad, min.y - pad, min.z - pad};
        r.max = ktm::fvec3{max.x + pad, max.y + pad, max.z + pad};
        return r;
    }
};

}  // namespace Corona::Spatial
