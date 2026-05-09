//
// Created by Administrator on 2025/12/2.
//
#pragma once

#include <pxr/base/gf/matrix4d.h>
#include <pxr/base/gf/rotation.h>
#include <pxr/base/gf/vec2f.h>
#include <pxr/base/gf/vec3d.h>
#include <pxr/base/gf/vec3f.h>
#include <pxr/base/vt/array.h>
#include <pxr/usd/sdf/assetPath.h>
#include <pxr/usd/sdf/layer.h>
#include <pxr/usd/sdf/path.h>
#include <pxr/usd/usd/attribute.h>
#include <pxr/usd/usd/prim.h>
#include <pxr/usd/usd/primRange.h>
#include <pxr/usd/usd/stage.h>
#include <pxr/usd/usd/timeCode.h>
#include <pxr/usd/usd/variantSets.h>
#include <pxr/usd/usdGeom/camera.h>
#include <pxr/usd/usdGeom/mesh.h>
#include <pxr/usd/usdGeom/metrics.h>
#include <pxr/usd/usdGeom/primvarsAPI.h>
#include <pxr/usd/usdGeom/tokens.h>
#include <pxr/usd/usdGeom/xform.h>
#include <pxr/usd/usdGeom/xformCommonAPI.h>
#include <pxr/usd/usdLux/diskLight.h>
#include <pxr/usd/usdLux/distantLight.h>
#include <pxr/usd/usdLux/rectLight.h>
#include <pxr/usd/usdLux/sphereLight.h>
#include <pxr/usd/usdShade/material.h>
#include <pxr/usd/usdShade/materialBindingAPI.h>
#include <pxr/usd/usdShade/shader.h>

#include <ranges>

#include "corona/resource/resource_manager.h"
#include "corona/resource/types/image.h"
#include "parse_common.h"

