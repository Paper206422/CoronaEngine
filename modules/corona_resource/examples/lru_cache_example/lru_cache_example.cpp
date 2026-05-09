#include "lru_cache_example.h"
#include <iomanip>
#include <cassert>
#include <random>
#include <future>
#include <stdexcept>

#include <fstream>
#include <iostream>
#include <random>
#include <regex>

#include "corona/kernel/core/i_logger.h"

// ------------------------------ CacheItem 实现 ------------------------------
CacheItem::CacheItem() : local_position_(0),
                         target_position_(0),
                         cache_size_(0),
                         last_access_time_(std::chrono::system_clock::now()) {}

CacheItem::CacheItem(std::string id, const char* data, size_t size, int position) : cache_item_id_(std::move(id)),
                                                                                    local_position_(position),
                                                                                    target_position_(position),
                                                                                    cache_size_(size),
                                                                                    last_access_time_(std::chrono::system_clock::now()) {
    if (data != nullptr && size > 0) {
        cache_data_.assign(data, data + size);  // 拷贝数据
    }
}

// ------------------------------ MemoryCache 实现 ------------------------------
MemoryCache::MemoryCache(size_t memory_capacity) : max_memory_capacity_(memory_capacity),
                                                   used_memory_capacity_(0) {}

MemoryCache::~MemoryCache() {
    memory_list_.clear();
    memory_map_.clear();
}

std::optional<CacheItem> MemoryCache::evict_back_item() {
    if (memory_list_.empty()) {
        return std::nullopt;
    }

    auto last_it = --memory_list_.end();
    std::string key = last_it->cache_item_id_;
    CacheItem evicted_item = std::move(*last_it);

    used_memory_capacity_ = (used_memory_capacity_ >= evicted_item.cache_size_) ? (used_memory_capacity_ - evicted_item.cache_size_) : 0;
    memory_map_.erase(key);
    memory_list_.pop_back();

    return std::make_optional<CacheItem>(std::move(evicted_item));
}

bool MemoryCache::insert_item(const std::string& key, const char* item_data, size_t size, int position) {
    auto it = memory_map_.find(key);  // 检查数据存在
    if (it != memory_map_.end()) {
        size_t old_size = it->second->cache_size_;
        size_t new_used = used_memory_capacity_ - old_size + size;

        if (new_used > max_memory_capacity_) {
                return false;  // 容量不足淘汰
        }

        // 更新数据
        it->second->cache_data_.assign(item_data, item_data + size);
        it->second->cache_size_ = size;
        it->second->local_position_ = 1;
        it->second->target_position_ = position;
        it->second->last_access_time_ = std::chrono::system_clock::now();
        memory_list_.splice(memory_list_.begin(), memory_list_, it->second);
        used_memory_capacity_ = new_used;
        return true;
    }

    if (used_memory_capacity_ + size > max_memory_capacity_) {
            return false;  // 容量不足淘汰
    }

    try {  // 插入新数据
        memory_list_.emplace_front(key, item_data, size, 1);
        memory_map_[key] = memory_list_.begin();
        used_memory_capacity_ += size;
        return true;
    } catch (...) {
        return false;
    }
}

std::optional<std::reference_wrapper<CacheItem>> MemoryCache::get_item(const std::string& key) {
    auto it = memory_map_.find(key);
    if (it == memory_map_.end()) {
        return std::nullopt;
    }

    it->second->last_access_time_ = std::chrono::system_clock::now();
    memory_list_.splice(memory_list_.begin(), memory_list_, it->second);

    return std::ref(*it->second);
}

void MemoryCache::erase_item(const std::string& key) {
    auto it = memory_map_.find(key);
    if (it != memory_map_.end()) {
        used_memory_capacity_ = (used_memory_capacity_ >= it->second->cache_size_) ? (used_memory_capacity_ - it->second->cache_size_) : 0;
        memory_list_.erase(it->second);
        memory_map_.erase(it);
    }
}

bool MemoryCache::contains(const std::string& key) {
    return memory_map_.contains(key);
}

