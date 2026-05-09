#include "corona/resource/types/scene.h"

#include <array>
#include <assimp/IOStream.hpp>
#include <assimp/IOSystem.hpp>
#include <assimp/Importer.hpp>
#include <cfloat>
#include <fstream>
#include <iostream>
#include <ranges>
#include <unordered_map>
#include <vector>

#include "corona/resource/types/image.h"
#include "parse_assimp.h"
#include "parse_usd.h"

#ifdef _WIN32
#include <Windows.h>
#endif

// ============================================================================
// 自定义 IOStream 和 IOSystem 实现
// 用于支持 Unicode 路径并正确解析 MTL 等外部引用文件
// ============================================================================

namespace {

/**
 * @brief 自定义 IOStream 实现，使用 std::ifstream 支持 Unicode 路径
 */
class UnicodeIOStream : public Assimp::IOStream {
   public:
    UnicodeIOStream(const std::filesystem::path& path, const char* mode)
        : m_path(path), m_size(0) {
        std::ios_base::openmode open_mode = std::ios::binary;
        if (mode[0] == 'r') {
            open_mode |= std::ios::in;
        }
        if (mode[0] == 'w' || (mode[0] == 'r' && mode[1] == '+')) {
            open_mode |= std::ios::out;
        }

        m_stream.open(path, open_mode);
        if (m_stream.is_open()) {
            m_stream.seekg(0, std::ios::end);
            m_size = static_cast<size_t>(m_stream.tellg());
            m_stream.seekg(0, std::ios::beg);
        }
    }

    ~UnicodeIOStream() override {
        if (m_stream.is_open()) {
            m_stream.close();
        }
    }

    bool IsOpen() const { return m_stream.is_open(); }

    size_t Read(void* pvBuffer, size_t pSize, size_t pCount) override {
        m_stream.read(static_cast<char*>(pvBuffer), static_cast<std::streamsize>(pSize * pCount));
        return static_cast<size_t>(m_stream.gcount()) / pSize;
    }

    size_t Write(const void* pvBuffer, size_t pSize, size_t pCount) override {
        m_stream.write(static_cast<const char*>(pvBuffer), static_cast<std::streamsize>(pSize * pCount));
        return m_stream.good() ? pCount : 0;
    }

    aiReturn Seek(size_t pOffset, aiOrigin pOrigin) override {
        std::ios_base::seekdir dir;
        switch (pOrigin) {
            case aiOrigin_SET:
                dir = std::ios::beg;
                break;
            case aiOrigin_CUR:
                dir = std::ios::cur;
                break;
            case aiOrigin_END:
                dir = std::ios::end;
                break;
            default:
                return aiReturn_FAILURE;
        }
        m_stream.seekg(static_cast<std::streamoff>(pOffset), dir);
        return m_stream.good() ? aiReturn_SUCCESS : aiReturn_FAILURE;
    }

    size_t Tell() const override {
        return static_cast<size_t>(const_cast<std::fstream&>(m_stream).tellg());
    }

    size_t FileSize() const override {
        return m_size;
    }

    void Flush() override {
        m_stream.flush();
    }

   private:
    std::filesystem::path m_path;
    std::fstream m_stream;
    size_t m_size;
};

/**
 * @brief 自定义 IOSystem 实现，支持 Unicode 路径和相对路径解析
 *
 * 这个 IOSystem 会将相对路径解析为相对于场景文件所在目录的绝对路径，
 * 从而让 Assimp 能够正确找到 MTL 文件等外部引用。
 */
class UnicodeIOSystem : public Assimp::IOSystem {
   public:
    explicit UnicodeIOSystem(const std::filesystem::path& base_dir)
        : m_base_dir(base_dir) {}

    bool Exists(const char* pFile) const override {
        std::filesystem::path resolved = resolve_path(pFile);
        return std::filesystem::exists(resolved);
    }

    char getOsSeparator() const override {
#ifdef _WIN32
        return '\\';
#else
        return '/';
#endif
    }

    Assimp::IOStream* Open(const char* pFile, const char* pMode = "rb") override {
        std::filesystem::path resolved = resolve_path(pFile);
        auto* stream = new UnicodeIOStream(resolved, pMode);
        if (!stream->IsOpen()) {
            delete stream;
            return nullptr;
        }
        return stream;
    }

    void Close(Assimp::IOStream* pFile) override {
        delete pFile;
    }

