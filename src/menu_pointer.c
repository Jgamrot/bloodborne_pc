/* SPDX-License-Identifier: GPL-3.0-or-later
 * Mouse pointer in the game's menus (menu_pointer.h). Ported from droogie's bbhost
 * (https://github.com/droogie/bbhost, GPL-3.0-or-later, engine/menu_pointer.cpp), which mapped the
 * engine's list component and its Scaleform objects; the notes below are bbhost's, shortened.
 *
 * The list component (vtable 0x5799fb0): +0x30 listener (slot 0x10 takes &index, called after
 * the cursor moves), +0x70 item count, +0x74 cursor, +0x78 cursor override (when >= 0), +0x7c
 * cells per line, +0x80 visible lines (1: one line holds every item), +0x84 scroll along the
 * line, +0x88 the root clip's wrapper, +0x24c scroll in lines, +0x258 item provider (slot 0x18
 * builds a wrapper for "Item_<cell>_<line>"), +0x2b0 wraps around. Its update (sub_1ecff30) is
 * given a pointer to a focus byte. SetCursor (sub_1ecf6b0) scrolls if it must, asks the row's
 * predicate, moves the "Cursor" glow and stores the index (1; 2 refused; 0 out of range); the
 * listener and the move sound are the update's, so a hover does them too.
 *
 * A value wrapper holds a GFx::Value at +0x30 (interface +0x40, type +0x48, data +0x50); type
 * & 0x8f == 10 is a display object, whose native DisplayObject is *(data + 0x88): parent +0x38,
 * flags +0x6b (0x40 visible), GetBounds at vtable +0x1f0. sub_402040 is its world matrix.
 * Coordinates are the movie's stage: 1920x1080 pixels, 20 twips to the pixel. */
#define _GNU_SOURCE
#include "menu_pointer.h"

#include "engine_hooks.h"
#include "gpu/bbgpu.h"
#include "runtime.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

enum {
    SET_CURSOR = 0x1ecf6b0,
    SCROLL_BY = 0x1ed0dd0,    /* (component, along the line, lines), clamped */
    HIDE_CURSORS = 0x1ecf0e0, /* hides every visible row's Cursor */
    CHILD = 0x1edb220,        /* wrapper = parent.GetMember(name) */
    CURSOR_NAME = 0x4d34044,  /* "Cursor" */
    WORLD_MATRIX = 0x402040,
    MENU_FLOW = 0x5980e38,    /* the front end's menu flow: ptr; input blocked if *(u64 *)(+0xa78) */
    INPUT_BLOCK_B = 0x5962878, /* ptr; blocked if *(u32 *)(+0x2e4) */
    REGION = 0x5528948,       /* CSLocalize's region: 5 decides with Circle (Japan's way) */
    MENU_SE = 0x597fc60,      /* the menu sound request {id, priority} and its label */
    MENU_SE_LABEL = 0x597fc68,
    CURSOR_MOVE_LABEL = 0x4d344e4,
    EXEC_END = 0x54d96dc,     /* the end of the eboot's executable segment */
};
enum {
    FLOW_STARTED = 0xb11, /* 0 on the title and the front end, 1 once in the game */
    FLOW_MENU = 0xa88,    /* the open menu, if any (also screens with no list, such as Stats) */
    LISTENER = 0x30, COUNT = 0x70, CURSOR = 0x74, CURSOR_OVERRIDE = 0x78, LINE_LEN = 0x7c,
    LINES = 0x80, LINE_SCROLL = 0x84, ROOT_TYPE = 0xc8, ROOT_DATA = 0xd0, SCROLL = 0x24c,
    PROVIDER = 0x258, WRAPS = 0x2b0,
    WRAPPER_VALUE = 0x30, WRAPPER_INTERFACE = 0x40, WRAPPER_TYPE = 0x48, WRAPPER_DATA = 0x50,
    NATIVE = 0x88, PARENT = 0x38, FLAGS = 0x6b, VISIBLE = 0x40, GET_BOUNDS = 0x1f0,
};
enum { PAD_UP = 0x10, PAD_RIGHT = 0x20, PAD_DOWN = 0x40, PAD_LEFT = 0x80, PAD_CIRCLE = 0x2000, PAD_CROSS = 0x4000 };
enum { CLICK_MS = 250, PRESS_MS = 60, FOCUS_MS = 400, SEEN_SLOTS = 32 };

