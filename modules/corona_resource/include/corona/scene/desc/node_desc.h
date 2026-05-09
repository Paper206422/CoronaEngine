#pragma once

#include <string>
#include <string_view>

#include "json_helper.hpp"

namespace Corona::Resource::Scene {
/**
 * @brief 节点描述基类
 * @details 用于描述场景图中节点的基本信息和参数，支持序列化、哈希计算和参数管理
 */
struct NodeDesc {
   public:
    /// @brief 默认构造函数
    NodeDesc();

    /// @brief 虚析构函数
    virtual ~NodeDesc();

    /**
     * @brief 带类型的构造函数
     * @param type 节点类型
     */
    explicit NodeDesc(std::string_view type);

    /**
     * @brief 带类型和名称的构造函数
     * @param type 节点类型
     * @param name 节点名称
     */
    explicit NodeDesc(std::string_view type, std::string name);

    /**
     * @brief 获取类名
     * @return 类的类型名称字符串
     */
    [[nodiscard]] virtual const char* class_name() const noexcept;

    /**
     * @brief 获取文件名
     * @return 与节点关联的文件名，如果未设置则返回空字符串
     */
    [[nodiscard]] std::string file_name() const noexcept;

    /**
     * @brief 获取插件名称
     * @return 根据类型和子类型生成的插件名称
     */
    [[nodiscard]] std::string plugin_name() const noexcept;

    /**
     * @brief 获取参数的字符串表示
     * @return JSON 格式的参数字符串
     */
    [[nodiscard]] std::string parameter_string() const;

    /**
     * @brief 获取指定键的参数值
     * @param key 参数键名
     * @return 参数值的 JSON 对象，如果不存在则返回空对象
     */
    [[nodiscard]] JsonWrapper value(const std::string& key) const;

    /**
     * @brief 检查是否包含指定的参数键
     * @param key 参数键名
     * @return 如果包含该键则返回 true
     */
    [[nodiscard]] bool contains(const std::string& key) const;

    /**
     * @brief 获取参数的引用（可修改）
     * @param key 参数键名
     * @return 参数值的引用
     */
    [[nodiscard]] JsonWrapper& operator[](const std::string& key);

    /**
     * @brief 获取参数的常量引用
     * @param key 参数键名
     * @return 参数值的常量引用
     */
    [[nodiscard]] const JsonWrapper& operator[](const std::string& key) const;

    /**
     * @brief 相等性比较运算符
     * @param other 要比较的另一个节点描述
     * @return 如果两个节点的哈希值相等则返回 true
     */
    [[nodiscard]] bool operator==(const NodeDesc& other) const;

    /**
     * @brief 更新参数（左值引用版本）
     * @param params 要更新的参数对象
     */
    void update_parameters(const JsonWrapper& params);

    /**
     * @brief 更新参数（右值引用版本）
     * @param params 要更新的参数对象
     */
    void update_parameters(const JsonWrapper&& params);

    /**
     * @brief 设置参数值（模板函数）
     * @tparam Args 参数类型
     * @param key 参数键名
     * @param args 要设置的值
     */
    template <typename... Args>
    void set_value(const std::string& key, Args&&... args);

    /**
     * @brief 设置节点类型
     * @param type 新的节点类型
     */
    void set_type(std::string_view type) noexcept;

    /**
     * @brief 初始化节点（空参数）
     */
    void init();

    /**
     * @brief 从文本字符串初始化节点
     * @param text JSON 格式的参数文本
     */
    void init(const char* text);

    /**
     * @brief 从参数对象初始化节点
     * @param params 参数对象
     */
    virtual void init(const JsonWrapper& params);

    /**
     * @brief 计算节点的完整哈希值
     * @return 节点的哈希值
     * @details 使用缓存机制，只在首次调用或重置后重新计算
     */
    [[nodiscard]] std::uint64_t hash() const;

    /**
     * @brief 计算节点的拓扑哈希值
     * @return 节点的拓扑哈希值
     * @details 拓扑哈希只考虑节点的结构，不考虑具体参数值
     */
    [[nodiscard]] std::uint64_t topology_hash() const;

    /**
     * @brief 重置完整哈希值缓存
     */
    void reset_hash() const noexcept;

    /**
     * @brief 重置拓扑哈希值缓存
     */
    void reset_topology_hash() const noexcept;

   protected:
    /**
     * @brief 计算节点的哈希值（虚函数）
     * @return 计算得到的哈希值
     * @details 派生类可以重写此函数以自定义哈希计算逻辑
     */
    [[nodiscard]] virtual std::uint64_t compute_hash() const;

    /**
     * @brief 计算节点的拓扑哈希值（虚函数）
     * @return 计算得到的拓扑哈希值
     * @details 派生类可以重写此函数以自定义拓扑哈希计算逻辑
     */
    [[nodiscard]] virtual std::uint64_t compute_topology_hash() const;

   public:
    /// @brief 节点名称
    std::string name{""};
    /// @brief 节点子类型
    std::string sub_type{""};
    /// @brief 构造函数名称
    std::string construct_name{"constructor"};

   protected:
    /// @brief 节点类型（字符串视图）
    std::string_view type_{""};
    /// @brief 节点参数（JSON 对象）
    JsonWrapper params_{};

   private:
    /// @brief 是否已计算完整哈希值的原子标志
    mutable bool is_computed_hash_{false};
    /// @brief 是否已计算拓扑哈希值的原子标志
    mutable bool is_computed_topology_hash_{false};
    /// @brief 缓存的完整哈希值
    mutable std::uint64_t cached_hash_{0};
    /// @brief 缓存的拓扑哈希值
    mutable std::uint64_t cached_topology_hash_{0};
};

}  // namespace Corona::Resource::Scene

template <typename... Args>
void Corona::Resource::Scene::NodeDesc::set_value(const std::string& key, Args&&... args) {
    params_[key] = JsonWrapper(std::forward<Args>(args)...);
}