size_t MemoryCache::get_used_capacity() {
    return used_memory_capacity_;
}

size_t MemoryCache::get_max_capacity() {
    return max_memory_capacity_;
}

// ------------------------------ 路径工具函数实现 ------------------------------
std::filesystem::path validate_and_normalize_root_path(const std::string& input_path) {
    if (input_path.empty() || input_path.find_first_of(kIllegalChar) != std::string::npos) {
        throw std::invalid_argument("Invalid root path");
    }

    std::filesystem::path normalized_path;
    try {
        normalized_path = std::filesystem::canonical(std::filesystem::absolute(input_path));
    } catch (...) {
        try {
            if (!std::filesystem::create_directories(input_path)) {
                throw std::runtime_error("Failed to create directories");
            }
            normalized_path = std::filesystem::canonical(std::filesystem::absolute(input_path));
        } catch (...) {
            throw std::invalid_argument("create root path error");
        }
    }

    std::string path_string = normalized_path.string();
    // 修复：区分文件名长度和完整路径长度
    if (path_string.length() > kMaxFullPathLength) {
        throw std::invalid_argument("Path length exceeds maximum allowed!");
    }

    // 修复：使用随机文件名避免多进程冲突
    std::random_device rd;
    std::mt19937 gen(rd());
    std::uniform_int_distribution<> dis(100000, 999999);
    std::string random_suffix = std::to_string(dis(gen));
    std::filesystem::path test_file = normalized_path / (std::string(kTestFilePrefix) + random_suffix);

    try {
        std::ofstream test_out(test_file, std::ios::binary | std::ios::out);
        if (!test_out.is_open()) {
            throw std::invalid_argument("Cannot create test file - no write permission");
        }
        test_out.close();
        if (std::filesystem::exists(test_file)) {
            std::filesystem::remove(test_file);
        }
    } catch (const std::exception& e) {
        if (std::filesystem::exists(test_file)) {
            std::filesystem::remove(test_file);
        }
        throw std::invalid_argument(std::string("No write permission for root directory: ") + e.what());
    }

    if (!std::filesystem::is_directory(normalized_path) || !std::filesystem::exists(normalized_path)) {
        throw std::invalid_argument("The root path is not a valid directory or does not exist");
    }

    return normalized_path;
}

std::filesystem::path validate_and_normalize_key_path(const std::filesystem::path& root_path, const std::string& key) {
    if (key.empty() || key.find_first_of(kIllegalChar) != std::string::npos) {
        throw std::invalid_argument("char error!");
    }

    // 修复：同时检测 Unix(/) 和 Windows(\) 风格的路径遍历
    std::regex path_traversal_regex(R"(\.\.[/\\]|\.\.$ )");
    if (std::regex_search(key, path_traversal_regex)) {
        throw std::invalid_argument("Cache key contains path traversal characters(../ or ..\\)");
    }

    // 检查各路径组件长度（文件名限制）
    if (key.length() > kMaxPathLength) {
        throw std::invalid_argument("Cache key is too long");
    }

    std::filesystem::path key_path = root_path / key;
    std::filesystem::path normalized_key_path;

    // 修复：使用 weakly_canonical 替代 canonical + absolute 回退
    // weakly_canonical 会规范化路径但不要求文件存在
    try {
        normalized_key_path = std::filesystem::weakly_canonical(key_path);
    } catch (const std::exception& e) {
        throw std::invalid_argument(std::string("Failed to normalize key path: ") + e.what());
    }

    // 修复：检测符号链接攻击
    if (std::filesystem::exists(normalized_key_path) &&
        std::filesystem::is_symlink(normalized_key_path)) {
        throw std::invalid_argument("Symbolic links are not allowed in cache paths");
    }

    std::filesystem::path normalized_root = std::filesystem::weakly_canonical(root_path);
    std::filesystem::path normalized_key_abs = normalized_key_path;  // 已经是规范化的绝对路径

    auto root_it = normalized_root.begin();
    auto key_it = normalized_key_abs.begin();
    for (; root_it != normalized_root.end() && key_it != normalized_key_abs.end(); ++root_it, ++key_it) {
        if (*root_it != *key_it) {
            break;
        }
    }

    if (root_it != normalized_root.end()) {
        throw std::invalid_argument("Cache key path exceeds root directory scope");
    }

    return normalized_key_path;
}

