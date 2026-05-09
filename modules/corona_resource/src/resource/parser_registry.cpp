#include "corona/resource/parser_registry.h"

#include <algorithm>
#include <cctype>

namespace Corona::Resource {

namespace {
// 将字符串转换为小写
inline std::string to_lower(std::string str) {
    std::transform(str.begin(), str.end(), str.begin(),
                   [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    return str;
}
}  // namespace

void ParserRegistry::clear() {
    parsers_.clear();
    parser_registry_.clear();
    export_parser_registry_.clear();
}

bool ParserRegistry::register_parser_impl(std::shared_ptr<IParser> parser) {
    if (!parser) {
        return false;
    }

    // Check if parser of same type is already registered
    auto const it = std::ranges::find_if(parsers_,
                                         [&parser](const std::shared_ptr<IParser>& p) {
                                             return typeid(*p) == typeid(*parser);
                                         });
    if (it != parsers_.end()) {
        // In a real scenario, we might want to log this, but ParserRegistry doesn't hold the logger.
        // We could pass a logger or just return false.
        return false;
    }
    parsers_.push_back(parser);

    // Register all import extensions supported by the parser (convert to lowercase)
    for (const auto& ext : parser->get_supported_extensions()) {
        auto lower_ext = to_lower(ext.first);
        typename decltype(parser_registry_)::accessor accessor;
        if (parser_registry_.insert(accessor, lower_ext)) {
            accessor->second = parser;
        }
    }

    // Register all export extensions supported by the parser (convert to lowercase)
    for (const auto& ext : parser->get_supported_export_extensions()) {
        auto lower_ext = to_lower(ext.first);
        typename decltype(export_parser_registry_)::accessor accessor;
        if (export_parser_registry_.insert(accessor, lower_ext)) {
            accessor->second = parser;
        }
    }

    return true;
}

std::shared_ptr<IParser> ParserRegistry::find_parser(const std::filesystem::path& path) {
    auto ext = to_lower(path.extension().string());
    {
        // Try to find by extension directly
        typename decltype(parser_registry_)::const_accessor accessor;
        if (parser_registry_.find(accessor, ext)) {
            return accessor->second;
        }
    }

    // If not found, iterate all parsers
    auto const it = std::ranges::find_if(parsers_,
                                         [&path](const std::shared_ptr<IParser>& p) {
                                             return p->is_supported(path);
                                         });
    if (it == parsers_.end()) {
        return nullptr;
    }

    // Cache the result (with lowercase extension)
    if (!ext.empty()) {
        typename decltype(parser_registry_)::accessor accessor;
        if (parser_registry_.insert(accessor, ext)) {
            accessor->second = *it;
        }
    }

    return *it;
}

std::shared_ptr<IParser> ParserRegistry::find_export_parser(const std::filesystem::path& path) {
    auto ext = to_lower(path.extension().string());
    {
        // Try to find by extension directly in export registry
        typename decltype(export_parser_registry_)::const_accessor accessor;
        if (export_parser_registry_.find(accessor, ext)) {
            return accessor->second;
        }
    }

    // If not found in cache, iterate all parsers
    auto const it = std::ranges::find_if(parsers_,
                                         [&path](const std::shared_ptr<IParser>& p) {
                                             return p->is_export_supported(path);
                                         });
    if (it == parsers_.end()) {
        return nullptr;
    }

    // Cache the result (with lowercase extension)
    if (!ext.empty()) {
        typename decltype(export_parser_registry_)::accessor accessor;
        if (export_parser_registry_.insert(accessor, ext)) {
            accessor->second = *it;
        }
    }

    return *it;
}

}  // namespace Corona::Resource
