# Validation and current limits

## Accepted physical-device behavior

- Current M5 iPad update: the player confirmed the top-left FPS counter hides
  on tap and reappears from the same corner. Before launch, the installed build
  and all protected save, cloud, preference, environment and pipeline files
  matched the fresh backup. Device-motion samples reached guest six-axis reads
  without sensor errors, and the current runtime acknowledged iCloud sync.
  Those runtime observations do not certify physical aim/motion in every
  orientation or a new cross-device save round trip.
- M5 iPad Pro 13-inch: 4:3 world/HUD proportions, gameplay, sound and controls.
- iPhone 17 Pro Max: 239:110 gameplay/HUD and sound/controls; generated
  presentation observed around 120 displayed FPS in a gameplay sample.
- DualSense: live motion consumed by the game; authored left/right rumble;
  backflips accepted by the player; five successive held-trigger long jumps
  all produced the intended recoil, including rolling follow-ups.
- Wall-jump and side-flip updates were installed along with frame generation;
  the player reported the update working well. This is not certification of
  every haptic event, level, cutscene, controller or long session.
- The original iPad save was preserved byte-for-byte across the cloud update.
  Its complete committed digest was imported and verified on the iPhone before
  guest boot. The phone also uploaded later game saves.

## Known limits

- Shared top-left FPS counter: real game-free Catalyst UIKit fixture passes81
  checks for hidden/reveal hit testing, both landscape safe areas, compact L3
  clearance, normal ZL/L3 centers, saved visibility, accessibility, FG labeling
  and stale/reset sampling. Explicit corner taps take priority over expanded
  shoulder hit rims; the target never expands beyond80×22pt. Physical-device
  hide/reveal was accepted on the M5 iPad; delivery to the phone remains pending.
  Gamepad/settings/gyro/controller/haptic policies
  are unchanged from19.

- Optional device-local Core Haptics is a separate sink for the original native
  bands and verified takeoff composition. It never changes controller gains,
  textures or trigger curves. Native-band On gain stays 0.20 with a 0.18 intensity cap.
  Build18's stronger continuous action cues failed physical feel as too strong
  and buzzing. Build19 emits a single lower-strength transient (0.10–0.20,
  sharpness0.90–1) per confirmed in-game event, with no sustained cue envelope.
  Same-tick cues select the strongest event; duplicates, stale events and bursts
  within50ms are consumed without delayed replay. Native intensity0.055 or more
  suppresses extra taps, and stronger native output immediately preempts a tap.
  Quiet native texture pauses for at most30ms around a tap, so two players do
  not sum on the actuator. Controller gains and native capture mapping are unchanged.
  The local sink requires fresh game frames (150 ms), a native value newer than
  activation, foreground/permit state and a supported actuator. Effects have a
  finite 100 ms hardware lease for native continuous output; transients end
  themselves and release their player within30ms. Off, background, controller selection, stale
  heartbeat, native stops and engine failures release output; old engine callbacks
  cannot restart a new engine. Settings/reset recovery require fresh input.
  The coordinator's physical hardware probe reports iPad unsupported and iPhone
  supported. The player reports native Bullet Bill capture felt, while normal
  jumps/landings, long jumps/backflips, cap throws, coins and ground pounds were
  missing/too faint. The earlier global no-feel report is superseded by that
  narrower observation. Phone-specific event transients avoid multiplying
  already-small controller cues by another .20/.30; native bands/strong capture
  gain are unchanged. No touch/controller button edge creates an event.
  Seven extra first-step callbacks are guarded independently
  by exact main build, RTTI, singleton/vtable ownership and expected code bytes.
  Their separate bounded queue cannot evict or enter controller cues. Standard
  3D/2D coins and HackCap ThrowStart are covered; special variants remain untested.
  Build17 full controls and the three-switch sheet were physically accepted.
  Build18 changes activation to tap; its haptic texture/strength failed.
  Build19 actual sink/tick tests pass30 checks, including input-only silence,
  one-shot playback, native preemption and lifecycle cleanup; policy2600 checks
  and sanitizers pass. New transient feel and tap delivery still require physical follow-up. No
  audio or generic vibration fallback is used.

- The gear consumes a fixed 44-point hit region before gameplay routing. Opening
  activates on normal tap release with at most 12 points of motion; a resting
  gameplay thumb is allowed and presentation neutralizes all owned input.
  Cancellation, second gear fingers, rotation, disconnect/background and stale generations
  cannot open it later. Expanded +/- hit regions keep at least a 5-point gap.
  The UIKit adapter inspects real coalesced touch samples as well as the latest
  endpoint, so a rapid out-and-back excursion over 12 points stays cancelled.
  The portable canonical contract tests geometry/gesture boundaries; preview
  renders do not substitute for actual UIKit/device touch testing.

- The Gyro On/Off switch uses the existing Auto/Off source router and the
  existing guest six-axis ABI. Device transforms, source arbitration, original
  sample-age rejection, history reset and touch-only operation have local tests.
  Real iPad/iPhone aiming, shake actions, orientation and controller regression
  still require physical testing. No device update is implied by a build.

- Three thunder-effect geometry shaders remain unsupported in the original
  tested shader set. Full-game visual correctness isn't certified.
- Internal rendering is 1600×900. Camera/display aspect is separate from raster
  resolution. Presets are chosen at build time, not detected on the device.