// ------------------------------ DiskCache 实现 ------------------------------
std::filesystem::path DiskCache::get_safe_key_path(const std::string& key) const {
    if (key.empty()) {
        throw std::invalid_argument("Empty cache key");
    }
    return validate_and_normalize_key_path(disk_directory_, key);
}

std::optional<CacheItem> DiskCache::read_file(const std::string& key) const {
    std::filesystem::path file_path;
    try {
        file_path = get_safe_key_path(key);
    } catch (const std::exception& e) {
        CFW_LOG_WARNING("cannot get the right key path: {}", e.what());
        return std::nullopt;
    }

    if (!std::filesystem::exists(file_path) || !std::filesystem::is_regular_file(file_path)) {
        return std::nullopt;
    }

    try {
        std::ifstream file(file_path, std::ios::binary | std::ios::ate);  // 打开后文件指针直接定位到文件末尾
        if (!file.is_open()) {
            return std::nullopt;
        }

        std::streampos file_size_pos = file.tellg();
        if (file_size_pos < 0) {
            file.close();
            return std::nullopt;
        }
        size_t file_size = static_cast<size_t>(file_size_pos);

        std::vector<char> data(file_size);
        file.seekg(0);  // 将文件指针移回文件开头
        if (!file.read(data.data(), file_size)) {
            file.close();
            return std::nullopt;
        }

        file.close();
        return CacheItem(key, data.data(), file_size, 0);
    } catch (const std::filesystem::filesystem_error& e) {
        CFW_LOG_ERROR("Filesystem error reading cache file '{}': {}", key, e.what());
        return std::nullopt;
    } catch (const std::bad_alloc& e) {
        CFW_LOG_ERROR("Memory allocation failed reading cache file '{}': {}", key, e.what());
        return std::nullopt;
    } catch (const std::exception& e) {
        CFW_LOG_ERROR("Error reading cache file '{}': {}", key, e.what());
        return std::nullopt;
    }
}

bool DiskCache::write_file(const CacheItem& item) const {
    std::filesystem::path file_path;
    try {
        file_path = get_safe_key_path(item.cache_item_id_);
    } catch (const std::exception& e) {
        CFW_LOG_ERROR("Invalid cache key '{}': {}", item.cache_item_id_, e.what());
        return false;
    }

    try {
        // 修复：检查父目录是否为符号链接
        auto parent_path = file_path.parent_path();
        if (std::filesystem::exists(parent_path) && std::filesystem::is_symlink(parent_path)) {
            CFW_LOG_ERROR("Parent directory is a symlink, refusing to write: {}", parent_path.string());
            return false;
        }

        if (!std::filesystem::create_directories(parent_path)) {
            if (!std::filesystem::exists(parent_path)) {
                CFW_LOG_ERROR("Failed to create parent directory: {}", parent_path.string());
                return false;
            }
        }  // 自动创建文件的父目录

        std::ofstream file(file_path, std::ios::binary | std::ios::trunc);  // 以二进制模式打开文件,若文件已存在，清空原有内容
        if (!file.is_open()) {
            return false;
        }

        file.write(item.cache_data_.data(), item.cache_size_);
        if (!file) {
            file.close();
            return false;
        }

        file.flush();  // 强制将缓冲区数据刷入磁盘
        file.close();

        return std::filesystem::exists(file_path) && std::filesystem::file_size(file_path) == item.cache_size_;
    } catch (const std::filesystem::filesystem_error& e) {
        CFW_LOG_ERROR("Filesystem error writing cache file '{}': {}", item.cache_item_id_, e.what());
        return false;
    } catch (const std::exception& e) {
        CFW_LOG_ERROR("Error writing cache file '{}': {}", item.cache_item_id_, e.what());
        return false;
    }
}

