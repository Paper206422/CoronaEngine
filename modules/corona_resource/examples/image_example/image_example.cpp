/**
 * @file image_example.cpp
 * @brief Example demonstrating Image resource loading with Corona Resource Manager
 *
 * This example shows how to:
 * - Load various image formats (PNG, JPG, BMP, TGA)
 * - Handle invalid images gracefully
 * - Utilize resource caching
 * - Work with the ResourceManager API
 */

#include <filesystem>
#include <fstream>
#include <iostream>
#include <vector>

#include "corona/resource/resource_manager.h"
#include "corona/resource/types/image.h"

#ifndef CORONARESOURCE_SOURCE_DIR
#define CORONARESOURCE_SOURCE_DIR ""
#endif

using namespace Corona::Resource;

// Example statistics
struct ExampleStats {
    int passed{0};
    int failed{0};
    int total{0};

    void record_pass() {
        passed++;
        total++;
    }

    void record_fail() {
        failed++;
        total++;
    }

    void print() const {
        std::cout << "\n=== Image Example Results ===" << std::endl;
        std::cout << "Total: " << total << std::endl;
        std::cout << "Passed: " << passed << " ("
                  << (total > 0 ? (passed * 100.0 / total) : 0) << "%)" << std::endl;
        std::cout << "Failed: " << failed << std::endl;
    }
};

ExampleStats g_stats;

// Test 1: Load PNG image
void test_load_png() {
    std::cout << "\n[Test] Loading PNG image..." << std::endl;

    try {
        auto& manager = ResourceManager::get_instance();
        auto temp_path = std::filesystem::path(CORONARESOURCE_SOURCE_DIR) / "examples/assets/test_mitsuba/kitchen/textures/bread-bin-front-bump.png";

        // 检查文件是否存在
        if (!std::filesystem::exists(temp_path)) {
            std::cerr << "PNG image file does not exist: " << temp_path << std::endl;
            g_stats.record_fail();
            return;
        }

        // Load image through ResourceManager
        auto resource_id = manager.import_sync(temp_path);

        if (resource_id == IResource::INVALID_UID) {
            std::cerr << "Failed to load PNG image (resource_id = 0)" << std::endl;
            g_stats.record_fail();
            return;
        }

        auto handle = manager.acquire_read<Image>(resource_id);

        if (!handle) {
            std::cerr << "Failed to load PNG image (handle is null)" << std::endl;
            g_stats.record_fail();
            return;
        }

        // 输出图片数据信息
        std::cout << "  Image ID: " << resource_id << std::endl;
        std::cout << "  Width: " << handle->get_width() << std::endl;
        std::cout << "  Height: " << handle->get_height() << std::endl;
        std::cout << "  Channels: " << handle->get_channels() << std::endl;
        std::cout << "  Data pointer: " << static_cast<void*>(handle->get_data()) << std::endl;
        std::cout << "  Float data pointer: " << static_cast<void*>(handle->get_float_data()) << std::endl;

        // 检查数据是否有效
        unsigned char* data = handle->get_data();
        if (data) {
            std::cout << "  First 4 bytes: ";
            for (int i = 0; i < std::min(4, handle->get_width() * handle->get_height() * handle->get_channels()); ++i) {
                std::cout << static_cast<int>(data[i]) << " ";
            }
            std::cout << std::endl;
        } else {
            std::cerr << "  WARNING: Data pointer is null!" << std::endl;
        }

        // Export to test folder
        auto export_dir = std::filesystem::path(CORONARESOURCE_SOURCE_DIR) / "examples/assets/_generated";
        std::filesystem::create_directories(export_dir);
        auto export_path = export_dir / "test_export_png.png";
        if (manager.export_sync(resource_id, export_path)) {
            std::cout << "  Exported to: " << export_path << std::endl;
        } else {
            std::cerr << "  Failed to export PNG image" << std::endl;
        }

        std::cout << "✓ PNG image loaded successfully (ID: " << resource_id << ")" << std::endl;
        g_stats.record_pass();
    } catch (const std::exception& e) {
        std::cerr << "Exception: " << e.what() << std::endl;
        g_stats.record_fail();
    }
}

