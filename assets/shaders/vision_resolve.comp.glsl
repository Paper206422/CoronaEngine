#version 460
#extension GL_EXT_nonuniform_qualifier : enable

// Zero-copy Vision resolve pass.
// Reads Vision's PRE-tonemap linear HDR color (float32 RGBA, row-major
// y*width+x) from a CUDA buffer imported into Vulkan, applies Vision's exposure
// + ACES tone map, and writes the engine's RGBA16F display image. The float32 ->
// half16 narrowing happens implicitly on imageStore into the rgba16 target, so
// no CPU readback / conversion is needed.
//
// The source is Vision's accumulation_buffer_/rt_buffer_ (the input to
// FrameBuffer::tone_mapping_), NOT view_texture_: that final-color texture is a
// cuArray whose memory cannot be exported. So we tone map here instead, and this
// MUST match Vision exactly or Vision<->Native switching shifts color. Vision
// (FrameBuffer::compile_tone_mapping + apply_exposure) does:
//     exposed = 1 - exp(-color * exposure)   // NOT the engine's linear c*E
//     ldr     = ACES(exposed)
// and for headless (no window) does NOT apply sRGB gamma, so we stop at ACES.

layout (local_size_x = 8, local_size_y = 8) in;

// Bindless SSBO pool (matches lighting.comp.glsl set=1 layout).
layout (set = 1, binding = 0) readonly buffer SSBOPool { uint data[]; } ssbos[];
// Bindless storage-image pool (matches tonemap.comp.glsl set=2 rgba16 layout).
layout (set = 2, binding = 0, rgba16) uniform image2D imagesRGBA16[];

layout(push_constant) uniform PushConsts
{
    uvec2 gbufferSize;
    uint  srcBufferIndex;   // imported Vision pre-tonemap buffer (float4 per pixel)
    uint  outputImage;      // engine finalOutputImage (RGBA16F)
    float exposure;         // Vision FrameBuffer exposure (default 1.0)
} pushConsts;

vec3 acesFilmicToneMapCurve(vec3 x)
{
    float a = 2.51f;
    float b = 0.03f;
    float c = 2.43f;
    float d = 0.59f;
    float e = 0.14f;
    return clamp((x * (a * x + b)) / (x * (c * x + d) + e), 0.0, 1.0);
}

void main()
{
    if (gl_GlobalInvocationID.x >= pushConsts.gbufferSize.x ||
        gl_GlobalInvocationID.y >= pushConsts.gbufferSize.y) {
        return;
    }

    ivec2 pixel = ivec2(gl_GlobalInvocationID.xy);
    uint base = (gl_GlobalInvocationID.y * pushConsts.gbufferSize.x +
                 gl_GlobalInvocationID.x) * 4u;

    uint srcIdx = nonuniformEXT(pushConsts.srcBufferIndex);
    vec3 hdr = vec3(
        uintBitsToFloat(ssbos[srcIdx].data[base + 0u]),
        uintBitsToFloat(ssbos[srcIdx].data[base + 1u]),
        uintBitsToFloat(ssbos[srcIdx].data[base + 2u]));

    // Vision exposure curve, then ACES (no sRGB for headless path).
    vec3 exposed = vec3(1.0) - exp(-hdr * pushConsts.exposure);
    vec3 ldr = acesFilmicToneMapCurve(exposed);

    imageStore(imagesRGBA16[nonuniformEXT(pushConsts.outputImage)], pixel, vec4(ldr, 1.0));
}
