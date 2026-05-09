#include <cstring>
#include <filesystem>
#include <iomanip>
#include <iostream>

#include "corona/resource/resource_manager.h"
#include "corona/resource/types/image.h"
#include "corona/resource/types/scene.h"
#include "stb_image.h"

#ifndef CORONARESOURCE_SOURCE_DIR
#define CORONARESOURCE_SOURCE_DIR ""
#endif

// 验证纹理数据：将加载的图片写回文件并对比
void verify_texture_data(Corona::Resource::ResourceManager& mgr, std::uint64_t texture_id, const std::string& output_name) {
    if (texture_id == Corona::Resource::InvalidTextureId) {
        return;
    }

    auto image_handle = mgr.acquire_read<Corona::Resource::Image>(texture_id);
    if (!image_handle) {
        std::cerr << "  [Verify] Failed to acquire texture: " << texture_id << std::endl;
        return;
    }

    unsigned char* data = image_handle->get_data();
    if (!data) {
        std::cerr << "  [Verify] No data for texture: " << texture_id << std::endl;
        return;
    }

    int width = image_handle->get_width();
    int height = image_handle->get_height();
    int channels = image_handle->get_channels();

    // 创建输出目录
    std::filesystem::path output_dir = std::filesystem::path(CORONARESOURCE_SOURCE_DIR) / "examples/assets/_generated";
    std::filesystem::create_directories(output_dir);

    // 使用 ResourceManager 导出 PNG 文件
    std::filesystem::path output_path = output_dir / (output_name + "_verify.png");
    bool result = mgr.export_sync(texture_id, output_path);

    if (result) {
        std::cout << "  [Verify] Wrote: " << output_path << " (" << width << "x" << height << "x" << channels << ")" << std::endl;

        // 重新加载写入的图片进行对比
        int verify_width, verify_height, verify_channels;
        unsigned char* verify_data = stbi_load(output_path.string().c_str(), &verify_width, &verify_height, &verify_channels, 0);

        if (verify_data) {
            bool match = (width == verify_width && height == verify_height && channels == verify_channels);
            if (match) {
                size_t data_size = static_cast<size_t>(width) * height * channels;
                match = (memcmp(data, verify_data, data_size) == 0);
            }

            if (match) {
                std::cout << "  [Verify] ✓ Data matches perfectly!" << std::endl;
            } else {
                std::cerr << "  [Verify] ✗ Data mismatch!" << std::endl;
                std::cerr << "    Original: " << width << "x" << height << "x" << channels << std::endl;
                std::cerr << "    Verified: " << verify_width << "x" << verify_height << "x" << verify_channels << std::endl;
            }
            stbi_image_free(verify_data);
        } else {
            std::cerr << "  [Verify] Failed to reload: " << stbi_failure_reason() << std::endl;
        }
    } else {
        std::cerr << "  [Verify] Failed to write: " << output_path << std::endl;
    }
}

// 输出纹理数据信息
void print_texture_info(Corona::Resource::ResourceManager& mgr, std::uint64_t texture_id, const std::string& texture_type) {
    if (texture_id == Corona::Resource::InvalidTextureId) {
        std::cout << "        " << texture_type << ": None" << std::endl;
        return;
    }

    auto image_handle = mgr.acquire_read<Corona::Resource::Image>(texture_id);
    if (!image_handle) {
        std::cout << "        " << texture_type << ": ID=" << texture_id << " (Failed to acquire)" << std::endl;
        return;
    }

    std::cout << "        " << texture_type << ": ID=" << texture_id << std::endl;
    std::cout << "          Width: " << image_handle->get_width() << std::endl;
    std::cout << "          Height: " << image_handle->get_height() << std::endl;
    std::cout << "          Channels: " << image_handle->get_channels() << std::endl;

    unsigned char* data = image_handle->get_data();
    float* float_data = image_handle->get_float_data();

    if (data) {
        std::cout << "          Data pointer: " << static_cast<void*>(data) << std::endl;
        int pixel_count = std::min(4, image_handle->get_width() * image_handle->get_height() * image_handle->get_channels());
        std::cout << "          First " << pixel_count << " bytes: ";
        for (int i = 0; i < pixel_count; ++i) {
            std::cout << static_cast<int>(data[i]) << " ";
        }
        std::cout << std::endl;
    } else if (float_data) {
        std::cout << "          Float data pointer: " << static_cast<void*>(float_data) << std::endl;
        int pixel_count = std::min(4, image_handle->get_width() * image_handle->get_height() * image_handle->get_channels());
        std::cout << "          First " << pixel_count << " floats: ";
        for (int i = 0; i < pixel_count; ++i) {
            std::cout << float_data[i] << " ";
        }
        std::cout << std::endl;
    } else {
        std::cout << "          WARNING: No data available!" << std::endl;
    }
}