typedef int64_t(BB_GUEST_ABI *GuestFn)(uint64_t, uint64_t, uint64_t, uint64_t, uint64_t, uint64_t);

static int g_on, g_log;
static volatile int64_t g_focus_ms, g_click_ms, g_press_ms;
static volatile int g_click, g_owns;
static volatile uint32_t g_press;

static int64_t now_ms(void) {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (int64_t)t.tv_sec * 1000 + t.tv_nsec / 1000000;
}
static uint64_t addr(uint64_t bn) { return (uint64_t)(uintptr_t)bb_guest(BB_BN(bn)); }
static GuestFn fn(uint64_t bn) { return (GuestFn)bb_guest(BB_BN(bn)); }
static uint64_t ptr(const void *p) { return (uint64_t)(uintptr_t)p; }
static int32_t i32(const unsigned char *b, size_t at) { int32_t v; memcpy(&v, b + at, 4); return v; }
static uint32_t u32(const unsigned char *b, size_t at) { uint32_t v; memcpy(&v, b + at, 4); return v; }
static uint64_t u64(const unsigned char *b, size_t at) { uint64_t v; memcpy(&v, b + at, 8); return v; }
static int rd(uint64_t a, void *out, size_t n) { return a >= 0x1000 && bb_read(a, out, n); }

/* A function of the eboot: in its executable segment and opening with push rbp; mov rbp, rsp. */
static int guest_code(uint64_t a) {
    unsigned char p[4];
    return a >= addr(0x400000) && a < addr(EXEC_END) && rd(a, p, 4) && p[0] == 0x55 && p[1] == 0x48 &&
           p[2] == 0x89 && p[3] == 0xe5;
}
static uint64_t slot(uint64_t object, size_t offset) {
    uint64_t vt = 0, f = 0;
    return object && rd(object, &vt, 8) && rd(vt + offset, &f, 8) && guest_code(f) ? f : 0;
}

/* A wrapper the game builds into our buffer. Its GFx::Value links itself into the movie's
 * managed values, so it is released before the buffer goes, as the game's own stack wrappers. */
typedef struct { _Alignas(16) unsigned char b[0x80]; } Wrapper;
static void wrapper_free(Wrapper *w) {
    if (!(u32(w->b, WRAPPER_TYPE) & 0x40)) return;
    const uint64_t release = slot(u64(w->b, WRAPPER_INTERFACE), 0x18);
    if (release)
        ((GuestFn)(uintptr_t)release)(u64(w->b, WRAPPER_INTERFACE), ptr(w->b + WRAPPER_VALUE), u64(w->b, WRAPPER_DATA), 0, 0, 0);
}
static uint64_t display(const Wrapper *w) {
    uint64_t d = 0;
    const uint64_t data = u64(w->b, WRAPPER_DATA);
    return (u32(w->b, WRAPPER_TYPE) & 0x8f) == 10 && data && rd(data + NATIVE, &d, 8) ? d : 0;
}
static void child(Wrapper *out, Wrapper *parent, const char *name) {
    memset(out, 0, sizeof(*out));
    fn(CHILD)(ptr(out->b), ptr(parent->b), ptr(name), 0, 0, 0);
}