size_t DiskCache::calculate_directory_size() const {
    size_t total_size = 0;
    if (!std::filesystem::exists(disk_directory_)) {
        return 0;
    }
    // 递归目录迭代器，遍历 disk_directory_ 及其所有子目录下的所有文件/目录项
    for (const auto& p : std::filesystem::recursive_directory_iterator(disk_directory_)) {
        if (p.is_regular_file()) {  // 判断当前迭代项是否为普通文件
            total_size += p.file_size();
        }
    }
    return total_size;
}

bool DiskCache::evict_oldest_file(const std::string& skip_key) {
    if (!std::filesystem::exists(disk_directory_) || disk_list_.empty() || disk_map_.empty()) {
        return false;
    }

    std::string oldest_file_key;
    std::list<std::string>::iterator oldest_it;
    bool found_valid = false;

    for (auto it = disk_list_.rbegin(); it != disk_list_.rend(); ++it) {
        const std::string& current_key = *it;
        if (!skip_key.empty() && current_key == skip_key) {
            continue;
        }
        auto map_it = disk_map_.find(current_key);
        if (map_it != disk_map_.end()) {
            oldest_file_key = current_key;
            oldest_it = --it.base();
            found_valid = true;
            break;
        }
    }

    if (!found_valid) {
        return false;
    }

    auto map_it = disk_map_.find(oldest_file_key);
    if (map_it == disk_map_.end()) {
        return false;
    }

    try {
        std::filesystem::path file_path = get_safe_key_path(oldest_file_key);
        if (std::filesystem::exists(file_path) && std::filesystem::is_regular_file(file_path)) {
            std::filesystem::remove(file_path);
        }
    } catch (const std::exception& e) {
        CFW_LOG_ERROR("Error evicting cache file '{}': {}", oldest_file_key, e.what());
        return false;
    }

    used_disk_capacity_ = (used_disk_capacity_ >= map_it->second.first.cache_size_) ? (used_disk_capacity_ - map_it->second.first.cache_size_) : 0;

    disk_list_.erase(oldest_it);
    disk_map_.erase(map_it);
    return true;
}

DiskCache::DiskCache(size_t max_capacity, const std::string& directory) : max_disk_capacity_(max_capacity),
                                                                          disk_directory_(directory) {
    used_disk_capacity_ = 0;

    try {
        disk_directory_ = validate_and_normalize_root_path(directory);
    } catch (const std::exception& e) {
        CFW_LOG_ERROR("Invalid disk cache directory: {}", e.what());
    }

    // 根据磁盘已有文件初始化
    if (std::filesystem::exists(disk_directory_)) {
        for (const auto& p : std::filesystem::recursive_directory_iterator(disk_directory_)) {
            if (p.is_regular_file()) {
                std::string key = std::filesystem::relative(p.path(), disk_directory_).string();
                size_t size = p.file_size();

                CacheItem cache_item(key, nullptr, size, 0);  // 仅存元数据，不存完整数据
                cache_item.last_access_time_ = std::chrono::system_clock::now();
                disk_list_.push_back(key);
                auto list_it_ = --disk_list_.end();
                disk_map_.emplace(key, std::make_pair(std::move(cache_item), list_it_));
                used_disk_capacity_ += size;
            }
        }
    }
}

DiskCache::~DiskCache() {
    if (std::filesystem::exists(disk_directory_)) {
        disk_list_.clear();  // 不删除文件，仅释放代码内存
        disk_map_.clear();
    }
}