   private:
    /**
     * @brief 从 UTF-8 字符串构造 std::filesystem::path
     * 兼容 C++17 和 C++20，包含对非 UTF-8 编码（如 GBK）的容错处理
     */
    static std::filesystem::path path_from_utf8(const char* utf8_str) {
#ifdef _WIN32
        if (utf8_str == nullptr) return {};
        // Windows 上明确使用 WideCharToMultiByte 进行 UTF-8 到 UTF-16 的转换
        // 这样可以避免 MSVC std::filesystem::u8path 在某些系统区域设置下的潜在问题
        int wchars_num = MultiByteToWideChar(CP_UTF8, 0, utf8_str, -1, nullptr, 0);
        if (wchars_num > 0) {
            std::vector<wchar_t> wstr(wchars_num);
            MultiByteToWideChar(CP_UTF8, 0, utf8_str, -1, wstr.data(), wchars_num);
            // 移除可能包含的 null 终止符
            if (!wstr.empty() && wstr.back() == L'\0') {
                wstr.pop_back();
            }
            return std::filesystem::path(wstr.begin(), wstr.end());
        }
        // 如果 CP_UTF8 转换失败，尝试直接使用 ANSI 转换
        CFW_LOG_WARNING("Path conversion from UTF-8 failed (Win32), trying local encoding");
        return std::filesystem::path(utf8_str);
#else
        try {
#if __cplusplus >= 202002L || (defined(_MSVC_LANG) && _MSVC_LANG >= 202002L)
            // C++20: 使用 char8_t 构造函数
            return std::filesystem::path(reinterpret_cast<const char8_t*>(utf8_str));
#else
            // C++17: 使用 u8path
            return std::filesystem::u8path(utf8_str);
#endif
        } catch (const std::exception& e) {
            // 如果 UTF-8 转换失败（例如遇到了 GBK 编码的字符串），
            // 则尝试作为系统本地编码（ANSI）直接构造 path
            CFW_LOG_WARNING("Path conversion from UTF-8 failed: {}, trying local encoding", e.what());
            return std::filesystem::path(utf8_str);
        }
#endif
    }

    /**
     * @brief 解析路径，将相对路径转换为基于场景目录的绝对路径
     * @param pFile UTF-8 编码的路径字符串
     */
    std::filesystem::path resolve_path(const char* pFile) const {
        std::filesystem::path file_path = path_from_utf8(pFile);

        // 如果是绝对路径，直接返回
        if (file_path.is_absolute()) {
            return file_path;
        }

        // 相对路径：基于场景所在目录解析
        return m_base_dir / file_path;
    }

