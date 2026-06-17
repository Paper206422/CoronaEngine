#pragma once

#include <chrono>
#include <corona/utils/path_utils.h>
#include <filesystem>
#include <optional>
#include <string>

namespace Corona::Network {

inline std::optional<std::filesystem::path> resolve_project_relative_path(
    const std::filesystem::path& project_root,
    const std::string& relative_path) {
    if (relative_path.empty()) return std::nullopt;

    std::filesystem::path rel = Utils::utf8_to_path(relative_path);
    if (rel.is_absolute()) return std::nullopt;

    for (const auto& part : rel) {
        if (part == "..") return std::nullopt;
    }

    return project_root / rel.lexically_normal();
}

inline std::string make_transfer_key(const std::string& peer_id,
                                     uint64_t transfer_id) {
    return peer_id + "/" +
     std::to_string(transfer_id);
}

template <typename TimePoint, typename Duration>
inline bool has_file_group_timed_out(TimePoint create_time,
                                     TimePoint last_activity_time,
                                     TimePoint now,
                                     Duration timeout) {
    const bool has_activity = last_activity_time != TimePoint{};
    const auto reference_time = has_activity ? last_activity_time : create_time;
    return now - reference_time > timeout;
}

}  // namespace Corona::Network
