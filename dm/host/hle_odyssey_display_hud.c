// Odyssey 1.4.1 live HUD transforms, paired with the guarded camera adapter.
// Only primary al::EuiScreen layouts from the prepared 4:3 profile participate.
// Local edits exist only during Calculate; the original bakes the draw matrices.
// The map-screen rule below also runs for prepared wide (phone) profiles.
#include "dm.h"
#include "odyssey_display.h"
#include "odyssey_display_hud.h"
#include <math.h>
#include <stdatomic.h>

typedef void (*hud_calculate_fn)(void *layout, void *draw_info, int recursive);
static hud_calculate_fn hud_original;
static uintptr_t hud_layout_vptr, hud_screen_vptr, hud_pane_vptr, hud_root_vptr;
static uintptr_t hud_parts_vptr, hud_parts_ex_vptr;
static _Thread_local unsigned hud_depth;
static pthread_mutex_t hud_stats_lock = PTHREAD_MUTEX_INITIALIZER;
static dm_odyssey_display_hud_stats hud_stats;
static char hud_seen[32][64];
static unsigned hud_seen_count;
static int hud_phone; // Prepared wide profile: map-screen rule only, never the live HUD.

// These guards pin the receiving ABI, owner chain, tree/field access, matrix
// calculation and later picture draw. Another game/SDK must derive its own.
static const uint32_t hud_words_layout_calc[] = {
    0xf9400c08, 0xb40003a8, 0xd10183ff, 0xf9001bf5, 0xa9044ff4, 0xa9057bfd,
    0x910143fd, 0xaa0003f5, 0x2a0203f4, 0x910003e0, 0xaa1503e2, 0xaa0103f3,
    0x3900a3ff, 0xa901ffff, 0xf90003ff, 0xa900ffff, 0x97fbc156, 0xf9006275,
    0xf9400ea0, 0xf9400008, 0xf9404d08, 0x12000283, 0x910003e2, 0xaa1303e1,
    0xd63f0100, 0xf900627f, 0xa9457bfd, 0xa9444ff4, 0xf9401bf5, 0x910183ff,
    0xd65f03c0,
};
static const uint32_t hud_words_pane_calc[] = {
    0xfc1b0fe8, 0xf90007f9, 0xa9015ff8, 0xa90257f6, 0xa9034ff4, 0xa9047bfd,
    0x910103fd, 0xaa0003f3, 0x7940b268, 0xaa0203f4, 0xaa0103f5, 0x37000068,
    0x39407689, 0x34000449,
};
static const uint32_t hud_words_pane_local_matrix[] = {
    0xf9400c0b, 0xf9400428, 0x9101c169, 0xf100017f, 0x9a890108, 0x3940702c,
    0x2949240a, 0x340001ac, 0xb940580e, 0x531e7dcc, 0x531c7dcd, 0x3610018e,
    0x1e270140, 0x2d420821, 0x1e210800, 0x1e26000a, 0x1e270120, 0x1e220801,
    0x1e260029, 0x14000004, 0x39416c0d, 0x53067dac, 0x53047dad, 0x2d460801,
    0xbd403800, 0x120005ad, 0x710009bf, 0x540000c0, 0x710005bf, 0x54000101,
    0xbd405163, 0x1e3c1004, 0x14000003, 0xbd405163, 0x1e2c1004, 0x1e240863,
    0x1e232821, 0x1200058c, 0x7100099f, 0x540000c0, 0x7100059f, 0x54000101,
    0xbd405563, 0x1e2c1004, 0x14000003, 0xbd405563, 0x1e3c1004, 0x1e240863,
    0x1e232842,
};
static const uint32_t hud_words_pane_load_matrix[] = {
    0xf81e0ff3, 0xa9017bfd, 0x910043fd, 0xaa0103f3, 0x9101c001, 0x91020260,
    0x321c07e2, 0x94047a12, 0x3903ba7f, 0xa9417bfd, 0xf84207f3, 0xd65f03c0,
};
static const uint32_t hud_words_screen_initialize[] = {
    0xd100c3ff, 0xf9000bf3, 0xa9027bfd, 0x910083fd, 0xf9001401, 0xf0004a08,
    0xf943a908, 0xaa0003f3, 0x9102c000, 0x910003e1, 0x91004108, 0xa9000be8,
    0x97fce57c, 0x3943ba68, 0x321d0108, 0x3903ba68, 0xa9427bfd, 0xf9400bf3,
    0x9100c3ff, 0xd65f03c0,
};
static const uint32_t hud_words_layout_ctor[] = {
    0xa9be4ff4, 0xa9017bfd, 0x910043fd, 0xaa0103f3, 0xaa0003f4, 0x97fba704,
    0x90004ac8, 0xf9410508, 0x91004108, 0xa907fe9f, 0xf9000288, 0x321703e8,
    0xa906fe9f, 0xa908fe93, 0x79013288, 0xa9417bfd, 0xa8c24ff4, 0xd65f03c0,
};
static const uint32_t hud_words_pane_ctor_fields[] = {
    0xf9000396, 0xb9400368, 0xb9003268, 0xb9400768, 0xb9003668, 0xb9400b68,
    0xb9003a68, 0xb9400348, 0xb9003e68, 0xb9400748, 0xb9004268, 0xb9400b48,
    0xb9004668, 0xb9400328, 0xb9004a68, 0xb9400728, 0xb9004e68,
};
static const uint32_t hud_words_pane_name[] = {
    0x39400028, 0x34000c28, 0x3902e008, 0xaa0103e9, 0x38401d28, 0x34000be8,
};
static const uint32_t hud_words_picture_calc[] = {
    0xd10103ff, 0xa90157f6, 0xa9024ff4, 0xa9037bfd, 0x9100c3fd, 0x12000063,
    0xaa0203f5, 0xaa0103f4, 0xaa0003f3, 0x97ffda0b, 0xf9407268, 0xb4000de8,
    0xf9400268, 0xf9405908, 0xaa1303e0, 0xaa1403e1, 0xd63f0100,
};
static const uint32_t hud_words_picture_draw[] = {
    0xd10103ff, 0xa90157f6, 0xa9024ff4, 0xa9037bfd, 0x9100c3fd, 0xaa0003f4,
    0xf9407280, 0xaa0203f3, 0xaa0103f5, 0xb4000a80, 0xf94066a8, 0x39400108,
    0x37080a28, 0xaa1503e1, 0xaa1303e2, 0x97ffede0, 0x3943e288, 0xf9407282,
    0x7100091f, 0x54000108, 0xaa1303e0, 0xaa1503e1, 0xa9437bfd, 0xa9424ff4,
    0xa94157f6, 0x910103ff, 0x17ffdd26,
};
static const uint32_t hud_words_parts_name_lookup_boundary[] = {
    0xaa1f03e8, 0x9102e009, 0x3868692a, 0x3868682b, 0x6b0b015f, 0x540000c1,
    0x3400008a, 0x91000508, 0xf100611f, 0x54ffff2b, 0xd65f03c0, 0xaa1f03e0,
    0xd65f03c0,
};
typedef struct { uint32_t offset; const uint32_t *words; size_t size; } hud_code_guard;
static const hud_code_guard hud_guards[] = {
    {0x90f2e0, hud_words_parts_name_lookup_boundary, sizeof hud_words_parts_name_lookup_boundary},
    {0xa19b00, hud_words_layout_calc, sizeof hud_words_layout_calc},
    {0x909494, hud_words_pane_calc, sizeof hud_words_pane_calc},
    {0x9096d0, hud_words_pane_local_matrix, sizeof hud_words_pane_local_matrix},
    {0x909d1c, hud_words_pane_load_matrix, sizeof hud_words_pane_load_matrix},
    {0xa1d3e0, hud_words_screen_initialize, sizeof hud_words_screen_initialize},
    {0xa18f70, hud_words_layout_ctor, sizeof hud_words_layout_ctor},
    {0x908b98, hud_words_pane_ctor_fields, sizeof hud_words_pane_ctor_fields},
    {0x908d18, hud_words_pane_name, sizeof hud_words_pane_name},
    {0x912c44, hud_words_picture_calc, sizeof hud_words_picture_calc},
    {0x913080, hud_words_picture_draw, sizeof hud_words_picture_draw},
};

