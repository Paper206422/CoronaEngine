#version 460
#extension GL_EXT_nonuniform_qualifier : enable
layout(push_constant) uniform PushConsts {
    uint outputImage;
    uint outputWidth;
    uint outputHeight;
    uint originX;
    uint originY;
    float cursorX;
    float cursorY;
    uint cursorShape;
    uint preserveExisting;
} pushConsts;
layout(set = 2, binding = 0, rgba16) uniform image2D images[];
layout(local_size_x = 8, local_size_y = 8, local_size_z = 1) in;
float lineAlpha(float distanceToLine, float halfWidth)
{
    return 1.0 - smoothstep(halfWidth, halfWidth + 1.0, distanceToLine);
}
vec4 over(vec4 bg, vec4 fg)
{
    return vec4(fg.rgb + bg.rgb * (1.0 - fg.a),
                fg.a + bg.a * (1.0 - fg.a));
}
vec4 cursorColor(float alpha, bool dark)
{
    vec3 color = dark ? vec3(0.02, 0.025, 0.03) : vec3(0.96, 0.98, 1.0);
    return vec4(color * alpha, alpha);
}
float arrowFill(vec2 p)
{
    if (p.x < 0.0 || p.y < 0.0 || p.x > 16.0 || p.y > 22.0) return 0.0;
    float shaft = step(7.0, p.y) * step(p.y, 20.0) *
                  step(abs(p.x - 6.5), 2.0 + 0.22 * (p.y - 7.0));
    float head = step(p.y, 13.0) * step(p.x, p.y * 0.62 + 1.0) *
                 step(p.y * 0.22 - 1.0, p.x);
    float tip = step(p.y, 8.0) * step(p.x, p.y * 0.92 + 1.0);
    return max(max(shaft, head), tip);
}
vec4 drawArrow(vec2 p)
{
    float fill = arrowFill(p);
    float outline = 0.0;
    for (int oy = -1; oy <= 1; ++oy) {
        for (int ox = -1; ox <= 1; ++ox) {
            outline = max(outline, arrowFill(p + vec2(ox, oy)));
        }
    }
    vec4 outColor = cursorColor(max(outline - fill, 0.0), true);
    return over(outColor, cursorColor(fill, false));
}
vec4 drawCrosshair(vec2 p)
{
    vec2 d = p - vec2(10.0);
    float radius = length(d);
    float ring = lineAlpha(abs(radius - 7.0), 1.0);
    float h = lineAlpha(abs(d.y), 0.75) * step(2.5, abs(d.x)) * step(abs(d.x), 10.0);
    float v = lineAlpha(abs(d.x), 0.75) * step(2.5, abs(d.y)) * step(abs(d.y), 10.0);
    float white = max(ring, max(h, v));
    float dark = lineAlpha(abs(radius - 7.0), 2.0) * (1.0 - ring);
    vec4 outColor = cursorColor(dark * 0.75, true);
    return over(outColor, cursorColor(white, false));
}
void main()
{
    ivec2 pos = ivec2(gl_GlobalInvocationID.xy) + ivec2(pushConsts.originX, pushConsts.originY);
    if (pos.x >= int(pushConsts.outputWidth) || pos.y >= int(pushConsts.outputHeight)) {
        return;
    }
    vec4 base = pushConsts.preserveExisting != 0u
        ? imageLoad(images[nonuniformEXT(pushConsts.outputImage)], pos)
        : vec4(0.0);
    vec2 local = vec2(pos) + vec2(0.5) - vec2(pushConsts.cursorX, pushConsts.cursorY);
    vec4 cursor = vec4(0.0);
    if (pushConsts.cursorShape == 2u) {
        cursor = drawCrosshair(local + vec2(10.0));
    } else if (pushConsts.cursorShape != 5u) {
        cursor = drawArrow(local);
    }
    imageStore(images[nonuniformEXT(pushConsts.outputImage)], pos, over(base, cursor));
}
