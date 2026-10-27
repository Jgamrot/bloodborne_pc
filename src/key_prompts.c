/* SPDX-License-Identifier: GPL-3.0-or-later
 * Keyboard prompt formatter for the player's 1.09 game image. The formatter site and
 * glyph names were documented by droogie's bbhost (GPL-3.0-or-later); this implementation
 * uses the native port's own key bindings and guarded engine hook. No game textures or
 * third-party prompt-mod files are distributed. */
#include "key_prompts.h"
#include "engine_hooks.h"
#include "gpu/bbgpu.h"
#include "input_bindings.h"

#include <SDL3/SDL.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <uchar.h>

#define FORMATTER BB_BN(0x1ee7270)
static const BbCode FORMATTER_PROLOGUE = {18, 0x7dffdc99bb984501ull};
static const char16_t IMAGE_FORMAT[] = u"<img src='%s' vspace='-8'>";
static const char16_t KEY_FORMAT[] = u"[%s]";
/* MsgRepositoryImp::LookupEntry, also identified in bbhost. */
#define LOOKUP_ENTRY BB_BN(0x136f340)
static const BbCode LOOKUP_PROLOGUE = {15, 0xc129c946d74b4a37ull};

typedef struct { const char *tag; int action[4]; } Prompt;
#define NONE (-1)
/* The game calls Cross KG_Cancel and Circle KG_OK in the Western menu layout. */
static const Prompt PROMPTS[] = {
    {"OK", {BIND_BACK, NONE, NONE, NONE}},
    {"Cancel", {BIND_CONFIRM, NONE, NONE, NONE}},
    {"R1", {BIND_ATTACK, NONE, NONE, NONE}},
    {"R2", {BIND_STRONG, NONE, NONE, NONE}},
    {"L1", {BIND_TRANSFORM, NONE, NONE, NONE}},
    {"L2", {BIND_FIREARM, NONE, NONE, NONE}},
    {"L3", {BIND_L3, NONE, NONE, NONE}},
    {"R3", {BIND_LOCK_ON, NONE, NONE, NONE}},
    {"R_U", {BIND_BLOOD_VIAL, NONE, NONE, NONE}},
    {"R_L", {BIND_USE_ITEM, NONE, NONE, NONE}},
    {"L_U", {BIND_DPAD_UP, NONE, NONE, NONE}},
    {"L_D", {BIND_SWITCH_ITEM, NONE, NONE, NONE}},
    {"L_L", {BIND_SWITCH_LEFT, NONE, NONE, NONE}},
    {"L_R", {BIND_SWITCH_RIGHT, NONE, NONE, NONE}},
    {"L_UD", {BIND_DPAD_UP, BIND_SWITCH_ITEM, NONE, NONE}},
    {"L_LR", {BIND_SWITCH_LEFT, BIND_SWITCH_RIGHT, NONE, NONE}},
    {"L_UDLR", {BIND_DPAD_UP, BIND_SWITCH_ITEM, BIND_SWITCH_LEFT, BIND_SWITCH_RIGHT}},
    {"LS", {BIND_MOVE_F, BIND_MOVE_L, BIND_MOVE_B, BIND_MOVE_R}},
    {"RS", {BIND_LOOK_U, BIND_LOOK_D, BIND_LOOK_L, BIND_LOOK_R}},
    {"TP_L", {BIND_GESTURES, NONE, NONE, NONE}},
    {"TP_R", {BIND_EFFECTS, NONE, NONE, NONE}},
};

static int same16(const char16_t *a, const char16_t *b) {
    for (int i = 0; i < 64; ++i) {
        if (a[i] != b[i]) return 0;
        if (!a[i]) return 1;
    }
    return 0;
}

static int tag_name(const char16_t *name, char *out, size_t size) {
    size_t i = 0;
    for (; i + 1 < size && name[i]; ++i) {
        if (name[i] < 0x20 || name[i] > 0x7e) return 0;
        out[i] = (char)name[i];
    }
    if (name[i]) return 0;
    out[i] = 0;
    return 1;
}

