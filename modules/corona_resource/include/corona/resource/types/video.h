#pragma once
#include "corona/resource/resource.h"

namespace Corona::Resource {

class Video : public IResource {
   public:
    explicit Video(const std::filesystem::path& path);
    ~Video() override = default;
};

class VideoParser : public IParser {
   public:
    VideoParser();
    ~VideoParser() override = default;

   protected:
};

}  // namespace Corona::Resource