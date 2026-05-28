#pragma once
#include <oneapi/tbb/concurrent_hash_map.h>

#include <atomic>
#include <condition_variable>
#include <memory>
#include <shared_mutex>

namespace Corona::Resource {

// Forward declarations
class IResource;
using TResourceID = std::uint64_t;

/**
 * @brief 资源加载状态枚举
 */
enum class LoadState {
    Unloaded,  ///< 未加载
    Loading,   ///< 正在加载
    Ready,     ///< 加载完成且就绪
    Failed     ///< 加载失败
};

/**
 * @brief 资源条目
 *
 * 存储资源实例、同步锁和加载状态。
 */
struct ResourceEntry {
    std::shared_ptr<IResource> resource;
    std::shared_mutex mutex;
    std::atomic<LoadState> state{LoadState::Unloaded};
    std::condition_variable_any cv;
    std::atomic<int> ref_count{0};  // 资源引用计数，防止共享资源提前释放
};

/**
 * @brief 资源读取句柄 (RAII)
 *
 * 持有资源的共享锁 (Shared Lock)，提供对资源的只读访问。
 * 当句柄销毁时，自动释放锁。
 */
template <typename T = IResource>
class ReadHandle {
   public:
    static_assert(std::is_base_of_v<IResource, T>, "T must inherit from IResource");

    ReadHandle() = default;
    /**
     * @brief 构造函数
     * @param entry 资源条目
     * @param lock 已获取的共享锁
     */
    ReadHandle(std::shared_ptr<ResourceEntry> entry, std::shared_lock<std::shared_mutex> lock)
        : entry_(std::move(entry)), lock_(std::move(lock)) {}

    ReadHandle(ReadHandle&&) = default;
    ReadHandle& operator=(ReadHandle&&) = default;
    ReadHandle(const ReadHandle&) = delete;
    ReadHandle& operator=(const ReadHandle&) = delete;

    ~ReadHandle() {
        if (entry_) entry_->ref_count--;
    }

    /**
     * @brief 检查句柄是否有效
     * @return true 有效（持有锁且资源就绪）
     * @return false 无效
     */
    [[nodiscard]] bool valid() const {
        return entry_ && lock_.owns_lock() && entry_->state == LoadState::Ready && entry_->resource;
    }

    /**
     * @brief 访问资源指针
     */
    const T* operator->() const {
        return static_cast<const T*>(entry_->resource.get());
    }

    /**
     * @brief 解引用资源
     */
    const T& operator*() const {
        return *static_cast<const T*>(entry_->resource.get());
    }

    /**
     * @brief 布尔转换操作符，用于检查有效性
     */
    explicit operator bool() const { return valid(); }

   private:
    std::shared_ptr<ResourceEntry> entry_;
    std::shared_lock<std::shared_mutex> lock_;
};

/**
 * @brief 资源写入句柄 (RAII)
 *
 * 持有资源的独占锁 (Unique Lock)，提供对资源的读写访问。
 * 当句柄销毁时，自动释放锁。
 */
template <typename T = IResource>
class WriteHandle {
   public:
    static_assert(std::is_base_of_v<IResource, T>, "T must inherit from IResource");

    WriteHandle() = default;
    /**
     * @brief 构造函数
     * @param entry 资源条目
     * @param lock 已获取的独占锁
     */
    WriteHandle(std::shared_ptr<ResourceEntry> entry, std::unique_lock<std::shared_mutex> lock)
        : entry_(std::move(entry)), lock_(std::move(lock)) {}

    WriteHandle(WriteHandle&&) = default;
    WriteHandle& operator=(WriteHandle&&) = default;
    WriteHandle(const WriteHandle&) = delete;
    WriteHandle& operator=(const WriteHandle&) = delete;

    ~WriteHandle() {
        if (entry_) entry_->ref_count--;
    }

    /**
     * @brief 检查句柄是否有效
     * @return true 有效（持有锁且资源就绪）
     * @return false 无效
     */
    [[nodiscard]] bool valid() const {
        return entry_ && lock_.owns_lock() && entry_->state == LoadState::Ready && entry_->resource;
    }

    /**
     * @brief 访问资源指针
     */
    T* operator->() {
        return static_cast<T*>(entry_->resource.get());
    }

    /**
     * @brief 解引用资源
     */
    T& operator*() {
        return *static_cast<T*>(entry_->resource.get());
    }

    /**
     * @brief 布尔转换操作符，用于检查有效性
     */
    explicit operator bool() const { return valid(); }

   private:
    std::shared_ptr<ResourceEntry> entry_;
    std::unique_lock<std::shared_mutex> lock_;
};

/**
 * @brief 资源缓存
 *
 * 管理所有加载的资源，提供线程安全的查找、创建和移除操作。
 * 负责分发资源的读写句柄。
 */
class ResourceCache {
   public:
    ResourceCache() = default;
    ~ResourceCache();

    /**
     * @brief 获取现有条目或创建新条目
     *
     * 如果资源不存在，创建一个状态为 Loading 的新条目。
     *
     * @param rid 资源ID
     * @return std::pair<std::shared_ptr<ResourceEntry>, bool> {资源条目, 是否是新创建的}
     */
    std::pair<std::shared_ptr<ResourceEntry>, bool> get_or_create_entry(TResourceID rid);

    /**
     * @brief 获取资源条目
     *
     * @param rid 资源ID
     * @return std::shared_ptr<ResourceEntry> 资源条目，如果不存在返回 nullptr
     */
    std::shared_ptr<ResourceEntry> get_entry(TResourceID rid);

    /**
     * @brief 移除资源条目
     *
     * @param rid 资源ID
     * @return true 移除成功
     * @return false 资源不存在
     */
    bool remove_entry(TResourceID rid);

    /**
     * @brief 清空所有缓存
     */
    void clear();

    /**
     * @brief 添加已加载的资源到缓存
     *
     * 将外部加载的资源添加到缓存中，状态设置为 Ready。
     *
     * @param rid 资源ID
     * @param resource 资源指针
     * @return true 添加成功
     * @return false 资源已存在
     */
    bool add_resource(TResourceID rid, std::shared_ptr<IResource> resource);

    /**
     * @brief 获取资源的读取句柄
     *
     * 尝试获取资源的共享锁。如果资源未就绪，返回无效句柄。
     *
     * @param rid 资源ID
     * @return ResourceReadHandle<T> 读取句柄
     */
    template <typename T = IResource>
    ReadHandle<T> acquire_read(TResourceID rid) {
        auto entry = get_entry(rid);
        if (!entry) return {};

        std::shared_lock lock(entry->mutex);
        if (entry->state != LoadState::Ready || !entry->resource) {
            return {};
        }
        entry->ref_count++;
        return ReadHandle<T>(std::move(entry), std::move(lock));
    }

    /**
     * @brief 获取资源的写入句柄
     *
     * 尝试获取资源的独占锁。如果资源未就绪，返回无效句柄。
     *
     * @param rid 资源ID
     * @return ResourceWriteHandle<T> 写入句柄
     */
    template <typename T = IResource>
    WriteHandle<T> acquire_write(TResourceID rid) {
        auto entry = get_entry(rid);
        if (!entry) return {};

        std::unique_lock lock(entry->mutex);
        if (entry->state != LoadState::Ready || !entry->resource) {
            return {};
        }
        entry->ref_count++;
        return WriteHandle<T>(std::move(entry), std::move(lock));
    }

   private:
    tbb::concurrent_hash_map<TResourceID, std::shared_ptr<ResourceEntry>> resources_{};
};

}  // namespace Corona::Resource
