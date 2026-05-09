#include "corona/resource/types/audio.h"

namespace Corona::Resource {

Audio::Audio(const std::filesystem::path& path) : IResource(path) {}

AudioParser::AudioParser() {
    // register_extension(".wav");
    // register_extension(".mp3");
    // register_extension(".ogg");
    // register_extension(".flac");
}

}  // namespace Corona::Resource