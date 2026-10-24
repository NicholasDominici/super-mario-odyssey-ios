# Supported game inputs

The player build supports Super Mario Odyssey, base title ID
`0100000000010000`, plus update **1.4.1**, package `v393216` (update title
`0100000000010800`). Supply the base **NSP or XCI** and update NSP together with your own
console `prod.keys`. Extraction uses the upstream LibHac tool and validates NCA
integrity. This wrapper does not enable damaged-file overrides or provisional
profiles. No firmware image is required by this tested build path.

The original tested local inputs were a cartridge-format `.xci` base and an
update `.nsp`. The folder scanner recognizes that combination even when the
cartridge filename has no title-ID tag; the extracted module identities are
still checked. Keep only one base game and the supported update in that folder.

The exact merged update modules used for the working port are:

| Module | NSO build ID | Original file SHA-256 |
| --- | --- | --- |
| main | `b424be150a8e7d78701cbe7a439d9ebf` | `47ac74a66234bc1eb717b18e01fe7c880d2dd50cf1115fd046f5e5878be5f85f` |
| subsdk0 | `93ff8252d975adf07230cb86c83301c5` | `d22d98656a19be240b554e7db8d69126d6427232521238d665aec3509087f2cf` |
| sdk | `fcf93a41b08c5193a1410d262602dc62` | `754cf4b581d749fbe3d457cf66497b141ef994cf592d247919d64a37dcc30d27` |

These are identifiers and checksums, not copies of game code. Other builds are
rejected. Do not disable the gate or rename another update to pass it.

## Already-extracted files

The same merged files can be provided as:

```text
/private/game-folder/
  ExeFS/main
  ExeFS/subsdk0
  ExeFS/sdk
  RomFS/LayoutData/...
  RomFS/LocalizedData/...
  RomFS/SoundData/SeResourceStd2nd.aras
  control.nacp              (optional when explicit app name/version are used)
  icon.jpg                  (optional; absent means no game-derived app icon)
```

Prepare the shaders from the NSP workflow first. Advanced repeat builds can
reuse that private iOS cache:

```sh
python tools/odyssey.py \
  --extracted-dir /path/to/merged-1.4.1 \
  --shaders /path/to/0100000000010000_build/shader/ios \
  --preset ipad --bundle-id com.yourname.odyssey \
  --work /path/to/private-build \
  --output /path/to/Odyssey-ipad-unsigned.ipa
```

`--rewritten /path/to/rewritten-modules` can reuse exact-build rewritten modules;
the camera and all six haptic observer guards are checked before use. Omitting
it rewrites all three original NSOs. `--prepare-only` validates and prepares the
camera/HUD without shaders, Xcode compilation, signing, or device access.

The build creates a separate RomFS copy (APFS clones when available) and replaces
only the corrected layout archives (210 for 4:3 builds, 211 for phone builds)
and the 15 Balloon World event/message archives in that copy. Original game files remain
unchanged. All game-bearing outputs and local receipts stay outside the repo.

## Why a Mac build is necessary

The game code is rewritten offline and embedded into the app's signed Mach-O.
It cannot be imported later as executable code by a generic unsigned shell app.
A completed private IPA includes both those rewritten modules and the game
assets; it is not a redistributable source artifact. CI checks source only.