namespace Corona::Resource {

namespace UsdTokens {
inline const pxr::TfToken kSt{"st"};
inline const pxr::TfToken kUv{"uv"};
inline const pxr::TfToken kFile{"file"};
inline const pxr::TfToken kDiffuseColor{"diffuseColor"};
inline const pxr::TfToken kMetallic{"metallic"};
inline const pxr::TfToken kRoughness{"roughness"};
inline const pxr::TfToken kNormal{"normal"};
inline const pxr::TfToken kOpacity{"opacity"};                     // 透明度
inline const pxr::TfToken kOpacityThreshold{"opacityThreshold"};   // Alpha 测试阈值
inline const pxr::TfToken kDisplayColor{"primvars:displayColor"};  // USD 顶点颜色属性
inline const pxr::TfToken kFilename{"filename"};
inline const pxr::TfToken kUsdUVTexture{"UsdUVTexture"};
}  // namespace UsdTokens

// Note: TextureCache is now defined in parse_common.h

// USD-specific global normalization parameters (extends common base)
struct UsdGlobalNormalizationParams : public GlobalNormalizationParams {
    bool is_z_up = false;  // 是否为 Z-up 坐标系，需要转换到 Y-up
};

// 计算场景中所有网格的全局 AABB（在世界空间）
inline UsdGlobalNormalizationParams compute_usd_global_normalization_params(
    const pxr::UsdStageRefPtr& stage) {
    UsdGlobalNormalizationParams params;
    std::array<float, 3> global_min = {FLT_MAX, FLT_MAX, FLT_MAX};
    std::array<float, 3> global_max = {-FLT_MAX, -FLT_MAX, -FLT_MAX};

    // 检测 USD 场景的上轴（upAxis）
    pxr::TfToken up_axis = pxr::UsdGeomGetStageUpAxis(stage);
    params.is_z_up = (up_axis == pxr::UsdGeomTokens->z);
    if (params.is_z_up) {
        CFW_LOG_INFO("[USD] Detected Z-up coordinate system, will convert to Y-up");
    } else {
        CFW_LOG_INFO("[USD] Detected Y-up coordinate system (or default)");
    }

    // 使用 UsdTraverseInstanceProxies 确保能遍历到实例中的 Mesh，从而正确计算全局包围盒
    for (const pxr::UsdPrim& prim : stage->Traverse(pxr::UsdTraverseInstanceProxies(pxr::UsdPrimDefaultPredicate))) {
        if (!prim.IsA<pxr::UsdGeomMesh>()) continue;

        pxr::UsdGeomMesh mesh(prim);
        pxr::VtArray<pxr::GfVec3f> points;
        mesh.GetPointsAttr().Get(&points, pxr::UsdTimeCode::Default());

        // 获取世界变换矩阵
        pxr::GfMatrix4d world_matrix = mesh.ComputeLocalToWorldTransform(pxr::UsdTimeCode::Default());

        for (const auto& point : points) {
            pxr::GfVec3d world_pos = world_matrix.Transform(pxr::GfVec3d(point[0], point[1], point[2]));
            global_min[0] = std::min(global_min[0], static_cast<float>(world_pos[0]));
            global_min[1] = std::min(global_min[1], static_cast<float>(world_pos[1]));
            global_min[2] = std::min(global_min[2], static_cast<float>(world_pos[2]));
            global_max[0] = std::max(global_max[0], static_cast<float>(world_pos[0]));
            global_max[1] = std::max(global_max[1], static_cast<float>(world_pos[1]));
            global_max[2] = std::max(global_max[2], static_cast<float>(world_pos[2]));
        }
    }

    // 使用公共函数计算归一化参数
    finalize_normalization_params(params, global_min, global_max, "USD");

    return params;
}

inline Transform extract_usd_transform(const pxr::UsdGeomXformable& xformable) {
    Transform transform;

    pxr::GfMatrix4d local_matrix{};
    bool reset_xform_stack = false;
    xformable.GetLocalTransformation(&local_matrix, &reset_xform_stack, pxr::UsdTimeCode::Default());

    pxr::GfVec3d translation = local_matrix.ExtractTranslation();
    transform.position = {static_cast<float>(translation[0]),
                          static_cast<float>(translation[1]),
                          static_cast<float>(translation[2])};

    pxr::GfRotation rotation = local_matrix.ExtractRotation();
    pxr::GfVec3d euler = rotation.Decompose(pxr::GfVec3d::XAxis(),
                                            pxr::GfVec3d::YAxis(),
                                            pxr::GfVec3d::ZAxis());
    transform.rotation = {static_cast<float>(euler[0]),
                          static_cast<float>(euler[1]),
                          static_cast<float>(euler[2])};

    pxr::GfVec3d scale{};
    for (int i = 0; i < 3; ++i) {
        pxr::GfVec3d col(local_matrix[0][i], local_matrix[1][i], local_matrix[2][i]);
        scale[i] = col.GetLength();
    }
    transform.scale = {static_cast<float>(scale[0]),
                       static_cast<float>(scale[1]),
                       static_cast<float>(scale[2])};

    return transform;
}

inline void process_usd_mesh(const pxr::UsdGeomMesh& usd_mesh, Scene& scene,
                             std::uint32_t node_index,
                             std::unordered_map<std::string, std::uint32_t>& material_map,
                             const UsdGlobalNormalizationParams& global_params,
                             const UsdImportOptions& options = UsdImportOptions{}) {
    std::string mesh_name = usd_mesh.GetPrim().GetName().GetString();

    pxr::VtArray<pxr::GfVec3f> points;
    pxr::VtArray<pxr::GfVec3f> normals;
    pxr::VtArray<int> face_vertex_counts;
    pxr::VtArray<int> face_vertex_indices;

    usd_mesh.GetPointsAttr().Get(&points, pxr::UsdTimeCode::Default());
    usd_mesh.GetNormalsAttr().Get(&normals, pxr::UsdTimeCode::Default());
    usd_mesh.GetFaceVertexCountsAttr().Get(&face_vertex_counts, pxr::UsdTimeCode::Default());
    usd_mesh.GetFaceVertexIndicesAttr().Get(&face_vertex_indices, pxr::UsdTimeCode::Default());

    if (points.empty() || face_vertex_indices.empty()) {
        CFW_LOG_WARNING("[USD] Mesh '{}' is empty, skipping", mesh_name);
        return;
    }

    pxr::VtArray<pxr::GfVec2f> uvs;
    pxr::UsdGeomPrimvarsAPI primvars_api(usd_mesh);
    pxr::UsdGeomPrimvar st_primvar = primvars_api.GetPrimvar(UsdTokens::kSt);
    if (!st_primvar) {
        st_primvar = primvars_api.GetPrimvar(UsdTokens::kUv);
    }
    if (st_primvar) {
        st_primvar.Get(&uvs, pxr::UsdTimeCode::Default());
    }

    std::uint32_t material_index = InvalidIndex;
    // 先检查并应用 MaterialBindingAPI，避免 USD 警告
    if (pxr::UsdShadeMaterialBindingAPI::CanApply(usd_mesh.GetPrim())) {
        pxr::UsdShadeMaterialBindingAPI::Apply(usd_mesh.GetPrim());
    }
    pxr::UsdShadeMaterialBindingAPI binding_api(usd_mesh.GetPrim());
    if (pxr::UsdShadeMaterial bound_material = binding_api.ComputeBoundMaterial()) {
        std::string mat_path = bound_material.GetPath().GetString();
        auto it = material_map.find(mat_path);
        if (it != material_map.end()) {
            material_index = it->second;
        }
    }

    // 如果没有绑定材质，尝试从 displayColor primvar 创建材质
    if (material_index == InvalidIndex) {
        pxr::VtArray<pxr::GfVec3f> display_colors;
        pxr::UsdGeomPrimvar display_color_primvar = primvars_api.GetPrimvar(UsdTokens::kDisplayColor);
        if (display_color_primvar && display_color_primvar.Get(&display_colors, pxr::UsdTimeCode::Default())) {
            if (!display_colors.empty()) {
                // 使用第一个颜色值作为整个网格的基础颜色
                pxr::GfVec3f color = display_colors[0];

                // 生成基于颜色的唯一材质键
                std::string color_key = std::format("displayColor_{:.3f}_{:.3f}_{:.3f}",
                                                    color[0], color[1], color[2]);

                auto it = material_map.find(color_key);
                if (it != material_map.end()) {
                    material_index = it->second;
                } else {
                    // 创建新材质
                    MaterialData mat_data;
                    mat_data.name = color_key;
                    mat_data.base_color = {color[0], color[1], color[2], 1.0f};
                    mat_data.roughness = 0.5f;
                    mat_data.metallic = 0.0f;
                    mat_data.albedo_texture = get_or_create_default_white_texture();

                    material_index = static_cast<std::uint32_t>(scene.data.materials.size());
                    material_map[color_key] = material_index;
                    scene.data.materials.emplace_back(std::move(mat_data));

                    CFW_LOG_DEBUG("[USD] Mesh '{}': created material from displayColor ({}, {}, {})",
                                  mesh_name, color[0], color[1], color[2]);
                }
            }
        }
    }

    // 获取世界变换矩阵
    pxr::GfMatrix4d world_matrix = usd_mesh.ComputeLocalToWorldTransform(pxr::UsdTimeCode::Default());

    // 提取法线变换矩阵（世界变换的逆转置的3x3部分）
    pxr::GfMatrix4d normal_matrix = world_matrix.GetInverse().GetTranspose();

    bool has_per_vertex_normals = (normals.size() == points.size());
    bool has_per_face_normals = (normals.size() == face_vertex_indices.size());
    bool has_per_vertex_uvs = (uvs.size() == points.size());
    bool has_per_face_uvs = (uvs.size() == face_vertex_indices.size());

    std::vector<Vertex> unindexed_vertices;
    std::vector<std::uint32_t> indices;

    if (has_per_face_normals || has_per_face_uvs) {
        // 按面属性展开顶点
        size_t index_offset = 0;
        for (int vertex_count : face_vertex_counts) {
            if (vertex_count < 3) {
                index_offset += vertex_count;
                continue;
            }

            for (int i = 1; i < vertex_count - 1; ++i) {
                int pos_idx0 = face_vertex_indices[index_offset];
                int pos_idx1 = face_vertex_indices[index_offset + i];
                int pos_idx2 = face_vertex_indices[index_offset + i + 1];

                size_t attr_idx0 = index_offset;
                size_t attr_idx1 = index_offset + i;
                size_t attr_idx2 = index_offset + i + 1;

                for (int v = 0; v < 3; ++v) {
                    int pos_idx = (v == 0) ? pos_idx0 : (v == 1) ? pos_idx1
                                                                 : pos_idx2;
                    size_t attr_idx = (v == 0) ? attr_idx0 : (v == 1) ? attr_idx1
                                                                      : attr_idx2;

                    Vertex vertex;

                    // 将顶点位置变换到世界空间
                    if (options.apply_world_transform) {
                        pxr::GfVec3d world_pos = world_matrix.Transform(
                            pxr::GfVec3d(points[pos_idx][0], points[pos_idx][1], points[pos_idx][2]));
                        vertex.position = {static_cast<float>(world_pos[0]),
                                           static_cast<float>(world_pos[1]),
                                           static_cast<float>(world_pos[2])};
                    } else {
                        vertex.position = {points[pos_idx][0], points[pos_idx][1], points[pos_idx][2]};
                    }

                    // 处理法线
                    if (has_per_face_normals && attr_idx < normals.size()) {
                        if (options.apply_world_transform) {
                            pxr::GfVec3d world_normal = normal_matrix.TransformDir(
                                pxr::GfVec3d(normals[attr_idx][0], normals[attr_idx][1], normals[attr_idx][2]));
                            world_normal.Normalize();
                            vertex.normal = {static_cast<float>(world_normal[0]),
                                             static_cast<float>(world_normal[1]),
                                             static_cast<float>(world_normal[2])};
                        } else {
                            vertex.normal = {normals[attr_idx][0], normals[attr_idx][1], normals[attr_idx][2]};
                        }
                    } else if (has_per_vertex_normals && pos_idx < static_cast<int>(normals.size())) {
                        if (options.apply_world_transform) {
                            pxr::GfVec3d world_normal = normal_matrix.TransformDir(
                                pxr::GfVec3d(normals[pos_idx][0], normals[pos_idx][1], normals[pos_idx][2]));
                            world_normal.Normalize();
                            vertex.normal = {static_cast<float>(world_normal[0]),
                                             static_cast<float>(world_normal[1]),
                                             static_cast<float>(world_normal[2])};
                        } else {
                            vertex.normal = {normals[pos_idx][0], normals[pos_idx][1], normals[pos_idx][2]};
                        }
                    }

                    // 处理UV
                    if (has_per_face_uvs && attr_idx < uvs.size()) {
                        vertex.tex_coords = {uvs[attr_idx][0], uvs[attr_idx][1]};
                    } else if (has_per_vertex_uvs && pos_idx < static_cast<int>(uvs.size())) {
                        vertex.tex_coords = {uvs[pos_idx][0], uvs[pos_idx][1]};
                    }

                    indices.push_back(static_cast<std::uint32_t>(unindexed_vertices.size()));
                    unindexed_vertices.push_back(vertex);
                }
            }

            index_offset += vertex_count;
        }
    } else {
        // 按顶点属性处理
        unindexed_vertices.reserve(points.size());
        for (size_t i = 0; i < points.size(); ++i) {
            Vertex v;

            // 将顶点位置变换到世界空间
            if (options.apply_world_transform) {
                pxr::GfVec3d world_pos = world_matrix.Transform(
                    pxr::GfVec3d(points[i][0], points[i][1], points[i][2]));
                v.position = {static_cast<float>(world_pos[0]),
                              static_cast<float>(world_pos[1]),
                              static_cast<float>(world_pos[2])};
            } else {
                v.position = {points[i][0], points[i][1], points[i][2]};
            }

            // 处理法线
            if (has_per_vertex_normals && i < normals.size()) {
                if (options.apply_world_transform) {
                    pxr::GfVec3d world_normal = normal_matrix.TransformDir(
                        pxr::GfVec3d(normals[i][0], normals[i][1], normals[i][2]));
                    world_normal.Normalize();
                    v.normal = {static_cast<float>(world_normal[0]),
                                static_cast<float>(world_normal[1]),
                                static_cast<float>(world_normal[2])};
                } else {
                    v.normal = {normals[i][0], normals[i][1], normals[i][2]};
                }
            }

            // 处理UV
            if (has_per_vertex_uvs && i < uvs.size()) {
                v.tex_coords = {uvs[i][0], uvs[i][1]};
            }

            unindexed_vertices.push_back(v);
        }

        // 构建索引
        size_t index_offset = 0;
        for (int vertex_count : face_vertex_counts) {
            if (vertex_count < 3) {
                index_offset += vertex_count;
                continue;
            }

            for (int i = 1; i < vertex_count - 1; ++i) {
                indices.push_back(static_cast<std::uint32_t>(face_vertex_indices[index_offset]));
                indices.push_back(static_cast<std::uint32_t>(face_vertex_indices[index_offset + i]));
                indices.push_back(static_cast<std::uint32_t>(face_vertex_indices[index_offset + i + 1]));
            }

            index_offset += vertex_count;
        }
    }

    CFW_LOG_DEBUG("[USD] Mesh '{}' loaded: {} vertices, {} indices",
                  mesh_name, unindexed_vertices.size(), indices.size());

    // =========================================================================
    // Phase 1: 数据验证与清理
    // =========================================================================

    // 1. 验证并修复 NaN/Inf 数据
    if (options.validate_data) {
        validate_and_fix_vertices(unindexed_vertices, mesh_name);
    }

    // 2. 移除退化三角形
    if (options.remove_degenerate_triangles) {
        remove_degenerate_triangles(unindexed_vertices, indices,
                                    options.degenerate_area_threshold, mesh_name);

        // 如果所有三角形都被移除，跳过此网格
        if (indices.empty()) {
            CFW_LOG_WARNING("[USD] Mesh '{}': all triangles are degenerate, skipping", mesh_name);
            return;
        }
    }

    // 3. 法线处理
    if (options.always_regenerate_normals) {
        // 强制重新生成所有法线
        generate_smooth_normals(unindexed_vertices, indices, mesh_name);
    } else if (options.generate_normals_if_missing && vertices_need_normals(unindexed_vertices)) {
        // 仅在缺失时生成法线
        generate_smooth_normals(unindexed_vertices, indices, mesh_name);
    } else {
        // 确保现有法线都是有效的单位向量
        validate_and_fix_normals(unindexed_vertices, mesh_name);
    }

    // =========================================================================
    // Phase 2: UV 处理
    // =========================================================================
    if (options.flip_uvs) {
        flip_uv_v_coordinate(unindexed_vertices, mesh_name);
    }

    // =========================================================================
    // 使用公共优化流水线
    // =========================================================================
    MeshOptimizeResult opt_result = optimize_mesh_pipeline(
        unindexed_vertices,
        indices,
        options.simplify_mesh,
        options.simplification_error,
        mesh_name);

    if (!opt_result.success) {
        CFW_LOG_WARNING("[USD] Mesh '{}' optimization failed, skipping", mesh_name);
        return;
    }

    // 使用全局归一化参数
    const std::array<float, 3>& center = global_params.center;
    float scale_factor = global_params.scale_factor;

    // =========================================================================
    // 坐标系转换配置
    // =========================================================================
    bool need_coordinate_fix = global_params.is_z_up && options.convert_to_engine_coords;

    // 配置坐标系转换
    CoordinateSystemConfig coord_config;
    coord_config.is_z_up = need_coordinate_fix;
    coord_config.flip_winding = options.flip_winding_order;

    // 处理单个网格的 lambda
    auto process_single_mesh = [&](std::vector<Vertex>& vertices,
                                   std::vector<std::uint32_t>& mesh_indices,
                                   const std::string& sub_mesh_name) {
        if (vertices.empty()) return;

        // 计算原始 AABB
        std::array<float, 3> aabb_min, aabb_max;
        compute_aabb(vertices, aabb_min, aabb_max);

        // 应用坐标系转换（包含归一化）
        apply_coordinate_system_transform(
            vertices,
            center,
            scale_factor,
            coord_config,
            sub_mesh_name);

        // 转换为 uint16 索引
        std::vector<std::uint16_t> final_indices = convert_indices_to_uint16(mesh_indices);

        // 如果应用了坐标系转换且需要翻转绕序
        if (need_coordinate_fix && options.flip_winding_order) {
            flip_triangle_winding_order(final_indices, sub_mesh_name);
        }

        // 重新计算 AABB (基于变换后的顶点)
        compute_aabb(vertices, aabb_min, aabb_max);

        CFW_LOG_DEBUG("[USD] Mesh '{}' assigned vertices {}, indices {}, material index {}",
                      sub_mesh_name,
                      vertices.size(),
                      final_indices.size(),
                      material_index);

        // 构建 MeshData
        MeshData mesh_data = build_mesh_data(
            std::move(vertices),
            std::move(final_indices),
            material_index,
            aabb_min,
            aabb_max,
            center,
            scale_factor);

        // 生成 LOD
        if (options.lod_options.enabled) {
            mesh_data.lod_levels = generate_lod_levels(
                mesh_data.vertices,
                mesh_data.indices,
                options.lod_options,
                sub_mesh_name);
        }

        std::uint32_t mesh_idx = scene.add_mesh(std::move(mesh_data));

        // 只有第一个子网格绑定到当前节点
        if (scene.data.nodes[node_index].mesh_index == InvalidIndex) {
            scene.data.nodes[node_index].mesh_index = mesh_idx;
        } else {
            // 为后续子网格创建新节点（作为当前节点的子节点）
            std::uint32_t sub_node_index = scene.add_node(sub_mesh_name, node_index);
            scene.data.nodes[sub_node_index].mesh_index = mesh_idx;
            // 子网格使用单位变换（因为它们已经在父节点的坐标系中）
            scene.data.nodes[sub_node_index].transform = Transform{};
        }
    };

    if (opt_result.was_split) {
        // 处理拆分的子网格
        for (size_t i = 0; i < opt_result.sub_meshes.size(); ++i) {
            auto& sub_mesh = opt_result.sub_meshes[i];
            std::string sub_mesh_name = mesh_name + "_split" + std::to_string(i);
            process_single_mesh(sub_mesh.vertices, sub_mesh.indices, sub_mesh_name);
        }
    } else {
        // 处理单个网格（检查顶点数量）
        if (opt_result.vertices.size() > 65535) {
            CFW_LOG_ERROR("[USD] Mesh '{}' has {} vertices, which exceeds the uint16 limit. Skipping to prevent device loss.",
                          mesh_name, opt_result.vertices.size());
            return;
        }
        process_single_mesh(opt_result.vertices, opt_result.indices, mesh_name);
    }
}

inline void process_usd_light(const pxr::UsdPrim& prim, Scene& scene, std::uint32_t node_index) {
    LightData light;

    if (prim.IsA<pxr::UsdLuxSphereLight>()) {
        // 点光源 (SphereLight)
        pxr::UsdLuxSphereLight sphere_light(prim);
        light.type = LightData::LightType::Point;

        float radius = 1.0f;
        sphere_light.GetRadiusAttr().Get(&radius, pxr::UsdTimeCode::Default());
        light.radius = radius;

    } else if (prim.IsA<pxr::UsdLuxDistantLight>()) {
        // 平行光 (DistantLight) - 即方向光
        pxr::UsdLuxDistantLight distant_light(prim);
        light.type = LightData::LightType::Directional;

    } else if (prim.IsA<pxr::UsdLuxRectLight>()) {
        // 矩形光 (RectLight) - 区域光
        pxr::UsdLuxRectLight rect_light(prim);
        light.type = LightData::LightType::Area;

        float width = 1.0f, height = 1.0f;
        rect_light.GetWidthAttr().Get(&width, pxr::UsdTimeCode::Default());
        rect_light.GetHeightAttr().Get(&height, pxr::UsdTimeCode::Default());
        light.size = {width, height};

    } else if (prim.IsA<pxr::UsdLuxDiskLight>()) {
        // 圆盘光 (DiskLight) - 视为区域光
        pxr::UsdLuxDiskLight disk_light(prim);
        light.type = LightData::LightType::Area;

        float radius = 1.0f;
        disk_light.GetRadiusAttr().Get(&radius, pxr::UsdTimeCode::Default());
        light.size = {radius * 2.0f, radius * 2.0f};

    } else {
        return;
    }

    // 获取通用光照属性 (强度和颜色)
    pxr::UsdLuxLightAPI light_api(prim);
    if (light_api) {
        float intensity = 1.0f;
        light_api.GetIntensityAttr().Get(&intensity, pxr::UsdTimeCode::Default());
        light.intensity = intensity;

        pxr::GfVec3f color(1.0f);
        light_api.GetColorAttr().Get(&color, pxr::UsdTimeCode::Default());
        light.color = {color[0], color[1], color[2]};
    }

    auto light_index = static_cast<std::uint32_t>(scene.data.lights.size());
    scene.data.lights.emplace_back(light);
    scene.data.nodes[node_index].light_index = light_index;
}

inline void process_usd_camera(const pxr::UsdGeomCamera& usd_camera, Scene& scene, std::uint32_t node_index) {
    CameraData camera;

    float focal_length = 50.0f;
    usd_camera.GetFocalLengthAttr().Get(&focal_length, pxr::UsdTimeCode::Default());

    float horizontal_aperture = 36.0f;
    usd_camera.GetHorizontalApertureAttr().Get(&horizontal_aperture, pxr::UsdTimeCode::Default());

    camera.fov = 2.0f * std::atan(horizontal_aperture / (2.0f * focal_length)) * 180.0f / 3.14159265f;

    pxr::GfVec2f clipping_range(0.1f, 10000.0f);
    usd_camera.GetClippingRangeAttr().Get(&clipping_range, pxr::UsdTimeCode::Default());
    camera.near_clip = clipping_range[0];
    camera.far_clip = clipping_range[1];

    float vertical_aperture = 24.0f;
    usd_camera.GetVerticalApertureAttr().Get(&vertical_aperture, pxr::UsdTimeCode::Default());
    camera.aspect_ratio = horizontal_aperture / vertical_aperture;

    auto camera_index = static_cast<std::uint32_t>(scene.data.cameras.size());
    scene.data.cameras.emplace_back(camera);
    scene.data.nodes[node_index].camera_index = camera_index;
}

inline std::uint64_t load_usd_texture(const pxr::UsdShadeInput& input,
                                      const std::filesystem::path& scene_dir,
                                      TextureCache& texture_cache) {
    if (!input) return InvalidTextureId;

    pxr::UsdShadeConnectableAPI source;
    pxr::TfToken source_name;
    pxr::UsdShadeAttributeType source_type;

    if (!pxr::UsdShadeConnectableAPI::GetConnectedSource(input, &source, &source_name, &source_type)) {
        return InvalidTextureId;
    }

    pxr::UsdShadeShader shader(source.GetPrim());
    if (!shader) return InvalidTextureId;

    pxr::TfToken shader_id;
    shader.GetIdAttr().Get(&shader_id);

    if (shader_id != UsdTokens::kUsdUVTexture) {
        return InvalidTextureId;
    }

    pxr::UsdShadeInput file_input = shader.GetInput(UsdTokens::kFile);
    if (!file_input) return InvalidTextureId;

    pxr::SdfAssetPath asset_path;
    if (!file_input.Get(&asset_path)) return InvalidTextureId;

    std::string resolved_path = asset_path.GetResolvedPath();
    if (resolved_path.empty()) {
        resolved_path = asset_path.GetAssetPath();
        if (!resolved_path.empty() && resolved_path[0] != '/' && resolved_path[1] != ':') {
            resolved_path = (scene_dir / resolved_path).string();
        }
    }

    if (resolved_path.empty()) {
        return InvalidTextureId;
    }

    auto cache_it = texture_cache.find(resolved_path);
    if (cache_it != texture_cache.end()) {
        return cache_it->second;
    }

    ImageParser image_parser;
    auto image = image_parser.parse_usd_asset(resolved_path);
    if (!image) {
        return InvalidTextureId;
    }

    TResourceID tex_id = image->get_uid();
    texture_cache[resolved_path] = tex_id;

    ResourceManager::get_instance().add_resource(tex_id, image);

    return tex_id;
}

inline std::uint64_t load_custom_texture(const pxr::UsdPrim& prim,
                                         const std::filesystem::path& scene_dir,
                                         TextureCache& texture_cache) {
    pxr::UsdAttribute filename_attr = prim.GetAttribute(UsdTokens::kFilename);
    if (!filename_attr) return InvalidTextureId;

    std::string filename;
    if (!filename_attr.Get(&filename)) return InvalidTextureId;
    if (filename.empty()) return InvalidTextureId;

    std::filesystem::path tex_path = scene_dir / filename;
    if (tex_path.extension() == ".tex") {
        for (const auto& ext : {".jpg", ".png", ".jpeg", ".tga", ".bmp", ".hdr", ".exr"}) {
            std::filesystem::path try_path = tex_path;
            try_path.replace_extension(ext);
            if (std::filesystem::exists(try_path)) {
                tex_path = try_path;
                break;
            }
        }
    }

    if (!std::filesystem::exists(tex_path)) {
        return InvalidTextureId;
    }

    std::string path_str = tex_path.string();
    auto cache_it = texture_cache.find(path_str);
    if (cache_it != texture_cache.end()) {
        return cache_it->second;
    }

    ImageParser image_parser;
    auto image = image_parser.parse_usd_asset(path_str);
    if (!image) {
        return InvalidTextureId;
    }

    TResourceID tex_id = image->get_uid();
    texture_cache[path_str] = tex_id;

    ResourceManager::get_instance().add_resource(tex_id, image);

    return tex_id;
}

inline std::uint64_t find_and_load_material_texture(const pxr::UsdPrim& material_prim,
                                                    const std::filesystem::path& scene_dir,
                                                    TextureCache& texture_cache) {
    for (const auto& child : material_prim.GetChildren()) {
        std::uint64_t tex_id = load_custom_texture(child, scene_dir, texture_cache);
        if (tex_id != InvalidTextureId) {
            return tex_id;
        }
        tex_id = find_and_load_material_texture(child, scene_dir, texture_cache);
        if (tex_id != InvalidTextureId) {
            return tex_id;
        }
    }
    return InvalidTextureId;
}

// ============================================================================
// Material Extraction Helper
// ============================================================================
inline MaterialData extract_material_data(const pxr::UsdShadeMaterial& material,
                                          const pxr::UsdPrim& prim,
                                          const std::filesystem::path& scene_dir,
                                          TextureCache& texture_cache,
                                          const std::string& name_suffix = "") {
    MaterialData mat_data;
    mat_data.name = prim.GetName().GetString() + name_suffix;

    bool color_found = false;

    if (pxr::UsdShadeShader surface_shader = material.ComputeSurfaceSource()) {
        // 漫反射颜色 / 反照率纹理 (Diffuse color / Albedo texture)
        if (auto diffuse_input = surface_shader.GetInput(UsdTokens::kDiffuseColor)) {
            pxr::GfVec3f diffuse_color{};
            if (diffuse_input.Get(&diffuse_color)) {
                mat_data.base_color = {diffuse_color[0], diffuse_color[1], diffuse_color[2], 1.0f};
                color_found = true;
                CFW_LOG_DEBUG("[USD] Material '{}': using diffuseColor ({}, {}, {}, {})",
                              mat_data.name, diffuse_color[0], diffuse_color[1], diffuse_color[2], 1.0f);
            } else {
                mat_data.albedo_texture = load_usd_texture(diffuse_input, scene_dir, texture_cache);
                if (mat_data.albedo_texture != InvalidTextureId) {
                    color_found = true;  // 纹理也算作找到了颜色源
                }
            }
        }
        // 金属度 (Metallic)
        if (auto metallic_input = surface_shader.GetInput(UsdTokens::kMetallic)) {
            float metallic = 0.0f;
            if (metallic_input.Get(&metallic)) {
                mat_data.metallic = metallic;
            } else {
                mat_data.metallic_texture = load_usd_texture(metallic_input, scene_dir, texture_cache);
            }
        }
        // 粗糙度 (Roughness)
        if (auto roughness_input = surface_shader.GetInput(UsdTokens::kRoughness)) {
            float roughness = 0.5f;
            if (roughness_input.Get(&roughness)) {
                mat_data.roughness = roughness;
            } else {
                mat_data.roughness_texture = load_usd_texture(roughness_input, scene_dir, texture_cache);
            }
        }
        // 法线 (Normal)
        if (auto normal_input = surface_shader.GetInput(UsdTokens::kNormal)) {
            mat_data.normal_texture = load_usd_texture(normal_input, scene_dir, texture_cache);
        }

        // 透明度 (Opacity)
        if (auto opacity_input = surface_shader.GetInput(UsdTokens::kOpacity)) {
            float opacity = 1.0f;
            if (opacity_input.Get(&opacity)) {
                // 防止 opacity 为 0 导致全透明（某些 DCC 工具可能将未使用的 opacity 设为 0）
                constexpr float kMinOpacity = 0.001f;
                if (opacity <= kMinOpacity) {
                    CFW_LOG_WARNING("[USD] Material '{}': opacity = {} is too small, treating as opaque (1.0)",
                                    mat_data.name, opacity);
                    opacity = 1.0f;
                }
                // 将 opacity 值存储到 base_color 的 alpha 通道
                mat_data.base_color[3] = opacity;
                // 如果 opacity < 1，设置为 Blend 模式
                if (opacity < 1.0f) {
                    mat_data.alpha_mode = AlphaMode::Blend;
                    CFW_LOG_DEBUG("[USD] Material '{}': opacity = {}, using Blend mode",
                                  mat_data.name, opacity);
                }
            } else {
                // opacity 连接到纹理
                mat_data.opacity_texture = load_usd_texture(opacity_input, scene_dir, texture_cache);
                if (mat_data.opacity_texture != InvalidTextureId) {
                    mat_data.alpha_mode = AlphaMode::Blend;
                    // 确保 base_color[3] 为 1.0，让渲染器完全依赖 opacity_texture
                    mat_data.base_color[3] = 1.0f;
                    CFW_LOG_DEBUG("[USD] Material '{}': using opacity texture (id={}), Blend mode, base_color.a=1.0",
                                  mat_data.name, mat_data.opacity_texture);
                } else {
                    CFW_LOG_WARNING("[USD] Material '{}': opacity input connected but texture load failed",
                                    mat_data.name);
                }
            }
        }

        // Alpha 测试阈值 (opacityThreshold)
        if (auto threshold_input = surface_shader.GetInput(UsdTokens::kOpacityThreshold)) {
            float threshold = 0.0f;
            if (threshold_input.Get(&threshold) && threshold > 0.0f) {
                mat_data.alpha_cutoff = threshold;
                // 如果设置了阈值，切换到 Mask 模式
                mat_data.alpha_mode = AlphaMode::Mask;
                CFW_LOG_DEBUG("[USD] Material '{}': opacityThreshold = {}, using Mask mode",
                              mat_data.name, threshold);
            }
        }
    }

    // 如果没有找到任何颜色，记录警告
    if (!color_found) {
        CFW_LOG_WARNING("[USD] Material '{}': no color found, using default white", mat_data.name);
    }

    // 回退：在材质子节点中搜索纹理 (Fallback: search for texture in material children)
    if (mat_data.albedo_texture == InvalidTextureId) {
        mat_data.albedo_texture = find_and_load_material_texture(prim, scene_dir, texture_cache);
    }

    // 修复：如果有纹理但颜色为黑色/接近黑色，将 base_color 设为白色
    fix_black_material_with_texture(mat_data, "USD");

    CFW_LOG_DEBUG("[USD] Material '{}': albedo_texture = {} (InvalidTextureId = {})",
                  mat_data.name, mat_data.albedo_texture, InvalidTextureId);

    // 如果未找到反照率纹理，使用默认白色纹理
    if (mat_data.albedo_texture == InvalidTextureId) {
        mat_data.albedo_texture = get_or_create_default_white_texture();
    }

    return mat_data;
}

inline void add_material_to_scene(Scene& scene,
                                  std::unordered_map<std::string, std::uint32_t>& material_map,
                                  const std::string& key,
                                  MaterialData&& mat_data) {
    auto mat_index = static_cast<std::uint32_t>(scene.data.materials.size());
    material_map[key] = mat_index;
    scene.data.materials.emplace_back(std::move(mat_data));
}

inline bool is_material_processed(const std::unordered_map<std::string, std::uint32_t>& material_map,
                                  const std::string& path) {
    return std::ranges::any_of(material_map | std::views::keys,
                               [&path](const std::string& key) { return key.starts_with(path); });
}

// ============================================================================
// Main Material Processing
// ============================================================================
inline void process_usd_materials(const pxr::UsdStageRefPtr& stage, Scene& scene,
                                  std::unordered_map<std::string, std::uint32_t>& material_map,
                                  const std::filesystem::path& scene_dir) {
    TextureCache texture_cache;

    // Collect prims with variant sets
    std::vector<pxr::UsdPrim> variant_prims;
    for (const pxr::UsdPrim& prim : stage->Traverse()) {
        if (prim.HasVariantSets()) {
            variant_prims.emplace_back(prim);
        }
    }

    // Process variant materials
    for (const auto& variant_prim : variant_prims) {
        pxr::UsdVariantSets variant_sets = variant_prim.GetVariantSets();
        for (const auto& set_name : variant_sets.GetNames()) {
            pxr::UsdVariantSet variant_set = variant_sets.GetVariantSet(set_name);
            std::string original_selection = variant_set.GetVariantSelection();

            for (const auto& variant_name : variant_set.GetVariantNames()) {
                variant_set.SetVariantSelection(variant_name);

                for (const pxr::UsdPrim& prim : stage->Traverse()) {
                    if (!prim.IsA<pxr::UsdShadeMaterial>()) continue;

                    pxr::UsdShadeMaterial material(prim);
                    std::string suffix = "_" + variant_name;
                    std::string mat_key = prim.GetPath().GetString() + suffix;

                    auto mat_data = extract_material_data(material, prim, scene_dir, texture_cache, suffix);
                    add_material_to_scene(scene, material_map, mat_key, std::move(mat_data));
                }
            }
            variant_set.SetVariantSelection(original_selection);
        }
    }

    // Process non-variant materials
    for (const pxr::UsdPrim& prim : stage->Traverse()) {
        if (!prim.IsA<pxr::UsdShadeMaterial>()) continue;

        std::string prim_path = prim.GetPath().GetString();
        if (is_material_processed(material_map, prim_path)) continue;

        pxr::UsdShadeMaterial material(prim);
        auto mat_data = extract_material_data(material, prim, scene_dir, texture_cache);
        add_material_to_scene(scene, material_map, prim_path, std::move(mat_data));
    }
}

// ============================================================================
// Node Processing - 递归遍历 USD prim 层级结构
// ============================================================================
inline void process_usd_node(const pxr::UsdPrim& prim, Scene& scene,
                             std::uint32_t parent_index,
                             std::unordered_map<std::string, std::uint32_t>& material_map,
                             const UsdGlobalNormalizationParams& global_params,
                             std::unordered_map<std::string, std::uint32_t>& node_name_map,
                             const UsdImportOptions& options = UsdImportOptions{}) {
    std::string node_name = prim.GetName().GetString();
    std::uint32_t node_index = scene.add_node(node_name, parent_index);
    node_name_map[prim.GetPath().GetString()] = node_index;

    // 提取局部变换
    if (prim.IsA<pxr::UsdGeomXformable>()) {
        pxr::UsdGeomXformable xformable(prim);
        scene.data.nodes[node_index].transform = extract_usd_transform(xformable);
    }

    // 处理 Mesh
    if (prim.IsA<pxr::UsdGeomMesh>()) {
        pxr::UsdGeomMesh mesh(prim);
        process_usd_mesh(mesh, scene, node_index, material_map, global_params, options);
    }

    // 处理 Light
    if (prim.IsA<pxr::UsdLuxSphereLight>() ||
        prim.IsA<pxr::UsdLuxDistantLight>() ||
        prim.IsA<pxr::UsdLuxRectLight>() ||
        prim.IsA<pxr::UsdLuxDiskLight>()) {
        process_usd_light(prim, scene, node_index);
    }

    // 处理 Camera
    if (prim.IsA<pxr::UsdGeomCamera>()) {
        pxr::UsdGeomCamera camera(prim);
        process_usd_camera(camera, scene, node_index);
    }

    // 递归处理子节点
    // 使用 UsdTraverseInstanceProxies 以便能够进入 Instance 内部 (例如 Kitchen_set_instanced.usd)
    for (const auto& child : prim.GetFilteredChildren(pxr::UsdTraverseInstanceProxies(pxr::UsdPrimDefaultPredicate))) {
        process_usd_node(child, scene, node_index, material_map, global_params, node_name_map, options);
    }
}

// ============================================================================
// Main Scene Processing - USD 场景完整导入入口
// ============================================================================
inline void process_usd_scene(const pxr::UsdStageRefPtr& stage, Scene& scene,
                              const std::filesystem::path& scene_dir,
                              const UsdImportOptions& options = UsdImportOptions{}) {
    if (!stage) {
        CFW_LOG_ERROR("[USD] Invalid stage, cannot process scene");
        return;
    }

    CFW_LOG_INFO("[USD] Processing USD scene from: {}", scene_dir.string());

    // 1. 计算全局归一化参数
    UsdGlobalNormalizationParams global_params = compute_usd_global_normalization_params(stage);

    // 2. 处理材质
    std::unordered_map<std::string, std::uint32_t> material_map;
    process_usd_materials(stage, scene, material_map, scene_dir);
    CFW_LOG_INFO("[USD] Processed {} materials", scene.data.materials.size());

    // 3. 处理节点层级
    std::unordered_map<std::string, std::uint32_t> node_name_map;
    pxr::UsdPrim root_prim = stage->GetPseudoRoot();

    // 创建 USD 场景的根容器节点，承载全局变换
    std::string root_name = scene_dir.stem().string();
    if (root_name.empty()) root_name = "USD_Root";
    std::uint32_t usd_root_index = scene.add_node(root_name, InvalidIndex);

    // 配置根变换
    auto& root_transform = scene.data.nodes[usd_root_index].transform;

    // Mesh 已经在 process_usd_mesh 中应用了归一化（平移+缩放）
    root_transform.scale = {1.0f, 1.0f, 1.0f};
    root_transform.position = {0.0f, 0.0f, 0.0f};
    root_transform.rotation = {0.0f, 0.0f, 0.0f};

    // 使用 UsdTraverseInstanceProxies 确保根节点下的直接实例也能被展开
    for (const auto& child : root_prim.GetFilteredChildren(pxr::UsdTraverseInstanceProxies(pxr::UsdPrimDefaultPredicate))) {
        process_usd_node(child, scene, usd_root_index, material_map, global_params, node_name_map, options);
    }

    CFW_LOG_INFO("[USD] Scene processing complete: {} nodes, {} meshes, {} lights, {} cameras",
                 scene.data.nodes.size(),
                 scene.data.meshes.size(),
                 scene.data.lights.size(),
                 scene.data.cameras.size());
}

}  // namespace Corona::Resource
