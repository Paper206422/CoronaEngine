#pragma once

#include <corona/shader_include.h>
#include <CabbageHardware.h>
#include <optional>
#include <vector>

// Helicon codegen translates GLSL `uint` to C++ `uint` (not `unsigned int`)
// in SSBO struct members. Provide the missing typedef.
using uint = uint32_t;

#include GLSL(../../../assets/shaders/visibility.vert.glsl)
#include GLSL(../../../assets/shaders/visibility.frag.glsl)
#include GLSL(../../../assets/shaders/lighting.comp.glsl)
#include GLSL(../../../assets/shaders/sky.comp.glsl)
#include GLSL(../../../assets/shaders/tonemap.comp.glsl)
#include GLSL(../../../assets/shaders/debug_resolve.comp.glsl)

struct Hardware {
    // === Visibility Buffer (replaces GBuffer rasterization output) ===
    HardwareImage visibilityImage;          // RGBA32_UINT: R=instanceID, G=primitiveID
    HardwareImage depthImage;               // D32_FLOAT: depth (kept from GBuffer)

    // === Final composited output ===
    HardwareImage finalOutputImage;
    HardwareExecutor executor;

    // === Uniform buffers ===
    HardwareBuffer uniformBuffer;
    HardwareBuffer vpUniformBuffer;         // renamed: view-projection matrix

    // === Instance & Material tables (uploaded per frame) ===
    HardwareBuffer instanceInfoBuffer;
    HardwareBuffer materialTableBuffer;

    // === Shader pipelines ===
    bool shaderHasInit = false;
    std::optional<RasterizerPipeline<visibility_vert_glsl, visibility_frag_glsl>> visibilityPipeline;
    std::optional<ComputePipeline<lighting_comp_glsl>> lightingPipeline;
    std::optional<ComputePipeline<sky_comp_glsl>> skyPipeline;
    std::optional<ComputePipeline<tonemap_comp_glsl>> tonemapPipeline;
    std::optional<ComputePipeline<debug_resolve_comp_glsl>> debugResolvePipeline;

    // === CPU-side uniform data ===
    struct UniformBufferObject {
        // Light data (for shadow mapping, etc.)
        ktm::fvec3 lightPosition;
        float padding0;
        ktm::fmat4x4 lightViewMatrix;
        ktm::fmat4x4 lightProjMatrix;

        // Eye/Camera data
        ktm::fvec3 eyePosition;
        float padding1;
        ktm::fvec3 eyeDir;
        float padding2;
        ktm::fmat4x4 eyeViewMatrix;
        ktm::fmat4x4 eyeProjMatrix;
    } uniformBufferObjects{};

    struct VPUniformBufferObject {
        ktm::fmat4x4 viewProjMatrix;
    } vpUniformBufferObjects{};

    // === GPU-side instance info table (matches GLSL InstanceInfo layout) ===
    // 80 bytes = 20 uints per entry:
    //   [0..15]  mat4 modelMatrix
    //   [16]     vertexBufferIndex
    //   [17]     indexBufferIndex
    //   [18]     materialID
    //   [19]     objectID
    struct InstanceInfo {
        ktm::fmat4x4 modelMatrix;
        uint32_t vertexBufferIndex;
        uint32_t indexBufferIndex;
        uint32_t materialID;
        uint32_t objectID;
    };
    std::vector<InstanceInfo> instanceInfoData;

    // === GPU-side material table (matches GLSL MaterialInfo layout) ===
    // 64 bytes = 16 uints per entry:
    //   [0]      textureDescriptor
    //   [1]      metallic  (as float bits)
    //   [2]      roughness (as float bits)
    //   [3]      subsurface
    //   [4]      specular
    //   [5]      specularTint
    //   [6]      anisotropic
    //   [7]      sheen
    //   [8]      sheenTint
    //   [9]      clearcoat
    //   [10]     clearcoatGloss
    //   [11]     padding
    //   [12..15] materialColor (vec4)
    struct MaterialInfo {
        uint32_t textureDescriptor;
        float metallic;
        float roughness;
        float subsurface;
        float specular;
        float specularTint;
        float anisotropic;
        float sheen;
        float sheenTint;
        float clearcoat;
        float clearcoatGloss;
        float padding0;
        ktm::fvec4 materialColor;
    };
    std::vector<MaterialInfo> materialTableData;

    // === Render dimensions ===
    ktm::uvec2 gbufferSize{};
};
