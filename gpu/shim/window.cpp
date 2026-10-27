// bbport: SDL3 window for the Vulkan swapchain (X11 or Wayland).
#include <algorithm>
#include <atomic>
#include <cctype>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cmath>
#include <cstring>
#include <SDL3/SDL.h>
#include "common/assert.h"
#include "common/logging/log.h"
#include "sdl_window.h"
#include "bbport_overlay.h"
#include "stage_point.h"
#include "bbport_settings.h"
#include "../bbgpu.h"

void NoteMouseWheel(float y); // below: wheel notches for the pad read
void NoteMouseMotion(float x, float y); // below: motion for the mouse camera
bool TakeWindowStatus(std::string& status); // below: a status for the title (shader pre-build)
void SetMouseCaptured(bool captured);
static std::atomic<bool> g_menu_pointer{false}; // below: a menu shows the pointer
static std::atomic<bool> g_window_focused{false};
static std::atomic<int> g_window_points_w{0}, g_window_points_h{0};
static bool g_pad_in_use = false; // window thread: the last input came from a controller
static std::atomic<SDL_DisplayID> g_game_display{0}; // ChooseDisplay's answer, 0 before the window

// The monitor the game's window opened on (BB_DISPLAY), 0 before it opened: bbgpu.cpp's display
// refresh rate is that monitor's, not the primary one's.
SDL_DisplayID BbGameDisplay() { return g_game_display.load(); }

