// Diagnostics for the exact-build primary HUD adapter, with no device claims.
#pragma once
#include <stdint.h>
typedef struct {
    uint64_t calls, adapted, declined, skipped, nested, disabled, edited_fields;
    uint64_t map_roots, map_icons; // Map-screen rule: recorded Map roots, corrected icon roots.
    uint64_t menu_cursors; // Menu ParCursor positions converted into root-local units.
    int installed;
    double last_aspect;
    float last_root_scale_y, last_root_position_x, last_root_position_y;
    char last_owner[64];
} dm_odyssey_display_hud_stats;
void dm_odyssey_display_hud_install(void);
void dm_odyssey_display_hud_snapshot(dm_odyssey_display_hud_stats *out);