// Test 2: Load JPG image
void test_load_jpg() {
    std::cout << "\n[Test] Loading JPG image..." << std::endl;

    try {
        auto& manager = ResourceManager::get_instance();
        auto temp_path = std::filesystem::path(CORONARESOURCE_SOURCE_DIR) / "examples/assets/test_mitsuba/kitchen/textures/Chopping-Board.jpg";

        // 检查文件是否存在
        if (!std::filesystem::exists(temp_path)) {
            std::cerr << "JPG image file does not exist: " << temp_path << std::endl;
            g_stats.record_fail();
            return;
        }

        auto resource_id = manager.import_sync(temp_path);

        if (resource_id == IResource::INVALID_UID) {
            std::cerr << "Failed to load JPG image (resource_id = 0)" << std::endl;
            g_stats.record_fail();
            return;
        }

        auto handle = manager.acquire_read<Image>(resource_id);

        if (!handle) {
            std::cerr << "Failed to load JPG image (handle is null)" << std::endl;
            g_stats.record_fail();
            return;
        }

        // 输出图片数据信息
        std::cout << "  Image ID: " << resource_id << std::endl;
        std::cout << "  Width: " << handle->get_width() << std::endl;
        std::cout << "  Height: " << handle->get_height() << std::endl;
        std::cout << "  Channels: " << handle->get_channels() << std::endl;
        std::cout << "  Data pointer: " << static_cast<void*>(handle->get_data()) << std::endl;

        // 检查数据是否有效
        unsigned char* data = handle->get_data();
        if (data) {
            std::cout << "  First 4 bytes: ";
            for (int i = 0; i < std::min(4, handle->get_width() * handle->get_height() * handle->get_channels()); ++i) {
                std::cout << static_cast<int>(data[i]) << " ";
            }
            std::cout << std::endl;
        } else {
            std::cerr << "  WARNING: Data pointer is null!" << std::endl;
        }

        std::cout << "✓ JPG image loaded successfully (ID: " << resource_id << ")" << std::endl;

        // Export to test folder
        auto export_dir = std::filesystem::path(CORONARESOURCE_SOURCE_DIR) / "examples/assets/_generated";
        std::filesystem::create_directories(export_dir);
        auto export_path = export_dir / "test_export_jpg.jpg";
        if (manager.export_sync(resource_id, export_path)) {
            std::cout << "  Exported to: " << export_path << std::endl;
        } else {
            std::cerr << "  Failed to export JPG image" << std::endl;
        }

        g_stats.record_pass();
    } catch (const std::exception& e) {
        std::cerr << "Exception: " << e.what() << std::endl;
        g_stats.record_fail();
    }
}

// Test 3: Load BMP image
void test_load_bmp() {
    std::cout << "\n[Test] Loading BMP image..." << std::endl;

    try {
        auto& manager = ResourceManager::get_instance();
        auto temp_path = std::filesystem::path(CORONARESOURCE_SOURCE_DIR) / "examples/assets/test_assimp/banner_pure.bmp";

        if (!std::filesystem::exists(temp_path)) {
            std::cerr << "BMP image file does not exist: " << temp_path << std::endl;
            g_stats.record_fail();
            return;
        }

        auto resource_id = manager.import_sync(temp_path);

        if (resource_id == IResource::INVALID_UID) {
            std::cerr << "Failed to load BMP image (resource_id = 0)" << std::endl;
            g_stats.record_fail();
            return;
        }

        auto handle = manager.acquire_read<Image>(resource_id);

        if (!handle) {
            std::cerr << "Failed to load BMP image (handle is null)" << std::endl;
            g_stats.record_fail();
            return;
        }

        std::cout << "✓ BMP image loaded successfully (ID: " << resource_id << ")" << std::endl;

        // Export to test folder
        auto export_dir = std::filesystem::path(CORONARESOURCE_SOURCE_DIR) / "examples/assets/_generated";
        std::filesystem::create_directories(export_dir);
        auto export_path = export_dir / "test_export_bmp.bmp";
        if (manager.export_sync(resource_id, export_path)) {
            std::cout << "  Exported to: " << export_path << std::endl;
        } else {
            std::cerr << "  Failed to export BMP image" << std::endl;
        }

        g_stats.record_pass();
    } catch (const std::exception& e) {
        std::cerr << "Exception: " << e.what() << std::endl;
        g_stats.record_fail();
    }
}

