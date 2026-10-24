/* SPDX-License-Identifier: GPL-2.0-or-later
 * PC features installed through the engine hooks (engine_features.h). The features themselves
 * (in-game PC menu, enhancements, keyboard and mouse) add themselves to these lists. */
#include "engine_features.h"
#include "cloth_rate.h"
#include "engine_hooks.h"
#include "key_prompts.h"
#include "menu_pointer.h"
#include "mouse_camera.h"
#include "occlusion_queries.h"
#include "pc_menu.h"
#include "rebirth.h"
#include "wind_pace.h"

#include <stddef.h>
#include <stdio.h>

typedef int (*Install)(void);
typedef void (*Frame)(void);

/* The menu pointer rides on the menus' list update, which the PC menu hooks when it is on. */
static int menu_pointer_install(void) {
    if (!bb_menu_pointer_install()) return 0;
    const int hooks = bb_menu_lists_hook();
    if (bb_menu_lists_hooked()) return 1 + hooks;
    bb_menu_pointer_off();
    puts("Menu pointer: off - the menus' list update could not be hooked");
    return 0;
}

static const Install installs[] = {bb_cloth_rate_install,
                                   bb_pc_menu_install, bb_rebirth_install, bb_mouse_camera_install,
                                   bb_key_prompts_install, menu_pointer_install,
                                   bb_occlusion_queries_install, bb_wind_pace_install};
static const Frame frames[] = {bb_pc_menu_frame, bb_menu_pointer_frame};

int bb_engine_install(void) {
    int hooks = 0;
    for (size_t i = 0; i < sizeof(installs) / sizeof(*installs); ++i)
        if (installs[i]) hooks += installs[i]();
    /* The main-thread tick, when a feature registered one (bb_on_main_frame). */
    return hooks + bb_main_frame_install();
}

void bb_engine_frame(void) {
    for (size_t i = 0; i < sizeof(frames) / sizeof(*frames); ++i)
        if (frames[i]) frames[i]();
}