bool DiskCache::insert_item(CacheItem item) {
    const std::string& current_updating_key = item.cache_item_id_;
    size_t new_item_size = item.cache_size_;

    if (current_updating_key.empty() || new_item_size == 0 || item.cache_data_.empty()) {
        return false;
    }

    auto map_it = disk_map_.find(current_updating_key);
    size_t old_item_size = 0;
    if (map_it != disk_map_.end()) {
        old_item_size = map_it->second.first.cache_size_;
    }

    auto calculate_estimated_capacity = [&]() -> size_t {
        size_t current_used = used_disk_capacity_;

        if (old_item_size > 0 && used_disk_capacity_ >= old_item_size) {
            current_used -= old_item_size;
        } else if (old_item_size > 0) {
            current_used = 0;
        }

        return current_used + new_item_size;
    };

    size_t estimated_capacity = calculate_estimated_capacity();

    // 修复：添加最大迭代次数防止无限循环
    size_t evict_iterations = 0;
    while (estimated_capacity > max_disk_capacity_) {
        if (evict_iterations++ >= kMaxEvictIterations) {
            CFW_LOG_ERROR("Disk cache eviction exceeded maximum iterations ({})", kMaxEvictIterations);
            return false;
        }
        if (!evict_oldest_file(current_updating_key)) {
            return false;
        }

        map_it = disk_map_.find(current_updating_key);
        old_item_size = 0;
        if (map_it != disk_map_.end()) {
            old_item_size = map_it->second.first.cache_size_;
        }

        estimated_capacity = calculate_estimated_capacity();
    }

    if (map_it != disk_map_.end()) {
        try {
            std::filesystem::path old_file_path = get_safe_key_path(current_updating_key);
            if (std::filesystem::exists(old_file_path) && std::filesystem::is_regular_file(old_file_path)) {
                std::filesystem::remove(old_file_path);
            }
        } catch (const std::exception& e) {
            CFW_LOG_ERROR("old file path is error: {}", e.what());
            return false;
        }

        used_disk_capacity_ = (used_disk_capacity_ >= map_it->second.first.cache_size_) ? (used_disk_capacity_ - map_it->second.first.cache_size_) : 0;

        disk_list_.erase(map_it->second.second);
        disk_map_.erase(map_it);
    }

    if (!write_file(item)) {
        return false;
    }

    try {
        disk_list_.push_front(current_updating_key);
        auto list_it = disk_list_.begin();
        item.last_access_time_ = std::chrono::system_clock::now();

        disk_map_.emplace(disk_list_.front(), std::make_pair(std::move(item), list_it));

        used_disk_capacity_ += new_item_size;
    } catch (const std::exception& e) {
        try {
            CFW_LOG_ERROR("file '{}' insert error: {}",current_updating_key, e.what());
            std::filesystem::path new_file_path = get_safe_key_path(current_updating_key);
            if (std::filesystem::exists(new_file_path)) {
                std::filesystem::remove(new_file_path);
            }
        } catch (const std::exception& e) {
            CFW_LOG_ERROR("cannot remove new file '{}' : {}",current_updating_key,e.what());
        }
        return false;
    }

    return true;
}

std::optional<std::reference_wrapper<CacheItem>> DiskCache::get_item(const std::string& key) {
    auto map_it = disk_map_.find(key);
    if (map_it == disk_map_.end()) {
        return std::nullopt;
    }

    auto item_option = read_file(key);
    if (!item_option) {
        disk_list_.erase(map_it->second.second);  // O(1) 使用迭代器删除
        disk_map_.erase(map_it);
        return std::nullopt;
    }

    // 将读出的完整数据回填到 map 中
    map_it->second.first.cache_data_ = std::move(item_option->cache_data_);
    map_it->second.first.last_access_time_ = std::chrono::system_clock::now();

    // 提升到链表头部
    disk_list_.splice(disk_list_.begin(), disk_list_, map_it->second.second);
    return std::ref(map_it->second.first);
}

void DiskCache::erase_item(const std::string& key) {
    auto map_it = disk_map_.find(key);
    if (map_it == disk_map_.end()) {
        return;
    }

    used_disk_capacity_ = (used_disk_capacity_ >= map_it->second.first.cache_size_) ? (used_disk_capacity_ - map_it->second.first.cache_size_) : 0;

    try {
        std::filesystem::path file_path = get_safe_key_path(key);
        if (std::filesystem::exists(file_path)) {
            std::filesystem::remove(file_path);
        }
    } catch (const std::exception& e) {
        CFW_LOG_ERROR("cannot erase  '{}' : {}",key,e.what());
    }

    disk_list_.erase(map_it->second.second);
    disk_map_.erase(map_it);
}