namespace Frontend {

namespace {
bool ContainsIgnoringCase(const char* text, const char* part) {
    const size_t length = std::strlen(part);
    for (; *text; ++text) {
        size_t i = 0;
        while (i < length && text[i] &&
               std::tolower(static_cast<unsigned char>(text[i])) ==
                   std::tolower(static_cast<unsigned char>(part[i]))) {
            ++i;
        }
        if (i == length) {
            return true;
        }
    }
    return length == 0;
}

// The monitor the window (and fullscreen) goes to. BB_DISPLAY: its number in SDL's order (1, 2,
// ...; the launcher's Monitor choice sets it) or a part of its name; without it SDL's primary
// display. The monitors are logged so a report says which one was taken. (parsifal295,
// Supermedo/bloodborne_pc PR #66; bbport 0.5-pre1, deadinside28/bloodborne_pc 39940f2.)
SDL_DisplayID ChooseDisplay() {
    const SDL_DisplayID primary = SDL_GetPrimaryDisplay();
    const char* wanted = std::getenv("BB_DISPLAY");
    int count = 0;
    SDL_DisplayID* ids = SDL_GetDisplays(&count);
    SDL_DisplayID chosen = 0;
    if (ids && wanted && *wanted) {
        char* end = nullptr;
        const long number = std::strtol(wanted, &end, 10);
        if (end && *end == '\0') {
            if (number >= 1 && number <= count) {
                chosen = ids[number - 1];
            }
        } else {
            for (int i = 0; i < count && !chosen; ++i) {
                const char* name = SDL_GetDisplayName(ids[i]);
                if (name && ContainsIgnoringCase(name, wanted)) {
                    chosen = ids[i];
                }
            }
        }
    }
    const SDL_DisplayID display = chosen ? chosen : primary;
    for (int i = 0; ids && i < count; ++i) {
        const char* name = SDL_GetDisplayName(ids[i]);
        const SDL_DisplayMode* mode = SDL_GetDesktopDisplayMode(ids[i]);
        std::printf("Display %d: %s %dx%d%s%s\n", i + 1, name ? name : "?", mode ? mode->w : 0,
                    mode ? mode->h : 0, ids[i] == primary ? " (primary)" : "",
                    ids[i] == display ? " <- the game's" : "");
    }
    if (wanted && *wanted && !chosen) {
        std::printf("Display: BB_DISPLAY=%s matches none, the primary one is used\n", wanted);
    }
    SDL_free(ids);
    return display;
}

// The window's size when it is not fullscreen: the output resolution, made smaller (same shape)
// until it fits the monitor's free area with room for the title bar. A window always opened at
// 1920 x 1080 covered a 1080p monitor like fullscreen (#124) and did not follow a smaller output
// such as 1280 x 720 (#100). (After Supermedo 5bfa7c2, nick24051998, where the launcher places
// the window at the output size on the chosen monitor; here the window opens that way, also for
// shortcut, Steam and Proton starts.) BB_WINDOW_SIZE=WxH sets it; 0 keeps the size the port asks
// for (1920 x 1080).
void WindowedSize(SDL_DisplayID display, s32& width, s32& height) {
    s32 w = 0, h = 0;
    const char* wanted = std::getenv("BB_WINDOW_SIZE");
    if (wanted && !std::strcmp(wanted, "0")) {
        return;
    }
    if (!wanted || std::sscanf(wanted, "%dx%d", &w, &h) != 2 || w < 320 || h < 180) {
        const int r = std::clamp(BbSettings::Get().output_res.load(), 0, BbSettings::OutputCount - 1);
        w = BbSettings::OutputWidths[r];
        h = BbSettings::OutputHeights[r];
    }
    SDL_Rect room{};
    if (SDL_GetDisplayUsableBounds(display, &room) && room.w > 0 && room.h > 0) {
        float scale = SDL_GetDisplayContentScale(display);
        scale = scale > 0.0f ? scale : 1.0f;
        const double room_w = room.w - 16.0 * scale, room_h = room.h - 40.0 * scale;
        const double fit = std::min({1.0, room_w / w, room_h / h});
        if (fit < 1.0) {
            w = std::max(2, int(w * fit) / 2 * 2);
            h = std::max(2, int(h * fit) / 2 * 2);
        }
    }
    width = w;
    height = h;
}
} // namespace

WindowSDL::WindowSDL(s32 width_, s32 height_, const char* title) : width{width_}, height{height_} {
    // Gamepads are sampled by runtime_pad.c; their events are pumped here with the window's.
    if (!SDL_InitSubSystem(SDL_INIT_VIDEO | SDL_INIT_GAMEPAD)) {
        UNREACHABLE_MSG("Failed to initialize SDL video: {}", SDL_GetError());
    }
    SDL_PropertiesID props = SDL_CreateProperties();
    SDL_SetStringProperty(props, SDL_PROP_WINDOW_CREATE_TITLE_STRING, title);
    const SDL_DisplayID display = ChooseDisplay();
    g_game_display = display;
    s32 window_w = width_, window_h = height_;
    WindowedSize(display, window_w, window_h);
    SDL_SetNumberProperty(props, SDL_PROP_WINDOW_CREATE_X_NUMBER, SDL_WINDOWPOS_CENTERED_DISPLAY(display));
    SDL_SetNumberProperty(props, SDL_PROP_WINDOW_CREATE_Y_NUMBER, SDL_WINDOWPOS_CENTERED_DISPLAY(display));
    SDL_SetNumberProperty(props, SDL_PROP_WINDOW_CREATE_WIDTH_NUMBER, window_w);
    SDL_SetNumberProperty(props, SDL_PROP_WINDOW_CREATE_HEIGHT_NUMBER, window_h);
    SDL_SetBooleanProperty(props, SDL_PROP_WINDOW_CREATE_RESIZABLE_BOOLEAN, true);
    SDL_SetBooleanProperty(props, SDL_PROP_WINDOW_CREATE_VULKAN_BOOLEAN, true);
    fullscreen_applied = BbSettings::Get().fullscreen.load(); // BB_FULLSCREEN, from the launcher
    SDL_SetBooleanProperty(props, SDL_PROP_WINDOW_CREATE_FULLSCREEN_BOOLEAN, fullscreen_applied);
    base_title = title;
    window = SDL_CreateWindowWithProperties(props);
    SDL_DestroyProperties(props);
    ASSERT_MSG(window, "Failed to create window: {}", SDL_GetError());
    // BB_FULLSCREEN_MODE=exclusive (the launcher's Fullscreen type): fullscreen switches the
    // display to its desktop mode instead of a borderless window over it (the default). A
    // window is borderless in fullscreen until it is given a display mode; the in-game
    // Fullscreen switch keeps it. (RafaelHGOliveira, Supermedo/bloodborne_pc PR #68.)
    if (const char* mode = std::getenv("BB_FULLSCREEN_MODE"); mode && !std::strcmp(mode, "exclusive")) {
        const SDL_DisplayMode* desktop = SDL_GetDesktopDisplayMode(SDL_GetDisplayForWindow(window));
        if (!desktop || !SDL_SetWindowFullscreenMode(window, desktop)) {
            LOG_WARNING(Frontend, "Exclusive fullscreen unavailable, staying borderless: {}", SDL_GetError());
        } else {
            std::printf("Display: exclusive fullscreen %dx%d at %.0f Hz\n", desktop->w, desktop->h,
                        double(desktop->refresh_rate));
        }
    }

    const char* driver = SDL_GetCurrentVideoDriver();
    const SDL_PropertiesID wp = SDL_GetWindowProperties(window);
#ifdef _WIN32
    if (driver && !std::strcmp(driver, "windows")) {
        window_info.type = WindowSystemType::Windows;
        window_info.render_surface = SDL_GetPointerProperty(wp, SDL_PROP_WINDOW_WIN32_HWND_POINTER, nullptr);
        on_hdr_display = SDL_GetBooleanProperty(wp, SDL_PROP_WINDOW_HDR_ENABLED_BOOLEAN, false);
    } else
#endif
    if (driver && !std::strcmp(driver, "x11")) {
        window_info.type = WindowSystemType::X11;
        window_info.display_connection = SDL_GetPointerProperty(wp, SDL_PROP_WINDOW_X11_DISPLAY_POINTER, nullptr);
        window_info.render_surface = reinterpret_cast<void*>(SDL_GetNumberProperty(wp, SDL_PROP_WINDOW_X11_WINDOW_NUMBER, 0));
    } else if (driver && !std::strcmp(driver, "wayland")) {
        window_info.type = WindowSystemType::Wayland;
        window_info.display_connection = SDL_GetPointerProperty(wp, SDL_PROP_WINDOW_WAYLAND_DISPLAY_POINTER, nullptr);
        window_info.render_surface = SDL_GetPointerProperty(wp, SDL_PROP_WINDOW_WAYLAND_SURFACE_POINTER, nullptr);
    } else {
        UNREACHABLE_MSG("Unsupported SDL video driver {}", driver ? driver : "(none)");
    }
    int w = 0, h = 0;
    SDL_GetWindowSizeInPixels(window, &w, &h);
    width = w;
    height = h;
    LOG_INFO(Frontend, "Window {}x{} on {}", w, h, driver);
    if (on_hdr_display) {
        std::printf("Display: HDR on in Windows\n");
    }
}

WindowSDL::~WindowSDL() {
    // Never leave the desktop with a captured mouse or a hidden pointer, also when the game
    // closes while the camera holds the mouse.
    if (mouse_captured) {
        mouse_captured = false;
        SDL_SetWindowRelativeMouseMode(window, false);
        SetMouseCaptured(false);
    }
    if (cursor_hidden_by_port) {
        SDL_ShowCursor();
        cursor_hidden_by_port = false;
    }
    SDL_DestroyWindow(window);
}

void WindowSDL::BeginTextInput(const std::string& initial, const std::string& prompt) {
    std::scoped_lock lock{text_mutex};
    text = initial;
    text_prompt = prompt;
    text_state = 0;
    text_requested = true;
}

int WindowSDL::PollTextInput(std::string& out) {
    std::scoped_lock lock{text_mutex};
    out = text;
    return text_state;
}

void WindowSDL::UpdateTextTitle() {
    const std::string title = text_active ? base_title + " \u2014 " + text_prompt + ": " + text + "_  (Enter = OK, Esc = cancel)"
                                          : base_title;
    SDL_SetWindowTitle(window, title.c_str());
    BbOverlay::SetTextEntry(text_active, text_prompt, text);
}

static bool cursor_hidden_by_port = false;

bool WindowSDL::PollEvents() {
    {
        std::scoped_lock lock{text_mutex};
        if (text_requested) { // SDL text input must be toggled from the window thread
            text_requested = false;
            text_active = true;
            SDL_StartTextInput(window);
            UpdateTextTitle();
        }
    }
    if (!text_active) {
        BbOverlay::UpdateTextInput(window);
    }
    // A status the renderer shows while the game cannot draw yet (shader pre-build progress).
    if (std::string status; !text_active && TakeWindowStatus(status)) {
        const std::string title = status.empty() ? base_title : base_title + " — " + status;
        SDL_SetWindowTitle(window, title.c_str());
    }
    // Fullscreen follows the setting (the in-game PC menu changes it while playing). The size
    // change arrives as a window event below and resizes the swapchain as a drag would.
    const bool want_fullscreen = BbSettings::Get().fullscreen.load();
    if (want_fullscreen != fullscreen_applied) {
        fullscreen_applied = want_fullscreen;
        SDL_SetWindowFullscreen(window, want_fullscreen);
    }
    // The mouse camera (src/mouse_camera.c) holds the mouse after a click in the window, while
    // the setting is on and nothing else needs the pointer: focus elsewhere, the overlay or a
    // text entry gives it back (a click takes it again).
    const bool focused = SDL_GetWindowFlags(window) & SDL_WINDOW_INPUT_FOCUS;
    g_window_focused.store(focused, std::memory_order_relaxed);
    {
        int w = 0, h = 0;
        SDL_GetWindowSize(window, &w, &h);
        g_window_points_w.store(w, std::memory_order_relaxed);
        g_window_points_h.store(h, std::memory_order_relaxed);
    }
    // A menu with the pointer (src/menu_pointer.c) shows the cursor; the camera takes the mouse
    // back without a click when the menu closes, if it held it when the menu opened.
    const bool menu_pointer = g_menu_pointer.load(std::memory_order_relaxed);
    if (menu_pointer && !menu_pointer_seen) {
        menu_pointer_seen = true;
        rearm_after_menu = mouse_captured;
    } else if (!menu_pointer && menu_pointer_seen) {
        menu_pointer_seen = false;
        mouse_armed = mouse_armed || rearm_after_menu;
        rearm_after_menu = false;
    }
    const bool can_capture = BbSettings::Get().mouse_camera.load() && !text_active &&
                             !BbOverlay::ReleasesMouse() && focused && !menu_pointer;
    if (!can_capture && !menu_pointer) {
        mouse_armed = false;
    }
    if ((can_capture && mouse_armed) != mouse_captured) {
        mouse_captured = can_capture && mouse_armed;
        SDL_SetWindowRelativeMouseMode(window, mouse_captured);
        SetMouseCaptured(mouse_captured);
    }
    SDL_Event event;
    while (SDL_PollEvent(&event)) {
        if (event.type == SDL_EVENT_GAMEPAD_BUTTON_DOWN ||
            (event.type == SDL_EVENT_GAMEPAD_AXIS_MOTION &&
             (event.gaxis.value > 8000 || event.gaxis.value < -8000))) {
            g_pad_in_use = true;
        } else if (event.type == SDL_EVENT_MOUSE_MOTION || event.type == SDL_EVENT_MOUSE_BUTTON_DOWN ||
                   event.type == SDL_EVENT_KEY_DOWN) {
            g_pad_in_use = false;
        }
        if (text_active && (event.type == SDL_EVENT_TEXT_INPUT || event.type == SDL_EVENT_KEY_DOWN)) {
            std::scoped_lock lock{text_mutex};
            if (event.type == SDL_EVENT_TEXT_INPUT) {
                text += event.text.text;
            } else if (event.key.key == SDLK_BACKSPACE && !text.empty()) {
                size_t cut = text.size() - 1; // drop one UTF-8 code point
                while (cut > 0 && (static_cast<unsigned char>(text[cut]) & 0xC0) == 0x80) --cut;
                text.erase(cut);
            } else if (event.key.key == SDLK_RETURN || event.key.key == SDLK_KP_ENTER || event.key.key == SDLK_ESCAPE) {
                text_state = event.key.key == SDLK_ESCAPE ? 2 : 1;
                text_active = false;
                SDL_StopTextInput(window);
            }
            UpdateTextTitle();
            continue;
        }
        // The controller finishes the text dialog too: Cross (A) accepts, Circle (B) cancels.
        if (text_active && event.type == SDL_EVENT_GAMEPAD_BUTTON_DOWN &&
            (event.gbutton.button == SDL_GAMEPAD_BUTTON_SOUTH ||
             event.gbutton.button == SDL_GAMEPAD_BUTTON_EAST)) {
            std::scoped_lock lock{text_mutex};
            text_state = event.gbutton.button == SDL_GAMEPAD_BUTTON_SOUTH ? 1 : 2;
            text_active = false;
            SDL_StopTextInput(window);
            UpdateTextTitle();
            continue;
        }
        if (BbOverlay::HandleEvent(event)) {
            continue;
        }
        switch (event.type) {
        case SDL_EVENT_WINDOW_PIXEL_SIZE_CHANGED:
        case SDL_EVENT_WINDOW_RESIZED: {
            int w = 0, h = 0;
            SDL_GetWindowSizeInPixels(window, &w, &h);
            width = w;
            height = h;
            break;
        }
        case SDL_EVENT_MOUSE_BUTTON_DOWN:
            mouse_armed = can_capture; // a click in a menu is the pointer's, not the camera's
            break;
        case SDL_EVENT_MOUSE_MOTION:
            if (mouse_captured) {
                NoteMouseMotion(event.motion.xrel, event.motion.yrel);
            }
            break;
        case SDL_EVENT_WINDOW_FOCUS_LOST:
            mouse_armed = false;
            // A screenshot tool or another app can take focus while relative mode is on:
            // release the clip and show the pointer instead of carrying both into the background.
            if (mouse_captured) {
                mouse_captured = false;
                SDL_SetWindowRelativeMouseMode(window, false);
                SetMouseCaptured(false);
            }
            if (cursor_hidden_by_port) {
                SDL_ShowCursor();
                cursor_hidden_by_port = false;
            }
            break;
        case SDL_EVENT_MOUSE_WHEEL:
            NoteMouseWheel(event.wheel.direction == SDL_MOUSEWHEEL_FLIPPED ? -event.wheel.y : event.wheel.y);
            break;
#ifdef _WIN32
        // HDR switched in Windows (Win+Alt+B) or the window moved to another display.
        case SDL_EVENT_WINDOW_HDR_STATE_CHANGED:
            on_hdr_display = event.window.data1 != 0;
            break;
#endif
        case SDL_EVENT_QUIT:
        case SDL_EVENT_WINDOW_CLOSE_REQUESTED:
            // Release relative mode (its clip) and the pointer before the window goes away.
            if (mouse_captured) {
                mouse_captured = false;
                SDL_SetWindowRelativeMouseMode(window, false);
                SetMouseCaptured(false);
            }
            if (cursor_hidden_by_port) {
                SDL_ShowCursor();
                cursor_hidden_by_port = false;
            }
            is_open = false;
            break;
        default:
            break;
        }
    }
    // Hidden while playing on a controller; the mouse camera's relative mode hides it on its own.
    // mouse_hide_cursor keeps it hidden over the game and its menus too (mouse-to-pad tools,
    // #88), but not over the guide menu or the map, which are used with the pointer.
    const bool hide_always = BbSettings::Get().mouse_hide_cursor.load() && !BbOverlay::ReleasesMouse();
    // Track our own hide flag: SDL_CursorVisible() does not mirror the Win32 ShowCursor counter,
    // so toggling on it could hide the pointer repeatedly and leave the counter negative (the
    // pointer then stays gone system-wide after a screenshot tool takes focus).
    const bool show = (!g_pad_in_use && !hide_always) || !focused || text_active;
    if (!mouse_captured) {
        if (show && cursor_hidden_by_port) {
            SDL_ShowCursor();
            cursor_hidden_by_port = false;
        } else if (!show && !cursor_hidden_by_port) {
            SDL_HideCursor();
            cursor_hidden_by_port = true;
        }
    }
    return is_open;
}

} // namespace Frontend

