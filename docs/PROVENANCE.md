# Source provenance and publication boundary

This repository snapshots [seedds/nxnative](https://github.com/seedds/nxnative)
at commit `3de606fd11f5e39c6b148e22e06f392daaecd0c4`, with the Odyssey iPad/iPhone
changes developed locally on top. Upstream MIT copyright/license and bundled
third-party notices are preserved. Shared runtime profiles for other titles are
upstream metadata; this repo's player workflow and validation focus on Odyssey.

The local additions include controller motion and authored vibration transport,
exact-build jump observers and guarded trigger output, corrected camera/HUD
preparation for 4:3 and 239:110, optional VideoToolbox frame interpolation,
transactional save-commit capture and private CloudKit coordination. The public
entry points replace machine-specific build/signing scripts with configurable
paths and identities.

HUD preparation is an original structural SARC/FLYT/FLAN implementation of the
aspect-ratio strategy documented by SMO-AAR at commit
`e8fd670d1faeab3d8c4904177928bcfd14afb42c`. It doesn't vendor that mod's source
or game-bearing outputs. Its primary-source reference is linked in README.md.

`tools/ios_displays.tsv` records iPhone and iPad model names and native display
resolutions from [ios-resolution.com](https://www.ios-resolution.com), retrieved
2026-10-23, limited to models that run iOS/iPadOS 26.

`dm/gfx/tools/dmsh_xlate_bin` contains the upstream redistributable **tool**
binaries and managed dependencies matching `dmsh_chain.lock`, not shaders from
a game. They are retained because rebuilding the translator changes its shader
fingerprints. Their exact bytes are pinned in
[TOOLCHAIN-BINARIES.json](TOOLCHAIN-BINARIES.json); the publication audit rejects
changed/unlisted tools and other binary files. Corresponding tool source, project references and third-party
notices are in dm/gfx/tools/dmsh_xlate and dm/third_party. Game shader caches are
generated from a player's own files and excluded from publication.

Public contents are source, build scripts, tests with synthetic fixtures,
licenses, and reverse-engineered metadata/checksums. No source history from the
private working directory is imported. Private screenshots, game icons/fonts,
RomFS/ExeFS, NSOs, rewritten bytes, translated shaders, device logs, signing
profiles, credentials, saves, apps and IPAs are excluded. Run tools/audit_repo.py
against the index before pushing. CI must never accept private game inputs or
upload private game-bearing artifacts.

The MIT license applies to the port code, not to Nintendo's game, content, or
trademarks, or to components with their own licenses.