// Test 4: Load TGA image
void test_load_tga() {
    std::cout << "\n[Test] Loading TGA image..." << std::endl;

    try {
        auto& manager = ResourceManager::get_instance();
        auto temp_path = std::filesystem::path(CORONARESOURCE_SOURCE_DIR) / "examples/assets/test_pbrt/kitchen/textures/bread-bin-front-bump.tga";

        // 检查文件是否存在
        if (!std::filesystem::exists(temp_path)) {
            std::cerr << "TGA image file does not exist: " << temp_path << std::endl;
            g_stats.record_fail();
            return;
        }

        auto resource_id = manager.import_sync(temp_path);

        if (resource_id == IResource::INVALID_UID) {
            std::cerr << "Failed to load TGA image (resource_id = 0)" << std::endl;
            g_stats.record_fail();
            return;
        }

        auto handle = manager.acquire_read<Image>(resource_id);

        if (!handle) {
            std::cerr << "Failed to load TGA image (handle is null)" << std::endl;
            g_stats.record_fail();
            return;
        }

        std::cout << "✓ TGA image loaded successfully (ID: " << resource_id << ")" << std::endl;

        // Export to test folder
        auto export_dir = std::filesystem::path(CORONARESOURCE_SOURCE_DIR) / "examples/assets/_generated";
        std::filesystem::create_directories(export_dir);
        auto export_path = export_dir / "test_export_tga.tga";
        if (manager.export_sync(resource_id, export_path)) {
            std::cout << "  Exported to: " << export_path << std::endl;
        } else {
            std::cerr << "  Failed to export TGA image" << std::endl;
        }

        g_stats.record_pass();
    } catch (const std::exception& e) {
        std::cerr << "Exception: " << e.what() << std::endl;
        g_stats.record_fail();
    }
}

// Test 5: Load invalid image
void test_load_invalid_image() {
    std::cout << "\n[Test] Loading invalid image (should fail gracefully)..." << std::endl;
    auto temp_path = std::filesystem::path(CORONARESOURCE_SOURCE_DIR) /
                     "examples/assets/_generated/invalid.png";
    try {
        auto& manager = ResourceManager::get_instance();
        std::filesystem::create_directories(temp_path.parent_path());
        {
            std::ofstream f(temp_path, std::ios::binary);
            f << "Not an image";
        }

        auto resource_id = manager.import_sync(temp_path);

        // 先检查 ID，再根据结果获取 handle
        if (resource_id == IResource::INVALID_UID) {
            std::cout << "✓ Invalid image correctly rejected" << std::endl;
            g_stats.record_pass();
        } else {
            auto handle = manager.acquire_read<Image>(resource_id);
            if (!handle) {
                std::cout << "✓ Invalid image correctly rejected" << std::endl;
                g_stats.record_pass();
            } else {
                std::cerr << "Parser accepted invalid image data" << std::endl;
                g_stats.record_fail();
            }
        }
    } catch (const std::exception& e) {
        std::cout << "✓ Exception thrown for invalid image: " << e.what() << std::endl;
        g_stats.record_pass();
    }
}

// Test 6: Load non-existent image
void test_load_nonexistent_image() {
    std::cout << "\n[Test] Loading non-existent image (should fail gracefully)..." << std::endl;

    try {
        auto& manager = ResourceManager::get_instance();
        auto temp_path = std::filesystem::path(CORONARESOURCE_SOURCE_DIR) / "examples/assets/test_mitsuba/kitchen/textures/bread-bain-front-bump.png";

        // Make sure file doesn't exist
        if (std::filesystem::exists(temp_path)) {
        }

        auto resource_id = manager.import_sync(temp_path);

        if (resource_id == IResource::INVALID_UID) {
            std::cout << "✓ Correctly returned invalid ID for non-existent file" << std::endl;
            g_stats.record_pass();
        } else {
            std::cerr << "Should have returned invalid ID for non-existent file" << std::endl;
            g_stats.record_fail();
        }
    } catch (const std::exception& e) {
        std::cerr << "Unexpected exception: " << e.what() << std::endl;
        g_stats.record_fail();
    }
}

// Test 7: Cache functionality
void test_image_cache() {
    std::cout << "\n[Test] Image caching..." << std::endl;

    try {
        auto& manager = ResourceManager::get_instance();
        auto temp_path = std::filesystem::path(CORONARESOURCE_SOURCE_DIR) / "examples/assets/test_mitsuba/kitchen/textures/bread-bin-front-bump.png";

        // 检查文件是否存在
        if (!std::filesystem::exists(temp_path)) {
            std::cerr << "Image file does not exist for cache test: " << temp_path << std::endl;
            g_stats.record_fail();
            return;
        }

        // Load image first time
        auto resource_id1 = manager.import_sync(temp_path);

        if (resource_id1 == IResource::INVALID_UID) {
            std::cerr << "Failed to load image for cache test" << std::endl;
            g_stats.record_fail();
            return;
        }

        // Load same image second time (should be cached, return same ID)
        auto resource_id2 = manager.import_sync(temp_path);

        if (resource_id1 == resource_id2) {
            std::cout << "✓ Image caching works correctly (ID: " << resource_id1 << ")" << std::endl;
            g_stats.record_pass();
        } else {
            std::cerr << "Image was not cached properly (ID1: " << resource_id1
                      << ", ID2: " << resource_id2 << ")" << std::endl;
            g_stats.record_fail();
        }
    } catch (const std::exception& e) {
        std::cerr << "Exception: " << e.what() << std::endl;
        g_stats.record_fail();
    }
}

