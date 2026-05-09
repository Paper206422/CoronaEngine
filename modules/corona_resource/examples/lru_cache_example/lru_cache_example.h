#pragma once

#ifndef LRU_CACHE_EXAMPLE_H
#define LRU_CACHE_EXAMPLE_H

#include <chrono>
#include <cstring>
#include <ctime>
#include <filesystem>
#include <list>
#include <mutex>
#include <optional>
#include <string>
#include <unordered_map>
#include <vector>

// 全局常量声明
const std::string kIllegalChar = "<>:\"|?*";  // 移除 / 和 \ 以支持子目录 key
const std::string kIllegalCharStrict = "<>:\"/\\|?*";  // 严格模式（不允许子目录）
constexpr size_t kMaxPathLength = 255;      // 文件名最大长度
constexpr size_t kMaxFullPathLength = 4096; // 完整路径最大长度
constexpr size_t kMaxEvictIterations = 1000; // 淘汰循环最大迭代次数
inline const char* kTestFilePrefix = ".cache_perm_test_";

// 缓存项结构体
struct CacheItem {
    std::string cache_item_id_;                               // 数据编号
    std::vector<char> cache_data_;                            // 数据
    int local_position_;                                      // 当前存储位置
    int target_position_;                                     // 目标存储位置
    size_t cache_size_;                                       // 数据大小
    std::chrono::system_clock::time_point last_access_time_;  // 上次访问时间

    CacheItem();
    CacheItem(std::string id, const char* data, size_t size, int position);

    // 禁用拷贝，允许移动
    CacheItem(const CacheItem&) = delete;
    CacheItem& operator=(const CacheItem&) = delete;
    CacheItem(CacheItem&& other) noexcept = default;
    CacheItem& operator=(CacheItem&& other) noexcept = default;

    ~CacheItem() = default;
};

// 内存缓存结构体
struct MemoryCache {
   private:
    size_t max_memory_capacity_;
    size_t used_memory_capacity_;
    std::list<CacheItem> memory_list_;  // 双向链表
    std::unordered_map<std::string, std::list<CacheItem>::iterator> memory_map_;
    int cache_level_ = 1;

   public:
    explicit MemoryCache(size_t memory_capacity);
    ~MemoryCache();

    MemoryCache(const MemoryCache&) = delete;
    MemoryCache& operator=(const MemoryCache&) = delete;

    // 淘汰队尾数据
    std::optional<CacheItem> evict_back_item();

    // 插入数据
    bool insert_item(const std::string& key, const char* item_data, size_t size, int position);

    // 获取数据项，同时更新LRU
    std::optional<std::reference_wrapper<CacheItem>> get_item(const std::string& key);

    // 删数据
    void erase_item(const std::string& key);

    // 检查存在
    bool contains(const std::string& key);

    size_t get_used_capacity();
    size_t get_max_capacity();
};

// 磁盘路径验证工具函数声明
std::filesystem::path validate_and_normalize_root_path(const std::string& input_path);
std::filesystem::path validate_and_normalize_key_path(const std::filesystem::path& root_path, const std::string& key);

// 磁盘缓存结构体
struct DiskCache {
   private:
    size_t max_disk_capacity_;
    size_t used_disk_capacity_;
    std::filesystem::path disk_directory_;
    int cache_level_ = 0;            // 磁盘为0
    std::list<std::string> disk_list_;
    std::unordered_map<std::string, std::pair<CacheItem, std::list<std::string>::iterator>> disk_map_;

    std::filesystem::path get_safe_key_path(const std::string& key) const;

    // 从磁盘读取数据
    std::optional<CacheItem> read_file(const std::string& key) const;

    // 写入文件
    bool write_file(const CacheItem& item) const;

    // 计算目录已使用内存
    size_t calculate_directory_size() const;

    // 淘汰最久未访问的文件
    bool evict_oldest_file(const std::string& skip_key = "");

   public:
    DiskCache(size_t max_capacity, const std::string& directory);
    ~DiskCache();

    bool insert_item(CacheItem item);
    std::optional<std::reference_wrapper<CacheItem>> get_item(const std::string& key);
    void erase_item(const std::string& key);
    bool contains(const std::string& key) const;
    size_t get_used_capacity();
};

// 磁盘和内存管理（缓存管理器）
struct CacheManager {
   private:
    MemoryCache memory_cache_;
    DiskCache disk_cache_;
    std::mutex manager_mutex_;

    // 内存满时，将最久未访问的数据刷盘
    bool flush_memory_to_disk();

   public:
    CacheManager(size_t memory_max_capacity, size_t disk_max_capacity, const std::string& directory);
    ~CacheManager() = default;

    // 插入数据
    bool put_item(const std::string& key, const char* data, size_t size);

    std::optional<std::reference_wrapper<CacheItem>> get_item(const std::string& key);

    void erase_item(const std::string& key);

    size_t get_memory_used_capacity();
    size_t get_disk_used_capacity();
};

#endif  // LRU_CACHE_EXAMPLE_H