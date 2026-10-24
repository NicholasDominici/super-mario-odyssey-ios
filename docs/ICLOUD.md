# Optional iCloud saves

Local saves work without any CloudKit setup. Cloud sync is experimental; see
VALIDATION.md. It uploads complete game save commits quietly and imports remote
progress only before the game starts. A local committed snapshot is kept first.

## Set up your own container

1. Use your own paid developer team's explicit App ID and a bundle ID you control,
   such as `com.yourname.odyssey`. Keep them the same across your devices.
2. In your Apple Developer account, enable iCloud/CloudKit on that App ID and
   create/associate `iCloud.com.yourname.odyssey`.
3. Build both display variants with the same extra option:

   ```sh
   python tools/odyssey.py --nsp-dir /path/to/Odyssey --keys /path/to/prod.keys \
     --preset ipad --bundle-id com.yourname.odyssey \
     --cloud-container iCloud.com.yourname.odyssey \
     --output /path/to/Odyssey-ipad-cloud-unsigned.ipa
   ```

   Use `--preset iphone`, or the other device's model from
   `python tools/odyssey.py --list-presets`, and a different output path for it.
4. Sign with tools/sign_install.py. Its development profile must include that
   exact container, CloudKit service, Development environment, memory capability,
   and the target device. An existing profile can be passed with `--profile`.
5. Sign both devices into the same iCloud account. Launch the device with your
   current progress first, save in-game, and let it remain open with a connection
   until `Documents/cloud-save/status.json` acknowledges the local digest.
   `log.txt` also records sync failures. Close it before starting the other device.
6. Launch the second device. Its first cloud restore runs before game boot.
   Back up `Documents/save` on both devices while testing the handoff.

The private database uses record type **GameSave**, record name
`0100000000010000-save-format-1`, fields `payload` (Asset), `digest` (String),
`device` (String), and `updated` (Date/Time). Development CloudKit can create this
schema while testing; use [CloudKit Console](https://icloud.developer.apple.com/)
to inspect it. No public queries or record sharing are required.

This signing helper intentionally uses Development. Production is a separate
environment. Before implementing distribution, follow Apple's
[schema deployment guide](https://developer.apple.com/documentation/cloudkit/deploying-an-icloud-container-s-schema),
test the deployed schema and migration, and use a matching distribution profile.
Changing environments does not move an existing save automatically.

## Switching devices and conflicts

Play on one device at a time. Save, allow upload to finish, close it, then open
the other device. Background execution and network availability are controlled
by iOS, so an immediate force-close can interrupt an outstanding upload. The
coordinator retries later; it doesn't promise instant delivery while suspended.

Different Apple accounts have separate private saves. If the account changes,
the coordinator doesn't silently publish the previous account's progress to it.
If both devices changed independently, a conflict needs an explicit choice and
the alternatives are backed up. Remote files never replace the live mounted save.
Offline play with a valid local save is supported. A fresh device unable to
reach iCloud offers retry or an explicit start without iCloud.

The source contains the snapshot integrity, conflict and compare-and-swap tests.
Those tests don't substitute for testing your own provisioning, account, schema,
network, background behavior, and both directions of an actual device handoff.
