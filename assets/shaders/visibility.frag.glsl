#version 460
#extension GL_EXT_nonuniform_qualifier : enable

layout(push_constant) uniform PushConsts
{
    uint textureIndex;
    uint uniformBufferIndex;
    uint instanceID;
    uint padding0;
    mat4 modelMatrix;
} pushConsts;

layout(set = 1, binding = 0) readonly buffer UniformBufferObject
{
    mat4 viewProjMatrix;
} uniformBufferObjects[];

layout (set = 0, binding = 0) uniform sampler2D textures[];

layout(location = 0) in vec2 fragTexCoord;
layout(location = 1) flat in uint v_instanceID;

layout(location = 0) out uvec4 visibilityData;

void main()
{
    // Alpha-cutout: sample texture to discard transparent fragments
    if (pushConsts.textureIndex != 0)
    {
        vec4 sampleColor = texture(textures[pushConsts.textureIndex], fragTexCoord);
        if (sampleColor.a < 0.5)
        {
            discard;
        }
    }

    visibilityData = uvec4(v_instanceID, uint(gl_PrimitiveID), 0u, 0u);
}
