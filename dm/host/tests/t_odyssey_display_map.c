// Synthetic receiving objects execute the actual map-screen rule of the HUD
// adapter, for a prepared phone profile and for the prepared 4:3 profile.
#include "../hle_odyssey_display_hud.c"
#include <assert.h>
module_t g_mod[MAX_MOD]; int g_nmod;
static int enabled, ready;
static double requested_aspect = 951.0 / 669.0;
int dm_odyssey_display_enabled(void) { return enabled; }
double dm_odyssey_display_aspect(void) { return requested_aspect; }
void dm_odyssey_display_layout_snapshot(dm_odyssey_display_layout *out) {
    memset(out, 0, sizeof *out); out->aspect = requested_aspect;
}
void dm_odyssey_display_hud_ready(void) { ++ready; }

static void put_pointer(uint8_t *p, size_t offset, const void *value) {
    uintptr_t word = (uintptr_t)value; memcpy(p + offset, &word, sizeof word);
}
static void put_float(uint8_t *p, size_t offset, float value) { memcpy(p + offset, &value, sizeof value); }
static uint8_t layout[0xa0] __attribute__((aligned(8)));
static uint8_t screen[0xc0] __attribute__((aligned(8)));
static uint8_t root[0xd8] __attribute__((aligned(8)));
static char owner_name[64];
static float expect_x, expect_y, expect_sx, expect_sy;
static unsigned delegates;
static void delegate(void *value, void *draw, int recursive) {
    assert(value == layout && draw == (void *)0x88 && recursive == 1);
    ++delegates;
    assert(fabsf(hud_float(root, 0x30) - expect_x) < .001f && fabsf(hud_float(root, 0x34) - expect_y) < .001f);
    assert(fabsf(hud_float(root, 0x48) - expect_sx) < .00001f && fabsf(hud_float(root, 0x4c) - expect_sy) < .00001f);
}
static void objects(const char *owner, float x, float y, float sx, float sy) {
    memset(layout, 0, sizeof layout); memset(screen, 0, sizeof screen); memset(root, 0, sizeof root);
    hud_layout_vptr = 0x1000; hud_screen_vptr = 0x2000; hud_pane_vptr = 0x3000; hud_root_vptr = 0x4000;
    hud_parts_vptr = 0x5000; hud_parts_ex_vptr = 0x6000;
    put_pointer(layout, 0, (void *)hud_layout_vptr); put_pointer(layout, 0x18, root); put_pointer(layout, 0x88, screen);
    put_pointer(screen, 0, (void *)hud_screen_vptr); put_pointer(screen, 0x30, layout);
    strcpy(owner_name, owner); put_pointer(screen, 0xb8, owner_name);
    put_pointer(root, 0, (void *)hud_pane_vptr);
    put_pointer(root, 0x20, root + 0x20); put_pointer(root, 0x28, root + 0x20);
    put_float(root, 0x30, x); put_float(root, 0x34, y); put_float(root, 0x48, sx); put_float(root, 0x4c, sy);
    put_float(root, 0x50, 1280); put_float(root, 0x54, 720);
    strcpy((char *)root + 0xb8, "RootPane");
    hud_original = delegate;
    expect_x = x; expect_y = y; expect_sx = sx; expect_sy = sy;
}
// Calculate, then require every authored field back exactly (dirty bit aside).
static void calculate(void) {
    uint8_t before[sizeof root]; memcpy(before, root, sizeof root);
    unsigned count = delegates;
    hud_calculate(layout, (void *)0x88, 1);
    assert(delegates == count + 1);
    for (unsigned i = 0; i < sizeof root; i++) if (i != 0x58) assert(before[i] == root[i]);
}
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
    put_pointer(b, 0x1350310, b + 0x909494); put_pointer(b, 0x135d260, b + 0x909494);
    put_pointer(b, 0x1350330, b + 0x90f2e0); put_pointer(b, 0x135d280, b + 0x90f2e0);
    hud_original = NULL; ready = 0;
}
int main(void) {
    g_nmod = 1; strcpy(g_mod[0].name, "main"); strcpy(g_mod[0].build_id, "b424be150a8e7d78701cbe7a439d9ebf");
    g_mod[0].size = 0x1360000; g_mod[0].text_end = 0xa2c000; g_mod[0].data_off = 0x11a0000;
    g_mod[0].base = calloc(1, g_mod[0].size); assert(g_mod[0].base);
    int phone = DM_GAME_DISPLAY_ASPECT > 16.0 / 9.0;
    // The explicit opt-out and a damaged guard keep the slot untouched.
    guard_fixture(); setenv("DM_ODYSSEY_DYNAMIC_DISPLAY", "0", 1); dm_odyssey_display_hud_install(); assert(!hud_original);
    unsetenv("DM_ODYSSEY_DYNAMIC_DISPLAY");
    guard_fixture(); g_mod[0].base[hud_guards[0].offset] ^= 1; dm_odyssey_display_hud_install(); assert(!hud_original);
    guard_fixture(); dm_odyssey_display_hud_install();
    assert(hud_original && hud_phone == phone && ready == !phone);
    assert(hud_pointer(g_mod[0].base, 0x135d358) == (uintptr_t)hud_calculate);
    free(g_mod[0].base);

    // Before Map has calculated there is nothing to follow: icons stay as written.
    objects("MapIcon", 300, 120, phone ? .817696f : 1, phone ? 1 : .75f); calculate();
    float s = phone ? (float)(16.0 / 9.0 / DM_GAME_DISPLAY_ASPECT) : 1;
    float target = (float)(requested_aspect * 9 / 16);
    for (unsigned mode = 0; mode < (phone ? 1u : 2u); mode++) {
        enabled = !phone && mode == 1; // 4:3: static prepared root, then the live plan.
        float base_x = phone ? s : 1, base_y = phone ? 1 : .75f;
        float live_y = enabled ? target : base_y;
        // Map's root is recorded around its own Calculate (and live plan).
        objects("Map", 0, 0, base_x, base_y); expect_sy = live_y; calculate();
        // Checkpoints, hints and the route line follow Map's live root.
        const char *icons[] = {"MapIcon", "MapIconLine"};
        for (unsigned i = 0; i < 2; i++) {
            objects(icons[i], 300, -120, base_x, base_y);
            expect_x = 300 * base_x; expect_y = -120 * live_y; expect_sy = live_y; calculate();
        }
        // The player marker's uniform reset regains the prepared ratio first.
        objects("MapPlayer", -500, 200, 1.2f, 1.2f);
        expect_x = -500 * base_x; expect_y = 200 * live_y;
        expect_sx = 1.2f * base_x; expect_sy = 1.2f * live_y; calculate();
        // Other owners never take the map rule (a live plan still scales Y).
        objects("MapMiniIcon", 300, 120, base_x, base_y); expect_sy = live_y; calculate();
    }
    // A translated or out-of-range Map root is not followed; the last good one stays.
    enabled = 0;
    float kept = phone ? s : 1;
    objects("Map", 10, 0, kept, phone ? 1 : .75f); calculate();
    objects("Map", 0, 0, 1.5f, 1); calculate();
    objects("MapIcon", 100, 0, kept, phone ? 1 : .75f); expect_x = 100 * kept; calculate();
    dm_odyssey_display_hud_stats stats; dm_odyssey_display_hud_snapshot(&stats);
    assert(stats.map_icons == (phone ? 4u : 7u) && stats.map_roots == (phone ? 1u : 2u));
    printf("PASS: map-screen rule (%s): icon roots follow Map's root, player scale ratio, other owners untouched, exact restore\n",
           phone ? "phone" : "4:3");
    return 0;
}