/* Visible, and so is everything above it (hidden slots, a screen fading out). */
static int shown(uint64_t obj) {
    for (int depth = 0; obj && depth < 32; ++depth) {
        unsigned char flags = 0;
        if (!rd(obj + FLAGS, &flags, 1) || !(flags & VISIBLE) || !rd(obj + PARENT, &obj, 8)) return 0;
    }
    return 1;
}

typedef struct { float x1, y1, x2, y2; } Rect;

/* The point (stage pixels) inside the object's bounds, `grow` pixels around them; `world` gets
 * the bounds on the stage. DS3's SprjScaleformValue::HitTest on Bloodborne's vtable slots. */
static int hit(uint64_t obj, float sx, float sy, Rect *world, float grow) {
    const uint64_t get_bounds = slot(obj, GET_BOUNDS);
    if (!get_bounds) return 0;
    _Alignas(16) float identity[8] = {1, 0, 0, 0, 0, 1, 0, 0}, r[4] = {0}, m[8] = {1, 0, 0, 0, 0, 1, 0, 0};
    ((GuestFn)(uintptr_t)get_bounds)(ptr(r), obj, ptr(identity), 0, 0, 0);
    if (!(r[2] > r[0]) || !(r[3] > r[1])) return 0;
    fn(WORLD_MATRIX)(obj, ptr(m), 0, 0, 0, 0);
    const float xs[2] = {r[0], r[2]}, ys[2] = {r[1], r[3]};
    world->x1 = world->y1 = 1e9f;
    world->x2 = world->y2 = -1e9f;
    for (int i = 0; i < 2; ++i)
        for (int j = 0; j < 2; ++j) {
            const float wx = (m[0] * xs[i] + m[1] * ys[j] + m[3]) / 20.0f, wy = (m[4] * xs[i] + m[5] * ys[j] + m[7]) / 20.0f;
            world->x1 = fminf(world->x1, wx), world->x2 = fmaxf(world->x2, wx);
            world->y1 = fminf(world->y1, wy), world->y2 = fmaxf(world->y2, wy);
        }
    const float det = m[0] * m[5] - m[1] * m[4];
    if (fabsf(det) < 1e-12f) return 0;
    const float px = sx * 20.0f - m[3], py = sy * 20.0f - m[7];
    const float lx = (m[5] * px - m[1] * py) / det, ly = (-m[4] * px + m[0] * py) / det;
    const float g = grow * 20.0f / sqrtf(fabsf(det));
    return lx >= r[0] - g && lx <= r[2] + g && ly >= r[1] - g && ly <= r[3] + g;
}

static int cursor_of(const unsigned char *c) {
    const int o = i32(c, CURSOR_OVERRIDE);
    return o >= 0 ? o : i32(c, CURSOR);
}

/* Builds the wrapper of the row at a visible cell (packed: cell, line << 32); 0 when none. */
static int make_item(unsigned char *c, uint64_t packed, Wrapper *item) {
    memset(item, 0, sizeof(*item));
    const uint64_t provider = u64(c, PROVIDER), make = slot(provider, 0x18);
    if (!make) return 0;
    ((GuestFn)(uintptr_t)make)(ptr(item->b), provider, ptr(&packed), 0, 0, 0);
    return 1;
}

/* The item under the pointer (its absolute index) or -1. The cells walked are the ones
 * SetCursor can address; of the rows whose glow contains the point (glows overlap: 130 px on a
 * 68 px pitch in System), the nearest centre wins. An option row's value widget counts too. */
