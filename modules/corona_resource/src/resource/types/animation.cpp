#include "corona/resource/types/animation.h"

namespace Corona::Resource {

Animation::Animation(const std::filesystem::path& path) : IResource(path) {}

AnimationParser::AnimationParser() {
    // register_extension(".anim");
    // register_extension(".clip");
}

}  // namespace Corona::Resource