// Mouse wheel notches since the pad last took one: the pad read makes each a short press of the
// action bound to WheelUp / WheelDown (input_bindings.h).
static std::atomic<int> g_wheel_up{0}, g_wheel_down{0};
void NoteMouseWheel(float y) {
    if (y > 0) g_wheel_up.fetch_add(1, std::memory_order_relaxed);
    if (y < 0) g_wheel_down.fetch_add(1, std::memory_order_relaxed);
}

// One notch a read, each direction: bit 0 up, bit 1 down. A notch is held for one read and
// released the next, so two in a row read as two presses.
extern "C" uint32_t bbgpu_mouse_wheel_take(void) {
    static bool up_held, down_held;
    uint32_t bits = 0;
    if (up_held) up_held = false;
    else if (g_wheel_up.load(std::memory_order_relaxed) > 0) {
        g_wheel_up.fetch_sub(1, std::memory_order_relaxed);
        up_held = true;
        bits |= 1;
    }
    if (down_held) down_held = false;
    else if (g_wheel_down.load(std::memory_order_relaxed) > 0) {
        g_wheel_down.fetch_sub(1, std::memory_order_relaxed);
        down_held = true;
        bits |= 2;
    }
    return bits;
}

// Mouse motion for the mouse camera, in 1/16 counts, taken once a camera update on the game's
// thread. Motion that waited longer than 250 ms (a loading screen, a menu without the camera)
// is dropped rather than turning the camera all at once afterwards.
static std::atomic<long long> g_motion_x{0}, g_motion_y{0};
static std::atomic<unsigned long long> g_motion_taken_ms{0};
static std::atomic<bool> g_mouse_captured{false};
void NoteMouseMotion(float x, float y) {
    g_motion_x.fetch_add(std::llround(x * 16.0f), std::memory_order_relaxed);
    g_motion_y.fetch_add(std::llround(y * 16.0f), std::memory_order_relaxed);
}
void SetMouseCaptured(bool captured) {
    g_mouse_captured.store(captured, std::memory_order_relaxed);
    g_motion_x.store(0, std::memory_order_relaxed);
    g_motion_y.store(0, std::memory_order_relaxed);
}
extern "C" void bbgpu_set_menu_pointer(int active) {
    g_menu_pointer.store(active != 0, std::memory_order_relaxed);
}