static int item_at(unsigned char *c, float sx, float sy, uint64_t *packed_out) {
    const int count = i32(c, COUNT), cells = i32(c, LINE_LEN), lines = i32(c, LINES);
    const int cell_scroll = i32(c, LINE_SCROLL), line_scroll = i32(c, SCROLL);
    const int wraps = c[WRAPS] != 0;
    if (count <= 0 || cells <= 0 || lines <= 0 || cells > 64 || lines > 64) return -1;
    const int stride = lines != 1 ? cells : (cells > count ? cells : count);
    int best = -1;
    float best_d = 0;
    for (int line = 0; line < lines; ++line)
        for (int cell = 0; cell < cells; ++cell) {
            int index = (line_scroll + line) * stride + cell_scroll + cell;
            if (wraps) index %= count;
            if (index < 0 || index >= count) continue;
            const uint64_t packed = (uint32_t)cell | (uint64_t)(uint32_t)line << 32;
            Wrapper item, region;
            if (!make_item(c, packed, &item)) return -1;
            const uint64_t obj = display(&item);
            if (!obj || !shown(obj)) {
                wrapper_free(&item);
                continue;
            }
            child(&region, &item, (const char *)bb_guest(BB_BN(CURSOR_NAME)));
            uint64_t target = display(&region);
            Rect w = {0};
            int in = target ? hit(target, sx, sy, &w, 0) : hit(obj, sx, sy, &w, 0);
            static const char *const parts[] = {"Widgets/ComboBox", "Widgets/Slider"};
            for (int p = 0; p < 2 && !in; ++p) {
                Wrapper widget;
                child(&widget, &item, parts[p]);
                const uint64_t wobj = display(&widget);
                Rect ww = {0};
                if (wobj && shown(wobj) && hit(wobj, sx, sy, &ww, 0)) in = 1, w = ww;
                wrapper_free(&widget);
            }
            wrapper_free(&region);
            wrapper_free(&item);
            if (!in) continue;
            const float dx = (w.x1 + w.x2) * 0.5f - sx, dy = (w.y1 + w.y2) * 0.5f - sy, d = dx * dx + dy * dy;
            if (best < 0 || d < best_d) best = index, best_d = d, *packed_out = packed;
        }
    return best;
}

static uint32_t confirm_button(void) {
    int32_t region = -1;
    return rd(addr(REGION), &region, 4) && region == 5 ? PAD_CIRCLE : PAD_CROSS;
}

/* What a click on a row means: a slider's arrow steps it, a combo box steps toward the side
 * clicked, anything else decides. */
static uint32_t click_button(unsigned char *c, uint64_t packed, float sx, float sy) {
    Wrapper item;
    uint32_t button = confirm_button();
    if (!make_item(c, packed, &item)) return button;
    if (display(&item)) {
        static const struct { const char *path; float grow; int combo; uint32_t button; } parts[] = {
            {"Widgets/Slider/LeftArrow", 14, 0, PAD_LEFT}, {"Widgets/Slider/RightArrow", 14, 0, PAD_RIGHT},
            {"Widgets/ComboBox", 0, 1, 0},
        };
        for (int p = 0; p < 3; ++p) {
            Wrapper part;
            child(&part, &item, parts[p].path);
            const uint64_t obj = display(&part);
            Rect w = {0};
            const int in = obj && shown(obj) && hit(obj, sx, sy, &w, parts[p].grow);
            wrapper_free(&part);
            if (in) {
                button = parts[p].combo ? (sx < (w.x1 + w.x2) * 0.5f ? PAD_LEFT : PAD_RIGHT) : parts[p].button;
                break;
            }
        }
    }
    wrapper_free(&item);
    return button;
}

/* SetCursor's last step, on the row where it is now: its Cursor glow shown (slot 1 SetVisible). */
static void show_cursor(unsigned char *c, uint64_t packed) {
    Wrapper item, cursor;
    if (!make_item(c, packed, &item)) return;
    child(&cursor, &item, (const char *)bb_guest(BB_BN(CURSOR_NAME)));
    const uint64_t set_visible = display(&cursor) ? slot(ptr(cursor.b), 8) : 0;
    if (set_visible) ((GuestFn)(uintptr_t)set_visible)(ptr(cursor.b), 1, 0, 0, 0, 0);
    wrapper_free(&cursor);
    wrapper_free(&item);
}

