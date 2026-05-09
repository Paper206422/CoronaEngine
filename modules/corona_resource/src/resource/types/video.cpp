#include "corona/resource/types/video.h"

namespace Corona::Resource {

Video::Video(const std::filesystem::path& path) : IResource(path) {}

VideoParser::VideoParser() {
    // register_extension(".mp4");
    // register_extension(".avi");
    // register_extension(".mkv");
    // register_extension(".mov");
}

}  // namespace Corona::Resource