// Test 8: Import EXR
void test_load_exr() {
    std::cout << "\n[Test] Loading EXR image..." << std::endl;

    try {
        auto& manager = ResourceManager::get_instance();
        auto temp_path = std::filesystem::path(CORONARESOURCE_SOURCE_DIR) / "examples/assets/test_mitsuba/kitchen/TungstenRender.exr";

        // 检查文件是否存在
        if (!std::filesystem::exists(temp_path)) {
            std::cerr << "EXR image file does not exist: " << temp_path << std::endl;
            g_stats.record_fail();
            return;
        }

        auto resource_id = manager.import_sync(temp_path);

        if (resource_id == IResource::INVALID_UID) {
            std::cerr << "Failed to load EXR image (resource_id = 0)" << std::endl;
            g_stats.record_fail();
            return;
        }

        auto handle = manager.acquire_read<Image>(resource_id);

        if (!handle) {
            std::cerr << "Failed to load EXR image (handle is null)" << std::endl;
            g_stats.record_fail();
            return;
        }

        // 输出图片数据信息
        std::cout << "  Image ID: " << resource_id << std::endl;
        std::cout << "  Width: " << handle->get_width() << std::endl;
        std::cout << "  Height: " << handle->get_height() << std::endl;
        std::cout << "  Channels: " << handle->get_channels() << std::endl;
        std::cout << "  Data pointer (uint8): " << static_cast<void*>(handle->get_data()) << std::endl;
        std::cout << "  Float data pointer: " << static_cast<void*>(handle->get_float_data()) << std::endl;

        // 检查 float 数据是否有效（EXR 使用 float）
        float* float_data = handle->get_float_data();
        if (float_data) {
            std::cout << "  First 4 float values: ";
            for (int i = 0; i < std::min(4, handle->get_width() * handle->get_height() * handle->get_channels()); ++i) {
                std::cout << float_data[i] << " ";
            }
            std::cout << std::endl;
        } else {
            std::cerr << "  WARNING: Float data pointer is null!" << std::endl;
        }

        std::cout << "✓ EXR image loaded successfully (ID: " << resource_id << ")" << std::endl;

        // Export to test folder
        auto export_dir = std::filesystem::path(CORONARESOURCE_SOURCE_DIR) / "examples/assets/_generated";
        std::filesystem::create_directories(export_dir);
        auto export_path = export_dir / "test_export_exr.exr";
        if (manager.export_sync(resource_id, export_path)) {
            std::cout << "  Exported to: " << export_path << std::endl;
        } else {
            std::cerr << "  Failed to export EXR image" << std::endl;
        }

        g_stats.record_pass();
    } catch (const std::exception& e) {
        std::cerr << "Exception: " << e.what() << std::endl;
        g_stats.record_fail();
    }
}

// Test 9: Import HDR
void test_load_hdr() {
    std::cout << "\n[Test] Loading HDR image..." << std::endl;

    try {
        auto& manager = ResourceManager::get_instance();
        auto temp_path = std::filesystem::path(CORONARESOURCE_SOURCE_DIR) / "examples/assets/test_vision/spruit_sunrise_2k.hdr";

        // 检查文件是否存在
        if (!std::filesystem::exists(temp_path)) {
            std::cerr << "HDR image file does not exist: " << temp_path << std::endl;
            g_stats.record_fail();
            return;
        }

        auto resource_id = manager.import_sync(temp_path);

        if (resource_id == IResource::INVALID_UID) {
            std::cerr << "Failed to load HDR image (resource_id = 0)" << std::endl;
            g_stats.record_fail();
            return;
        }

        auto handle = manager.acquire_read<Image>(resource_id);

        if (!handle) {
            std::cerr << "Failed to load HDR image (handle is null)" << std::endl;
            g_stats.record_fail();
            return;
        }

        std::cout << "✓ HDR image loaded successfully (ID: " << resource_id << ")" << std::endl;

        // Export to test folder
        auto export_dir = std::filesystem::path(CORONARESOURCE_SOURCE_DIR) / "examples/assets/_generated";
        std::filesystem::create_directories(export_dir);
        auto export_path = export_dir / "test_export_hdr.hdr";
        if (manager.export_sync(resource_id, export_path)) {
            std::cout << "  Exported to: " << export_path << std::endl;
        } else {
            std::cerr << "  Failed to export HDR image" << std::endl;
        }

        g_stats.record_pass();
    } catch (const std::exception& e) {
        std::cerr << "Exception: " << e.what() << std::endl;
        g_stats.record_fail();
    }
}