static int input_blocked(void) {
    uint64_t a = 0, b = 0, v = 0;
    uint32_t w = 0;
    return (rd(addr(MENU_FLOW), &a, 8) && a && rd(a + 0xa78, &v, 8) && v) ||
           (rd(addr(INPUT_BLOCK_B), &b, 8) && b && rd(b + 0x2e4, &w, 4) && w);
}

/* The front end (title and the menus before the world), or a menu open in the world, or a list
 * that had the focus moments ago. */
static int in_menu(void) {
    uint64_t flow = 0, menu = 0;
    unsigned char started = 1;
    if (!rd(addr(MENU_FLOW), &flow, 8) || !flow) return 0;
    if (rd(flow + FLOW_STARTED, &started, 1) && !started) return 1;
    if (rd(flow + FLOW_MENU, &menu, 8) && menu) return 1;
    return now_ms() - g_focus_ms < FOCUS_MS;
}

/* Where each list last saw the pointer: a hover follows movement only, so a resting mouse never
 * fights the keyboard or a pad. A list not updated for a while is a new screen. */
static struct { unsigned char *comp; float x, y; int64_t ms; } g_seen[SEEN_SLOTS];
static int g_seen_next;
static int moved_for(unsigned char *c, float x, float y) {
    const int64_t now = now_ms();
    for (int i = 0; i < SEEN_SLOTS; ++i)
        if (g_seen[i].comp == c) {
            const int fresh = now - g_seen[i].ms > 250, moved = !fresh && (x != g_seen[i].x || y != g_seen[i].y);
            g_seen[i].x = x, g_seen[i].y = y, g_seen[i].ms = now;
            return moved;
        }
    const int i = g_seen_next++ % SEEN_SLOTS;
    g_seen[i].comp = c, g_seen[i].x = x, g_seen[i].y = y, g_seen[i].ms = now;
    return 0;
}

static void press(uint32_t buttons) {
    g_press = buttons;
    g_press_ms = now_ms();
}

void bb_menu_pointer_step(unsigned char *c, const unsigned char *input) {
    if (!g_on || !input || !*input || input_blocked()) return;
    g_focus_ms = now_ms();
    if (!g_owns) return;
    float sx, sy;
    if (!bbgpu_mouse_stage_position(&sx, &sy)) return;
    const int moved = moved_for(c, sx, sy);
    int click = 0;
    if (g_click) {
        if (now_ms() - g_click_ms > CLICK_MS) g_click = 0; /* no list claimed it */
        else click = 1;
    }
    /* A list of one cell on one line is a spinner (an option's value): a click steps it toward
     * the side it landed on. */
    if (i32(c, LINES) == 1 && i32(c, LINE_LEN) == 1 && i32(c, COUNT) > 1) {
        uint64_t root = 0;
        const uint64_t data = u64(c, ROOT_DATA);
        Rect w = {0};
        if (click && (u32(c, ROOT_TYPE) & 0x8f) == 10 && data && rd(data + NATIVE, &root, 8) && root &&
            shown(root) && hit(root, sx, sy, &w, 0)) {
            g_click = 0;
            press(sx < (w.x1 + w.x2) * 0.5f ? PAD_LEFT : PAD_RIGHT);
        }
        return;
    }
    if (!moved && !click) return;
    if (runtime_pad_buttons() & (PAD_UP | PAD_DOWN | PAD_LEFT | PAD_RIGHT)) return;
    uint64_t packed = 0;
    const int want = item_at(c, sx, sy, &packed);
    if (want < 0) return; /* a miss changes nothing, and a click on nothing does nothing */
    if (click) g_click = 0;
    const int was = cursor_of(c);
    int now = was;
    if (want != was) {
        /* SetCursor keeps a line of margin and scrolls when it lands on the first or last visible
         * line; under a pointer that would creep the list along. The pointer only targets rows on
         * screen, so the scroll is put back (the wheel scrolls), and the glow lit where the row is. */
        const int s1 = i32(c, LINE_SCROLL), s2 = i32(c, SCROLL);
        const int r = (int)fn(SET_CURSOR)(ptr(c), (uint64_t)(int64_t)want, 0, 0, 0, 0);
        const int d1 = s1 - i32(c, LINE_SCROLL), d2 = s2 - i32(c, SCROLL);
        if (r == 1 && (d1 || d2)) {
            fn(SCROLL_BY)(ptr(c), (uint64_t)(int64_t)d1, (uint64_t)(int64_t)d2, 0, 0, 0);
            fn(HIDE_CURSORS)(ptr(c), 0, 0, 0, 0, 0);
            show_cursor(c, packed);
        }
        now = cursor_of(c);
        if (g_log) printf("Menu pointer: list %p hover %d -> %d (set %d)\n", (void *)c, was, want, r);
    }
    /* A click acts on the row it landed on, once the cursor is there (a refused row is not chosen). */
    if (click && now == want) press(click_button(c, packed, sx, sy));
    if (now == was) return;
    /* What the list's update does once it sees the index change: the listener, the move sound. */
    const uint64_t listener = u64(c, LISTENER), call = slot(listener, 0x10);
    if (call) {
        int32_t index = now;
        ((GuestFn)(uintptr_t)call)(listener, ptr(&index), 0, 0, 0, 0);
    }
    int32_t *se = (int32_t *)bb_guest(BB_BN(MENU_SE));
    if (se[1] <= 0) {
        se[0] = 0, se[1] = 0;
        const uint64_t label = addr(CURSOR_MOVE_LABEL);
        memcpy(bb_guest(BB_BN(MENU_SE_LABEL)), &label, 8);
    }
}

