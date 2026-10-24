// Synthetic receiving objects execute the actual HUD adapter. No game payload.
#include "../hle_odyssey_display_hud.c"
#include <assert.h>
module_t g_mod[MAX_MOD]; int g_nmod;
static int enabled = 1, ready;
static double requested_aspect = 678.0 / 466.0;
static dm_odyssey_display_layout layout_geometry;
int dm_odyssey_display_enabled(void) { return enabled; }
double dm_odyssey_display_aspect(void) { return requested_aspect; }
void dm_odyssey_display_layout_snapshot(dm_odyssey_display_layout *out) {
    *out = layout_geometry; out->aspect = requested_aspect;
}
void dm_odyssey_display_hud_ready(void) { ++ready; }

static void put_pointer(uint8_t *p, size_t offset, const void *value) {
    uintptr_t word = (uintptr_t)value; memcpy(p + offset, &word, sizeof word);
}
static void put_float(uint8_t *p, size_t offset, float value) { memcpy(p + offset, &value, sizeof value); }
static void pane(uint8_t *p, const char *name) {
    memset(p, 0, 0xd8);
    put_pointer(p, 0, (void *)hud_pane_vptr);
    put_pointer(p, 0x20, p + 0x20); put_pointer(p, 0x28, p + 0x20);
    put_float(p, 0x48, 1); put_float(p, 0x4c, 1);
    put_float(p, 0x50, 1280); put_float(p, 0x54, 720);
    strcpy((char *)p + 0xb8, name);
}
static void attach(uint8_t *parent, uint8_t *child) {
    put_pointer(child, 0x18, parent);
    uintptr_t last = hud_pointer(parent, 0x20);
    put_pointer((uint8_t *)last, 8, child + 8);
    put_pointer(child, 8, (void *)last);
    put_pointer(child, 0x10, parent + 0x20);
    put_pointer(parent, 0x20, child + 8);
}
static uint8_t layout[0xa0] __attribute__((aligned(8)));
static uint8_t screen[0xc0] __attribute__((aligned(8)));
static uint8_t root[0xd8] __attribute__((aligned(8)));
static uint8_t children[8][0xd8] __attribute__((aligned(8)));
static char owner_name[64];
static unsigned delegates;
static int do_nested;
static float expected_root_y, expected_position_x, expected_position_y, expected_child_y;
static void *expected_draw = (void *)0x88;
static void delegate(void *value, void *draw, int recursive) {
    assert(value == layout && draw == expected_draw && recursive == 1);
    ++delegates;
    assert(fabsf(hud_float(root, 0x4c) - expected_root_y) < .000001f);
    assert(fabsf(hud_float(root, 0x30) - expected_position_x) < .0001f);
    assert(fabsf(hud_float(root, 0x34) - expected_position_y) < .0001f);
    if (expected_child_y > 0) assert(fabsf(hud_float(children[0], 0x4c) - expected_child_y) < .00001f);
    // The guest has baked a draw matrix: restoration must not erase it.
    put_float(root, 0x70, expected_root_y);
    if (do_nested && delegates < 2) hud_calculate(layout, draw, recursive);
    root[0x58] &= (uint8_t)~0x10;
}
static void objects(const char *owner) {
    memset(&layout_geometry, 0, sizeof layout_geometry);
    memset(layout, 0, sizeof layout); memset(screen, 0, sizeof screen);
    hud_layout_vptr = 0x1000; hud_screen_vptr = 0x2000; hud_pane_vptr = 0x3000; hud_root_vptr = 0x4000;
    hud_parts_vptr = 0x5000; hud_parts_ex_vptr = 0x6000;
    put_pointer(layout, 0, (void *)hud_layout_vptr); put_pointer(layout, 0x18, root); put_pointer(layout, 0x88, screen);
    put_pointer(screen, 0, (void *)hud_screen_vptr); put_pointer(screen, 0x30, layout);
    strcpy(owner_name, owner); put_pointer(screen, 0xb8, owner_name);
    pane(root, "RootPane"); put_float(root, 0x4c, .75f);
    for (unsigned i = 0; i < 8; i++) pane(children[i], "Child");
    hud_original = delegate; delegates = 0; expected_child_y = 0; do_nested = 0;
    expected_root_y = (float)(requested_aspect * 9 / 16); expected_position_x = expected_position_y = 0;
}
static void check_restored(const uint8_t before[0xd8], const uint8_t *p) {
    for (unsigned i = 0; i < 0xd8; i++) if (i != 0x58 && (i < 0x70 || i >= 0xa0)) assert(before[i] == p[i]);
    assert((p[0x58] & 0x10) != 0);
}
static void calculate(void) { hud_calculate(layout, expected_draw, 1); }
static void guard_fixture(void) {
    memset(g_mod[0].base, 0, g_mod[0].size);
    uint8_t *b = g_mod[0].base;
    for (unsigned i = 0; i < sizeof hud_guards / sizeof *hud_guards; i++)
        memcpy(b + hud_guards[i].offset, hud_guards[i].words, hud_guards[i].size);
    const struct { uint32_t vptr, typeinfo, name; const char *text; } types[] = {
        {0x135d2c8,0x135d390,0xf97484,"N3eui8LayoutExE"},
        {0x12ed3e8,0x12ed620,0xf0e634,"N2al9EuiScreenE"},
        {0x1350278,0x1350350,0xf2c1a0,"N2nn4ui2d5PartsE"},
        {0x135d1c8,0x135d2a0,0xf97474,"N3eui7PartsExE"},
    };
    for (unsigned i = 0; i < sizeof types / sizeof *types; i++) {
        strcpy((char *)b + types[i].name, types[i].text);
        put_pointer(b, types[i].typeinfo + 8, b + types[i].name);
        put_pointer(b, types[i].vptr - 8, b + types[i].typeinfo);
    }
    put_pointer(b, 0x135d358, b + 0xa19b00); put_pointer(b, 0x132b2e0, b + 0x909494); put_pointer(b, 0x135ee60, b + 0x909494);
    put_pointer(b, 0x1350310, b + 0x909494);put_pointer(b, 0x135d260, b + 0x909494);
    put_pointer(b, 0x1350330, b + 0x90f2e0);put_pointer(b, 0x135d280, b + 0x90f2e0);
    hud_original = NULL; ready = 0; memset(&hud_stats, 0, sizeof hud_stats);
}
int main(void) {
    // Real adapter guard set: each damaged code range must leave the one slot
    // untouched; the shipping default still requires the exact prepared game.
    g_nmod = 1; strcpy(g_mod[0].name, "main"); strcpy(g_mod[0].build_id, "b424be150a8e7d78701cbe7a439d9ebf");
    g_mod[0].size = 0x1360000; g_mod[0].text_end = 0xa2c000; g_mod[0].data_off = 0x11a0000;
    g_mod[0].base = calloc(1, g_mod[0].size); assert(g_mod[0].base);
    setenv("DM_ODYSSEY_DYNAMIC_DISPLAY", "1", 1);
    for (unsigned i = 0; i < sizeof hud_guards / sizeof *hud_guards; i++) {
        guard_fixture(); g_mod[0].base[hud_guards[i].offset] ^= 1; dm_odyssey_display_hud_install();
        assert(!hud_original && !ready && hud_pointer(g_mod[0].base, 0x135d358) == (uintptr_t)(g_mod[0].base + 0xa19b00));
    }
    guard_fixture(); g_mod[0].build_id[0] = '0'; dm_odyssey_display_hud_install(); assert(!hud_original && !ready);
    g_mod[0].build_id[0] = 'b'; setenv("DM_ODYSSEY_DYNAMIC_DISPLAY", "0", 1); dm_odyssey_display_hud_install(); assert(!hud_original && !ready);
    setenv("DM_ODYSSEY_DYNAMIC_DISPLAY", "invalid", 1); dm_odyssey_display_hud_install(); assert(!hud_original && !ready);
    unsetenv("DM_ODYSSEY_DYNAMIC_DISPLAY"); dm_odyssey_display_hud_install(); assert(hud_original && ready == 1 && hud_stats.installed);
    assert(hud_pointer(g_mod[0].base, 0x135d358) == (uintptr_t)hud_calculate);
    guard_fixture(); setenv("DM_ODYSSEY_DYNAMIC_DISPLAY", "1", 1); dm_odyssey_display_hud_install(); assert(hud_original && ready == 1);
    unsetenv("DM_ODYSSEY_DYNAMIC_DISPLAY");
    free(g_mod[0].base);

    // 1000 changing shapes, animated scale multipliers, and exact local restore:
    // there is no ratio accumulation and baked matrices survive until draw.
    objects("GenericPrimary");
    for (unsigned i = 0; i < 1000; i++) {
        requested_aspect = i & 1 ? 951.0 / 669.0 : 678.0 / 466.0;
        float animation = 1 + (float)(i % 9) * .1f;
        put_float(root, 0x4c, .75f * animation); expected_root_y = (float)(requested_aspect * 9 / 16) * animation;
        uint8_t before[sizeof root]; memcpy(before, root, sizeof root); calculate();
        check_restored(before, root); assert(hud_float(root, 0x70) == expected_root_y);
    }
    // Static edge root changes; the animated child translation is retained.
    requested_aspect = 951.0 / 669.0; objects("CounterCoin");
    strcpy((char *)children[0] + 0xb8, "All"); put_float(children[0],0x30,-548); put_float(children[0],0x34,312);
    attach(root,children[0]); put_float(root,0x34,90);
    expected_position_y = 360 * (1 - expected_root_y);
    uint8_t before_root[sizeof root], before_child[sizeof children[0]];
    memcpy(before_root,root,sizeof root); memcpy(before_child,children[0],sizeof children[0]); calculate();
    check_restored(before_root,root); assert(!memcmp(before_child,children[0],sizeof children[0]));
    // Closed Duo's left cutout, asymmetric right/top inset and open bottom
    // indicator move only their measured HUD edge group. Animated child locals
    // stay untouched and the temporary root values restore on every call.
    const char *safe_owners[] = {"CounterCoin","CounterLife","SaveMessage","KidsMode"};
    const char *safe_anchors[] = {"All","All","All","All"};
    for (unsigned scenario = 0; scenario < 4; scenario++) {
        requested_aspect = scenario < 2 ? 678.0 / 466.0 : 951.0 / 669.0;
        objects(safe_owners[scenario]); strcpy((char *)children[0]+0xb8,safe_anchors[scenario]);attach(root,children[0]);
        int sign = scenario < 2 ? 1 : -1;
        put_float(root,0x34,sign*90.0f);
        if (scenario == 0) put_float(root,0x30,7.5f);
        layout_geometry.left = scenario == 0 ? 84.0 / 678.0 * 1280 : 0;
        layout_geometry.right = scenario == 1 ? 42.0 / 678.0 * 1280 : 0;
        layout_geometry.top = scenario < 2 ? 12.0 / 466.0 * 720 : 0;
        layout_geometry.bottom = scenario >= 2 ? 34.0 / 669.0 * 720 : 0;
        expected_position_x = scenario == 0 ? 7.5f + (float)layout_geometry.left : scenario == 1 ? -(float)layout_geometry.right : 0;
        expected_position_y = sign * 360 * (1 - expected_root_y) +
            (sign > 0 ? -(float)layout_geometry.top : (float)layout_geometry.bottom);
        memcpy(before_root,root,sizeof root); memcpy(before_child,children[0],sizeof children[0]); calculate();
        check_restored(before_root,root); assert(!memcmp(before_child,children[0],sizeof children[0]));
    }
    // Shape-matched Menu fills and embedded parts are compensated through SCALE.
    // Prepared geometry must survive unchanged after Calculate, including sizes.
    objects("Menu"); layout_geometry.left = 160; layout_geometry.top = 24;layout_geometry.bottom = 40; const char *fills[] = {"PicCaptureUse","PicBG00","PicBG01","ParBG"};
    for (unsigned i = 0; i < 4; i++) {
        strcpy((char *)children[i] + 0xb8,fills[i]); put_float(children[i],0x54,i == 3 ? 720 : 960);
        put_float(children[i],0x4c,i == 3 ? 1/.75f : 1); attach(root,children[i]);
    }
    // Embedded CommonBg parts can repeat a primary pane name. The exact
    // Parts boundary excludes its children from the parent FLYT lookup.
    put_pointer(children[3],0,(void *)hud_parts_vptr);
    strcpy((char *)children[4]+0xb8,"RootPane");attach(children[3],children[4]);
    strcpy((char *)children[5]+0xb8,"PicBG00");attach(children[4],children[5]);
    expected_child_y = .75f / expected_root_y;
    uint8_t all_before[sizeof children]; memcpy(all_before,children,sizeof children); memcpy(before_root,root,sizeof root);
    calculate(); check_restored(before_root,root);
    for (unsigned i = 0; i < 4; i++) check_restored(all_before + i * sizeof children[0],children[i]);
    assert(hud_float(children[0],0x54) == 960 && hud_float(children[3],0x54) == 720);
    assert(!memcmp(all_before+4*sizeof children[0],children[4],2*sizeof children[0]));
    // The glasses filter keeps its prepared 1000/.75 surfaces' framing at any aspect.
    objects("FilterGlasses");
    const char *filters[] = {"PicCaptureUse","PicFilter"};
    for (unsigned i = 0; i < 2; i++) {
        strcpy((char *)children[i] + 0xb8, filters[i]); put_float(children[i], 0x54, 1000.0f / .75f); attach(root, children[i]);
    }
    expected_child_y = .75f / expected_root_y;
    memcpy(all_before, children, sizeof children); memcpy(before_root, root, sizeof root);
    calculate(); check_restored(before_root, root);
    for (unsigned i = 0; i < 2; i++) check_restored(all_before + i * sizeof children[0], children[i]);
    // Reentrant Calculate receives the already scoped local fields once; the
    // outer restore still owns them. It must not apply another target/base ratio.
    objects("GenericPrimary"); do_nested = 1; memcpy(before_root,root,sizeof root); calculate();
    assert(delegates == 2); check_restored(before_root,root);
    // Declines are all-or-none and still delegate unchanged, including a bad
    // field encountered late in a full-frame plan, cycle, owner, root or aspect.
    for (unsigned scenario = 0; scenario < 9; scenario++) {
        objects("GenericPrimary"); expected_root_y = .75f;
        if (scenario == 0) put_pointer(screen,0,(void *)0x9999);
        if (scenario == 1) put_pointer(screen,0x30,NULL);
        if (scenario == 2) put_pointer(root,0x18,children[0]);
        if (scenario == 3) put_float(root,0x50,1920);
        if (scenario == 4) put_float(root,0x3c,1);
        if (scenario == 5) requested_aspect = 2;
        if (scenario == 6) { attach(root,children[0]);put_pointer(children[0],0x10,children[0]+8); }
        if (scenario == 7) strcpy(owner_name,"../Unknown");
        if (scenario == 8) {
            strcpy(owner_name,"Menu");strcpy((char *)children[0]+0xb8,"PicCaptureUse");
            put_float(children[0],0x54,960);attach(root,children[0]);
        }
        memcpy(before_root,root,sizeof root); calculate();
        assert(!memcmp(before_root,root,0x70)); requested_aspect = 951.0 / 669.0;
    }
    for (unsigned scenario = 0; scenario < 7; scenario++) {
        objects("GenericPrimary"); expected_root_y = .75f;
        if (scenario == 0) layout_geometry.left = NAN;
        if (scenario == 1) layout_geometry.right = INFINITY;
        if (scenario == 2) layout_geometry.top = -1;
        if (scenario == 3) layout_geometry.bottom = NAN;
        if (scenario == 4) layout_geometry.left = 1280;
        if (scenario == 5) layout_geometry.top = 360,layout_geometry.bottom = 360;
        if (scenario == 6) layout_geometry.left = 1000,layout_geometry.right = 300;
        memcpy(before_root,root,sizeof root); calculate(); assert(!memcmp(before_root,root,0x70));
    }
    objects("CommonBgParts"); expected_root_y = .75f; memcpy(before_root,root,sizeof root); calculate(); assert(!memcmp(before_root,root,0x70));
    objects("GenericPrimary"); enabled = 0; expected_root_y = .75f;
    memcpy(before_root,root,sizeof root); calculate(); assert(!memcmp(before_root,root,0x70)); enabled = 1;
    dm_odyssey_display_hud_stats result; dm_odyssey_display_hud_snapshot(&result);
    assert(result.adapted == 1008 && result.declined == 16 && result.skipped == 1 && result.nested == 1 && result.disabled == 1);
    puts("PASS: actual HUD adapter exact guards, 1000 folds, animated locals, edge/fill/parts, baked matrices, nested restore, safe-area edges/fullbleed and all-or-none declines");
    return 0;
}
