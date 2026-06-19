//
// Created by Z on 2025/12/13.
//

#pragma once

#include "base/integral/integrator.h"
#include "base/sampler.h"
#include "base/illumination/lightsampler.h"
#include "base/warper.h"
#include "base/color/spectrum.h"
#include "base/sensor/frame_buffer.h"
#include "base/import/project_desc.h"
#include "UI/GUI.h"
#include "hotfix/hotfix.h"
#include "base/using.h"

namespace vision {

class Scene;

class Renderer : public GUI, public hotfix::Observer {
private:
    TIntegrator integrator_;
    TSampler sampler_;
    TLightSampler light_sampler_;
    TSpectrum spectrum_;
    WarperDesc warper_desc_;
    RenderSettingDesc render_setting_{};
    SP<FrameBuffer> frame_buffer_{nullptr};

public:
    Renderer() = default;
    void pre_init(const RendererDesc &renderer_desc);
    void init(const RendererDesc &renderer_desc, Scene &scene);
    void prepare(Scene &scene) noexcept;
    void update_runtime_object(const vision::IObjectConstructor *constructor) noexcept override;
    void upload_data(Scene &scene) noexcept;

    VS_MAKE_GUI_STATUS_FUNC(GUI, integrator_, light_sampler_, spectrum_, sampler_)
    bool render_UI(Widgets *widgets) noexcept override {
        widgets->use_window("renderer", [&] {
            vision::UI::render_UI(integrator_, widgets);
            vision::UI::render_UI(light_sampler_, widgets);
            vision::UI::render_UI(spectrum_, widgets);
            vision::UI::render_UI(sampler_, widgets);
        });
        return true;
    }

    OC_MAKE_MEMBER_GETTER_SETTER(sampler, &)
    OC_MAKE_MEMBER_GETTER_SETTER(light_sampler, &)
    OC_MAKE_MEMBER_GETTER_SETTER(integrator, &)
    OC_MAKE_MEMBER_GETTER_SETTER(spectrum, &)

    [[nodiscard]] PolymorphicMode polymorphic_mode() const noexcept { return render_setting_.polymorphic_mode; }

    [[nodiscard]] auto frame_buffer() const noexcept { return frame_buffer_.get(); }
    [[nodiscard]] auto frame_buffer() noexcept { return frame_buffer_.get(); }
    [[nodiscard]] uint2 resolution() const noexcept { return frame_buffer()->resolution(); }
    [[nodiscard]] SP<FrameBuffer> &frame_buffer_sp() noexcept { return frame_buffer_; }
    void set_frame_buffer(SP<FrameBuffer> fb) noexcept { frame_buffer_ = ocarina::move(fb); }

    [[nodiscard]] SP<Warper> load_warper() noexcept { return Node::create_shared<Warper>(warper_desc_); }
    [[nodiscard]] SP<Warper2D> load_warper2d() noexcept {
        WarperDesc warper_desc = warper_desc_;
        warper_desc.sub_type += "2d";
        return Node::create_shared<Warper2D>(warper_desc);
    }

    void prepare_lights(Scene &scene) noexcept;
    void tidy_up() noexcept;
};

}// namespace vision
