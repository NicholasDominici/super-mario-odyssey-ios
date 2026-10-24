"""Prepare private, exact-build display assets without modifying the inputs."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tempfile

from odyssey_displays import resolve
import prepare_odyssey_aspect as pad
import prepare_odyssey_phone as phone

TITLE = '0100000000010000'
MODULES = {
    'main': pad.MAIN_SHA256,
    'subsdk0': 'd22d98656a19be240b554e7db8d69126d6427232521238d665aec3509087f2cf',
    'sdk': '754cf4b581d749fbe3d457cf66497b141ef994cf592d247919d64a37dcc30d27',
}
REWRITTEN = {
    'main': '05214155b3568c8c7e3081f61c0f2e8ff55002e75d0b74e1dde5e62dc06b492f',
    'subsdk0': 'bc8cdf523557dce3789f2ba890998bf825e7ff102ea91fb1fd76d0f0f7c5db43',
    'sdk': 'f1f137f007d11574416e0262f42029ea31fc8656c44b56883a6abb08eae68875',
}


def outside_repo(path: Path, repo: Path) -> Path:
    """Reject game inputs/outputs inside this source checkout, including symlinks."""
    path = path.expanduser().resolve()
    if path == repo.resolve() or repo.resolve() in path.parents:
        raise ValueError('Keep game files, keys and build outputs outside the source repository.')
    return path


def verify_extraction(extracted: Path) -> None:
    """Accept only the three original 1.4.1 NSOs used by this port."""
    for name, expected in MODULES.items():
        path = extracted / 'ExeFS' / name
        if not path.is_file() or pad.sha(path.read_bytes()) != expected:
            raise ValueError(f'{name}: this port requires the original Odyssey 1.4.1 module; see docs/INPUTS.md.')
    for group in ('LayoutData', 'LocalizedData'):
        if not (extracted / 'RomFS' / group).is_dir():
            raise ValueError(f'Missing RomFS/{group}')


def prepare_assets(repo: Path, extracted: Path, rewritten: Path, output: Path, preset: str) -> dict:
    """Build and verify a separate camera/HUD/RomFS tree for one display preset."""
    display = resolve(preset)
    extracted = outside_repo(extracted, repo)
    rewritten = outside_repo(rewritten, repo)
    output = outside_repo(output, repo)
    for source in (extracted, rewritten):
        if source == output or output in source.parents:
            raise ValueError('Display output cannot contain an input directory')
    if extracted / 'RomFS' == output or extracted / 'RomFS' in output.parents or rewritten in output.parents:
        raise ValueError('Display output must be separate from RomFS and rewritten inputs')
    verify_extraction(extracted)
    for name, expected in REWRITTEN.items():
        if pad.sha((rewritten / (name + '.patched.bin')).read_bytes()) != expected:
            raise ValueError(f'{name}: rewritten module is stale or differs from the verified port. Omit --rewritten to regenerate it.')
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        if not (output / '.odyssey-display-output').is_file():
            raise ValueError(f'Refusing to replace an unmanaged folder: {output}')
        shutil.rmtree(output)
    stage = Path(tempfile.mkdtemp(prefix=output.name + '.partial-', dir=output.parent))
    try:
        (stage / '.odyssey-display-output').touch()
        overlay = stage / 'overlay'
        # The camera helper also verifies every accepted takeoff observer guard;
        # live 4:3 builds keep the rewritten module and use its copy only for that.
        camera = phone.prepare_camera(rewritten, stage / 'phone-camera', repo / 'dm/host/hle_odyssey_feedback.c',
                                      phone.ASPECT if display.live else display.aspect)
        if display.live:
            receipt = pad.create_overlay(extracted / 'RomFS', overlay, extracted / 'ExeFS/main', stage / 'layout.json')
            patched = rewritten
        else:
            overlay.mkdir()
            archives, records = [], []
            for group in ('LayoutData', 'LocalizedData'):
                for path in sorted((extracted / 'RomFS' / group).rglob('*.szs')):
                    before = path.read_bytes()
                    unpacked = pad.yaz0_decode(before) if before[:4] == b'Yaz0' else before
                    if unpacked[:4] != b'SARC':
                        continue
                    relative = str(path.relative_to(extracted / 'RomFS'))
                    changed = phone.patch_archive(unpacked, relative, records, aspect=display.aspect)
                    if changed == unpacked:
                        continue
                    after = pad.yaz0_literal(changed, before[:16]) if before[:4] == b'Yaz0' else changed
                    if before[:4] == b'Yaz0' and pad.yaz0_decode(after) != changed:
                        raise ValueError('Yaz0 round-trip failed')
                    target = overlay / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(after)
                    archives.append({'relative_path': relative, 'source_sha256': pad.sha(before), 'output_sha256': pad.sha(after)})
            receipt = {'archives': archives, 'layouts': records, 'aspect': display.ratio}
            patched = stage / 'phone-camera'
        # Both correct the map footer; phones also widen the shared footer part.
        expected = 210 if display.live else 211
        if len(receipt['archives']) != expected:
            raise ValueError(f'Expected exactly {expected} corrected layout archives')
        # APFS clones are copy-on-write; fall back to ordinary independent copies.
        romfs = stage / 'RomFS'
        cp = subprocess.run(['cp', '-cR', str(extracted / 'RomFS'), str(romfs)], capture_output=True)
        if cp.returncode:
            if romfs.exists():
                shutil.rmtree(romfs)
            shutil.copytree(extracted / 'RomFS', romfs)
        for archive in receipt['archives']:
            relative = archive['relative_path']
            original = extracted / 'RomFS' / relative
            target = romfs / relative
            shutil.copy2(overlay / relative, target)
            if pad.sha(original.read_bytes()) != archive['source_sha256'] or pad.sha(target.read_bytes()) != archive['output_sha256']:
                raise ValueError(f'Source/output integrity mismatch: {relative}')
        record = {'preset': display.preset, 'model': display.model, 'aspect': display.ratio, 'live_display': display.live,
                  'main_build_id': pad.BUILD_ID, 'modules_sha256': MODULES,
                  'camera': camera, 'layouts': receipt, 'patched': str(patched), 'romfs': str(romfs)}
        # Replace staging prefixes only in our local receipt; original paths stay intact.
        record = json.loads(json.dumps(record).replace(str(stage), str(output)))
        (stage / 'receipt.json').write_text(json.dumps(record, indent=2) + '\n')
        stage.rename(output)
        return {'patched': Path(record['patched']), 'romfs': Path(record['romfs']), 'receipt': output / 'receipt.json'}
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise
