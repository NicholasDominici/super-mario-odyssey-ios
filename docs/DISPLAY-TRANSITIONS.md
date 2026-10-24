# Live display changes

The UIKit frontend uses the active window's bounds and screen scale. Fold,
unfold, safe-area changes and window/display migration reflow the game picture,
full controls, gear and top-left FPS control without restarting the guest or
reopening saves. Invalid intermediate bounds retain the last valid drawable.
Touch-only cancellation releases virtual controls and gear ownership while
preserving physical controller input, feedback, gyro and stored settings.

Drawable size or scale changes invalidate owned interpolation snapshots through
`mtl_present_geometry_changed`. The worker resets model history on the next
epoch; UIKit does not wait for GPU work or release native swapchain ownership.

The camera and HUD archive corrections are prepared for 4:3 (210 archives) or
a phone aspect (211 archives).
The 4:3 preparation supports the guarded live path below. The separate 239:110
phone preparation retains its matching composition during live changes.

## Paired live Duo support

The `ipad` and `duo` build presets enable exact Odyssey 1.4.1 live camera/HUD
adaptation by default with the prepared **4:3** profile and landscape aspects
from 1 through 16:9. `duo` is an explicit alias for this universal preparation.
`DM_ODYSSEY_DYNAMIC_DISPLAY=0` disables it for diagnostics; no setting or relay is
required for normal use. It requires rewritten main observation gates for typed
`al::Projection::setProj` and `al::Projection::calcMtx`, plus independently
verified LayoutEx/Screen/Pane/Parts data and instruction guards. Missing gates,
wrong builds, phone-wide preparations or unsupported geometry retain the paired
prepared composition. The public builder pins the rewritten module containing
both gates and rejects old `--rewritten` inputs. Omit that option to regenerate
from the player's exact original modules. The wide phone preset does not reuse
the narrow HUD math.

The camera callbacks update aspect, dirty caches and horizontal culling bounds
without a persistent object-pointer registry. UIKit publishes scene geometry and
normalized safe insets; a verified guest present boundary latches them together
for the next camera/HUD interval. Native queue entries and frame-generation
captures/outputs retain the completed raster's own aspect and geometry generation.
Old rasters may briefly fit the new scene proportionally; they cannot acquire a
new aspect or interpolate across a geometry change.

The HUD adapter identifies primary layouts through their exact resource owner,
validates a bounded whole tree and respects embedded Parts boundaries. It applies
temporary local scale/edge/fill transforms during Calculate, restores locals
after the original bakes draw matrices and leaves animated children unchanged.
Measured HUD edge groups avoid the active cutout/home-indicator safe area;
backgrounds remain full bleed. Pane sizes are not temporarily changed before a
later draw reads them. Unknown layouts delegate unchanged and are counted.

The same Calculate adapter carries one map-screen rule for every preparation,
including phone builds, where it is the only rule installed. The game writes
map icon, route-line and player-marker root positions in the `Map` layout's root
units, so the adapter records `Map`'s root scale around its own Calculate and
applies it to those owners' roots, restoring them after the original bakes.

Real native Mac gameplay has filled both actual Duo Simulator postures through
one continuous fold/unfold session, with proportionate HUD and measured safe
insets. Game-free tests cover default activation, explicit opt-out, exact guard
rejection and repeated camera/HUD transitions. Source/package verification and
that Mac-backed visual proof are separate from physical Duo execution.
Phone-wide to narrow transitions, all menus/maps/effects and physical device
performance still require their own evidence. Controller, gyro, feedback, audio,
save and cloud behavior is unchanged.

Game-free tests cover repeated posture-sized transitions, invalid geometry,
scale changes and narrow touch layouts. A Simulator host fixture can exercise
production UIKit/touch/FPS code, but cannot establish rewritten guest execution,
in-game camera behavior, physical gyro, haptic feel or cloud handoff. Those need
separate runtime evidence. Device installation/testing remains a separate step.

The iOS 27.1 Simulator SDK and actual simulated GPU used during bring-up lack
the Metal 4 interfaces required by this renderer. A development Mac-backed Duo
preview can relay real native gameplay and inputs while exercising actual fold
controls and scene geometry. Its persistent label must identify the Mac backend;
it is not native Simulator game execution or physical device performance proof.