static void binding_name(int action, char *out, size_t size) {
    out[0] = 0;
    int key = bb_binding_key(action);
    int mouse = bb_binding_mouse(action);
    if (key) {
        const char *name = SDL_GetScancodeName((SDL_Scancode)key);
        if (name && *name) snprintf(out, size, "%s", name);
    }
    if (mouse) {
        static const char *const names[] = {"", "Mouse1", "Mouse2", "Mouse3", "Mouse4", "Mouse5", "Wheel Up", "Wheel Down"};
        if (mouse < (int)(sizeof(names) / sizeof(*names))) {
            size_t used = strlen(out);
            snprintf(out + used, size - used, "%s%s", used ? "/" : "", names[mouse]);
        }
    }
}

static void prompt_name(const Prompt *prompt, char *out, size_t size) {
    out[0] = 0;
    if (!strcmp(prompt->tag, "RS")) {
        int enabled = 1;
        if (bbgpu_setting_get("mouse_camera", &enabled) && enabled) {
            snprintf(out, size, "Mouse");
            return;
        }
    }
    for (int i = 0; i < 4 && prompt->action[i] != NONE; ++i) {
        char one[40];
        binding_name(prompt->action[i], one, sizeof(one));
        if (!one[0]) continue;
        size_t used = strlen(out);
        snprintf(out + used, size - used, "%s%s", used ? "/" : "", one);
    }
}

typedef struct { const char *name; int action; const char *fixed; } Placeholder;
static const Placeholder PLACEHOLDERS[] = {
    {"conclusion", BIND_CONFIRM, NULL}, {"cancel", BIND_BACK, NULL},
    {"OKIcon", BIND_INTERACT, NULL}, {"CancelIcon", BIND_ROLL, NULL},
    {"selectU", NONE, "Up"}, {"selectD", NONE, "Down"},
    {"selectL", NONE, "Left"}, {"selectR", NONE, "Right"},
    {"selectUD", NONE, "Up/Down"}, {"selectLR", NONE, "Left/Right"},
    {"selectAll", NONE, "Arrow Keys"}, {"viewChange", BIND_BLOOD_VIAL, NULL},
    {"commando", BIND_USE_ITEM, NULL}, {"spinReset", BIND_LOCK_ON, NULL},
    {"startMenuSwitch", BIND_MENU, NULL}, {"slectMenuSwitch", BIND_GESTURES, NULL},
    {"categoryChangeL", BIND_TRANSFORM, NULL}, {"categoryChangeR", BIND_ATTACK, NULL},
    {"shortCutL", BIND_FIREARM, NULL}, {"shortCutR", BIND_STRONG, NULL},
    {"pageUp", BIND_TRANSFORM, NULL}, {"pageDown", BIND_ATTACK, NULL},
    {"move", NONE, NULL}, {"spin", NONE, NULL},
};

/* Only a game's looked-up string reaches these scanners. Bounds also keep malformed mod text
 * from exhausting memory or running past a missing terminator. */
enum { MAX_MESSAGE = 4096, MAX_BUILT = 8192 };
static size_t append16(char16_t *out, size_t at, size_t cap, const char *ascii) {
    for (size_t i = 0; ascii[i] && at + 1 < cap; ++i)
        out[at++] = (unsigned char)ascii[i] < 0x80 ? (char16_t)ascii[i] : u'?';
    return at;
}

static int ascii_part(const char16_t *text, size_t start, size_t end, char *out, size_t cap) {
    if (end <= start || end - start >= cap) return 0;
    for (size_t i = start; i < end; ++i) {
        char16_t c = text[i];
        if (!((c >= u'A' && c <= u'Z') || (c >= u'a' && c <= u'z') ||
              (c >= u'0' && c <= u'9') || c == u'_')) return 0;
        out[i - start] = (char)c;
    }
    out[end - start] = 0;
    return 1;
}

static const Prompt *find_prompt(const char *name) {
    if (strncmp(name, "KG_", 3)) return NULL;
    for (size_t i = 0; i < sizeof(PROMPTS) / sizeof(*PROMPTS); ++i)
        if (!strcmp(name + 3, PROMPTS[i].tag)) return &PROMPTS[i];
    return NULL;
}

