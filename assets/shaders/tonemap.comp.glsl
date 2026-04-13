#version 460
#extension GL_EXT_nonuniform_qualifier : enable

layout (local_size_x = 8, local_size_y = 8) in;

layout (set = 2, binding = 0, rgba16) uniform image2D inputImageRGBA16[];

layout(push_constant) uniform PushConsts
{
    uvec2 gbufferSize;
    uint inputImage;
    uint outputImage;
    float exposure;
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

    vec4 hdrColor = imageLoad(inputImageRGBA16[pushConsts.inputImage], pixel);

    vec3 exposed = hdrColor.rgb * pushConsts.exposure;
    vec3 ldrColor = acesFilmicToneMapCurve(exposed);

    imageStore(inputImageRGBA16[pushConsts.outputImage], pixel, vec4(ldrColor, hdrColor.a));
}
