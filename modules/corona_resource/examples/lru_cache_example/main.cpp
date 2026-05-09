#include <iostream>
#include <thread>
#include <vector>
#include <atomic>
#include <chrono>
#include <cstring>
#include <iomanip>
#include <random>

#include "lru_cache_example.h"

// 生成随机字符串作为测试数据
std::string generate_random_string(size_t length) {
    const std::string chars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz";
    thread_local std::mt19937 gen(std::random_device{}());
    std::uniform_int_distribution<> dis(0, static_cast<int>(chars.size()) - 1);

    std::string result;
    result.reserve(length);
    for (size_t i = 0; i < length; ++i) {
        result += chars[dis(gen)];
    }
    return result;
}

// 基于 key 生成确定性数据（相同 key + length 总是产生相同结果，用于写入后验证）
std::string generate_deterministic_data(const std::string& key, size_t length) {
    const std::string chars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz";
    std::seed_seq seed(key.begin(), key.end());
    std::mt19937 gen(seed);
    std::uniform_int_distribution<> dis(0, static_cast<int>(chars.size()) - 1);

    std::string result;
    result.reserve(length);
    for (size_t i = 0; i < length; ++i) {
        result += chars[dis(gen)];
    }
    return result;
}

// 多线程写入测试函数（使用确定性数据，便于读取时验证）
void thread_write_worker(CacheManager& cache, int thread_id, int num_items, size_t data_size, std::atomic<int>& success_count, std::atomic<int>& fail_count) {
    for (int i = 0; i < num_items; ++i) {
        std::string key = "thread_" + std::to_string(thread_id) + "_item_" + std::to_string(i);
        std::string data = generate_deterministic_data(key, data_size);

        bool success = cache.put_item(key, data.data(), data.size());
        if (success) {
            success_count++;
        } else {
            fail_count++;
            std::cerr << "Thread " << thread_id << " failed to put item: " << key << std::endl;
        }
    }
}

// 多线程读取测试函数（验证数据正确性）
void thread_read_worker(CacheManager& cache, int thread_id, int num_items,
                        std::atomic<int>& hit_count, std::atomic<int>& miss_count,
                        std::atomic<int>& corrupt_count) {
    for (int i = 0; i < num_items; ++i) {
        std::string key = "thread_" + std::to_string(thread_id) + "_item_" + std::to_string(i);
        auto item_opt = cache.get_item(key);

        if (item_opt) {
            const auto& item = item_opt->get();
            std::string read_data(item.cache_data_.begin(), item.cache_data_.end());
            std::string expected_data = generate_deterministic_data(key, item.cache_size_);

            if (read_data == expected_data) {
                hit_count++;
            } else {
                corrupt_count++;
                std::cerr << "Thread " << thread_id << " data corrupted for: " << key << std::endl;
            }
        } else {
            miss_count++;
        }
    }
}

// 测试磁盘缓存淘汰机制
void test_disk_eviction(CacheManager& cache) {
    std::cout << "\n=== Testing Disk Cache Eviction ===" << std::endl;

    // 写入大量数据，触发内存刷盘和磁盘淘汰
    const size_t data_size = 1024 * 512; // 512KB per item
    const int num_items = 25; // 25 * 512KB = 12.5MB > 10MB disk capacity

    for (int i = 0; i < num_items; ++i) {
        std::string key = "disk_evict_item_" + std::to_string(i);
        std::string data = generate_random_string(data_size);

        bool success = cache.put_item(key, data.data(), data.size());
        std::cout << "Put disk item " << i << ": " << (success ? "OK" : "FAILED") << "  cache_used_memory:"
        <<cache.get_memory_used_capacity() / 1024<<"KB    disk_used_memory:"<<cache.get_disk_used_capacity() / 1024 << "KB"<<std::endl;
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }

    // 验证最早写入的key是否被淘汰
    std::string oldest_key = "disk_evict_item_0";
    auto item_opt = cache.get_item(oldest_key);
    if (!item_opt) {
        std::cout << "Oldest disk item (" << oldest_key << ") evicted as expected" << std::endl;
    } else {
        std::cout << "ERROR: Oldest disk item (" << oldest_key << ") still exists!" << std::endl;
    }

    // 验证最新写入的key是否存在
    std::string newest_key = "disk_evict_item_" + std::to_string(num_items - 1);
    item_opt = cache.get_item(newest_key);
    if (item_opt) {
        std::cout << "Newest disk item (" << newest_key << ") exists as expected" << std::endl;
    } else {
        std::cout << "ERROR: Newest disk item (" << newest_key << ") missing!" << std::endl;
    }
}