static const char *placeholder_name(const char *name, char *out, size_t cap) {
    for (size_t i = 0; i < sizeof(PLACEHOLDERS) / sizeof(*PLACEHOLDERS); ++i) {
        if (strcmp(name, PLACEHOLDERS[i].name)) continue;
        if (!strcmp(name, "move") || !strcmp(name, "spin")) {
            const Prompt *prompt = find_prompt(!strcmp(name, "move") ? "KG_LS" : "KG_RS");
            if (!prompt) return NULL;
            prompt_name(prompt, out, cap);
            return out[0] ? out : NULL;
        }
        if (PLACEHOLDERS[i].fixed) return PLACEHOLDERS[i].fixed;
        binding_name(PLACEHOLDERS[i].action, out, cap);
        return out[0] ? out : NULL;
    }
    return NULL;
}

/* Returns a newly allocated UTF-16 replacement, or NULL when no known prompt was found. */
static char16_t *rewrite_message(const char16_t *in) {
    char16_t *out = (char16_t *)malloc(MAX_BUILT * sizeof(*out));
    if (!out) return NULL;
    size_t o = 0;
    int changed = 0;
    for (size_t i = 0; i < MAX_MESSAGE && in[i];) {
        if (in[i] == u'<' && in[i + 1] == u'?') {
            size_t j = i + 2;
            while (j < MAX_MESSAGE && j - i < 42 && in[j] && in[j] != u'?' && in[j] != u'>') ++j;
            char name[40], label[96] = "";
            if (j + 1 < MAX_MESSAGE && in[j] == u'?' && in[j + 1] == u'>' &&
                ascii_part(in, i + 2, j, name, sizeof(name))) {
                const char *replacement = placeholder_name(name, label, sizeof(label));
                if (replacement && o + strlen(replacement) + 2 < MAX_BUILT) {
                    out[o++] = u'[';
                    o = append16(out, o, MAX_BUILT, replacement);
                    out[o++] = u']';
                    i = j + 2;
                    changed = 1;
                    continue;
                }
            }
        }
        if (in[i] == u'<' && in[i + 1] == u'i' && in[i + 2] == u'm' && in[i + 3] == u'g' &&
            in[i + 4] == u' ' && in[i + 5] == u's' && in[i + 6] == u'r' &&
            in[i + 7] == u'c' && in[i + 8] == u'=' &&
            (in[i + 9] == u'\'' || in[i + 9] == u'"')) {
            const char16_t quote = in[i + 9];
            size_t j = i + 10;
            while (j < MAX_MESSAGE && j - i < 65 && in[j] && in[j] != quote) ++j;
            char name[40];
            if (j < MAX_MESSAGE && in[j] == quote && ascii_part(in, i + 10, j, name, sizeof(name))) {
                const Prompt *prompt = find_prompt(name);
                size_t end = j + 1;
                while (end < MAX_MESSAGE && end - i < 85 && in[end] && in[end] != u'>') ++end;
                if (prompt && end < MAX_MESSAGE && in[end] == u'>') {
                    char label[96];
                    prompt_name(prompt, label, sizeof(label));
                    if (label[0] && o + strlen(label) + 2 < MAX_BUILT) {
                        out[o++] = u'[';
                        o = append16(out, o, MAX_BUILT, label);
                        out[o++] = u']';
                        i = end + 1;
                        changed = 1;
                        continue;
                    }
                }
            }
        }
        if (o + 1 >= MAX_BUILT) { free(out); return NULL; }
        out[o++] = in[i++];
    }
    if (o + 1 >= MAX_BUILT) { free(out); return NULL; }
    out[o] = 0;
    if (!changed) { free(out); return NULL; }
    return out;
}

static int read64(uint64_t at, uint64_t *value) { return bb_read(at, value, sizeof(*value)); }
static int read32(uint64_t at, uint32_t *value) { return bb_read(at, value, sizeof(*value)); }

/* Mirror the game's range lookup so a replacement can be installed before its own lookup
 * reads the offset. Any unfamiliar layout leaves the original text intact. */
