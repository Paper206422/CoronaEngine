#pragma once
#include <oneapi/tbb/task_group.h>

#include <future>

#include "parser_registry.h"
#include "resource.h"
#include "resource_cache.h"

namespace Corona::Resource {

/**
 * @brief 资源管理器类（单例模式）
 *
 * 负责资源的加载、卸载、缓存、导入、导出以及读写操作。
 * 支持同步和异步操作，并使用 TBB 进行并发任务管理。
 */
class ResourceManager final {
   public:
    /**
     * @brief 获取单例实例
     *
     * @return ResourceManager& 资源管理器实例的引用
     */
    static ResourceManager& get_instance();

    /**
     * @brief 删除拷贝构造函数
     */
    ResourceManager(const ResourceManager&) = delete;

    /**
     * @brief 删除拷贝赋值操作符
     */
    ResourceManager& operator=(const ResourceManager&) = delete;

    /**
     * @brief 注册资源解析器
     *
     * @tparam Parser 解析器类型
     * @tparam Args 构造函数参数类型
     * @param args 传递给 Parser 构造函数的参数
     * @return true 注册成功
     * @return false 注册失败
     */
    template <typename Parser, typename... Args>
    bool register_parser(Args&&... args);

    /**
     * @brief 注册已创建的解析器实例
     * @param parser 解析器实例
     * @return true 注册成功
     * @return false 注册失败
     */
    bool register_parser(std::shared_ptr<IParser> parser);

    /**
     * @brief 同步导入资源
     *
     * @param path 资源路径
     * @return TResourceID 资源ID，如果失败返回 IResource::INVALID_UID
     */
    TResourceID import_sync(const std::filesystem::path& path);

    /**
     * @brief 异步导入资源
     *
     * @param path 资源路径
     * @return std::future<TResourceID> 包含资源ID的future对象
     */
    std::future<TResourceID> import_async(const std::filesystem::path& path);

    /**
     * @brief 同步导出资源
     *
     * @param rid 资源ID
     * @param path 导出路径
     * @return true 导出成功
     * @return false 导出失败
     */
    bool export_sync(TResourceID rid, const std::filesystem::path& path);

    /**
     * @brief 异步导出资源
     *
     * @param rid 资源ID
     * @param path 导出路径
     * @return std::future<bool> 包含导出结果的future对象
     */
    std::future<bool> export_async(TResourceID rid, const std::filesystem::path& path);

    /**
     * @brief 获取资源读取句柄
     *
     * 尝试获取资源的共享锁。如果资源未就绪，返回无效句柄。
     *
     * @param rid 资源ID
     * @return ResourceReadHandle<T> 资源读取句柄
     */
    template <typename T = IResource>
    ReadHandle<T> acquire_read(TResourceID rid) {
        return resource_cache_.acquire_read<T>(rid);
    }

    /**
     * @brief 获取资源写入句柄
     *
     * 尝试获取资源的独占锁。如果资源未就绪，返回无效句柄。
     *
     * @param rid 资源ID
     * @return ResourceWriteHandle<T> 资源写入句柄
     */
    template <typename T = IResource>
    WriteHandle<T> acquire_write(TResourceID rid) {
        return resource_cache_.acquire_write<T>(rid);
    }

    /**
     * @brief 移除资源缓存
     *
     * @param rid 资源ID
     * @return true 移除成功
     * @return false 移除失败（资源不存在）
     */
    bool remove_cache(TResourceID rid);

    /**
     * @brief 异步移除资源缓存
     * @param rid 资源ID
     * @return 包含移除结果的future对象
     */
    std::future<bool> remove_cache_async(TResourceID rid);

    /**
     * @brief 添加已加载的资源到缓存
     *
     * 将外部加载的资源添加到管理器缓存中。
     *
     * @param rid 资源ID
     * @param resource 资源指针
     * @return true 添加成功
     * @return false 资源已存在
     */
    bool add_resource(TResourceID rid, std::shared_ptr<IResource> resource);

   private:
    /**
     * @brief 私有构造函数
     */
    ResourceManager();

    /**
     * @brief 析构函数
     *
     * 取消所有异步任务并清理资源。
     */
    ~ResourceManager();

    /**
     * @brief 内部加载逻辑
     *
     * 处理资源的加载、缓存查找和并发控制。
     *
     * @param path 资源路径
     * @return TResourceID 资源ID
     */
    TResourceID load_internal(const std::filesystem::path& path);

   private:
    tbb::task_group async_tasks_{};  ///< TBB任务组，用于管理异步任务

    ParserRegistry parser_registry_;
    ResourceCache resource_cache_;
};

template <typename Parser, typename... Args>
bool ResourceManager::register_parser(Args&&... args) {
    return parser_registry_.register_parser<Parser>(std::forward<Args>(args)...);
}

inline bool ResourceManager::register_parser(std::shared_ptr<IParser> parser) {
    return parser_registry_.register_parser(std::move(parser));
}
}  // namespace Corona::Resource