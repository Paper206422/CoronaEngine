#include <algorithm>
#include <cstdint>
#include <filesystem>
#include <iomanip>
#include <iostream>

#include "corona/resource/resource_manager.h"
#include "corona/resource/types/scene.h"

#ifndef CORONARESOURCE_SOURCE_DIR
#define CORONARESOURCE_SOURCE_DIR ""
#endif

using namespace Corona::Resource;

void print_lod_summary(const Scene& scene) {
    std::cout << "\n  LOD Summary:" << std::endl;
    std::cout << "  Meshes: " << scene.data.meshes.size() << std::endl;

    for (std::uint32_t i = 0; i < scene.data.meshes.size(); ++i) {
        const auto& mesh = scene.data.meshes[i];

        std::cout << "\n  Mesh " << i << ":" << std::endl;
        std::cout << "    LOD 0 (original): "
                  << mesh.vertices.size() << " vertices, "
                  << mesh.indices.size() / 3 << " triangles" << std::endl;

        std::uint32_t lod_count = scene.get_mesh_lod_count(i);
        if (lod_count == 0) {
            std::cout << "    No additional LOD levels generated." << std::endl;
            continue;
        }

        for (std::uint32_t lod = 0; lod < lod_count; ++lod) {
            const auto& level = scene.get_mesh_lod(i, lod);

            float vert_ratio = mesh.vertices.empty()
                                   ? 0.0f
                                   : 100.0f * static_cast<float>(level.vertices.size()) /
                                         static_cast<float>(mesh.vertices.size());
            float tri_ratio = mesh.indices.empty()
                                  ? 0.0f
                                  : 100.0f * static_cast<float>(level.indices.size()) /
                                        static_cast<float>(mesh.indices.size());

            std::cout << "    LOD " << (lod + 1) << ": "
                      << level.vertices.size() << " vertices ("
                      << std::fixed << std::setprecision(1) << vert_ratio << "%), "
                      << level.indices.size() / 3 << " triangles ("
                      << tri_ratio << "%), "
                      << "error=" << std::setprecision(6) << level.error
                      << ", threshold=" << std::setprecision(4) << level.screen_threshold
                      << std::endl;
        }

        // 展示最低级 LOD 可用于物理碰撞
        const auto& collision_lod = scene.get_mesh_lod(i, lod_count - 1);
        std::cout << "    -> Collision mesh (LOD " << lod_count << "): "
                  << collision_lod.vertices.size() << " vertices, "
                  << collision_lod.indices.size() / 3 << " triangles" << std::endl;
    }
}

int main(int argc, char* argv[]) {
    auto& mgr = ResourceManager::get_instance();

    mgr.register_parser<ImageParser>();

    // 创建带 LOD 选项的 SceneParser
    auto scene_parser = std::make_shared<SceneParser>();
    scene_parser->assimp_options.lod_options.enabled = true;
    scene_parser->assimp_options.lod_options.level_count = 3;
    scene_parser->assimp_options.lod_options.target_ratios = {0.5f, 0.25f, 0.05f};
    scene_parser->assimp_options.lod_options.max_errors = {0.05f, 0.2f, 1.0f};
    scene_parser->assimp_options.lod_options.max_triangles = {0, 0, 200};  // 各级三角形上限（0=不限制）
    mgr.register_parser(scene_parser);

    // 递归扫描文件夹，收集常用模型文件
    std::vector<std::filesystem::path> test_files;
    {
        std::filesystem::path scan_dir =
            std::filesystem::path(L"C:\\Users\\Lee\\Documents\\测试");
        static const std::vector<std::string> model_extensions = {
            ".obj", ".fbx", ".gltf", ".glb", ".dae", ".stl", ".3ds",
            ".usd", ".usda", ".usdc", ".usdz"};

        if (std::filesystem::exists(scan_dir)) {
            for (const auto& entry : std::filesystem::recursive_directory_iterator(scan_dir)) {
                if (!entry.is_regular_file()) continue;
                std::string ext = entry.path().extension().string();
                std::transform(ext.begin(), ext.end(), ext.begin(), ::tolower);
                for (const auto& valid_ext : model_extensions) {
                    if (ext == valid_ext) {
                        test_files.push_back(entry.path());
                        break;
                    }
                }
            }
            std::sort(test_files.begin(), test_files.end());
        } else {
            std::cerr << "Scan directory not found: " << scan_dir << std::endl;
        }

        std::cout << "Found " << test_files.size() << " model files." << std::endl;
    }

    for (const auto& model_path : test_files) {
        std::cout << "\n========================================" << std::endl;
        std::cout << "LOD Example: " << model_path.filename() << std::endl;
        std::cout << "========================================" << std::endl;

        auto rid = mgr.import_async(model_path).get();

        if (rid == IResource::INVALID_UID) {
            std::cerr << "Failed to import resource." << std::endl;
            continue;
        }

        auto scene_handle = mgr.acquire_read<Scene>(rid);
        if (scene_handle) {
            std::cout << "Successfully loaded!" << std::endl;
            print_lod_summary(*scene_handle);
        } else {
            std::cerr << "Failed to acquire read handle." << std::endl;
        }
    }

    return 0;
}