static uint64_t message_slot(uint64_t repo, uint32_t version, uint32_t category,
                             uint32_t entry, uint64_t *block) {
    if (!repo || version > 64 || category > 1024 || entry > 10000000) return 0;
    uint64_t versions, cats, b, offsets;
    uint32_t ranges, first;
    if (!read64(repo + 8, &versions) || !versions ||
        !read64(versions + (uint64_t)version * 8, &cats) || !cats ||
        !read64(cats + (uint64_t)category * 8, &b) || !b ||
        !read32(b + 0x0c, &ranges) || !ranges || ranges > (1u << 20) ||
        !read32(b + 0x2c, &first) || first > entry) return 0;
    uint32_t lo = 0, hi = ranges - 1;
    for (int guard = 0; guard < 64 && lo <= hi; ++guard) {
        uint32_t mid = lo + (hi - lo) / 2, last;
        uint64_t range = b + (uint64_t)mid * 16;
        if (!read32(range + 0x30, &last)) return 0;
        if (last < entry) { lo = mid + 1; continue; }
        if (!read32(range + 0x2c, &first)) return 0;
        if (first > entry) { if (!mid) return 0; hi = mid - 1; continue; }
        uint32_t index;
        if (!read32(range + 0x28, &index) ||
            !read64(b + 0x18, &offsets) || !offsets) return 0;
        *block = b;
        return offsets + ((uint64_t)entry - first + index) * 8;
    }
    return 0;
}

/* Messages already examined, by (language, category, entry): the lookup runs for every string
 * the game draws, so each one is scanned once and later lookups only probe this table, without
 * the lock or a memory read. Written under message_lock, read without it. A new repository
 * (another language loaded) starts the table over. */
enum { SEEN_SIZE = 1 << 16, SEEN_PROBES = 32 };
static uint64_t g_seen[SEEN_SIZE], g_seen_repo;
static uint64_t seen_key(const BbRegs *regs) {
    return ((uint64_t)(uint32_t)regs->rsi << 52 ^ (uint64_t)(uint32_t)regs->rdx << 32 ^ (uint32_t)regs->rcx) + 1;
}
static int seen(uint64_t key) {
    for (uint32_t i = 0, at = (uint32_t)(key * 0x9e3779b97f4a7c15ull >> 48); i < SEEN_PROBES; ++i) {
        const uint64_t v = __atomic_load_n(&g_seen[(at + i) & (SEEN_SIZE - 1)], __ATOMIC_ACQUIRE);
        if (v == key) return 1;
        if (!v) return 0;
    }
    return 0;
}
static void remember(uint64_t key) {
    for (uint32_t i = 0, at = (uint32_t)(key * 0x9e3779b97f4a7c15ull >> 48); i < SEEN_PROBES; ++i) {
        uint64_t *cell = &g_seen[(at + i) & (SEEN_SIZE - 1)];
        if (*cell == key) return;
        if (!*cell) { __atomic_store_n(cell, key, __ATOMIC_RELEASE); return; }
    }
}

static pthread_mutex_t message_lock = PTHREAD_MUTEX_INITIALIZER;
static unsigned rewritten_messages;
static BB_GUEST_ABI void replace_message(BbRegs *regs) {
    const uint64_t key = seen_key(regs);
    if (__atomic_load_n(&g_seen_repo, __ATOMIC_ACQUIRE) == regs->rdi && seen(key)) return;
    pthread_mutex_lock(&message_lock);
    if (g_seen_repo != regs->rdi) {
        memset(g_seen, 0, sizeof(g_seen));
        __atomic_store_n(&g_seen_repo, regs->rdi, __ATOMIC_RELEASE);
    }
    remember(key);
    pthread_mutex_unlock(&message_lock);
    uint64_t block = 0;
    uint64_t slot = message_slot(regs->rdi, (uint32_t)regs->rsi,
                                 (uint32_t)regs->rdx, (uint32_t)regs->rcx, &block);
    if (!slot) return;
    pthread_mutex_lock(&message_lock);
    uint64_t offset;
    if (!read64(slot, &offset) || !offset || offset > (1ull << 40)) goto done;
    const char16_t *original = (const char16_t *)(uintptr_t)(block + offset);
    /* The player's game dump supplies this text; strings are read only inside the mapped game. */
    char16_t *replacement = rewrite_message(original);
    if (!replacement) goto done;
    uint64_t relative = (uint64_t)(uintptr_t)replacement - block;
    memcpy((void *)(uintptr_t)slot, &relative, sizeof(relative));
    if (rewritten_messages++ < 8)
        printf("Key prompts: replaced message category %u entry %u\n",
               (unsigned)regs->rdx, (unsigned)regs->rcx);
done:
    pthread_mutex_unlock(&message_lock);
}

/* bb_hook_mid preserves the variadic call's AL value. The game reads RSI as the format
 * and RDX as its first argument after this hook returns. */