void bb_menu_pointer_frame(void) {
    if (!g_on) return;
    int on = 1;
    bbgpu_setting_get("mouse_menu", &on);
    const int owns = on && in_menu();
    g_owns = owns;
    bbgpu_set_menu_pointer(owns);
}

/* While a menu is open, even over the black bars beside the picture: a click there must not
 * turn into an attack's R1 (a tab switch). */
int bb_menu_pointer_owns_mouse(void) { return g_on && g_owns; }
void bb_menu_pointer_click(void) {
    g_click_ms = now_ms();
    g_click = 1;
}
void bb_menu_pointer_back(void) { press(confirm_button() == PAD_CROSS ? PAD_CIRCLE : PAD_CROSS); }
uint32_t bb_menu_pointer_buttons(void) {
    if (!g_press) return 0;
    if (now_ms() - g_press_ms > PRESS_MS) {
        g_press = 0;
        return 0;
    }
    return g_press;
}

void bb_menu_pointer_off(void) {
    g_on = 0;
    g_owns = 0;
}

int bb_menu_pointer_install(void) {
    const char *env = getenv("BB_MOUSE_MENU"), *log = getenv("BB_MOUSE_MENU_LOG");
    if (env && !strcmp(env, "0")) {
        puts("Menu pointer: off (BB_MOUSE_MENU=0)");
        return 0;
    }
    g_log = log && log[0] == '1';
    /* The functions the pointer calls, before anything relies on them. */
    static const uint64_t code[] = {SET_CURSOR, SCROLL_BY, HIDE_CURSORS, CHILD, WORLD_MATRIX};
    for (size_t i = 0; i < sizeof(code) / sizeof(*code); ++i)
        if (!guest_code(addr(code[i]))) {
            printf("Menu pointer: the list code at %#llx is not game 1.09's; off\n", (unsigned long long)code[i]);
            return 0;
        }
    if (strcmp((const char *)bb_guest(BB_BN(CURSOR_NAME)), "Cursor")) {
        puts("Menu pointer: the game's names are not where 1.09 has them; off");
        return 0;
    }
    g_on = 1;
    puts("Menu pointer: on (mouse_menu=0 turns it off)");
    return 1;
}