static uintptr_t hud_pointer(const void *p, size_t offset) {
    uintptr_t result; memcpy(&result, (const uint8_t *)p + offset, sizeof result); return result;
}
static float hud_float(const void *p, size_t offset) {
    float result; memcpy(&result, (const uint8_t *)p + offset, sizeof result); return result;
}
static int hud_aligned(const void *p) { return p && !((uintptr_t)p & 7); }
static int hud_name(const uint8_t *pane, const char *name) {
    const char *text = (const char *)pane + 0xb8;
    const char *end = memchr(text, 0, 25);
    return end && (size_t)(end - text) == strlen(name) && !memcmp(text, name, (size_t)(end - text));
}
static int hud_owner_name(const char *name, char output[64]) {
    if (!name) return 0;
    for (unsigned i = 0; i < 64; i++) {
        unsigned char c = (unsigned char)name[i];
        if (!c) { output[i] = 0; return i != 0; }
        if (i == 63 || !((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
                        (c >= '0' && c <= '9') || c == '_')) return 0;
        output[i] = (char)c;
    }
    return 0;
}
static int hud_in_names(const char *name, const char *const *names, size_t count) {
    for (size_t i = 0; i < count; i++) if (!strcmp(name, names[i])) return 1;
    return 0;
}
static int hud_skip_owner(const char *owner) {
    static const char *const names[] = {"FooterParts", "MapBG", "FadeBlack", "FadeWhite", "CommonBgParts"};
    return hud_in_names(owner, names, sizeof names / sizeof *names);
}
typedef struct { const char *owner, *anchor; float x, y; int sign; } hud_edge;
static const hud_edge hud_edges[] = {
    {"CounterCoin","All",-600,296,1}, {"CounterCollectCoin","All",-475,302.5f,1}, {"CounterLife","All",556,284,1},
    {"CounterLifeKids","All",556,284,1}, {"CounterLifeUp","All",556,284,1},
    {"CounterShine","All",-596,266,1}, {"MapMini","All",556,157,1},
    {"PlayGuideMenu","PicCaptureUse",556,220,1}, {"PlayGuideCamera","All",546,94,1},
    {"PlayGuideSkip","PicCaptureUse",382,312,1}, {"SaveMessage","All",-600,-320,-1},
    {"KidsMode","All",598,-334,-1}, {"PlayGuide","PicBase",0,-360,-1},
    {"PlayGuideMap","TxtGuide",-586,-316,-1}, {"PlayGuideBgm","PicSh",0,-324,-1},
    {"TalkMessage","PicBase",0,-360,-1}, {"MapFooter","ParFooter",0,-360,-1},
};
typedef struct { const char *owner, *pane; int part; } hud_fill;
static const hud_fill hud_fills[] = {
    {"BootLoading","PicFade",0}, {"ClosetHead","PicBG",0},
    {"Menu","PicCaptureUse",0}, {"Menu","PicBG00",0}, {"Menu","PicBG01",0},
    {"MiniGameMenu","PicCaptureUse",0}, {"MiniGameMenu","PicBG00",0}, {"MiniGameMenu","PicBG01",0},
    {"MiniGameRaceResult","PicCaptureUse",0}, {"ModeSelect","PicFade",0},
    {"RankList","PicBase",0}, {"ShopBG","PicCaptureUse",0}, {"ShopBG","PicBG00",0}, {"ShopBG","PicBG01",0},
    {"TalkMessageOver","PicBase",0}, {"WindowConfirm","PicCaptureUse",0},
    {"WindowConfirmData","PicCaptureUse",0}, {"WindowConfirmLanguage","PicCaptureUse",0},
    {"WindowConfirmWait","PicCaptureUse",0}, {"WindowConfirmWaitBlack","PicBG",0},
    {"WindowInfo","PicCaptureUse",0},
#define HUD_OPTION(n) {n,"PicCaptureUse00",0}, {n,"PicCaptureUse01",0}, {n,"PicBG00",0}, {n,"PicBG01",0}
    HUD_OPTION("OptionConfig"), HUD_OPTION("OptionData"), HUD_OPTION("OptionLanguage"),
    HUD_OPTION("OptionMode"), HUD_OPTION("OptionProcess"), HUD_OPTION("OptionSelect"),
#undef HUD_OPTION
    {"BootLoading","ParBG",1}, {"ContinueLoading","ParBG",1}, {"Menu","ParBG",1},
};
// Full-screen filters (Moe-Eye glasses): the 4:3 preparation sets their 1000-tall
// surfaces to 1000/.75 so they keep the authored framing; keep that at any aspect.
typedef struct { const char *owner, *pane; } hud_filter;
static const hud_filter hud_filters[] = {{"FilterGlasses","PicCaptureUse"}, {"FilterGlasses","PicFilter"}};

enum { HUD_PANES = 512, HUD_EDITS = 16 };
typedef struct { uint8_t *pane; size_t offset; float before, after; } hud_edit;
typedef struct {
    uint8_t *panes[HUD_PANES]; unsigned char primary[HUD_PANES]; unsigned pane_count;
    hud_edit edits[HUD_EDITS]; unsigned edit_count;
    float target_y;
    char owner[64];
} hud_plan;
static int hud_pane_valid(const uint8_t *pane) {
    if (!hud_aligned(pane) || !memchr(pane + 0xb8, 0, 25)) return 0;
    for (unsigned offset = 0x30; offset <= 0x54; offset += 4) {
        float value = hud_float(pane, offset);
        if (!isfinite(value) || fabsf(value) > 10000000) return 0;
    }
    return 1;
}
// Validate the complete tree before any field is changed. Intrusive links are
// allowed only once; malformed cycles and excessive depth/width fail closed.
static int hud_tree(hud_plan *plan, uint8_t *root) {
    plan->primary[0] = 1; plan->panes[plan->pane_count++] = root;
    for (unsigned index = 0; index < plan->pane_count; index++) {
        uint8_t *parent = plan->panes[index];
        if (!hud_pane_valid(parent)) return 0;
        uintptr_t sentinel = (uintptr_t)parent + 0x20, node = hud_pointer(parent, 0x28);
        unsigned siblings = 0;
        while (node != sentinel) {
            if (node < 8 || (node & 7) || ++siblings > HUD_PANES || plan->pane_count == HUD_PANES) return 0;
            uint8_t *child = (uint8_t *)(node - 8);
            for (unsigned j = 0; j < plan->pane_count; j++) if (plan->panes[j] == child) return 0;
            if (!hud_pane_valid(child) || hud_pointer(child, 0x18) != (uintptr_t)parent) return 0;
            // Parts::FindPaneByNameRecursive deliberately does not enter the
            // embedded layout. Apply that same owner boundary to rule lookup.
            uintptr_t parent_vptr = hud_pointer(parent, 0);
            plan->primary[plan->pane_count] = plan->primary[index] &&
                parent_vptr != hud_parts_vptr && parent_vptr != hud_parts_ex_vptr;
            plan->panes[plan->pane_count++] = child;
            node = hud_pointer(child, 0x10);
        }
    }
    return 1;
}
static uint8_t *hud_find(const hud_plan *plan, const char *name) {
    uint8_t *found = NULL;
    for (unsigned i = 0; i < plan->pane_count; i++) if (plan->primary[i] && hud_name(plan->panes[i], name)) {
        if (found) return NULL; // Ambiguous ownership is not an invitation to guess.
        found = plan->panes[i];
    }
    return found;
}
static int hud_add(hud_plan *plan, uint8_t *pane, size_t offset, float replacement) {
    if (plan->edit_count == HUD_EDITS || !isfinite(replacement) || fabsf(replacement) > 100000) return 0;
    plan->edits[plan->edit_count++] = (hud_edit){pane, offset, hud_float(pane, offset), replacement};
    return 1;
}
static int hud_layout_valid(const dm_odyssey_display_layout *geometry) {
    return isfinite(geometry->aspect) && geometry->aspect >= 1 && geometry->aspect <= 16.0 / 9.0 &&
        isfinite(geometry->top) && isfinite(geometry->left) &&
        isfinite(geometry->bottom) && isfinite(geometry->right) &&
        geometry->top >= 0 && geometry->left >= 0 && geometry->bottom >= 0 && geometry->right >= 0 &&
        geometry->left + geometry->right < 1280 && geometry->top + geometry->bottom < 720;
}
static int hud_plan_make(void *layout, const dm_odyssey_display_layout *geometry, hud_plan *plan) {
    if (!hud_aligned(layout) || hud_pointer(layout, 0) != hud_layout_vptr || !hud_layout_valid(geometry)) return 0;
    uint8_t *screen = (uint8_t *)hud_pointer(layout, 0x88);
    if (!hud_aligned(screen) || hud_pointer(screen, 0) != hud_screen_vptr ||
        hud_pointer(screen, 0x30) != (uintptr_t)layout ||
        !hud_owner_name((const char *)hud_pointer(screen, 0xb8), plan->owner)) return 0;
    if (hud_skip_owner(plan->owner)) return 2;
    uint8_t *root = (uint8_t *)hud_pointer(layout, 0x18);
    if (!hud_pane_valid(root) || hud_pointer(root, 0x18) || !hud_name(root, "RootPane") ||
        (hud_pointer(root, 0) != hud_pane_vptr && hud_pointer(root, 0) != hud_root_vptr) ||
        hud_float(root, 0x50) != 1280 || hud_float(root, 0x54) != 720 ||
        hud_float(root, 0x3c) != 0 || hud_float(root, 0x40) != 0 || hud_float(root, 0x44) != 0 ||
        hud_float(root, 0x48) < .01f || hud_float(root, 0x48) > 8 ||
        hud_float(root, 0x4c) < .01f || hud_float(root, 0x4c) > 8 || !hud_tree(plan, root)) return 0;
    plan->target_y = (float)(geometry->aspect * 9 / 16);
    if (!hud_add(plan, root, 0x4c, hud_float(root, 0x4c) * plan->target_y / .75f)) return 0;
    for (unsigned i = 0; i < sizeof hud_edges / sizeof *hud_edges; i++) {
        const hud_edge *edge = &hud_edges[i];
        if (strcmp(plan->owner, edge->owner)) continue;
        uint8_t *anchor = hud_find(plan, edge->anchor);
        // The measured child establishes identity, but its current translation may
        // be animated. Only RootPane's independently proven static edge offset
        // is replaced; do not pin the moving child to its authored first pose.
        if (!anchor || hud_float(root, 0x34) != edge->sign * 90.0f) return 0;
        // Safe-area values are already normalized into the unscaled 1280x720
        // game canvas and latched with aspect. Move only these measured edge
        // groups; full-frame capture/background panes continue to fill the panel.
        float dx = edge->x < 0 ? (float)geometry->left : edge->x > 0 ? -(float)geometry->right : 0;
        float dy = edge->sign > 0 ? -(float)geometry->top : (float)geometry->bottom;
        if ((dx != 0 && !hud_add(plan, root, 0x30, hud_float(root, 0x30) + dx)) ||
            !hud_add(plan, root, 0x34, edge->sign * 360.0f * (1 - plan->target_y) + dy)) return 0;
    }
    for (unsigned i = 0; i < sizeof hud_fills / sizeof *hud_fills; i++) {
        const hud_fill *fill = &hud_fills[i];
        if (strcmp(plan->owner, fill->owner)) continue;
        uint8_t *pane = hud_find(plan, fill->pane);
        if (!pane || hud_float(pane, 0x30) != 0 || hud_float(pane, 0x34) != 0 ||
            hud_float(pane, 0x3c) != 0 || hud_float(pane, 0x40) != 0 || hud_float(pane, 0x44) != 0 ||
            hud_float(pane, 0x50) != 1280 || hud_float(pane, 0x54) != (fill->part ? 720 : 960) ||
            hud_float(pane, 0x4c) <= 0 || hud_float(pane, 0x4c) > 8 ||
            !hud_add(plan, pane, 0x4c, hud_float(pane, 0x4c) * .75f / plan->target_y)) return 0;
    }
    for (unsigned i = 0; i < sizeof hud_filters / sizeof *hud_filters; i++) {
        const hud_filter *filter = &hud_filters[i];
        if (strcmp(plan->owner, filter->owner)) continue;
        uint8_t *pane = hud_find(plan, filter->pane);
        if (!pane || hud_float(pane, 0x30) != 0 || hud_float(pane, 0x34) != 0 ||
            hud_float(pane, 0x3c) != 0 || hud_float(pane, 0x40) != 0 || hud_float(pane, 0x44) != 0 ||
            hud_float(pane, 0x50) != 1280 || hud_float(pane, 0x54) != 1000.0f / .75f ||
            hud_float(pane, 0x4c) <= 0 || hud_float(pane, 0x4c) > 8 ||
            !hud_add(plan, pane, 0x4c, hud_float(pane, 0x4c) * .75f / plan->target_y)) return 0;
    }
    return 1;
}
static void hud_apply(const hud_plan *plan, int restore) {
    for (unsigned i = 0; i < plan->edit_count; i++) {
        const hud_edit *edit = &plan->edits[i];
        float value = restore ? edit->before : edit->after;
        memcpy(edit->pane + edit->offset, &value, sizeof value);
        edit->pane[0x58] |= 0x10; // Local restoration must invalidate the next calculation, not this baked draw.
    }
}
static void hud_record(int result, const hud_plan *plan, double aspect) {
    pthread_mutex_lock(&hud_stats_lock);
    if (result == 1) {
        ++hud_stats.adapted; hud_stats.edited_fields += plan->edit_count;
        hud_stats.last_aspect = aspect;
        hud_stats.last_root_scale_y = plan->edits[0].after;
        hud_stats.last_root_position_x = hud_float(plan->edits[0].pane, 0x30);
        hud_stats.last_root_position_y = hud_float(plan->edits[0].pane, 0x34);
        memcpy(hud_stats.last_owner, plan->owner, sizeof hud_stats.last_owner);
        int seen = 0;
        for (unsigned i = 0; i < hud_seen_count; i++) if (!strcmp(hud_seen[i], plan->owner)) seen = 1;
        if (!seen && hud_seen_count < 32) {
            memcpy(hud_seen[hud_seen_count++], plan->owner, sizeof hud_seen[0]);
            LOG("Odyssey display HUD: owner=%s aspect=%.6f rootY=%.6f position=(%.3f,%.3f) fields=%u panes=%u",
                plan->owner, aspect, hud_stats.last_root_scale_y, hud_stats.last_root_position_x, hud_stats.last_root_position_y,
                plan->edit_count, plan->pane_count);
        }
    } else if (result == 2) ++hud_stats.skipped;
    else ++hud_stats.declined;
    pthread_mutex_unlock(&hud_stats_lock);
}
// Full map screen (every owner below is constructed only by main+0x1ce2f0): the
// game writes each icon layout's root translation, and the player marker's
// uniform scale, in Map root units. Those skip Map's own prepared or live root
// correction, so icons drift from their spots away from the cursor. Map's root
// scale is recorded around its own Calculate and applied to the icon roots.
static pthread_mutex_t hud_map_lock = PTHREAD_MUTEX_INITIALIZER;
static struct { int valid; float base_x, base_y, live_x, live_y; } hud_map_root;
static int hud_map_icon_owner(const char *owner) {
    static const char *const names[] = {"MapIcon", "MapIconLine", "MapPlayer"};
    return hud_in_names(owner, names, sizeof names / sizeof *names);
}
static int hud_map_scale_valid(float x, float y) { return x >= .25f && x <= 1 && y >= .25f && y <= 1; }
// Small on purpose: Calculate runs on the guest thread's stack beside a live plan.
typedef struct { hud_edit edits[4]; unsigned edit_count; char owner[64]; } hud_map_edits;
static int hud_map_add(hud_map_edits *plan, uint8_t *pane, size_t offset, float replacement) {
    if (plan->edit_count == 4 || !isfinite(replacement) || fabsf(replacement) > 100000) return 0;
    plan->edits[plan->edit_count++] = (hud_edit){pane, offset, hud_float(pane, offset), replacement};
    return 1;
}
static void hud_map_apply(const hud_map_edits *plan, int restore) {
    for (unsigned i = 0; i < plan->edit_count; i++) {
        const hud_edit *edit = &plan->edits[i];
        float value = restore ? edit->before : edit->after;
        memcpy(edit->pane + edit->offset, &value, sizeof value);
        edit->pane[0x58] |= 0x10;
    }
}
// 1: icon edits planned; 2: this is Map, *map_root receives its root; 0: no rule.
static int hud_map_plan(void *layout, hud_map_edits *plan, uint8_t **map_root) {
    if (!hud_aligned(layout) || hud_pointer(layout, 0) != hud_layout_vptr) return 0;
    uint8_t *screen = (uint8_t *)hud_pointer(layout, 0x88);
    if (!hud_aligned(screen) || hud_pointer(screen, 0) != hud_screen_vptr ||
        hud_pointer(screen, 0x30) != (uintptr_t)layout ||
        !hud_owner_name((const char *)hud_pointer(screen, 0xb8), plan->owner)) return 0;
    int map = !strcmp(plan->owner, "Map");
    if (!map && !hud_map_icon_owner(plan->owner)) return 0;
    uint8_t *root = (uint8_t *)hud_pointer(layout, 0x18);
    if (!hud_pane_valid(root) || hud_pointer(root, 0x18) || !hud_name(root, "RootPane") ||
        (hud_pointer(root, 0) != hud_pane_vptr && hud_pointer(root, 0) != hud_root_vptr) ||
        hud_float(root, 0x50) != 1280 || hud_float(root, 0x54) != 720 ||
        hud_float(root, 0x3c) != 0 || hud_float(root, 0x40) != 0 || hud_float(root, 0x44) != 0 ||
        hud_float(root, 0x48) < .01f || hud_float(root, 0x48) > 8 ||
        hud_float(root, 0x4c) < .01f || hud_float(root, 0x4c) > 8) return 0;
    if (map) {
        // Map's own root is never translated; zoom and pan live on its All pane.
        if (hud_float(root, 0x30) != 0 || hud_float(root, 0x34) != 0 ||
            !hud_map_scale_valid(hud_float(root, 0x48), hud_float(root, 0x4c))) return 0;
        *map_root = root; return 2;
    }
    pthread_mutex_lock(&hud_map_lock);
    __typeof__(hud_map_root) m = hud_map_root;
    pthread_mutex_unlock(&hud_map_lock);
    if (!m.valid) return 0;
    float sx = hud_float(root, 0x48), sy = hud_float(root, 0x4c);
    if (!hud_map_add(plan, root, 0x30, hud_float(root, 0x30) * m.live_x) ||
        !hud_map_add(plan, root, 0x34, hud_float(root, 0x34) * m.live_y)) return 0;
    // A uniform root scale means the game reset it (al::setLocalScale); restore
    // the prepared ratio. A live plan then rescales Y on top, as for any layout.
    if (sx == sy && m.base_x != m.base_y &&
        (!hud_map_add(plan, root, 0x48, sx * m.base_x) || !hud_map_add(plan, root, 0x4c, sy * m.base_y))) return 0;
    return 1;
}
static void hud_map_record(int result, const uint8_t *map_root, float base_x, float base_y) {
    pthread_mutex_lock(&hud_map_lock);
    if (map_root) {
        float live_x = hud_float(map_root, 0x48), live_y = hud_float(map_root, 0x4c);
        int valid = hud_map_scale_valid(base_x, base_y) && hud_map_scale_valid(live_x, live_y);
        hud_map_root.valid = valid;
        if (valid) {
            hud_map_root.base_x = base_x; hud_map_root.base_y = base_y;
            hud_map_root.live_x = live_x; hud_map_root.live_y = live_y;
        }
    }
    pthread_mutex_unlock(&hud_map_lock);
    pthread_mutex_lock(&hud_stats_lock);
    if (result == 1) ++hud_stats.map_icons; else if (result == 2) ++hud_stats.map_roots;
    pthread_mutex_unlock(&hud_stats_lock);
}
static void hud_calculate(void *layout, void *draw_info, int recursive) {
    pthread_mutex_lock(&hud_stats_lock); ++hud_stats.calls; pthread_mutex_unlock(&hud_stats_lock);
    if (hud_depth) {
        pthread_mutex_lock(&hud_stats_lock); ++hud_stats.nested; pthread_mutex_unlock(&hud_stats_lock);
        hud_original(layout, draw_info, recursive); return;
    }
    ++hud_depth;
    // Map edits nest outside the live plan: applied first, restored last.
    hud_map_edits map = {0};
    uint8_t *map_root = NULL;
    int mapped = hud_map_plan(layout, &map, &map_root);
    float map_base_x = map_root ? hud_float(map_root, 0x48) : 0, map_base_y = map_root ? hud_float(map_root, 0x4c) : 0;
    if (mapped == 1) hud_map_apply(&map, 0);
    hud_plan plan = {0};
    int result = 0;
    if (!hud_phone && dm_odyssey_display_enabled()) {
        dm_odyssey_display_layout geometry;
        dm_odyssey_display_layout_snapshot(&geometry); // One latch for camera aspect and all four insets.
        result = hud_plan_make(layout, &geometry, &plan);
        if (result == 1) hud_apply(&plan, 0);
        hud_record(result, &plan, geometry.aspect);
    } else {
        pthread_mutex_lock(&hud_stats_lock); ++hud_stats.disabled; pthread_mutex_unlock(&hud_stats_lock);
    }
    if (mapped) hud_map_record(mapped, map_root, map_base_x, map_base_y);
    hud_original(layout, draw_info, recursive);
    if (result == 1) hud_apply(&plan, 1);
    if (mapped == 1) hud_map_apply(&map, 1);
    --hud_depth;
}
void dm_odyssey_display_hud_snapshot(dm_odyssey_display_hud_stats *out) {
    if (!out) return;
    pthread_mutex_lock(&hud_stats_lock); *out = hud_stats; pthread_mutex_unlock(&hud_stats_lock);
}
static int hud_guard(const module_t *m) {
    const uint8_t *b = m->base;
    if (!b || m->size < 0x135ee70 || m->text_end > m->size || m->data_off > 0x135d358 ||
        m->text_end > 0x135d358) return 0;
    const struct { uint32_t vptr, typeinfo, name; const char *text; } types[] = {
        {0x135d2c8, 0x135d390, 0xf97484, "N3eui8LayoutExE"},
        {0x12ed3e8, 0x12ed620, 0xf0e634, "N2al9EuiScreenE"},
        {0x1350278, 0x1350350, 0xf2c1a0, "N2nn4ui2d5PartsE"},
        {0x135d1c8, 0x135d2a0, 0xf97474, "N3eui7PartsExE"},
    };
    for (unsigned i = 0; i < sizeof types / sizeof *types; i++) {
        if (memcmp(b + types[i].name, types[i].text, strlen(types[i].text) + 1) ||
            hud_pointer(b, types[i].typeinfo + 8) != (uintptr_t)(b + types[i].name) ||
            hud_pointer(b, types[i].vptr - 8) != (uintptr_t)(b + types[i].typeinfo)) return 0;
    }
    if (hud_pointer(b, 0x135d358) != (uintptr_t)(b + 0xa19b00) ||
        hud_pointer(b, 0x132b2e0) != (uintptr_t)(b + 0x909494) ||
        hud_pointer(b, 0x135ee60) != (uintptr_t)(b + 0x909494) ||
        hud_pointer(b, 0x1350310) != (uintptr_t)(b + 0x909494) ||
        hud_pointer(b, 0x135d260) != (uintptr_t)(b + 0x909494) ||
        hud_pointer(b, 0x1350330) != (uintptr_t)(b + 0x90f2e0) ||
        hud_pointer(b, 0x135d280) != (uintptr_t)(b + 0x90f2e0)) return 0;
    for (unsigned i = 0; i < sizeof hud_guards / sizeof *hud_guards; i++) {
        const hud_code_guard *guard = &hud_guards[i];
        if (guard->offset > m->text_end || guard->size > m->text_end - guard->offset ||
            memcmp(b + guard->offset, guard->words, guard->size)) return 0;
    }
    return 1;
}
void dm_odyssey_display_hud_install(void) {
    const char *option = getenv("DM_ODYSSEY_DYNAMIC_DISPLAY");
    // Prepared 4:3 installs the live HUD and the map rule; a prepared phone
    // profile (wider than 16:9) installs only the map rule.
    int phone = DM_GAME_DISPLAY_ASPECT > 16.0 / 9.0 + .00001;
    if ((option && strcmp(option, "1")) || (!phone && fabs(DM_GAME_DISPLAY_ASPECT - 4.0 / 3.0) > .00001) || hud_original) return;
    module_t *m = NULL;
    for (int i = 0; i < g_nmod; i++) if (!strcmp(g_mod[i].name, "main")) { m = &g_mod[i]; break; }
    if (!m || strcmp(m->build_id, "b424be150a8e7d78701cbe7a439d9ebf") || !hud_guard(m)) {
        LOG("[RED] Odyssey display HUD: exact prepared ABI/owner guard failed; proportional composition retained");
        return;
    }
    hud_layout_vptr = (uintptr_t)(m->base + 0x135d2c8);
    hud_screen_vptr = (uintptr_t)(m->base + 0x12ed3e8);
    hud_pane_vptr = (uintptr_t)(m->base + 0x132b248);
    hud_root_vptr = (uintptr_t)(m->base + 0x135edc8);
    hud_parts_vptr = (uintptr_t)(m->base + 0x1350278);
    hud_parts_ex_vptr = (uintptr_t)(m->base + 0x135d1c8);
    hud_original = (hud_calculate_fn)(m->base + 0xa19b00);
    *(hud_calculate_fn *)(m->base + 0x135d358) = hud_calculate;
    hud_phone = phone;
    pthread_mutex_lock(&hud_stats_lock); hud_stats.installed = 1; pthread_mutex_unlock(&hud_stats_lock);
    if (phone) {
        LOG("Odyssey display HUD: exact1.4.1 LayoutEx adapter installed; prepared phone map-screen rule only");
        return;
    }
    dm_odyssey_display_hud_ready();
    LOG("Odyssey display HUD: exact1.4.1 LayoutEx primary owner adapter installed; narrow aspects only");
}
