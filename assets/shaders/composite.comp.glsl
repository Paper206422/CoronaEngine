#version 460
#extension GL_EXT_nonuniform_qualifier : enable

layout(push_constant) uniform PushConsts {
    uint bgImage;
    uint fgImage;
    uint outputImage;
    uint outputWidth;
    uint outputHeight;
    uint bgWidth;
    uint bgHeight;
} pushConsts;

layout(set = 0, binding = 0) uniform sampler2D textures[];
layout(set = 2, binding = 0, rgba16f) uniform image2D images[];

layout(local_size_x = 8, local_size_y = 8, local_size_z = 1) in;

// Linear -> sRGB OETF (IEC 61966-2-1). The whole optics/UI pipeline works in
// linear light and tone-maps with ACES but never gamma-encodes; the swapchain
// is R8G8B8A8_UNORM, so the present blit does NOT encode either. Without this
// the linear values reach an sRGB display un-encoded and the image looks too
// dark. This is the final present-producing pass, so encode here (and ONLY
// here — earlier composite/tonemap outputs are re-read as linear).
vec3 linearToSrgb(vec3 c)
{
    c = clamp(c, 0.0, 1.0);
    return mix(c * 12.92,
               1.055 * pow(c, vec3(1.0 / 2.4)) - 0.055,
               step(vec3(0.0031308), c));
}

void main()
{
    ivec2 pos = ivec2(gl_GlobalInvocationID.xy);

    if (pos.x >= pushConsts.outputWidth || pos.y >= pushConsts.outputHeight) {
        return;
    }

    vec2 uv = (vec2(pos) + 0.5) / vec2(pushConsts.outputWidth, pushConsts.outputHeight);

    ivec2 bgSize = ivec2(pushConsts.bgWidth, pushConsts.bgHeight);
    vec2 bgTexel = uv * vec2(bgSize) - 0.5;

    ivec2 base = ivec2(floor(bgTexel));
    ivec2 c0 = clamp(base, ivec2(0), bgSize - ivec2(1));
    ivec2 c1 = clamp(base + ivec2(1, 0), ivec2(0), bgSize - ivec2(1));
    ivec2 c2 = clamp(base + ivec2(0, 1), ivec2(0), bgSize - ivec2(1));
    ivec2 c3 = clamp(base + ivec2(1, 1), ivec2(0), bgSize - ivec2(1));
    vec2 f = fract(bgTexel);

    vec4 bg = mix(
        mix(imageLoad(images[pushConsts.bgImage], c0),
            imageLoad(images[pushConsts.bgImage], c1), f.x),
        mix(imageLoad(images[pushConsts.bgImage], c2),
            imageLoad(images[pushConsts.bgImage], c3), f.x),
        f.y
    );

    vec4 fg = texture(textures[pushConsts.fgImage], uv);
    vec3 color = fg.rgb + bg.rgb * (1.0 - fg.a);

    imageStore(images[pushConsts.outputImage], pos, vec4(linearToSrgb(color), 1.0));
}
