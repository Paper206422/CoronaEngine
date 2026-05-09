#include "corona/scene/desc/node_desc.h"

#include <functional>
#include <string>
#include <string_view>
#include <typeindex>

#include "corona/scene/desc/common.h"

namespace Corona::Resource::Scene {

NodeDesc::NodeDesc() : params_(JsonWrapper::object()) {}

NodeDesc::~NodeDesc() = default;

NodeDesc::NodeDesc(std::string_view type) : type_(type), params_(JsonWrapper::object()) {}

NodeDesc::NodeDesc(std::string_view type, std::string name)
    : type_(type), sub_type(std::move(name)), params_(JsonWrapper::object()) {}

const char* NodeDesc::class_name() const noexcept {
    return std::type_index(typeid(*this)).name();
}

std::string NodeDesc::file_name() const noexcept {
    auto item = params_.find("fn");
    if (item != params_.end() && item->is_string()) {
        return item->get<std::string>();
    }
    return "";
}

std::string NodeDesc::plugin_name() const noexcept {
    return "vision-" + to_lower(type_) + "-" + to_lower(sub_type);
}

std::string NodeDesc::parameter_string() const {
    return params_.dump();
}

JsonWrapper NodeDesc::value(const std::string& key) const {
    return params_.value(key, JsonWrapper::object());
}

bool NodeDesc::contains(const std::string& key) const {
    return params_.contains(key);
}

JsonWrapper& NodeDesc::operator[](const std::string& key) {
    return params_[key];
}

const JsonWrapper& NodeDesc::operator[](const std::string& key) const {
    return params_.at(key);
}

bool NodeDesc::operator==(const NodeDesc& other) const {
    return hash() == other.hash();
}

void NodeDesc::update_parameters(const JsonWrapper& params) {
    if (!params.is_object()) {
        return;
    }

    for (const auto& [key, value] : params.items()) {
        params_[key] = value;
    }
}

void NodeDesc::update_parameters(const JsonWrapper&& params) {
    if (!params.is_object()) {
        return;
    }

    for (const auto& [key, value] : params.items()) {
        params_[key] = value;
    }
}

void NodeDesc::set_type(std::string_view type) noexcept {
    type_ = type;
    reset_hash();
}

void NodeDesc::init() {
    init(JsonWrapper::object());
}

void NodeDesc::init(const char* text) {
    try {
        JsonWrapper parsed = JsonWrapper::parse(text);
        init(parsed);
    } catch (std::exception& e) {
        // Error parsing parameters
    }
}

void NodeDesc::init(const JsonWrapper& params) {
    if (!params.is_object()) {
        return;
    }

    // 'constructor' 字段是可选的,Vision 格式中不使用此字段
    auto constructor_item = params.find("constructor");
    if (constructor_item != params.end() && constructor_item->is_string()) {
        std::string func_name = constructor_item->get<std::string>();
        if (!func_name.empty()) {
            construct_name = func_name;
        }
    }

    // 'name' 字段是可选的,Vision 格式中可能在上层提供
    auto name_item = params.find("name");
    if (name_item != params.end() && name_item->is_string()) {
        name = name_item->get<std::string>();
    }
}

std::uint64_t NodeDesc::hash() const {
    if (is_computed_hash_) {
        return cached_hash_;
    }
    std::uint64_t h1 = std::hash<std::string_view>{}(class_name());
    std::uint64_t h2 = compute_hash();
    cached_hash_ = combine_hash(h1, h2);
    is_computed_hash_ = true;
    return cached_hash_;
}

std::uint64_t NodeDesc::topology_hash() const {
    if (is_computed_topology_hash_) {
        return cached_topology_hash_;
    }
    std::uint64_t h1 = std::hash<std::string_view>{}(class_name());
    std::uint64_t h2 = compute_topology_hash();
    cached_topology_hash_ = combine_hash(h1, h2);
    is_computed_topology_hash_ = true;
    return cached_topology_hash_;
}

void NodeDesc::reset_hash() const noexcept {
    is_computed_hash_ = false;
}

void NodeDesc::reset_topology_hash() const noexcept {
    is_computed_topology_hash_ = false;
}

std::uint64_t NodeDesc::compute_hash() const {
    std::uint64_t h1 = std::hash<std::string_view>{}(type_);
    std::uint64_t h2 = std::hash<std::string>{}(sub_type);
    return combine_hash(h1, h2);
}

std::uint64_t NodeDesc::compute_topology_hash() const {
    return std::hash<std::string_view>{}(class_name());
}

}  // namespace Corona::Resource::Scene