void print_scene_textures(Corona::Resource::ResourceManager& mgr, const Corona::Resource::Scene& scene) {
    std::cout << "\n  Texture Details:" << std::endl;

    int texture_index = 0;
    for (size_t i = 0; i < scene.data.materials.size(); ++i) {
        const auto& mat = scene.data.materials[i];
        std::cout << "    Material " << i << " (" << mat.name << "):" << std::endl;

        print_texture_info(mgr, mat.albedo_texture, "Albedo");
        print_texture_info(mgr, mat.normal_texture, "Normal");
        print_texture_info(mgr, mat.metallic_texture, "Metallic");
        print_texture_info(mgr, mat.roughness_texture, "Roughness");

        if (mat.albedo_texture != Corona::Resource::InvalidTextureId) {
            verify_texture_data(mgr, mat.albedo_texture, "texture_" + std::to_string(texture_index++));
        }
    }
}

void print_scene_summary(const Corona::Resource::Scene& scene) {
    std::cout << "\n  Scene Summary:" << std::endl;

    // 材质统计
    int total_materials = static_cast<int>(scene.data.materials.size());
    int materials_with_all_textures = 0;
    int materials_with_some_textures = 0;
    int materials_with_no_textures = 0;

    for (const auto& mat : scene.data.materials) {
        bool has_texture = (mat.albedo_texture != Corona::Resource::InvalidTextureId ||
                            mat.normal_texture != Corona::Resource::InvalidTextureId ||
                            mat.metallic_texture != Corona::Resource::InvalidTextureId ||
                            mat.roughness_texture != Corona::Resource::InvalidTextureId);

        if (mat.albedo_texture != Corona::Resource::InvalidTextureId &&
            mat.normal_texture != Corona::Resource::InvalidTextureId &&
            mat.metallic_texture != Corona::Resource::InvalidTextureId &&
            mat.roughness_texture != Corona::Resource::InvalidTextureId) {
            materials_with_all_textures++;
        } else if (has_texture) {
            materials_with_some_textures++;
        } else {
            materials_with_no_textures++;
        }
    }

    std::cout << "    Materials: " << total_materials << " total" << std::endl;
    std::cout << "      - " << materials_with_all_textures << " with all textures (100%)" << std::endl;
    std::cout << "      - " << materials_with_some_textures << " with partial textures" << std::endl;
    std::cout << "      - " << materials_with_no_textures << " with no textures" << std::endl;

    // 节点和几何统计（按新结构聚合）
    std::cout << "    Geometry:" << std::endl;
    std::cout << "      - " << scene.data.nodes.size() << " nodes" << std::endl;
    std::cout << "      - " << scene.data.meshes.size() << " meshes" << std::endl;

    size_t total_vertices = 0;
    size_t total_indices = 0;
    for (const auto& mesh : scene.data.meshes) {
        total_vertices += mesh.vertices.size();
        total_indices += mesh.indices.size();
    }
    std::cout << "      - " << total_vertices << " render vertices (position+normal+UV)" << std::endl;
    std::cout << "        Note: Count may exceed Blender's 'Vertices' due to UV seams and normal splits" << std::endl;
    std::cout << "        See docs/VERTEX_COUNT_EXPLANATION.md for details" << std::endl;

    // 统计每个 mesh 的详细信息
    std::cout << "      - Mesh details:" << std::endl;
    for (size_t i = 0; i < scene.data.meshes.size(); ++i) {
        const auto& mesh = scene.data.meshes[i];
        std::cout << "        Mesh " << i << ": "
                  << mesh.vertices.size() << " vertices, "
                  << mesh.indices.size() / 3 << " triangles" << std::endl;
        std::cout << "          AABB Min: (" << mesh.aabb_min[0] << ", " << mesh.aabb_min[1] << ", " << mesh.aabb_min[2] << ")" << std::endl;
        std::cout << "          AABB Max: (" << mesh.aabb_max[0] << ", " << mesh.aabb_max[1] << ", " << mesh.aabb_max[2] << ")" << std::endl;
        // for (size_t j = 0; j < mesh.vertices.size(); ++j) {
        //     const auto& vertex = mesh.vertices[j];
        //     std::cout << "          Vertex " << j << ":" << std::endl;
        //     std::cout << "            Position: (" << vertex.position[0] << ", " << vertex.position[1] << ", " << vertex.position[2] << ")" << std::endl;
        //     std::cout << "            Normal:   (" << vertex.normal[0] << ", " << vertex.normal[1] << ", " << vertex.normal[2] << ")" << std::endl;
        //     std::cout << "            TexCoord: (" << vertex.tex_coords[0] << ", " << vertex.tex_coords[1] << ")" << std::endl;
        // }
    }

    std::cout << "      - " << total_indices / 3 << " triangles (total)" << std::endl;

    // 光照和相机
    if (!scene.data.lights.empty()) {
        std::cout << "    Lights: " << scene.data.lights.size() << std::endl;
    }
    if (!scene.data.cameras.empty()) {
        std::cout << "    Cameras: " << scene.data.cameras.size() << std::endl;
    }
}