// 测试数据持久化（重启后读取磁盘文件）
void test_persistence(const std::string& cache_dir) {
    std::cout << "\n=== Testing Disk Persistence ===" << std::endl;

    // 创建新的CacheManager，加载已有磁盘缓存
    constexpr size_t memory_capacity = 1024 * 1024;
    constexpr size_t disk_capacity = 10 * 1024 * 1024;
    CacheManager new_cache(memory_capacity, disk_capacity, cache_dir);

    // 检查之前写入的最新磁盘数据是否存在（选择靠后的 key，确保未被淘汰）
    std::string test_key = "disk_evict_item_20";
    auto item_opt = new_cache.get_item(test_key);
    if (item_opt) {
        std::cout << "Persistent data (" << test_key << ") loaded from disk successfully" << std::endl;
    } else {
        std::cout << "ERROR: Persistent data (" << test_key << ") not found on disk!" << std::endl;
    }
}

int main() {
    constexpr size_t memory_capacity = 1024 * 1024;     // 1MB 内存缓存
    constexpr size_t disk_capacity = 10 * 1024 * 1024;  // 10MB 磁盘缓存
    const std::string cache_dir = "./cache_dir";

    CacheManager cache_manager(memory_capacity, disk_capacity, cache_dir);

    std::cout << "\n=== Multi-thread Concurrent Test ===" << std::endl;
    const int num_threads = 4;          // 并发线程数
    const int items_per_thread = 50;    // 每个线程写入的项数
    const size_t data_size_per_item = 1024; // 每个项的大小（1KB）

    std::atomic<int> write_success_count(0);
    std::atomic<int> write_fail_count(0);
    std::atomic<int> read_hit_count(0);
    std::atomic<int> read_miss_count(0);
    std::atomic<int> read_corrupt_count(0);

    // 启动写入线程
    std::vector<std::thread> write_threads;
    auto start_time = std::chrono::high_resolution_clock::now();

    for (int i = 0; i < num_threads; ++i) {
        write_threads.emplace_back(thread_write_worker, std::ref(cache_manager),
                                  i, items_per_thread, data_size_per_item,
                                  std::ref(write_success_count), std::ref(write_fail_count));
    }

    // 等待所有写入线程完成
    for (auto& t : write_threads) {
        t.join();
    }

    // 启动读取线程
    std::vector<std::thread> read_threads;
    for (int i = 0; i < num_threads; ++i) {
        read_threads.emplace_back(thread_read_worker, std::ref(cache_manager),
                                 i, items_per_thread,
                                 std::ref(read_hit_count), std::ref(read_miss_count),
                                 std::ref(read_corrupt_count));
    }

    // 等待所有读取线程完成
    for (auto& t : read_threads) {
        t.join();
    }

    auto end_time = std::chrono::high_resolution_clock::now();
    auto duration = std::chrono::duration_cast<std::chrono::milliseconds>(end_time - start_time);

    // 输出多线程测试统计
    std::cout << "Total write attempts: " << num_threads * items_per_thread << std::endl;
    std::cout << "Write successes: " << write_success_count << std::endl;
    std::cout << "Write failures: " << write_fail_count << std::endl;
    std::cout << "Read hits: " << read_hit_count << std::endl;
    std::cout << "Read misses: " << read_miss_count << std::endl;
    std::cout << "Read corruptions: " << read_corrupt_count << std::endl;
    std::cout << "Total time: " << duration.count() << " ms" << std::endl;

    // ========== 磁盘缓存淘汰测试 ==========
    test_disk_eviction(cache_manager);

    // ========== 磁盘持久化测试 ==========
    test_persistence(cache_dir);

    return 0;
}