bool DiskCache::contains(const std::string& key) const {
    return disk_map_.contains(key);
}

size_t DiskCache::get_used_capacity() {
    return used_disk_capacity_;
}

// ------------------------------ CacheManager 实现 ------------------------------

bool CacheManager::flush_memory_to_disk() {
    auto evict_back_item = memory_cache_.evict_back_item();
    if (!evict_back_item) {
        return false;
    }

    CacheItem evict_item = std::move(*evict_back_item);
    // move 前备份回退所需数据
    std::string backup_id = evict_item.cache_item_id_;
    std::vector<char> backup_data = evict_item.cache_data_;
    size_t backup_size = evict_item.cache_size_;
    int backup_pos = evict_item.local_position_;

    bool insert_ok = disk_cache_.insert_item(std::move(evict_item));
    if (!insert_ok) {
        memory_cache_.insert_item(backup_id, backup_data.data(), backup_size, backup_pos);
        return false;
    }
    return true;
}

CacheManager::CacheManager(size_t memory_max_capacity, size_t disk_max_capacity, const std::string& directory) : memory_cache_(memory_max_capacity), disk_cache_(disk_max_capacity, directory) {}

bool CacheManager::put_item(const std::string& key, const char* data, size_t size) {
    std::lock_guard<std::mutex> lock(manager_mutex_);
    if (key.empty() || (data == nullptr && size > 0) || size > memory_cache_.get_max_capacity()) {
        return false;
    }

    // 修复：添加最大迭代次数防止无限循环
    size_t flush_iterations = 0;
    while (true) {
        if (memory_cache_.insert_item(key,data,size,1)) {
            return true;
        }

        if (flush_iterations++ >= kMaxEvictIterations) {
            CFW_LOG_ERROR("Memory flush exceeded maximum iterations ({})", kMaxEvictIterations);
            return false;
        }
        if (!flush_memory_to_disk()) {
            return false;  // 内存不够刷盘
        }
    }

}

std::optional<std::reference_wrapper<CacheItem>> CacheManager::get_item(const std::string& key) {
    std::lock_guard<std::mutex> lock(manager_mutex_);

    // 先查内存
    if (auto mem_item = memory_cache_.get_item(key)) {
        return mem_item;
    }

    auto disk_item = disk_cache_.get_item(key);  // 再查磁盘
    if (!disk_item) {
        return std::nullopt;
    }

    auto& disk_item_ref = disk_item->get();
    // 修复：添加最大迭代次数防止无限循环
    size_t flush_iterations = 0;
    while (memory_cache_.get_used_capacity() + disk_item_ref.cache_size_ > memory_cache_.get_max_capacity()) {
        if (flush_iterations++ >= kMaxEvictIterations) {
            CFW_LOG_ERROR("get_item flush exceeded maximum iterations, returning disk item");
            return disk_item;
        }
        if (!flush_memory_to_disk()) {
            return disk_item;
        }
    }

    memory_cache_.insert_item(key, disk_item_ref.cache_data_.data(), disk_item_ref.cache_size_, 1);
    disk_cache_.erase_item(key);
    return memory_cache_.get_item(key);
}

void CacheManager::erase_item(const std::string& key) {
    std::lock_guard<std::mutex> lock(manager_mutex_);
    memory_cache_.erase_item(key);
    disk_cache_.erase_item(key);
}

size_t CacheManager::get_memory_used_capacity() {
    std::lock_guard<std::mutex> lock(manager_mutex_);
    return memory_cache_.get_used_capacity();
}

size_t CacheManager::get_disk_used_capacity() {
    std::lock_guard<std::mutex> lock(manager_mutex_);
    return disk_cache_.get_used_capacity();
}