int main(int argc, char* argv[]) {
    // Get singleton ResourceManager instance
    auto& mgr = Corona::Resource::ResourceManager::get_instance();

    // Register ImageParser for texture loading
    mgr.register_parser<Corona::Resource::ImageParser>();

    // Register SceneParser with ResourceManager to enable texture loading
    mgr.register_parser<Corona::Resource::SceneParser>();

    std::vector<std::filesystem::path> test_files = {
        // std::filesystem::path(CORONARESOURCE_SOURCE_DIR) / "examples/assets/test_assimp/DamagedHelmet/DamagedHelmet.usdz",
        // std::filesystem::path(CORONARESOURCE_SOURCE_DIR) / "examples/assets/test_assimp/Ball/Ball.usd",
        std::filesystem::path(CORONARESOURCE_SOURCE_DIR) / "examples/assets/test_assimp/old_stool/old_stool.obj",
        // std::filesystem::path(CORONARESOURCE_SOURCE_DIR) / "examples/assets/test_assimp/armadillo.obj",
        // std::filesystem::path(CORONARESOURCE_SOURCE_DIR) / "examples/assets/test_assimp/dancing_vampire.dae",
    };

    for (const auto& model_path : test_files) {
        std::cout << "\n========================================" << std::endl;
        std::cout << "Importing: " << model_path.filename() << std::endl;
        std::cout << "========================================" << std::endl;

        auto rid = mgr.import_async(model_path).get();

        if (rid == Corona::Resource::IResource::INVALID_UID) {
            std::cerr << "Failed to import resource." << std::endl;
            continue;
        }

        auto scene_handle = mgr.acquire_read<Corona::Resource::Scene>(rid);
        if (scene_handle) {
            std::cout << "Successfully loaded!" << std::endl;

            // 显示场景总结
            print_scene_summary(*scene_handle);

            // 显示纹理数据
            print_scene_textures(mgr, *scene_handle);

            // 导出场景
            std::filesystem::path export_path = std::filesystem::path(CORONARESOURCE_SOURCE_DIR) / "examples/assets/_generated" / (model_path.stem().string() + "_exported.obj");
            std::cout << "\n  Exporting scene to: " << export_path << std::endl;
            if (mgr.export_sync(rid, export_path)) {
                std::cout << "  Successfully exported scene!" << std::endl;
            } else {
                std::cerr << "  Failed to export scene." << std::endl;
            }

        } else {
            std::cerr << "Failed to acquire read handle." << std::endl;
        }
    }

    return 0;
}
