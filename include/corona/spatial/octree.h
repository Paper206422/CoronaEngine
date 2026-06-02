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
 * 便于后续把物理系统的实现迁移到 GeometrySystem 时无回归差异。
 */
struct OctreeConfig {
    int   max_depth            = 6;       ///< 最大递归深度
    int   max_objects_per_leaf = 4;       ///< 叶节点容量阈值，超过则尝试分裂
    float root_padding         = 0.01f;   ///< 根盒外扩，防边界物体跨层抖振
};

/**
 * @brief 通用模板化八叉树（递归空间分区）
 *
 * @tparam TPayload 叶节点存储的载荷类型，要求可拷贝/可移动且可比较（用于 dedupe）。
 *
 * 由 GeometrySystem 在 update() 中独占重建（rebuild），其它系统只读查询。
 * 所有查询接口采用递归剪枝，节点 bounds 不相交时跳过整棵子树。
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
        root_.reset();
    }

    /**
     * @brief 全量重建八叉树
     * @param root      场景根 AABB（已含 padding）
     * @param entries   所有需要插入的载荷
     */
    void rebuild(const AABB& root, std::span<const Entry> entries) {
        root_ = std::make_unique<Node>();
        root_->bounds = root;
        for (const auto& e : entries) {
            insert(root_.get(), e, 0);
        }
    }

    [[nodiscard]] std::size_t size() const noexcept {
        return count_entries(root_.get());
    }

    [[nodiscard]] bool empty() const noexcept {
        return !root_ || count_entries(root_.get()) == 0;
    }

    [[nodiscard]] const OctreeConfig& config() const noexcept { return cfg_; }

    // ============================================================
    // 查询接口（递归 + 剪枝）
    // ============================================================

    void query_aabb(const AABB& box, std::vector<TPayload>& out) const {
        if (!root_) return;
        query_aabb_impl(root_.get(), box, out);
    }

    void query_sphere(const ktm::fvec3& center, float radius,
                      std::vector<TPayload>& out) const {
        if (!root_) return;
        query_sphere_impl(root_.get(), center, radius, out);
    }

    /**
     * @brief 自定义谓词查询（视锥剔除等可基于此封装）
     */
    template <typename Predicate>
    void query_if(Predicate&& pred, std::vector<TPayload>& out) const {
        if (!root_) return;
        query_if_impl(root_.get(), pred, out);
    }

    /**
     * @brief 收集所有可能碰撞的 payload 对（i<j，已去重）
     */
    void collect_pairs(std::vector<std::pair<TPayload, TPayload>>& out) const {
        if (!root_) return;
        collect_pairs_impl(root_.get(), out);
    }

    struct Stats {
        std::size_t entries        = 0;
        int         nodes          = 0;
        int         leaves         = 0;
        int         max_depth_used = 0;
    };

    [[nodiscard]] Stats stats() const noexcept {
        Stats s;
        gather_stats(root_.get(), s, 0);
        return s;
    }

   private:
    struct Node {
        AABB                                bounds;
        std::vector<Entry>                  entries;   // 叶节点=全部对象；内部节点=跨分割面的对象
        std::array<std::unique_ptr<Node>, 8> children{};
        bool                                is_leaf = true;
    };

    static int octant_index(const ktm::fvec3& center, const ktm::fvec3& point) {
        return (point.x >= center.x ? 1 : 0)
             | (point.y >= center.y ? 2 : 0)
             | (point.z >= center.z ? 4 : 0);
    }

    static AABB child_bounds(const AABB& parent, int octant) {
        ktm::fvec3 c = parent.center();
        AABB child;
        child.min.x = (octant & 1) ? c.x : parent.min.x;
        child.max.x = (octant & 1) ? parent.max.x : c.x;
        child.min.y = (octant & 2) ? c.y : parent.min.y;
        child.max.y = (octant & 2) ? parent.max.y : c.y;
        child.min.z = (octant & 4) ? c.z : parent.min.z;
        child.max.z = (octant & 4) ? parent.max.z : c.z;
        return child;
    }

    int fits_in_one_octant(const AABB& parent, const AABB& box) const {
        ktm::fvec3 c = parent.center();
        int idx_min = octant_index(c, box.min);
        int idx_max = octant_index(c, box.max);
        return (idx_min == idx_max) ? idx_min : -1;
    }

    void subdivide(Node* node, int depth) {
        for (int i = 0; i < 8; ++i) {
            node->children[i] = std::make_unique<Node>();
            node->children[i]->bounds = child_bounds(node->bounds, i);
        }
        node->is_leaf = false;

        std::vector<Entry> old_entries;
        old_entries.swap(node->entries);
        for (const auto& e : old_entries) {
            int idx = fits_in_one_octant(node->bounds, e.bounds);
            if (idx >= 0) {
                node->children[idx]->entries.push_back(e);
            } else {
                node->entries.push_back(e);
            }
        }
        // 递归分裂：检查每个子节点是否需要继续分裂
        for (int i = 0; i < 8; ++i) {
            // 条件1：该子节点的条目数 >= 阈值（超容量了）
            //        static_cast<int> 是把 size_t 转成 int，消除有符号/无符号比较的警告
            // 条件2：深度还没到上限（还能往下分）
            if (static_cast<int>(node->children[i]->entries.size()) >= cfg_.max_objects_per_leaf
                && depth + 1 < cfg_.max_depth) {
                // 对第 i 个子节点继续分裂，深度 +1
                subdivide(node->children[i].get(), depth + 1);
                }
        }
    }

    void insert(Node* node, const Entry& entry, int depth) {
        if (node->is_leaf) {
            if (static_cast<int>(node->entries.size()) < cfg_.max_objects_per_leaf
                || depth >= cfg_.max_depth) {
                node->entries.push_back(entry);
                return;
            }
            subdivide(node,depth);
        }

        int idx = fits_in_one_octant(node->bounds, entry.bounds);
        if (idx >= 0) {
            insert(node->children[idx].get(), entry, depth + 1);
        } else {
            node->entries.push_back(entry);
        }
    }

    static std::size_t count_entries(const Node* node) {
        if (!node) return 0;
        std::size_t n = node->entries.size();
        for (const auto& child : node->children) {
            if (child) n += count_entries(child.get());
        }
        return n;
    }

    // === 递归查询 ===

    static void query_aabb_impl(const Node* node, const AABB& box,
                                std::vector<TPayload>& out) {
        if (!node->bounds.overlaps(box)) return;
        for (const auto& e : node->entries) {
            if (e.bounds.overlaps(box)) out.push_back(e.payload);
        }
        for (const auto& child : node->children) {
            if (child) query_aabb_impl(child.get(), box, out);
        }
    }

    static void query_sphere_impl(const Node* node, const ktm::fvec3& center,
                                  float radius, std::vector<TPayload>& out) {
        float r2 = radius * radius;
        float dx = std::max({node->bounds.min.x - center.x, 0.0f, center.x - node->bounds.max.x});
        float dy = std::max({node->bounds.min.y - center.y, 0.0f, center.y - node->bounds.max.y});
        float dz = std::max({node->bounds.min.z - center.z, 0.0f, center.z - node->bounds.max.z});
        if (dx * dx + dy * dy + dz * dz > r2) return;

        for (const auto& e : node->entries) {
            dx = std::max({e.bounds.min.x - center.x, 0.0f, center.x - e.bounds.max.x});
            dy = std::max({e.bounds.min.y - center.y, 0.0f, center.y - e.bounds.max.y});
            dz = std::max({e.bounds.min.z - center.z, 0.0f, center.z - e.bounds.max.z});
            if (dx * dx + dy * dy + dz * dz <= r2) out.push_back(e.payload);
        }
        for (const auto& child : node->children) {
            if (child) query_sphere_impl(child.get(), center, radius, out);
        }
    }

    template <typename Predicate>
    static void query_if_impl(const Node* node, const Predicate& pred,
                              std::vector<TPayload>& out) {
        if (!pred(node->bounds)) return;
        for (const auto& e : node->entries) {
            if (pred(e.bounds)) out.push_back(e.payload);
        }
        for (const auto& child : node->children) {
            if (child) query_if_impl(child.get(), pred, out);
        }
    }

    static void query_straddle_in_subtree(const Entry& straddle, const Node* subtree,
                                           std::vector<std::pair<TPayload, TPayload>>& out) {
        if (!straddle.bounds.overlaps(subtree->bounds)) return;
        for (const auto& e : subtree->entries) {
            if (straddle.bounds.overlaps(e.bounds)) {
                auto a = straddle.payload;
                auto b = e.payload;
                out.emplace_back(a < b ? a : b, a < b ? b : a);
            }
        }
        if (subtree->is_leaf) return;
        for (const auto& child : subtree->children) {
            if (child) query_straddle_in_subtree(straddle, child.get(), out);
        }
    }

    // ============================================================================
    // compare_subtrees() —— 跨子树碰撞检测
    // ============================================================================
    //检查两棵子树的条目之间是否有 AABB 重叠。
    static void compare_subtrees(const Node* a, const Node* b,
                                  std::vector<std::pair<TPayload, TPayload>>& out) {
        if (!a->bounds.overlaps(b->bounds)) return;

        for (const auto& ea : a->entries) {
            for (const auto& eb : b->entries) {
                if (ea.bounds.overlaps(eb.bounds)) {
                    auto pa = ea.payload;
                    auto pb = eb.payload;
                    out.emplace_back(pa < pb ? pa : pb, pa < pb ? pb : pa);
                }
            }
        }
        // A的跨面条目 vs B的深层子节点
        for (const auto& ea : a->entries) {
            for (const auto& cb : b->children) {
                if (cb) query_straddle_in_subtree(ea, cb.get(), out);
            }
        }
        // B的跨面条目 vs A的深层子节点
        for (const auto& eb : b->entries) {
            for (const auto& ca : a->children) {
                if (ca) query_straddle_in_subtree(eb, ca.get(), out);
            }
        }
        if (a->is_leaf && b->is_leaf) return;

        if (!a->is_leaf && !b->is_leaf) {
            for (const auto& ca : a->children) {
                if (!ca) continue;
                for (const auto& cb : b->children) {
                    if (!cb) continue;
                    compare_subtrees(ca.get(), cb.get(), out);
                }
            }
        }
        else if (!a->is_leaf) {
            for (const auto& ca : a->children) {
                if (ca) compare_subtrees(ca.get(), b, out);
            }
        }
        else {
            for (const auto& cb : b->children) {
                if (cb) compare_subtrees(a, cb.get(), out);
            }
        }
    }


    static void collect_pairs_impl(const Node* node,
                                   std::vector<std::pair<TPayload, TPayload>>& out) {
        if (!node) return;

        if (node->is_leaf) {
            for (std::size_t i = 0; i < node->entries.size(); ++i) {
                for (std::size_t j = i + 1; j < node->entries.size(); ++j) {
                    if (node->entries[i].bounds.overlaps(node->entries[j].bounds)) {
                        auto a = node->entries[i].payload;
                        auto b = node->entries[j].payload;
                        out.emplace_back(a < b ? a : b, a < b ? b : a);
                    }
                }
            }
            return;
        }

        // 跨分割条目间的对
        for (std::size_t i = 0; i < node->entries.size(); ++i) {
            for (std::size_t j = i + 1; j < node->entries.size(); ++j) {
                if (node->entries[i].bounds.overlaps(node->entries[j].bounds)) {
                    auto a = node->entries[i].payload;
                    auto b = node->entries[j].payload;
                    out.emplace_back(a < b ? a : b, a < b ? b : a);
                }
            }
        }

        // 跨分割条目 vs 每个子树的条目
        for (const auto& straddle : node->entries) {
            for (const auto& child : node->children) {
                if (child) {
                    query_straddle_in_subtree(straddle, child.get(), out);
                }
            }
        }

        // 不同子树条目之间的对（边界接触）
        for (int ci = 0; ci < 8; ++ci) {
            if (!node->children[ci]) continue;  // 跳过不存在的子节点
            for (int cj = ci + 1; cj < 8; ++cj) {
                if (!node->children[cj]) continue;  // 跳过不存在的子节点
                // 递归比较两棵子树之间的碰撞对
                compare_subtrees(node->children[ci].get(), node->children[cj].get(), out);
            }
        }

        // 递归子节点
        for (const auto& child : node->children) {
            if (child) collect_pairs_impl(child.get(), out);
        }
    }

    static void gather_stats(const Node* node, Stats& s, int depth) {
        if (!node) return;
        s.entries += node->entries.size();
        ++s.nodes;
        s.max_depth_used = std::max(s.max_depth_used, depth);
        if (node->is_leaf) {
            ++s.leaves;
        } else {
            for (const auto& child : node->children) {
                if (child) gather_stats(child.get(), s, depth + 1);
            }
        }
    }

    OctreeConfig            cfg_;
    std::unique_ptr<Node>   root_;
};

}  // namespace Corona::Spatial