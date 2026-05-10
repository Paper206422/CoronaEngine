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
        root_.reset();
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
        clear();
        root_bounds_ = root;
        entries_.assign(entries.begin(), entries.end());
        // TODO(M1.2): 构造真实的八叉树节点结构

        if (entries.empty()) {
            return;
        }

        root_ = std::make_unique<Node>();
        root_->bounds = root_bounds_;

        for (const Entry& e : entries_) {
            insert_recursive(*root_,e,0);
        }
    }

    [[nodiscard]] const AABB& root_bounds() const noexcept { return root_bounds_; }
    [[nodiscard]] std::size_t  size()        const noexcept { return entries_.size(); }
    [[nodiscard]] bool         empty()       const noexcept { return entries_.empty(); }

    // ============================================================
    // 查询接口（M1.2 之前为暴力实现）
    // ============================================================

    void query_aabb(const AABB& box, std::vector<TPayload>& out) const {
        if ( !root_ || !box.overlaps(root_bounds_)) {
            return;
        }

        query_aabb_recursive(*root_, box, out);
    }

    void query_sphere(const ktm::fvec3& center, float radius,
                      std::vector<TPayload>& out) const {
        if (!root_) {
            return;
        }

        float dx = std::max({root_bounds_.min.x - center.x, 0.0f, center.x - root_bounds_.max.x});
        float dy = std::max({root_bounds_.min.y - center.y, 0.0f, center.y - root_bounds_.max.y});
        float dz = std::max({root_bounds_.min.z - center.z, 0.0f, center.z - root_bounds_.max.z});
        if (dx * dx + dy * dy + dz * dz > radius * radius) {
            return;
        }

        query_sphere_recursive(*root_, center, radius, out);
    }

    /**
     * @brief 自定义谓词查询（视锥剔除等可基于此封装）
     */
    template <typename Predicate>
    void query_if(Predicate&& pred, std::vector<TPayload>& out) const {
        if ( !root_ || !pred(root_bounds_)) {
            return;
        }

        query_if_recursive(*root_, std::forward<Predicate>(pred), out);
    }

    /**
     * @brief 收集所有可能碰撞的 payload 对（i<j，已 dedupe）
     */
    void collect_pairs(std::vector<std::pair<TPayload, TPayload>>& out) const {
        if (!root_ || entries_.empty() < 2) {
            return;
        }

        std::vector<std::pair<TPayload, TPayload>> candidates;
        candidates.reserve(entries_.size()*4);

        collect_pairs_recursive(*root_,candidates);

        if (!candidates.empty()) {
            std::sort(candidates.begin(), candidates.end());
            auto last = std::unique(candidates.begin(), candidates.end());
            candidates.erase(last, candidates.end());
            out.swap(candidates);
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

        if (root_) {
            stats_recursive(*root_,0,s);
        }

        return s;
    }

   private:
    //八叉树节点结构
    struct Node {
        AABB bounds;
        std::vector<const Entry*> entries; //存储指向全局entries_的指针
        std::unique_ptr<std::array<Node,8>> children;

        [[nodiscard]] bool is_leaf() const noexcept {
            return children == nullptr;
        }
    };

    OctreeConfig       cfg_;
    AABB               root_bounds_{};
    std::vector<Entry> entries_;
    std::unique_ptr<Node> root_; //根节点

    // 递归插入条目到八叉树
    void insert_recursive(const Node& node,const Entry& entry,int depth) {
        if (!node.bounds.overlaps(entries_.bounds)) {
            return;
        }

        if (node.is_leaf()) {
            bool should_split = depth < cfg_.max_depth &&
                static_cast<int>(node.entries.size()) >= cfg_.max_objects_per_leaf;

            if (!should_split) {
                node.entries.push_back(&entry);
                return;
            }
            split_node(node);
        }

        for (int i = 0 ; i < 8 ; i ++ ) {
            insert_recursive((*node.children)[i],entry,depth+1);
        }
    }

    // 分裂节点为8个子节点
    void split_node(Node& node) {
        node.children = std::make_unique<std::array<Node,8>>();
        auto& children = *node.children;

        const ktm::fvec3 center = node.bounds.center();
        const auto& min = node.bounds.min;
        const auto& max = node.bounds.max;

        children[0].bounds.min = min;
        children[0].bounds.max = center;

        children[1].bounds.min = ktm::fvec3{center.x, min.y, min.z};
        children[1].bounds.max = ktm::fvec3{max.x, center.y, center.z};

        children[2].bounds.min = ktm::fvec3{min.x, center.y, min.z};
        children[2].bounds.max = ktm::fvec3{center.x, max.y, center.z};

        children[3].bounds.min = ktm::fvec3{center.x, center.y, min.z};
        children[3].bounds.max = ktm::fvec3{max.x, max.y, center.z};

        children[4].bounds.min = ktm::fvec3{min.x, min.y, center.z};
        children[4].bounds.max = ktm::fvec3{center.x, center.y, max.z};

        children[5].bounds.min = ktm::fvec3{center.x, min.y, center.z};
        children[5].bounds.max = ktm::fvec3{max.x, center.y, max.z};

        children[6].bounds.min = ktm::fvec3{min.x, center.y, center.z};
        children[6].bounds.max = ktm::fvec3{center.x, max.y, max.z};

        children[7].bounds.min = center;
        children[7].bounds.max = max;

        for (const Entry* e : node.entries) {
            for (int i = 0 ; i < 8 ; i ++ ) {
                if ( children[i].bounds.overlaps(e->bounds)) {
                    children[i].entries.push_back(e);
                }
            }
        }

        node.entries.clear();
    }

    // 递归查询AABB相交的条目
    void query_aabb_recursive(const Node& node,const AABB& box,
                            std::vector<TPayload>& out) const {
        if ( node.is_leaf()) {
            for (const Entry* e : node.entries) {
                if ( e->bounds.overlaps(box)) {
                    out.push_back(e->payload);
                }
            }
            return;
        }

        for (int i = 0 ; i < 8 ; i ++ ) {
            const Node& child = (*node.children)[i];
            if (box.overlaps(child.bounds)) {
                query_aabb_recursive(child,box,out);
            }
        }
    }

    // 递归查询球体相交的条目
    void query_sphere_recursive(const Node& node,const ktm::fvec3& center,float radius,
                                std::vector<TPayload>& out) const {
        if (node.is_leaf()) {
            const float r2 = radius * radius;
            for (const Entry* e : node.entries) {
                float dx = std::max({e->bounds.min.x - center.x, 0.0f, center.x - e->bounds.max.x});
                float dy = std::max({e->bounds.min.y - center.y, 0.0f, center.y - e->bounds.max.y});
                float dz = std::max({e->bounds.min.z - center.z, 0.0f, center.z - e->bounds.max.z});
                if (dx * dx + dy * dy + dz * dz <= r2 ) {
                    out.push_back(e->payload);
                }
            }
            return;
        }

        for (int i = 0 ; i < 8 ; i ++ ) {
            const Node& child = (*node.children)[i];
            float dx = std::max({child.bounds.min.x - center.x, 0.0f, center.x - child.bounds.max.x});
            float dy = std::max({child.bounds.min.y - center.y, 0.0f, center.y - child.bounds.max.y});
            float dz = std::max({child.bounds.min.z - center.z, 0.0f, center.z - child.bounds.max.z});
            if ( dx * dx + dy * dy + dz * dz <= radius * radius ) {
                query_sphere_recursive(child,center,radius,out);
            }
        }
    }

    // 递归查询满足谓词的条目
    template <typename Predicate>
    void query_if_recursive(const Node& node,Predicate&& pred,std::vector<TPayload>& out) const {
        if (node.is_leaf()) {
            for (const Entry* e : node.entries) {
                if (pred(e->bounds)) {
                    out.push_back(e->payload);
                }
            }
            return;
        }

        for (int i = 0 ; i < 8 ; i ++ ) {
            const Node& child = (*node.children)[i];
            if (pred(child.bounds)) {
                query_if_recursive(child,std::forward<Predicate>(pred),out);
            }
        }
    }

    // 递归收集所有可能碰撞的对
    void collect_pairs_recursive(const Node& node,
                            std::vector<std::pair<TPayload,TPayload>>& out) const {
        if (node.is_leaf()) {
            for (std::size_t i = 0 ; i < node.entries.size() ; i ++ ) {
                for (std::size_t j = i + 1; j < node.entries.size() ; j ++ ) {
                    const Entry* a = node.entries[i];
                    const Entry* b = node.entries[j];

                    if (a->payload < b->payload) {
                        out.emplace_back(a->payload,b->payload);
                    }else if ( b->payload < a->payload ) {
                        out.emplace_back(b->payload,a->payload);
                    }
                }
            }
            return;
        }

        for (int i = 0 ; i < 8 ; i ++ ) {
            collect_pair_recursive((*node.children)[i],out);
        }
    }

    // 递归收集统计信息
    void stats_recursive(const Node& node, int depth, Stats& s) const {
        s.nodes++;
        s.max_depth_used = std::max(s.max_depth_used,depth);

        if (node.is_leaf()) {
            s.leaves++;
            return;
        }

        for (int i = 0 ; i < 8 ; i ++ ) {
            stats_recursive((*node.children)[i],depth+1,s);
        }
    }
};

}  // namespace Corona::Spatial
