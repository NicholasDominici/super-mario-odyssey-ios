# Super Mario Odyssey for iPhone and iPad

[![Source checks](https://github.com/NicholasDominici/super-mario-odyssey-ios/actions/workflows/checks.yml/badge.svg)](https://github.com/NicholasDominici/super-mario-odyssey-ios/actions/workflows/checks.yml)

Super Mario Odyssey running natively on Apple Silicon, with Metal graphics,
touch controls, physical controller motion, and DualSense haptics and adaptive
triggers. No JIT or jailbreak. Built on [nxnative](https://github.com/seedds/nxnative).

Provide your own **base game, update 1.4.1, and console keys**. The build tools
prepare everything locally on your Mac. This repository contains the port's
source and tools; it does not contain Nintendo assets.

I've been playing on an **iPad Pro 13-inch (M5)** and **iPhone 17 Pro Max** on
iPadOS/iOS 27. Picture, sound, controls, motion and the main controller effects
have been tested in gameplay. [Installation](#install-it-yourself)

## What this adds

- A **4:3 iPad view** with corrected camera projection, HUD, dialogue backgrounds
  and screen transitions. Mario and circular icons keep their proportions.
- A separate **239:110 iPhone view**, matched to the tested iPhone 17 Pro Max.
- **Live Duo layouts** in the 4:3-prepared build: camera, HUD, safe areas and
  controls adapt together through landscape folding without restarting the game.
- **Per-model display presets** for iPhone and iPad models that run iOS 26, using
  each model's native resolution from [ios-resolution.com](https://www.ios-resolution.com).
- **Shake-to-throw Cappy**, using a compatible physical controller's motion sensors.
- The game's original left/right vibration patterns, translated to controller haptics.
- **PS5 DualSense support**, with independent handle haptics and adaptive trigger feedback for supported game events.
- Optional **up to 120 displayed FPS** through frame interpolation on supported
  devices.
- Private **iCloud save sync**, under your own developer team's container.

## Controls

Connect a controller in **Settings → Bluetooth** before opening the game.

Use the sticks to move and look, the face buttons to jump/throw Cappy, and
L2/R2 to crouch or roll. Shake the controller for
motion actions. Touch controls are available too; adaptive triggers require
the appropriate controller.

Tap the top-center **gear** to open Settings. A drag, cancelled touch or
second gear finger stays consumed without pressing a game control. VoiceOver
also offers **Open settings**. The gear remains available with a controller.
The full Odyssey touch layout always includes the D-pad and invisible floating
right stick, alongside the fixed left stick and Nintendo face diamond.

The frame-rate counter sits in the safe-area top-left on iPhone and iPad. Tap
it to hide its text; tap the same corner again to reveal it. Other gameplay
touches stay active. The app remembers visibility, and generated presentation
keeps the FG marker. The player confirmed hide/reveal working on the M5 iPad
in the current build; the new phone package remains pending installation.

Settings has exactly three switches: **Gyro**, **Device haptics**, and **Also
with controller**. Gyro On uses Auto, preferring fresh controller motion and
falling back to iPhone/iPad sensors. Off disables motion. Existing calibration
and controller feedback are preserved. The player reports iPhone device gyro
working; other orientations, handoffs and iPad gyro need their own checks.

Device haptics On follows native rumble and guarded gameplay events through a
separate finite phone sink. **Also with controller** controls only device
vibration; it does not change controller vibration or adaptive triggers.
Unsupported devices show **Unavailable on this device** and remain quiet. The
tested iPad has no built-in actuator. Bullet Bill capture is a felt-positive
native baseline. Build18's extra cues were physically rejected as too strong
and buzzing. Build19 uses lower-strength, sharp one-shot haptic transients for
confirmed in-game events; input edges never generate a cue. Strong native
rumble takes priority, and held or duplicate events cannot renew a tap. Its
physical feel is pending a new phone check. It covers guarded normal jumps/landings, long jumps/backflips,
cap throws, standard coins and ground pounds. Special actor variants are not
implied. Advanced stored preferences are retained without extra menu sections.

Existing stored frame-interpolation preferences are retained, and
`DM_FRAMEGEN` environment overrides keep precedence. The three-switch sheet
adds no display menu. No setting changes the game's 60 Hz simulation.

## Display and performance

Choose `--preset ipad` or `--preset duo` for the **4:3 preparation with live
landscape adaptation from 1:1 through 16:9**. Both produce a universal app with
the same guarded camera/HUD path; `duo` makes the intended target explicit.
Actual scene geometry and safe insets drive folding, rather than the phone/tablet
device name. The separate `--preset iphone` retains the **239:110** preparation
for the tested iPhone 17 Pro Max; use the Duo preset for a Duo.

You can also pass your iPhone or iPad model, such as `--preset iphone-16-pro` or
`--preset ipad-air-6th-gen-11`; the model name as listed, in quotes, works too.
Run `python tools/odyssey.py --list-presets` to see every model. iPad models
select the same live 4:3 build as `--preset ipad`, which fits the real screen at
runtime; `--preset iphone-duo` is the same as `--preset duo`. iPhone models are
wider than 16:9, so they build a static camera/HUD preparation at that model's
exact native aspect. Model names and resolutions come from
[ios-resolution.com](https://www.ios-resolution.com) and are kept in
[tools/ios_displays.tsv](tools/ios_displays.tsv). The build doesn't detect your
device, so choose the model you'll install on. Of the iPhone shapes, only 239:110
(iPhone 17 Pro Max) has been tested in gameplay.

The live path is enabled by default only after both exact-build camera and HUD
guards pass. Unsupported preparations or geometry keep proportional composition.
`DM_ODYSSEY_DYNAMIC_DISPLAY=0` is a diagnostic opt-out. See
[display transitions](docs/DISPLAY-TRANSITIONS.md) for source, frame ownership and
evidence limits. The observed Duo gameplay uses a labeled Mac-backed Simulator
preview; physical Duo execution and performance are untested.

The internal raster remains **1600 × 900**. Full-screen aspect does not mean
native display-pixel rendering. On the tested ProMotion devices the FPS overlay
can show around 120 with `FG`; roughly half those frames are generated. This
doesn't double physics speed or mean the GPU renders 120 original game frames.
Interpolation can introduce visual artifacts and latency and falls back when
unsupported. Use `--frame-generation off` to turn it off, or `--show-fps` to see
the counter. See [validation and limitations](docs/VALIDATION.md).

## Saves and updates

Progress lives in `Documents/save`, visible through the app's folder in Files
or Finder file sharing. **Back it up before deleting or replacing the app.**
Keep the same bundle ID and signing team when updating; deleting the app removes
its local container. The build/install tools don't delete an installed app or
launch it automatically. Save and fully close it before installing an update.

iCloud is **off by default**. Enable it only after following
[the iCloud setup guide](docs/ICLOUD.md), using the same container and environment
on both devices. Saves upload in the background after completed game commits;
there is no permanent sync button. Cloud imports happen before the game boots.
Use one device at a time and close it before switching.

An iPad-to-iPhone handoff has been verified. Some later phone save captures
failed intermittently; a tested interrupted-read fix and better diagnostics are
included, but its live follow-up and reverse handoff remain unverified. Keep
local backups and treat cloud sync as experimental.

## Building and contributing

The supported inputs are the base game (**NSP or XCI**) plus **update 1.4.1 (`v393216`)**,
title ID `0100000000010000`. The tools check exact module hashes/build IDs and
reject other versions. [Input details and extracted-folder support](docs/INPUTS.md)
cover the same files used for the tested builds.

The player-facing entry point is `tools/odyssey.py`. It uses the shared runtime
in `dm/`, the exact-build profile in `dm/games/0100000000010000/`, and structural
HUD preparation in `tools/prepare_odyssey_*.py`. All extracted files, rewritten
game modules, shader caches, signing profiles and IPAs stay outside the checkout.

Run checks without any game files:

```sh
python3 tools/check.py
```

For changes to binary observers, shaders or rendering, see
[AGENTS.md](AGENTS.md), [CLAUDE.md](CLAUDE.md) and the
[runtime development guide](docs/development.md). A source test passing is not
proof of gameplay performance or how a physical controller feels.

## Reporting bugs

[Open an issue](https://github.com/NicholasDominici/super-mario-odyssey-ios/issues)
with your device, OS version, port commit, game version, display preset and what
you were doing. The app's `log.txt` and diagnostics are in its Files folder.
Remove account/device details before posting; don't attach game files, keys,
saves or provisioning profiles.

## Credits

- [seedds/nxnative](https://github.com/seedds/nxnative): native runtime, offline
  code rewriting, graphics translation, build tooling, and the original game profile.
- [ly05010419/MacNativeGames](https://github.com/ly05010419/MacNativeGames): work
  used by nxnative; its license and notices are retained.
- [fayaz12g/smo-aar](https://github.com/fayaz12g/smo-aar/tree/e8fd670d1faeab3d8c4904177928bcfd14afb42c):
  the aspect-ratio approach, reimplemented here with structural archive checks.
- [Ryujinx and the other dependencies](dm/third_party/README.md): shader
  translation, codecs, headers and utilities, under their respective licenses.

Port source is MIT; see [LICENSE](LICENSE) and [source provenance](docs/PROVENANCE.md).
This is an unofficial fan project. Super Mario Odyssey and its game content
belong to Nintendo. The game and its assets are not covered by this source license.

## Install it yourself

You don't need Codex, Claude, or another AI assistant. You need an Apple Silicon
Mac, **Xcode 27 or newer**, an iPhone/iPad on **iOS/iPadOS 26 or newer**, your own
game files and keys, and a developer account capable of signing with
**Increased Memory Limit**. The tested signing path uses a paid Apple Developer
team. Free-account sideloading and lower-memory devices haven't been validated.
Allow about **40 GB free on the Mac** for game files, caches and packaging and
**12 GB on the device** for installation headroom; actual requirements vary.

1. **Prepare the Mac.** Install and open Xcode, accept its license, and sign in
   under **Xcode → Settings → Apple Accounts**. Select that Xcode under
   **Settings → Locations → Command Line Tools**. Install
   [Homebrew](https://brew.sh/) if you don't already have it, then run:

   ```sh
   brew install python xcodegen spirv-cross zstd
   brew install --cask dotnet-sdk
   ```

   The tools require **.NET 10**. If you install a newer SDK, also install the
   [.NET 10 SDK](https://dotnet.microsoft.com/en-us/download/dotnet/10.0) so the
   pinned shader translator's .NET 10 runtime is available.

2. **Download the source and prepare Python.** Open Terminal and run:

   ```sh
   git clone https://github.com/NicholasDominici/super-mario-odyssey-ios.git
   cd super-mario-odyssey-ios
   python3 -m venv .venv
   source .venv/bin/activate
   python -m pip install -r requirements.txt
   ```

3. **Put your game files together.** Create a folder outside the source repo,
   such as `~/Games/Odyssey`. Put your base-game **NSP or XCI** and update **1.4.1 NSP**
   there. Keep your `prod.keys` elsewhere, such as `~/Games/Keys/prod.keys`.
   Only one game's files should be in the folder. Don't rename a different
   update to 1.4.1; its actual build will be checked.

4. **Build your private IPA.** Replace the example paths below. Choose a bundle
   ID you control and keep it for future updates. For the tested 4:3 iPad:

   ```sh
   python tools/odyssey.py \
     --nsp-dir "$HOME/Games/Odyssey" \
     --keys "$HOME/Games/Keys/prod.keys" \
     --preset ipad \
     --bundle-id com.yourname.odyssey \
     --output "$HOME/Games/Odyssey-ipad-unsigned.ipa"
   ```

   For the tested iPhone 17 Pro Max layout, change `--preset ipad` to
   `--preset iphone`. For a Duo, use `--preset duo`. For another model, pass its
   name from `python tools/odyssey.py --list-presets`, such as
   `--preset iphone-16-pro`. Use a different output filename for each preparation. The first build takes
   longer because it prepares shaders. The last line prints the IPA's path.
   That IPA contains your game files; keep it private.

5. **Connect and prepare the device.** Connect it by USB, unlock it and tap
   **Trust**. Enable **Settings → Privacy & Security → Developer Mode**, then
   restart if prompted. Run `xcrun devicectl list devices` in Terminal and copy
   your device's identifier. Find your Team ID in your Apple Developer account's
   Membership details. [Signing help](docs/INSTALL.md) covers common errors.

6. **Sign and install.** Replace `YOUR_TEAM_ID`, `YOUR_DEVICE_ID` and the IPA path:

   ```sh
   python tools/sign_install.py \
     --ipa "$HOME/Games/Odyssey-ipad-unsigned.ipa" \
     --team YOUR_TEAM_ID \
     --device YOUR_DEVICE_ID \
     --install
   ```

   Xcode obtains a development profile for that device, the helper checks its
   memory entitlement, and then signs and installs the game. If Xcode reports a
   missing capability, follow [the profile setup steps](docs/INSTALL.md#profile-setup)
   and rerun using `--profile`. A signed IPA is also saved next to the unsigned one.
   Merely tapping an IPA in Files doesn't install it; development builds run only
   on devices allowed by their profile, and must be renewed when signing expires.

7. **Open Super Mario Odyssey and play.** Pair your controller, choose Start or
   Continue, and test movement, sound and a few jumps. When updating later, make
   an in-game save, fully close the app, back up its `save` folder, and repeat
   steps 4–6 with the same bundle ID and signing team. Optional iCloud setup is
   in [docs/ICLOUD.md](docs/ICLOUD.md).
