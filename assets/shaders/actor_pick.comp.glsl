#version 460
#extension GL_EXT_nonuniform_qualifier : enable

layout(local_size_x = 1, local_size_y = 1) in;

layout(set = 1, binding = 0) buffer SSBOPool { uint data[]; } ssbos[];
layout(set = 2, binding = 0, rgba32ui) uniform uimage2D imagesRGBA32UI[];

layout(push_constant) uniform PushConsts
{
    uvec2 pixel;
    uint visibilityImageIndex;
    uint outputBufferIndex;
} pushConsts;

void main()
{
    uvec4 visibilityData = imageLoad(
        imagesRGBA32UI[nonuniformEXT(pushConsts.visibilityImageIndex)],
        ivec2(pushConsts.pixel));
    ssbos[nonuniformEXT(pushConsts.outputBufferIndex)].data[0] = visibilityData.r;
}
