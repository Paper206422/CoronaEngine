#pragma once

#include <SDL3/SDL.h>

#include <cstdint>
#include <string>

namespace Corona::Systems::UI {

class Cursor3DManager {
   public:
    static Cursor3DManager& instance();

    bool set_mode(SDL_Window* window,
                  std::uintptr_t camera_handle,
                  std::string scene_id,
                  std::uintptr_t cursor_actor_handle,
                  bool enabled,
                  double viewport_x,
                  double viewport_y,
                  double viewport_width,
                  double viewport_height,
                  double start_x,
                  double start_y);

    bool handle_mouse_motion(const SDL_Event& event);
    void handle_window_focus_lost(SDL_Window* window, SDL_WindowID window_id);
    void force_disable();

   private:
    Cursor3DManager() = default;
};

}  // namespace Corona::Systems::UI