- iPad model presets and `iphone-duo` select the same live 4:3 build as `ipad`
  and `duo`. iPhone model presets other than 239:110 reuse the guarded phone
  camera and HUD rules at that model's exact aspect, without the live path. Those
  aspects pass synthetic unit checks only; their gameplay, HUD placement and
  transitions haven't been checked on a device.
- Every preparation compensates the Moe-Eye glasses filter (`FilterGlasses`)
  on the axis its root narrows: phones widen it to the full panel width (it
  previously stopped short of both sides), 4:3 sets its 1000-unit surfaces to
  1000/.75 so it keeps the authored framing, and the live adapter holds that
  framing at any supported aspect. The 4:3 and live forms are untested on a device.
  Phone preparations also widen the shared footer bars (`FooterParts`) to both
  edges. Every preparation now corrects the map footer (`MapFooter`), which was
  left at 16:9 and stretched its button guides; 4:3 pins it to the bottom edge
  and the live adapter treats it as a bottom-edge group. 4:3 builds now change
  210 archives and phone builds 211. These were measured against the original
  layouts. The player reported the 437:201 phone build with these fixes working
  on an iPhone 18 Pro; 4:3 and live iPad/Duo builds of them are untested on a device.
- Map icons are positioned by the game at runtime in the map's own root units,
  which skip the map's prepared or live correction, so they drifted from their
  spots away from the cursor. The exact-build Calculate adapter now records the
  `Map` layout's root scale and applies it to `MapIcon`, `MapIconLine` and
  `MapPlayer` root positions (restoring the player marker's prepared scale ratio
  after the game resets it), for phone, static 4:3 and live builds. Phone builds
  install that adapter for this rule only; the live HUD stays 4:3-only.
  Synthetic adapter tests cover both profiles. The player reported it working
  in that iPhone 18 Pro build; 4:3 and live builds are untested on a device, and
  the HUD minimap's icons are a separate path that is unchanged.
- 120 FPS is optional frame interpolation, with the simulation at 60 Hz.
  Hardware support, latency, artifacts, heat and sustained performance vary.
- Cloud save capture failed intermittently on some phone commits. The included
  EINTR retry fix preserves all consistency guards and improves diagnostics;
  the actual failing device branch, a full live retest of that fix and the
  reverse phone-to-iPad handoff are still unverified.
- The release candidate also gates cloud publication on a durable committed-save
  journal, and persists account/ancestry state before acknowledging sync. Failed
  writes retain pending progress and retry without requiring another game save.
  The production coordinator passes 24 synthetic scenarios and 251 checks using
  real Foundation write failures, including recovery after server acknowledgement,
  newer commits, import and account changes. Ordinary and sanitizer runs cover
  local logic; a fresh two-device physical handoff remains a separate check.
- Xcode 27 is the tested build toolchain; deployment minimum is iOS 26. Other
  devices, low-memory phones, free-account signing and ad hoc signing are unverified.
- A clean source build/signing-helper check does not automatically install or
  replace the already tested apps. New packaged artifacts need their own live QA.

## Repository workflow verification

The portable workflow was exercised with Xcode 27.1 and the original local
cartridge XCI plus update 1.4.1 NSP, in an independent private work directory.
It rebuilt the extractor from source, extracted and integrity-checked the merged
game, rewrote all three modules, split 27,984 shaders, prepared the matching HUD,
compiled the app and packed a private IPA. The shader pass reused a verified
local cache: 27,981 were ready and the same three documented shaders failed.
This was a full input-to-IPA check, not a new cold compile of every shader.

Separate extracted-file builds produced both the iPad and iPhone variants. All
209 output archive hashes for each preset match the accepted local display
build, and the phone rewritten-module hash matches its accepted camera/haptic
module. The controller, cloud and interpolation runtime sources are unchanged
from the local port. Both variants were signed and strictly verified with an
existing development profile; the phone check included its CloudKit entitlements.
No device app was replaced during repository validation. Automatic creation of
a new developer team's profile is not covered by those signing checks.

A clean source clone passed the game-free suite: 24 Python tests, native
controller/observer/viewport checks, save-commit callback tests, 146 save-archive
checks, and 17 coordinator scenarios with 153 checks. GitHub Actions runs the
same game-free suite. Private inputs, caches, IPAs, signing receipts and logs
are not uploaded to GitHub.

## Game-free checks

```sh
python3 tools/check.py
```

The checks cover structural layout handling with synthetic archives, preset,
model-table and CloudKit configuration, exact-profile signing policy, controller transport and
effect policy, gameplay-observer guards, presentation geometry, save archive
integrity/atomic restore, and the production CloudKit coordinator with controlled
transport callbacks. No real cloud account or device is touched.

## Local input verification

With the virtual environment active, use the same personal files as the port:

```sh
python tools/odyssey.py --extracted-dir /path/to/merged-1.4.1 \
  --preset ipad --prepare-only --work /path/to/private-ipad-check
python tools/odyssey.py --extracted-dir /path/to/merged-1.4.1 \
  --preset iphone --prepare-only --work /path/to/private-iphone-check
```

Both commands validate all three module hashes and the rewritten camera/haptic
guards. They create and read back the corrected layout archives (210 for 4:3,
211 for phone presets), hash-check
the original sources after preparation, and write private receipts. They never
sign or install. Optional `--rewritten` reuses an already checked local rewrite.

Before any requested live update, save and close the app, take a stable backup,
preserve bundle/team identity, install, then compare every save file before
launch. Verify gameplay, round HUD elements, dialogue/loading transitions,
controller actions and foreground/background behavior. Test cloud handoffs one
direction at a time and distinguish acknowledged digests from merely queued work.
