#pragma once
#include "corona/resource/resource.h"

namespace Corona::Resource {

class Animation : public IResource {
   public:
    explicit Animation(const std::filesystem::path& path);
    ~Animation() override = default;
};

class AnimationParser : public IParser {
   public:
    AnimationParser();
    ~AnimationParser() override = default;

   protected:
};

}  // namespace Corona::Resource