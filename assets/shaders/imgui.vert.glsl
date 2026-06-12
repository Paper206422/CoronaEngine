#version 460

out gl_PerVertex
{
    vec4 gl_Position;
};

layout(push_constant) uniform PushConsts
{
    layout(offset = 0) vec2 scale;
    layout(offset = 8) vec2 translate;
    layout(offset = 16) vec4 clip_rect;
    layout(offset = 32) uint texture_index;
} pushConsts;

layout(location = 0) in vec2 in_pos;
layout(location = 1) in vec2 in_uv;
layout(location = 2) in vec4 in_color;

layout(location = 0) out vec2 frag_uv;
layout(location = 1) out vec4 frag_color;

void main()
{
    frag_uv = in_uv;
    frag_color = in_color;
    gl_Position = vec4(in_pos * pushConsts.scale + pushConsts.translate, 0.0, 1.0);
}
