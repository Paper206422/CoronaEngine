//
// Created by Zero on 09/09/2022.
//

#include "base/shader_graph/shader_node.h"
#include "base/import/param_schema.h"
#include "rhi/common.h"
#include "base/mgr/pipeline.h"
#include "base/mgr/global.h"

namespace vision {
using namespace ocarina;

class ImageNode : public SlotsShaderNode {
private:
#define IMAGE_SLOTS_NO_DEFAULT(X) \
    X(vector, Number, 3u, false)

#define IMAGE_DECLARE_SLOT_(name, tag, dim, required) VS_MAKE_SLOT(name)
    IMAGE_SLOTS_NO_DEFAULT(IMAGE_DECLARE_SLOT_)
#undef IMAGE_DECLARE_SLOT_

    RegistrableTexture3D *texture_{};
    EncodedData<uint> tex_id_{};
    EncodedData<uint> gamma_correct_{false};
    ShaderNodeDesc desc_;
    EncodedData<float> scale_{1.f};
    mutable optional<float_array> cache_;

    [[nodiscard]] RegistrableTexture3D &obtain_texture(const ShaderNodeDesc &desc) noexcept {
        auto *rp = pipeline();
        if (rp->scene().geometry().has_gpu_resource()) {
            return rp->image_pool().obtain_texture(
                desc,
                rp->scene().geometry().bindless_array(),
                rp->scene().geometry().gpu_resource()->device());
        }
        return rp->image_pool().obtain_texture(desc, rp->bindless_array(), rp->device());
    }

public:
    ImageNode() = default;
    explicit ImageNode(const ShaderNodeDesc &desc)
        : SlotsShaderNode(desc),
          desc_(desc),
          scale_(desc["scale"].as_float(1.f)) {
        texture_ = &obtain_texture(desc);
        tex_id_ = texture_->index();
    }
    VS_MAKE_GUI_STATUS_FUNC(ShaderNode, vector_)
    OC_ENCODABLE_FUNC(ShaderNode, vector_, tex_id_, scale_)
    VS_MAKE_PLUGIN_NAME_FUNC
    VS_HOTFIX_MAKE_RESTORE(ShaderNode, vector_, texture_, tex_id_, desc_, scale_)

    [[nodiscard]] static const ParamSchema &param_schema() noexcept {
        static const ParamSchema schema = [] {
            ParamSchema ret;
#define IMAGE_REGISTER_PARAM_(name, tag, dim, required) ret.add_slot(#name, tag, dim, required);
            IMAGE_SLOTS_NO_DEFAULT(IMAGE_REGISTER_PARAM_)
#undef IMAGE_REGISTER_PARAM_
            ret.add_plain("fn", ParamType::String);
            ret.add_plain("scale", ParamType::Float);
            return ret;
        }();
        return schema;
    }

    void initialize_slots(const vision::ShaderNodeDesc &desc) noexcept override {
        const ParamSchema &schema = param_schema();
        validate_params(desc, schema);
#define IMAGE_INIT_SLOT_(name, tag, dim, required) VS_INIT_SLOT_NO_DEFAULT(name, tag);
        IMAGE_SLOTS_NO_DEFAULT(IMAGE_INIT_SLOT_)
#undef IMAGE_INIT_SLOT_
    }

    void reload(Widgets *widgets) noexcept {
        fs::path path = texture_->host_tex().path();
        if (Widgets::open_file_dialog(path)) {
            desc_.set_value("fn", path.string());
            desc_.reset_hash();
            texture_ = &obtain_texture(desc_);
            texture_->upload_immediately();
            tex_id_.hv() = texture_->index().hv();
            changed_ = true;
        }
    }

    void render_sub_UI(Widgets *widgets) noexcept override {
        vector_.render_UI(widgets);
        changed_ |= widgets->drag_float("scale", addressof(scale_.hv()), 0.05, 0);
        widgets->button_click("reload", [&] {
            reload(widgets);
        });
        widgets->image(texture_->host_tex());
    }

    bool render_UI(Widgets *widgets) noexcept override {
        bool ret = widgets->use_tree(ocarina::format("{} detail", name_), [&] {
            render_sub_UI(widgets);
        });
        return ret;
    }

    [[nodiscard]] AttrEvalContext evaluate(const string &key, const AttrEvalContext &ctx,
                                           const SampledWavelengths &swl) const noexcept override {
        float_array value = evaluate(ctx, swl).array;
        if (key == "Alpha") {
            if (channel_num() < 4) {
                return float_array::create(0);
            }
            return value.w();
        } else if (key == "Color") {
            return value.xyz();
        }
        return value;
    }

    [[nodiscard]] uint channel_num() const noexcept { return texture_->host_tex().channel_num(); }

    [[nodiscard]] AttrEvalContext evaluate(const AttrEvalContext &ctx,
                                           const SampledWavelengths &swl) const noexcept override {

        if (!cache_) {
            AttrEvalContext ctx_processed = vector_.evaluate(ctx, swl);
            float_array value = texture_->sample(channel_num(), ctx_processed.uv());
            value = value * *scale_;
            cache_.emplace(value);
        }
        return *cache_;
    }

    void on_after_decode() const noexcept override {
        cache_.reset();
    }

    [[nodiscard]] ocarina::vector<float> average() const noexcept override {
        return texture_->host_tex().average_vector();
    }
    [[nodiscard]] uint2 resolution() const noexcept override {
        return texture_->device_tex()->resolution().xy();
    }
    void for_each_pixel(const function<Image::foreach_signature> &func) const noexcept override {
        texture_->host_tex().for_each_pixel(func);
    }
};
}// namespace vision

VS_MAKE_CLASS_CREATOR_HOTFIX(vision, ImageNode)