// Test 10: Export functionality
void test_export_functionality() {
    std::cout << "\n[Test] Exporting PNG to JPG..." << std::endl;

    try {
        auto& manager = ResourceManager::get_instance();
        auto import_path = std::filesystem::path(CORONARESOURCE_SOURCE_DIR) / "examples/assets/test_mitsuba/kitchen/textures/Kitchen-carrot-uv.png";

        // 1. Import the original PNG
        if (!std::filesystem::exists(import_path)) {
            std::cerr << "  Source PNG image file does not exist: " << import_path << std::endl;
            g_stats.record_fail();
            return;
        }
        auto original_id = manager.import_sync(import_path);
        if (original_id == IResource::INVALID_UID) {
            std::cerr << "  Failed to import source PNG for export test." << std::endl;
            g_stats.record_fail();
            return;
        }

        // 2. Export it as a JPG
        auto export_dir = std::filesystem::path(CORONARESOURCE_SOURCE_DIR) / "examples/assets/_generated";
        std::filesystem::create_directories(export_dir);
        auto export_path = export_dir / "exported_image.jpg";

        bool export_success = manager.export_sync(original_id, export_path);
        if (!export_success) {
            std::cerr << "  Failed to export image to " << export_path << std::endl;
            g_stats.record_fail();
            return;
        }
        std::cout << "  Image exported to " << export_path << std::endl;

        // 3. Re-import the exported JPG
        auto reimported_id = manager.import_sync(export_path);
        if (reimported_id == IResource::INVALID_UID) {
            std::cerr << "  Failed to re-import the exported image from " << export_path << std::endl;
            g_stats.record_fail();
            return;
        }

        // 4. Compare the original and re-imported images
        auto original_handle = manager.acquire_read<Image>(original_id);
        auto reimported_handle = manager.acquire_read<Image>(reimported_id);

        if (!original_handle || !reimported_handle) {
            std::cerr << "  Failed to get handles for comparison." << std::endl;
            g_stats.record_fail();
            return;
        }

        bool dimensions_match = original_handle->get_width() == reimported_handle->get_width() &&
                                original_handle->get_height() == reimported_handle->get_height();

        // Note: Channels might differ (e.g., PNG with alpha -> JPG without alpha)
        // We accept 3 or 4 channels for this test.
        bool channels_ok = (original_handle->get_channels() == 3 || original_handle->get_channels() == 4) &&
                           (reimported_handle->get_channels() == 3);  // JPG is usually 3 channels

        if (dimensions_match && channels_ok) {
            std::cout << "✓ Export and re-import successful. Dimensions and channels are consistent." << std::endl;
            g_stats.record_pass();
        } else {
            std::cerr << "  Mismatch after export/re-import:" << std::endl;
            std::cerr << "    Original (W,H,C): (" << original_handle->get_width() << ", " << original_handle->get_height() << ", " << original_handle->get_channels() << ")" << std::endl;
            std::cerr << "    Re-imported (W,H,C): (" << reimported_handle->get_width() << ", " << reimported_handle->get_height() << ", " << reimported_handle->get_channels() << ")" << std::endl;
            g_stats.record_fail();
        }

    } catch (const std::exception& e) {
        std::cerr << "Exception in export test: " << e.what() << std::endl;
        g_stats.record_fail();
    }
}

int main() {
    std::cout << "=== Corona Resource Manager - Image Example ===" << std::endl;
    std::cout << "This example demonstrates loading various image formats\n"
              << std::endl;

    // Get manager singleton and register Image parser
    auto& manager = ResourceManager::get_instance();
    manager.register_parser<ImageParser>();

    // Run examples
    test_load_png();
    test_load_jpg();
    test_load_bmp();
    test_load_tga();
    test_load_exr();
    test_load_invalid_image();
    test_load_nonexistent_image();
    test_image_cache();
    // test_load_hdr();
    test_export_functionality();

    // Print results
    g_stats.print();

    return g_stats.failed > 0 ? 1 : 0;
}