// The presented frame's size (vk_presenter.cpp letterboxes it into the window).
static std::atomic<int> g_frame_w{0}, g_frame_h{0};
void BbNotePresentedFrame(int width, int height) {
    g_frame_w.store(width, std::memory_order_relaxed);
    g_frame_h.store(height, std::memory_order_relaxed);
}

extern "C" int bbgpu_mouse_stage_position(float* x, float* y) {
    const float ww = float(g_window_points_w.load(std::memory_order_relaxed));
    const float wh = float(g_window_points_h.load(std::memory_order_relaxed));
    const float fw = float(g_frame_w.load(std::memory_order_relaxed));
    const float fh = float(g_frame_h.load(std::memory_order_relaxed));
    if (!g_window_focused.load(std::memory_order_relaxed) || ww <= 0 || wh <= 0 || fw <= 0 || fh <= 0 ||
        g_mouse_captured.load(std::memory_order_relaxed)) {
        return 0;
    }
    float mx = 0, my = 0;
    SDL_GetMouseState(&mx, &my); // window points, like SDL_GetWindowSize
    return BbStage::Point(mx, my, ww, wh, fw, fh, x, y);
}

extern "C" int bbgpu_mouse_captured(void) {
    return g_mouse_captured.load(std::memory_order_relaxed);
}
extern "C" int bbgpu_mouse_motion_take(float* dx, float* dy) {
    const unsigned long long now = SDL_GetTicks();
    const unsigned long long last = g_motion_taken_ms.exchange(now, std::memory_order_relaxed);
    const long long x = g_motion_x.exchange(0, std::memory_order_relaxed);
    const long long y = g_motion_y.exchange(0, std::memory_order_relaxed);
    const bool stale = now - last > 250;
    *dx = stale ? 0.0f : float(x) / 16.0f;
    *dy = stale ? 0.0f : float(y) / 16.0f;
    return (*dx != 0.0f || *dy != 0.0f) ? 1 : 0;
}

// The window title's status (SetWindowStatus, any thread; empty: the plain title).
static std::mutex g_status_mutex;
static std::string g_status;
static bool g_status_changed = false;
void SetWindowStatus(const std::string& status) {
    std::scoped_lock lock{g_status_mutex};
    if (status != g_status) {
        g_status = status;
        g_status_changed = true;
    }
}
bool TakeWindowStatus(std::string& status) {
    std::scoped_lock lock{g_status_mutex};
    if (!g_status_changed) {
        return false;
    }
    g_status_changed = false;
    status = g_status;
    return true;
}

// The in-game PC menu's Quit Game: the same as closing the window (SDL_PushEvent is safe from
// any thread, here the game's menu thread).
extern "C" void bbgpu_request_quit(void) {
    SDL_Event event{};
    event.type = SDL_EVENT_QUIT;
    SDL_PushEvent(&event);
}