static BB_GUEST_ABI void replace_glyph(BbRegs *regs) {
    const char16_t *fmt = (const char16_t *)(uintptr_t)regs->rsi;
    if (!fmt || fmt[0] != u'<' || fmt[1] != u'i' || !same16(fmt, IMAGE_FORMAT)) return;
    const char16_t *arg = (const char16_t *)(uintptr_t)regs->rdx;
    if (!arg) return;
    char name[24];
    if (!tag_name(arg, name, sizeof(name)) || strncmp(name, "KG_", 3)) return;
    for (size_t i = 0; i < sizeof(PROMPTS) / sizeof(*PROMPTS); ++i) {
        if (strcmp(PROMPTS[i].tag, name + 3)) continue;
        char label[96];
        prompt_name(&PROMPTS[i], label, sizeof(label));
        if (!label[0]) return;
        static _Thread_local char16_t wide[96];
        size_t j = 0;
        for (; j + 1 < sizeof(wide) / sizeof(*wide) && label[j]; ++j)
            wide[j] = (unsigned char)label[j] < 0x80 ? (char16_t)label[j] : u'?';
        wide[j] = 0;
        regs->rsi = (uintptr_t)KEY_FORMAT;
        regs->rdx = (uintptr_t)wide;
        return;
    }
}

/* The keys the keyboard prompt images show (launcher KEYBOARD_PROMPT_LAYOUT): with those images in place
 * and these bindings, the game's own glyphs are already right. Mouse buttons 1..3. */
static const struct { int action, key_or_mouse; const char *key; } IMAGE_LAYOUT[] = {
    {BIND_INTERACT, 0, "E"}, {BIND_ROLL, 0, "Left Shift"}, {BIND_BLOOD_VIAL, 0, "R"},
    {BIND_USE_ITEM, 0, "Q"}, {BIND_TRANSFORM, 0, "F"}, {BIND_ATTACK, 1, NULL},
    {BIND_FIREARM, 2, NULL}, {BIND_STRONG_MOD, 0, "Left Ctrl"}, {BIND_L3, 0, "Space"},
    {BIND_LOCK_ON, 3, NULL}, {BIND_GESTURES, 0, "G"}, {BIND_EFFECTS, 0, "H"}, {BIND_MENU, 0, "Escape"},
};
static int bindings_match_images(void) {
    for (size_t i = 0; i < sizeof(IMAGE_LAYOUT) / sizeof(*IMAGE_LAYOUT); ++i) {
        if (IMAGE_LAYOUT[i].key) {
            if (bb_binding_key(IMAGE_LAYOUT[i].action) != (int)SDL_GetScancodeFromName(IMAGE_LAYOUT[i].key)) return 0;
        } else if (bb_binding_mouse(IMAGE_LAYOUT[i].action) != IMAGE_LAYOUT[i].key_or_mouse) {
            return 0;
        }
    }
    return 1;
}

int bb_key_prompts_install(void) {
    const char *selected = getenv("BB_BUTTON_PROMPTS");
    if (!selected || strcmp(selected, "Keyboard")) return 0;
    const char *images = getenv("BB_KEY_PROMPT_IMAGES");
    bb_bindings_load(getenv("BB_CONFIG"));
    if (images && !strcmp(images, "1") && bindings_match_images()) {
        puts("Key prompts: the keyboard prompt images match the key bindings");
        return 0;
    }
    const void *site = bb_guest(FORMATTER), *lookup = bb_guest(LOOKUP_ENTRY);
    if (!bb_code_is(site, FORMATTER_PROLOGUE) || !bb_code_is(lookup, LOOKUP_PROLOGUE)) {
        puts("Key prompts: message code is not the expected game 1.09 code; PlayStation glyphs remain");
        return 0;
    }
    bb_bindings_load(getenv("BB_CONFIG"));
    if (bb_hook_mid(LOOKUP_ENTRY, LOOKUP_PROLOGUE, replace_message)) {
        printf("Key prompts: %s\n", bb_hooks_error());
        return 0;
    }
    if (bb_hook_mid(FORMATTER, FORMATTER_PROLOGUE, replace_glyph)) {
        printf("Key prompts: formatted glyphs stayed as pad buttons: %s\n", bb_hooks_error());
        return 1;
    }
    puts("Key prompts: keyboard names installed for formatted glyphs and stored game text");
    return 2;
}
