#version 460
#extension GL_EXT_nonuniform_qualifier : enable

layout(push_constant) uniform PushConsts {
    uint inputImage;
    uint outputImage;
    uint outputWidth;
    uint outputHeight;
    float lenticularPitch;
    float slant;
    float phaseOffset;
    float parallaxScale;
    vec4 rgbSubpixelOffsets;
} pushConsts;

layout(set = 2, binding = 0, rgba16) uniform image2D images[];

layout(local_size_x = 8, local_size_y = 8, local_size_z = 1) in;

float wrapPhaseCentered(float phase)
{
    float wrapped = fract(phase);
    return 2.0 * wrapped - 1.0;
}

float channelSample(int channel, ivec2 pos)
{
    float rgbOffset = pushConsts.rgbSubpixelOffsets[channel];
    float pitch = max(abs(pushConsts.lenticularPitch), 1.0e-5);
    float phaseAccumulator =
        (float(pos.x) + rgbOffset - pushConsts.slant * float(pos.y)) / pitch +
        pushConsts.phaseOffset;
    float phase = wrapPhaseCentered(phaseAccumulator);
    float sampleX = float(pos.x) + phase * pushConsts.parallaxScale;
    ivec2 samplePos = ivec2(clamp(int(round(sampleX)), 0, int(pushConsts.outputWidth) - 1), pos.y);
    return imageLoad(images[pushConsts.inputImage], samplePos)[channel];
}

void main()
{
    ivec2 pos = ivec2(gl_GlobalInvocationID.xy);
    if (pos.x >= int(pushConsts.outputWidth) || pos.y >= int(pushConsts.outputHeight)) {
        return;
    }

    vec4 center = imageLoad(images[pushConsts.inputImage], pos);
    if (center.a <= 0.0) {
        imageStore(images[pushConsts.outputImage], pos, vec4(0.0));
        return;
    }

    vec3 warped;
    warped.r = channelSample(0, pos);
    warped.g = channelSample(1, pos);
    warped.b = channelSample(2, pos);
    imageStore(images[pushConsts.outputImage], pos, vec4(warped, center.a));
}
