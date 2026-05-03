#pragma once

#include <corona/spatial/aabb.h>

#include <array>
#include <cstddef>
#include <functional>
#include <memory>
#include <span>
#include <utility>
#include <vector>

namespace Corona::Spatial {

/**
 * @brief 八叉树调参
 *
 * 该结构与 mechanics_system.cpp 中 file-local 实现的常量保持兼容，
 * 便于后续把物理系统的实现迁移到 SceneSystem 时无回归差异。
 */
struct OctreeConfig {
    int   max_depth            = 6;       ///< 最大递归深度
    int   max_objects_per_leaf = 4;       ///< 叶节点容量阈值，超过则尝试分裂
    float root_padding         = 0.01f;   ///< 根盒外扩，防边界物体跨层抖振
};

/**
 * @brief 通用模板化八叉树
 *
 * @tparam TPayload 叶节点存储的载荷类型，要求可拷贝/可移动且可比较（用于 dedupe）。
 *
 * 设计目标：
 * - 由 SceneSystem 在 update() 中独占重建（rebuild），其它系统只读查询；
 * - 当前版本仅实现 rebuild + 查询，增量 insert/remove 留给后续优化。
 *
 * 所有查询接口当前为骨架实现：rebuild 后返回所有 entry（暴力遍历）。
 * 后续在 M1.2 中替换为真正的递归剪枝。
 */
template <typename TPayload>
class Octree {
   public:
    struct Entry {
        TPayload payload;
        AABB     bounds;
    };

    explicit Octree(OctreeConfig cfg = {}) : cfg_(cfg) {}

    void clear() noexcept {
        entries_.clear();
        root_bounds_ = AABB{};
    }

    /**
     * @brief 全量重建八叉树
     * @param root      场景根 AABB（已含 padding）
     * @param entries   所有需要插入的载荷
     *
     * 当前实现：仅缓存条目；查询走暴力遍历。
     */
    void rebuild(const AABB& root, std::span<const Entry> entries) {
        root_bounds_ = root;
        entries_.assign(entries.begin(), entries.end());
        // TODO(M1.2): 构造真实的八叉树节点结构
    }

    [[nodiscard]] const AABB& root_bounds() const noexcept { return root_bounds_; }
    [[nodiscard]] std::size_t  size()        const noexcept { return entries_.size(); }
    [[nodiscard]] bool         empty()       const noexcept { return entries_.empty(); }

    // ============================================================
    // 查询接口（M1.2 之前为暴力实现）
    // ============================================================

    void query_aabb(const AABB& box, std::vector<TPayload>& out) const {
        for (const Entry& e : entries_) {
            if (e.bounds.overlaps(box)) {
                out.push_back(e.payload);
            }
        }
    }

    void query_sphere(const ktm::fvec3& center, float radius,
                      std::vector<TPayload>& out) const {
        const float r2 = radius * radius;
        for (const Entry& e : entries_) {
            // AABB 到球心的最近点距离平方
            float dx = std::max({e.bounds.min.x - center.x, 0.0f, center.x - e.bounds.max.x});
            float dy = std::max({e.bounds.min.y - center.y, 0.0f, center.y - e.bounds.max.y});
            float dz = std::max({e.bounds.min.z - center.z, 0.0f, center.z - e.bounds.max.z});
            if (dx * dx + dy * dy + dz * dz <= r2) {
                out.push_back(e.payload);
            }
        }
    }

    /**
     * @brief 自定义谓词查询（视锥剔除等可基于此封装）
     */
    template <typename Predicate>
    void query_if(Predicate&& pred, std::vector<TPayload>& out) const {
        for (const Entry& e : entries_) {
            if (pred(e.bounds)) out.push_back(e.payload);
        }
    }

    /**
     * @brief 收集所有可能碰撞的 payload 对（i<j，已 dedupe）
     */
    void collect_pairs(std::vector<std::pair<TPayload, TPayload>>& out) const {
        for (std::size_t i = 0; i < entries_.size(); ++i) {
            for (std::size_t j = i + 1; j < entries_.size(); ++j) {
                if (entries_[i].bounds.overlaps(entries_[j].bounds)) {
                    out.emplace_back(entries_[i].payload, entries_[j].payload);
                }
            }
        }
    }

    struct Stats {
        std::size_t entries        = 0;
        int         nodes          = 0;   // M1.2 后填入
        int         leaves         = 0;
        int         max_depth_used = 0;
    };

    [[nodiscard]] Stats stats() const noexcept {
        Stats s;
        s.entries = entries_.size();
        return s;
    }

   private:
    OctreeConfig       cfg_;
    AABB               root_bounds_{};
    std::vector<Entry> entries_;
};

}  // namespace Corona::Spatial
