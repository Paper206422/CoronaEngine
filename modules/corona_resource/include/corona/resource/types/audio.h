#pragma once
#include "corona/resource/resource.h"

namespace Corona::Resource {

class Audio : public IResource {
   public:
    explicit Audio(const std::filesystem::path& path);
    ~Audio() override = default;
};

class AudioParser : public IParser {
   public:
    AudioParser();
    ~AudioParser() override = default;

   protected:
};

}  // namespace Corona::Resource