    std::filesystem::path m_base_dir;
};

}  // namespace

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
    int size = WideCharToMultiByte(CP_UTF8, 0, wstr.c_str(),
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

Scene::Scene(const std::filesystem::path& path) : IResource(path) {
}

std::string_view Scene::get_node_name(std::uint32_t node_idx) const {
    return data.nodes[node_idx].name;
}

std::string_view Scene::get_material_name(std::uint32_t mat_idx) const {
    return data.materials[mat_idx].name;
}

std::uint32_t Scene::add_node(std::string_view name, std::uint32_t parent) {
    auto new_index = static_cast<std::uint32_t>(data.nodes.size());
    data.nodes.emplace_back();
    NodeData& node = data.nodes.back();
    node.name = std::string{name};
    if (parent != InvalidIndex) {
        NodeData& p = data.nodes[parent];
        node.parent = &p;
        p.children.push_back(&node);
    }
    return new_index;
}

std::uint32_t Scene::add_mesh(MeshData&& mesh) {
    auto mesh_index = static_cast<std::uint32_t>(data.meshes.size());
    data.meshes.push_back(std::move(mesh));
    return mesh_index;
}

SceneParser::SceneParser() {
    register_extension(".usd", [this](const auto& path, ResourceCache& cache) { return parse_usd(path); });
    register_extension(".usda", [this](const auto& path, ResourceCache& cache) { return parse_usd(path); });
    register_extension(".usdc", [this](const auto& path, ResourceCache& cache) { return parse_usd(path); });
    register_extension(".usdz", [this](const auto& path, ResourceCache& cache) { return parse_usd(path); });

    register_extension(".fbx", [this](const auto& path, ResourceCache& cache) { return parse_assimp(path); });
    register_extension(".obj", [this](const auto& path, ResourceCache& cache) { return parse_assimp(path); });
    register_extension(".gltf", [this](const auto& path, ResourceCache& cache) { return parse_assimp(path); });
    register_extension(".glb", [this](const auto& path, ResourceCache& cache) { return parse_assimp(path); });
    register_extension(".dae", [this](const auto& path, ResourceCache& cache) { return parse_assimp(path); });
    // register_extension(".blend", [this](const auto& path, ResourceCache& cache) { return parse_assimp(path); });
    register_extension(".3ds", [this](const auto& path, ResourceCache& cache) { return parse_assimp(path); });
    // register_extension(".ply", [this](const auto& path, ResourceCache& cache) { return parse_assimp(path); });
    register_extension(".stl", [this](const auto& path, ResourceCache& cache) { return parse_assimp(path); });
}

std::shared_ptr<IResource> SceneParser::parse_usd(const std::filesystem::path& path) {
    // FIX: Convert path to UTF-8 for OpenUSD on Windows
    pxr::UsdStageRefPtr stage = pxr::UsdStage::Open(path_to_utf8(path));
    if (!stage) {
        CFW_LOG_ERROR("Failed to open USD stage: {}", path_to_utf8(path));
        return nullptr;
    }
    auto scene = std::make_shared<Scene>(path);
    std::filesystem::path scene_dir = path.parent_path();

    process_usd_scene(stage, *scene, scene_dir, usd_options);

    return scene;
}

std::shared_ptr<IResource> SceneParser::parse_assimp(const std::filesystem::path& path) {
    // 获取场景文件所在目录，用于解析相对路径引用（如 MTL 文件）
    std::filesystem::path scene_dir = path.parent_path();

    // 获取文件扩展名作为格式提示
    std::string extension = path.extension().string();

    Assimp::Importer importer;

    // 设置自定义 IOSystem 以支持 Unicode 路径并正确解析相对路径引用
    // 注意：Importer 会获取 IOSystem 的所有权，无需手动删除
    importer.SetIOHandler(new UnicodeIOSystem(scene_dir));

    // 注意：不再移除原始法线 (aiComponent_NORMALS)
    // 保留模型原始法线以保持艺术家设计的硬边/软边效果
    // aiProcess_GenSmoothNormals 只在模型没有法线时才会生成

    // 使用自定义 IOSystem 后，可以直接使用 ReadFile
    // 将路径转换为 UTF-8 字符串供 Assimp 使用
    // 注意：u8string() 返回的类型在 C++17 是 std::string，在 C++20 是 std::u8string
    auto path_u8 = path.u8string();
    std::string path_str(reinterpret_cast<const char*>(path_u8.data()), path_u8.size());
    const aiScene* ai_scene = importer.ReadFile(
        path_str,
        aiProcess_Triangulate |
            aiProcess_ValidateDataStructure |
            aiProcess_FindDegenerates |
            aiProcess_FindInvalidData |
            aiProcess_RemoveComponent |
            aiProcess_GenSmoothNormals |
            aiProcess_JoinIdenticalVertices |
            aiProcess_SortByPType |
            aiProcess_FlipUVs |
            aiProcess_GenBoundingBoxes |
            aiProcess_MakeLeftHanded |    // 转换为左手坐标系
            aiProcess_FlipWindingOrder);  // 翻转三角形绕序以匹配左手坐标系

    if (!ai_scene || ai_scene->mFlags & AI_SCENE_FLAGS_INCOMPLETE || !ai_scene->mRootNode) {
        CFW_LOG_ERROR("[Assimp] Failed to load scene: {}", path_to_utf8(path));
        CFW_LOG_ERROR("[Assimp] Error: {}", importer.GetErrorString());
        return nullptr;
    }

    // === 调试日志：场景概览 ===
    CFW_LOG_INFO("[Assimp] Loading scene: {}", path_to_utf8(path));
    CFW_LOG_INFO("[Assimp] Scene stats: {} meshes, {} materials, {} textures",
                 ai_scene->mNumMeshes, ai_scene->mNumMaterials, ai_scene->mNumTextures);

    // === 调试日志：列出所有材质 ===
    CFW_LOG_INFO("[Assimp] Materials in scene:");
    for (unsigned int i = 0; i < ai_scene->mNumMaterials; ++i) {
        aiString name;
        ai_scene->mMaterials[i]->Get(AI_MATKEY_NAME, name);
        CFW_LOG_INFO("  [{}] {}", i, name.C_Str());
    }

    // === 调试日志：列出所有Mesh及其材质索引 ===
    CFW_LOG_INFO("[Assimp] Meshes in scene:");
    for (unsigned int i = 0; i < ai_scene->mNumMeshes; ++i) {
        aiMesh* mesh = ai_scene->mMeshes[i];
        CFW_LOG_INFO("  [{}] '{}': {} verts, {} faces, materialIndex={}",
                     i, mesh->mName.C_Str(), mesh->mNumVertices, mesh->mNumFaces, mesh->mMaterialIndex);
    }

    auto scene = std::make_shared<Scene>(path);
    std::vector<std::uint32_t> material_map;

    process_assimp_materials(ai_scene, *scene, material_map, scene_dir, path, assimp_options.image_options);

    // 创建初始变换矩阵，用于处理不同格式的坐标系差异
    // STL 格式通常使用 Z-up 坐标系，需要旋转到 Y-up
    aiMatrix4x4 initial_transform;
    if (extension == ".stl") {
        // 绕 X 轴旋转 -90 度（将 Z-up 转换为 Y-up）
        // cos(-90°) = 0, sin(-90°) = -1
        // 旋转矩阵：
        // [1,  0,    0,   0]
        // [0,  0,    1,   0]  (原 Z 变成新 Y)
        // [0, -1,    0,   0]  (原 Y 变成新 -Z)
        // [0,  0,    0,   1]
        initial_transform = aiMatrix4x4(
            1.0f, 0.0f, 0.0f, 0.0f,
            0.0f, 0.0f, -1.0f, 0.0f,
            0.0f, 1.0f, 0.0f, 0.0f,
            0.0f, 0.0f, 0.0f, 1.0f);
        CFW_LOG_INFO("[Assimp] STL format detected, applying Z-up to Y-up coordinate transform");
    }

    // 计算全局归一化参数，确保所有子网格使用相同的变换
    GlobalNormalizationParams global_params = compute_global_normalization_params(ai_scene, initial_transform);
    process_assimp_node(ai_scene->mRootNode, ai_scene, *scene, InvalidIndex, material_map, global_params, initial_transform, assimp_options);

    std::unordered_map<std::string, std::uint32_t> node_name_map;

    build_node_name_map(*scene, node_name_map);
    process_assimp_lights(ai_scene, *scene, node_name_map);
    process_assimp_cameras(ai_scene, *scene, node_name_map);

    return scene;
}

const std::vector<Vertex>& Scene::get_mesh_vertices(std::uint32_t mesh_idx) const {
    return data.meshes[mesh_idx].vertices;
}

const std::vector<std::uint16_t>& Scene::get_mesh_indices(std::uint32_t mesh_idx) const {
    return data.meshes[mesh_idx].indices;
}

const Vertex& Scene::get_vertex_global(std::uint32_t mesh_idx, std::uint16_t local_index) const {
    return data.meshes[mesh_idx].vertices[local_index];
}

std::uint32_t Scene::get_mesh_lod_count(std::uint32_t mesh_idx) const {
    return static_cast<std::uint32_t>(data.meshes[mesh_idx].lod_levels.size());
}

const LODLevel& Scene::get_mesh_lod(std::uint32_t mesh_idx, std::uint32_t lod_level) const {
    return data.meshes[mesh_idx].lod_levels[lod_level];
}

AABB Scene::get_scene_aabb() const {
    if (data.meshes.empty()) {
        return AABB{};  // 返回全零 AABB
    }

    std::array<float, 3> scene_min = {FLT_MAX, FLT_MAX, FLT_MAX};
    std::array<float, 3> scene_max = {-FLT_MAX, -FLT_MAX, -FLT_MAX};

    for (const auto& mesh : data.meshes) {
        scene_min[0] = std::min(scene_min[0], mesh.aabb_min[0]);
        scene_min[1] = std::min(scene_min[1], mesh.aabb_min[1]);
        scene_min[2] = std::min(scene_min[2], mesh.aabb_min[2]);

        scene_max[0] = std::max(scene_max[0], mesh.aabb_max[0]);
        scene_max[1] = std::max(scene_max[1], mesh.aabb_max[1]);
        scene_max[2] = std::max(scene_max[2], mesh.aabb_max[2]);
    }

    return AABB{scene_min, scene_max};
}

}  // namespace Corona::Resource
