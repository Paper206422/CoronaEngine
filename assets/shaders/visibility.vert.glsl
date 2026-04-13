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

layout(location = 0) in vec3 inPosition;
layout(location = 1) in vec3 inNormal;     // declared to match vertex stride, not used
layout(location = 2) in vec2 inTexCoord;

layout(location = 0) out vec2 fragTexCoord;     // needed for alpha-cutout
layout(location = 1) flat out uint v_instanceID;

void main()
{
    vec4 worldPos = pushConsts.modelMatrix * vec4(inPosition, 1.0);
    gl_Position = uniformBufferObjects[pushConsts.uniformBufferIndex].viewProjMatrix * worldPos;
    fragTexCoord = inTexCoord;
    v_instanceID = pushConsts.instanceID;
}
