#include "corona/resource/resource_manager.h"

#include "corona/kernel/core/i_logger.h"

#include <unordered_set>

#ifdef _WIN32
#include <Windows.h>
#endif

namespace {
/**
 * @brief 将 std::filesystem::path 转换为 UTF-8 编码的字符串
 * 用于日志输出，确保中文路径正确显示
 */
inline std::string path_to_utf8(const std::filesystem::path& path) {
#ifdef _WIN32
    const std::wstring& wstr = path.native();
    if (wstr.empty()) {
        return {};
    }
    int const size = WideCharToMultiByte(CP_UTF8, 0, wstr.c_str(),
                                         static_cast<int>(wstr.size()), nullptr, 0, nullptr, nullptr);
    if (size <= 0) {
        return path.string();
    }
    std::string utf8_str(static_cast<size_t>(size), '\0');
    WideCharToMultiByte(CP_UTF8, 0, wstr.c_str(),
                        static_cast<int>(wstr.size()), utf8_str.data(), size, nullptr, nullptr);
    return utf8_str;
#else
    return path.string();
#endif
}
}  // namespace

namespace Corona::Resource {

ResourceManager& ResourceManager::get_instance() {
    static ResourceManager instance;
    return instance;
}

ResourceManager::ResourceManager() = default;

ResourceManager::~ResourceManager() {
    // 取消所有正在进行的异步任务并等待它们完成
    async_tasks_.cancel();
    async_tasks_.wait();
    parser_registry_.clear();
    resource_cache_.clear();
}

TResourceID ResourceManager::import_sync(const std::filesystem::path& path) {
    return load_internal(path);
}

std::future<TResourceID> ResourceManager::import_async(const std::filesystem::path& path) {
    auto promise = std::make_shared<std::promise<TResourceID>>();
    auto future = promise->get_future();

    // 将加载任务提交到任务组
    async_tasks_.run([this, path, promise]() {
        try {
            promise->set_value(load_internal(path));
        } catch (...) {
            promise->set_value(IResource::INVALID_UID);
        }
    });

    return future;
}

bool ResourceManager::export_sync(TResourceID rid, const std::filesystem::path& path) {
    auto const parser = parser_registry_.find_export_parser(path);
    if (!parser) {
        return false;
    }

    if (auto const handle = resource_cache_.acquire_read(rid)) {
        return parser->export_to(*handle, path);
    }
    return false;
}

std::future<bool> ResourceManager::export_async(TResourceID rid, const std::filesystem::path& path) {
    auto promise = std::make_shared<std::promise<bool>>();
    auto future = promise->get_future();

    async_tasks_.run([this, rid, path, promise]() {
        promise->set_value(export_sync(rid, path));
    });
    return future;
}

bool ResourceManager::remove_cache(TResourceID rid) {
    return resource_cache_.remove_entry(rid);
}

std::future<bool> ResourceManager::remove_cache_async(TResourceID rid) {
    auto promise = std::make_shared<std::promise<bool>>();
    auto future = promise->get_future();
    async_tasks_.run([this, rid, promise]() {
        promise->set_value(remove_cache(rid));
    });
    return future;
}

bool ResourceManager::add_resource(TResourceID const rid, std::shared_ptr<IResource> resource) {
    return resource_cache_.add_resource(rid, std::move(resource));
}

TResourceID ResourceManager::load_internal(const std::filesystem::path& path) {
    // 1. 检查路径是否为空
    if (path.empty()) {
        CFW_LOG_ERROR("[ResourceManager] Cannot load resource: path is empty");
        return IResource::INVALID_UID;
    }

    // 2. 规范化路径（处理相对路径、冗余分隔符等）
    std::filesystem::path normalized_path;
    try {
        // 如果是相对路径，转换为绝对路径
        if (path.is_relative()) {
            normalized_path = std::filesystem::absolute(path);
        } else {
            normalized_path = path;
        }
        // 规范化路径（移除 "." 和 ".." 等）
        normalized_path = std::filesystem::weakly_canonical(normalized_path);
    } catch (const std::filesystem::filesystem_error& e) {
        CFW_LOG_ERROR("[ResourceManager] Invalid path '{}': {}", path_to_utf8(path), e.what());
        return IResource::INVALID_UID;
    }

    // 3. 检查路径是否存在
    std::error_code ec;
    if (!std::filesystem::exists(normalized_path, ec)) {
        if (ec) {
            CFW_LOG_ERROR("[ResourceManager] Cannot access path '{}': {}", path_to_utf8(normalized_path), ec.message());
        } else {
            CFW_LOG_ERROR("[ResourceManager] File not found: '{}'", path_to_utf8(normalized_path));
        }
        return IResource::INVALID_UID;
    }

    // 4. 检查是否为常规文件（而非目录）
    if (!std::filesystem::is_regular_file(normalized_path, ec)) {
        CFW_LOG_ERROR("[ResourceManager] Path is not a regular file: '{}'", path_to_utf8(normalized_path));
        return IResource::INVALID_UID;
    }

    auto const rid = IResource::generate_uid(normalized_path);

    // 防止递归导入自死锁：parser 在解析资源时可能间接调用 import_sync(X) →
    // load_internal(X) 回到同一资源，此时本线程已持有 Loading 状态，再进入会
    // cv.wait() 永久阻塞等自己完成。用 thread_local 集合追踪并提前中断循环。
    thread_local std::unordered_set<TResourceID> tls_loading_resources;
    if (!tls_loading_resources.insert(rid).second) {
        CFW_LOG_ERROR("[ResourceManager] Circular import detected for resource: '{}'",
                      path_to_utf8(normalized_path));
        return IResource::INVALID_UID;
    }
    struct TlsGuard {
        std::unordered_set<TResourceID>* set;
        TResourceID rid;
        ~TlsGuard() { set->erase(rid); }
    } tls_guard{&tls_loading_resources, rid};

    if (auto [entry, is_creator] = resource_cache_.get_or_create_entry(rid); is_creator) {
        std::shared_ptr<IResource> resource = nullptr;
        bool success = false;

        try {
            if (const auto parser = parser_registry_.find_parser(normalized_path)) {
                resource = parser->import_from(normalized_path, this->resource_cache_);
                if (resource) {
                    success = true;
                    CFW_LOG_DEBUG("[ResourceManager] Successfully loaded resource: '{}'", path_to_utf8(normalized_path));
                } else {
                    CFW_LOG_ERROR("[ResourceManager] Parser returned null for: '{}'", path_to_utf8(normalized_path));
                }
            } else {
                CFW_LOG_ERROR("[ResourceManager] No parser found for file type: '{}'", normalized_path.extension().string());
            }
        } catch (const std::exception& e) {
            CFW_LOG_ERROR("[ResourceManager] Exception while loading '{}': {}", path_to_utf8(normalized_path), e.what());
        } catch (...) {
            CFW_LOG_ERROR("[ResourceManager] Unknown exception while loading '{}'", path_to_utf8(normalized_path));
        }

        std::unique_lock lock(entry->mutex);
        if (success) {
            entry->resource = resource;
            entry->state = LoadState::Ready;
            lock.unlock();
            entry->cv.notify_all();  // 通知等待的线程加载完成
            return rid;
        } else {
            entry->state = LoadState::Failed;
            lock.unlock();
            entry->cv.notify_all();
            resource_cache_.remove_entry(rid);  // 加载失败，移除缓存
            return IResource::INVALID_UID;
        }
    } else {
        // 如果不是创建者，等待资源加载完成
        std::shared_lock lock(entry->mutex);
        entry->cv.wait(lock, [&entry] { return entry->state != LoadState::Loading; });
        if (entry->state == LoadState::Ready) {
            return rid;
        }
        return IResource::INVALID_UID;
    }
}
}  // namespace Corona::Resource