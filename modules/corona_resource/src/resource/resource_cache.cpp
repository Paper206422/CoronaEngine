#include "corona/resource/resource_cache.h"

#include "corona/kernel/core/i_logger.h"

namespace Corona::Resource {

ResourceCache::~ResourceCache() {
    clear();
}

std::pair<std::shared_ptr<ResourceEntry>, bool> ResourceCache::get_or_create_entry(TResourceID rid) {
    typename decltype(resources_)::accessor accessor;
    if (resources_.insert(accessor, rid)) {
        auto entry = std::make_shared<ResourceEntry>();
        entry->state = LoadState::Loading;
        accessor->second = entry;
        return {entry, true};
    }
    return {accessor->second, false};
}

std::shared_ptr<ResourceEntry> ResourceCache::get_entry(TResourceID rid) {
    typename decltype(resources_)::const_accessor accessor;
    if (resources_.find(accessor, rid)) {
        return accessor->second;
    }
    return nullptr;
}

bool ResourceCache::remove_entry(TResourceID rid) {
    typename decltype(resources_)::accessor accessor;
    if (resources_.find(accessor, rid)) {
        if (accessor->second->ref_count > 0) {
            CFW_LOG_DEBUG("[ResourceCache] Resource {} has {} active references, delay remove",
                         rid, accessor->second->ref_count.load());
            return false;
        }
        return resources_.erase(accessor);
    }
    return false;
}

void ResourceCache::clear() {
    resources_.clear();
}

bool ResourceCache::add_resource(TResourceID rid, std::shared_ptr<IResource> resource) {
    if (!resource) return false;

    typename decltype(resources_)::accessor accessor;
    if (resources_.insert(accessor, rid)) {
        auto entry = std::make_shared<ResourceEntry>();
        entry->resource = std::move(resource);
        entry->state = LoadState::Ready;
        accessor->second = entry;
        return true;
    }

    return false;
}

}  // namespace Corona::Resource
