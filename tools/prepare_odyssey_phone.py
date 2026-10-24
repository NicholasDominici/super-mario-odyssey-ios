#!/usr/bin/env python3
"""Prepare a phone-only Odyssey profile, guarded camera copy, and HUD overlay.

Original game files and the accepted iPad artifacts remain unchanged. This tool
does not build, sign, install, launch, or regenerate shaders.
"""
from __future__ import annotations

import argparse
from fractions import Fraction
import json
import math
from pathlib import Path
import re
import struct

import prepare_odyssey_aspect as common

TITLE = '0100000000010000'
CLOUD = ''  # Callers opt into their own CloudKit container.
ASPECT = Fraction(239, 110)
SCALE_X = Fraction(16, 9) / ASPECT
EDGE_DX = 640 * (1 - float(SCALE_X))
WIPES = frozenset({'WipeCircle', 'WipeMiss', 'WipeSkip', 'WipeResultGrand',
                   'WipeWorldSelect', 'WipeWorldSelectCapture', 'WipeResultMain'})
ROOT_EDGES = {name: (1 if values[2] > 0 else -1, values[1], values[2], values[3])
              for name, values in common.EDGE_ANCHORS.items() if values[2] != 0}
# These measured static panes have different positions in this supplied version
# from the upstream mod's literals. Their own animation channels are checked.
CHILD_EDGES = {'ContinueLoading': {'ParLogo': (-510.0, 270.0)},
               'Menu': {'List': (-590.0, -29.0), 'ParLogo': (-510.0, 270.0)},
               # Drawn under the title menu: its logo must move with Menu's or
               # both copies show side by side.
               'BootLoading': {'ParLogo': (-510.0, 270.0)}}
WIDE_BANDS = {'PlayGuide': {'PicBase': (0.0, -360.0, 1280.0, 280.0)},
              'TalkMessage': {'PicBase': (0.0, -360.0, 1280.0, 280.0)},
              'ContinueLoading': {'PicFooter': (0.0, -360.0, 1280.0, 58.0)}}
# The shared footer part is narrowed by each parent's root. Widen only its bars,
# not its button guides, so every footer reaches both panel edges.
EMBEDDED_BANDS = {'FooterParts': {'PicBaseB': (0.0, 0.0, 1280.0, 58.0),
                                  'PicBaseT': (0.0, 58.0, 1280.0, 4.0)}}
PROGRESS_ANIM_SHA = 'e24fdce215dc90b1963362ce7723ca78b2fba75a4e5a33bdb585d0106d9d9c1b'


def phone_display(path: Path) -> dict:
    """Require actual queried native pixels; do not infer from a device name."""
    data = json.loads(path.read_text())
    if data.get('info', {}).get('outcome') != 'success':
        raise ValueError('display query did not succeed')
    displays = [d for d in data['result']['displays'] if d.get('primary')]
    if len(displays) != 1:
        raise ValueError('expected exactly one primary phone display')
    pixels = sorted(displays[0]['nativeSize'])
    if pixels != [1320, 2868] or displays[0]['pointScale'] != 3:
        raise ValueError(f'unexpected phone display: {pixels}')
    return {'native_portrait': pixels, 'native_landscape': list(reversed(pixels)),
            'point_scale': 3, 'aspect': f'{ASPECT.numerator}:{ASPECT.denominator}',
            'evidence': str(path.resolve()), 'evidence_sha256': common.sha(path.read_bytes())}


def panes(data: bytes, label: str) -> tuple[str, dict[str, tuple[int, bytes]]]:
    """Read structural FLYT pane boundaries, rejecting duplicate pane names."""
    if len(data) < 20 or data[:4] != b'FLYT':
        raise ValueError(f'{label}: invalid FLYT')
    order = common.endian(data)
    pos = struct.unpack_from(order + 'H', data, 6)[0]
    size, count = struct.unpack_from(order + 'IH', data, 12)
    if size != len(data) or pos < 20:
        raise ValueError(f'{label}: invalid FLYT size')
    result = {}
    for _ in range(count):
        if pos + 8 > size:
            raise ValueError(f'{label}: truncated section')
        tag, length = struct.unpack_from(order + '4sI', data, pos)
        if length < 8 or pos + length > size:
            raise ValueError(f'{label}: invalid section length')
        if tag in common.PANE_TAGS:
            if length < 0x54:
                raise ValueError(f'{label}: short pane')
            name = data[pos + 12:pos + 36].split(b'\0', 1)[0].decode()
            if name in result:
                raise ValueError(f'{label}: duplicate pane {name}')
            result[name] = (pos, tag)
        pos += length
    if pos != size or 'RootPane' not in result:
        raise ValueError(f'{label}: missing structural root / trailing bytes')
    return order, result


def wide_scale(aspect: Fraction) -> Fraction:
    """RootPane X multiplier that keeps 16:9 HUD shapes on a wider display."""
    if not aspect > Fraction(16, 9):
        raise ValueError(f'{aspect} is not wider than 16:9')
    return Fraction(16, 9) / aspect


def patch_layout(data: bytes, label: str, records: list, tracks: list, aspect: Fraction = ASPECT) -> bytes:
    """Apply the evidenced wide-aspect rule with static edge and mask fixes."""
    scale_x = wide_scale(aspect)
    edge_dx = 640 * (1 - float(scale_x))
    order, index = panes(data, label)
    name = Path(label).stem
    if name in common.SKIP and name not in EMBEDDED_BANDS:
        records.append({'member': label, 'action': 'preserve_embedded_or_fullframe',
                        'source_sha256': common.sha(data)})
        return data
    output, changes = bytearray(data), []

    def static(pane, channels=None):
        conflicts = [t for t in tracks if t['target'] == pane and
                     (channels is None or (t['kind'] in ('FLPA', 'RLPA') and t['channel'] in channels))]
        if conflicts:
            raise ValueError(f'{label}: {pane} correction conflicts with animation {conflicts}')

    def write(pane, field, relative, expected, after):
        pos, _ = index[pane]
        before = struct.unpack_from(order + 'f', data, pos + relative)[0]
        if before != expected or not math.isfinite(after):
            raise ValueError(f'{label}: {pane}.{field} expected {expected}, found {before}')
        struct.pack_into(order + 'f', output, pos + relative, after)
        changes.append({'pane': pane, 'field': field, 'offset': pos + relative,
                        'before': before, 'after': struct.unpack_from(order + 'f', output, pos + relative)[0]})

    def widen(pane, expected):
        pos, tag = index[pane]
        actual = struct.unpack_from(order + '2f', data, pos + 0x2c) + struct.unpack_from(order + '2f', data, pos + 0x4c)
        if tag != b'pic1' or actual != expected or struct.unpack_from(order + '2f', data, pos + 0x44) != (1.0, 1.0):
            raise ValueError(f'{label}: measured full-width surface {pane} changed')
        static(pane, {8})
        write(pane, 'width', 0x4c, 1280.0, 1280.0 / float(scale_x))

    if name in EMBEDDED_BANDS:
        for pane, expected in EMBEDDED_BANDS[name].items():
            widen(pane, expected)
        records.append({'member': label, 'action': 'phone_embedded_bands', 'source_sha256': common.sha(data),
                        'output_sha256': common.sha(output), 'changes': changes,
                        'animation_tracks_checked': len(tracks)})
        return bytes(output)

    root, _ = index['RootPane']
    root_scale = struct.unpack_from(order + '2f', data, root + 0x44)
    root_size = struct.unpack_from(order + '2f', data, root + 0x4c)
    if root_scale != (1.0, 1.0) or any(not math.isfinite(v) or not 0 < v <= 16384 for v in root_size):
        raise ValueError(f'{label}: unexpected authored root transform/size')
    if (name in ROOT_EDGES or name in WIPES) and root_size != (1280.0, 720.0):
        raise ValueError(f'{label}: unexpected measured edge/wipe canvas')
    static('RootPane', {6, 7})
    if name in WIPES:
        # Upstream SMO-AAR expands a round wipe uniformly until its mask covers
        # the wider panel. Normal root squish would leave its sides uncovered.
        write('RootPane', 'scale_y', 0x48, 1.0, 1 / float(scale_x))
    else:
        write('RootPane', 'scale_x', 0x44, 1.0, float(scale_x))
    if name in ROOT_EDGES:
        side, anchor, x, y = ROOT_EDGES[name]
        ap, _ = index[anchor]
        if struct.unpack_from(order + '2f', data, ap + 0x2c) != (x, y):
            raise ValueError(f'{label}: measured edge anchor changed')
        static('RootPane')
        write('RootPane', 'translation_x', 0x2c, 0.0, side * edge_dx)
    for pane, (x, y) in CHILD_EDGES.get(name, {}).items():
        pos, _ = index[pane]
        if struct.unpack_from(order + '2f', data, pos + 0x2c) != (x, y):
            raise ValueError(f'{label}: measured static pane {pane} changed')
        static(pane, {0})
        # Preserve edge distance in uniform UI pixels, including offscreen
        # authored positions. Animated ListPos remains wholly unchanged.
        write(pane, 'translation_x', 0x2c, x, x + math.copysign(edge_dx / float(scale_x), x))
    if name == 'ContinueLoading':
        # This is an actual horizontally travelling progress icon, not a fixed
        # corner HUD. Its authored range and progress-bar animation are expanded
        # together below, preserving duration and full-panel endpoints.
        for pane, expected_xy in {'HomeIcon': (-690.0, -324.0), 'PicFooterBar': (-640.0, -304.0), 'PicProgressBar': (-640.0, -304.0)}.items():
            pos, _ = index[pane]
            if struct.unpack_from(order + '2f', data, pos + 0x2c) != expected_xy:
                raise ValueError(f'{label}: unexpected loading-progress position')
            if pane != 'HomeIcon':
                static(pane, {0})
            write(pane, 'translation_x', 0x2c, expected_xy[0], expected_xy[0] / float(scale_x))
        static('PicFooterBar', {8})
        write('PicFooterBar', 'width', 0x4c, 1280.0, 1280.0 / float(scale_x))
        if struct.unpack_from(order + 'f', data, index['PicProgressBar'][0] + 0x4c)[0] != 0.0:
            raise ValueError(f'{label}: expected zero-width animated progress bar')
    for pane in sorted(common.FULL_FRAME_PANES.get(name, set()) | common.FULL_FRAME_PARTS.get(name, set())):
        pos, tag = index[pane]
        part = pane in common.FULL_FRAME_PARTS.get(name, set())
        if tag != (b'prt1' if part else b'pic1') or data[pos + 9] != 0:
            raise ValueError(f'{label}: unexpected full-frame pane {pane}')
        if struct.unpack_from(order + '2f', data, pos + 0x2c) != (0.0, 0.0) or struct.unpack_from(order + '3f', data, pos + 0x38) != (0.0, 0.0, 0.0):
            raise ValueError(f'{label}: off-center/rotated full-frame pane {pane}')
        if struct.unpack_from(order + '4f', data, pos + 0x44) != (1.0, 1.0, 1280.0, 720.0):
            raise ValueError(f'{label}: unexpected full-frame surface dimensions')
        static(pane, {6 if part else 8})
        write(pane, 'scale_x' if part else 'width', 0x44 if part else 0x4c,
              1.0 if part else 1280.0, (1.0 if part else 1280.0) / float(scale_x))
    for pane, expected in {**WIDE_BANDS.get(name, {}), **common.SCREEN_FILTERS.get(name, {})}.items():
        widen(pane, expected)
    records.append({'member': label, 'action': 'phone_widescreen', 'source_sha256': common.sha(data),
                    'output_sha256': common.sha(output), 'changes': changes,
                    'animation_tracks_checked': len(tracks)})
    return bytes(output)


def patch_progress_animation(data: bytes, label: str, records: list, aspect: Fraction = ASPECT) -> bytes:
    """Scale measured Hermite position/width values and slopes, keeping time."""
    scale_x = wide_scale(aspect)
    if common.sha(data) != PROGRESS_ANIM_SHA:
        raise ValueError(f'{label}: source progress animation differs from measured file')
    output = bytearray(data)
    order = common.endian(data)
    changes = []
    expected_tracks = {('HomeIcon', 0): 2, ('PicProgressBar', 8): 4}
    seen = set()
    for track in common.animation_tracks(data, label):
        key = (track['target'], track['channel'])
        if track['kind'] != 'FLPA' or key not in expected_tracks:
            raise ValueError(f'{label}: unexpected progress animation track')
        offset = track['offset']
        _, _, curve, _, count, _, key_offset = struct.unpack_from(order + '4BHHI', data, offset)
        if curve != 2 or count != expected_tracks[key] or offset + key_offset + count * 12 > len(data):
            raise ValueError(f'{label}: unexpected Hermite key format')
        keys = []
        for i in range(count):
            pos = offset + key_offset + i * 12
            time, value, slope = struct.unpack_from(order + '3f', data, pos)
            struct.pack_into(order + '2f', output, pos + 4, value / float(scale_x), slope / float(scale_x))
            keys.append({'offset': pos, 'time_unchanged': time, 'value_before': value, 'value_after': value / float(scale_x),
                         'slope_before': slope, 'slope_after': slope / float(scale_x)})
        changes.append({'pane': key[0], 'channel': key[1], 'keys': keys})
        seen.add(key)
    if seen != set(expected_tracks):
        raise ValueError('missing measured loading-progress animation tracks')
    records.append({'member': label, 'action': 'scale_loading_progress_animation', 'source_sha256': common.sha(data),
                    'output_sha256': common.sha(output), 'changes': changes})
    return bytes(output)


def members(data: bytes, label: str) -> list[tuple[str, int, int]]:
    """Validate SARC named ranges once, retaining exact original member packing."""
    if len(data) < 40 or data[:4] != b'SARC' or data[6:8] not in (b'\xff\xfe', b'\xfe\xff'):
        raise ValueError(f'{label}: invalid SARC')
    order = '<' if data[6:8] == b'\xff\xfe' else '>'
    header = struct.unpack_from(order + 'H', data, 4)[0]
    size, start = struct.unpack_from(order + 'II', data, 8)
    if size != len(data) or not 20 <= header < start <= size or data[header:header + 4] != b'SFAT':
        raise ValueError(f'{label}: invalid SARC ranges')
    fat_size, count = struct.unpack_from(order + 'HH', data, header + 4)
    nodes, sfnt = header + fat_size, header + fat_size + 16 * count
    if fat_size != 12 or data[sfnt:sfnt + 4] != b'SFNT' or sfnt + 8 > start or struct.unpack_from(order + 'H', data, sfnt + 4)[0] != 8:
        raise ValueError(f'{label}: invalid SARC table')
    names, result = sfnt + 8, []
    for i in range(count):
        _, attr, lo, hi = struct.unpack_from(order + '4I', data, nodes + i * 16)
        pos = names + (attr & 0xffffff) * 4
        end = data.find(b'\0', pos, start)
        if attr >> 24 != 1 or not 0 <= lo <= hi <= size - start or not names <= pos < end < start:
            raise ValueError(f'{label}: invalid named member')
        result.append((data[pos:end].decode(), start + lo, start + hi))
    ranges = sorted((lo, hi) for _, lo, hi in result)
    if any(hi > next_lo for (_, hi), (next_lo, _) in zip(ranges, ranges[1:])):
        raise ValueError(f'{label}: overlapping members')
    return result


def patch_archive(data: bytes, label: str, records: list, depth=0, aspect: Fraction = ASPECT) -> bytes:
    if depth > 5:
        raise ValueError('archive nesting limit')
    ranges = members(data, label)
    tracks = [t for name, lo, hi in ranges if data[lo:lo + 4] == b'FLAN'
              for t in common.animation_tracks(data[lo:hi], label + '/' + name)]
    output = bytearray(data)
    for name, lo, hi in ranges:
        body, child = data[lo:hi], label + '/' + name
        body = common.patch_menu_member(name, body, child, records)
        if body[:4] == b'SARC':
            body = patch_archive(body, child, records, depth + 1, aspect)
        elif name.endswith('.bflyt'):
            body = patch_layout(body, child, records, tracks, aspect)
        elif name.endswith('ContinueLoading_ProgressBar.bflan'):
            body = patch_progress_animation(body, child, records, aspect)
        elif body[:4] == b'Yaz0':
            raise ValueError(f'{child}: unexpected nested compression')
        if len(body) != hi - lo:
            raise ValueError(f'{child}: member size changed')
        output[lo:hi] = body
    return bytes(output)


def camera_bytes(aspect=ASPECT) -> bytes:
    bits = struct.unpack('<I', struct.pack('<f', float(aspect)))[0]
    return struct.pack('<2I', 0x5280000b | ((bits & 0xffff) << 5), 0x72a0000b | ((bits >> 16) << 5))


def prepare_camera(source: Path, destination: Path, feedback_source: Path, aspect: Fraction = ASPECT) -> dict:
    """Copy the rewritten modules/tables; change only two guarded instructions."""
    kind = 'Phone' if aspect > Fraction(16, 9) else 'Display'
    text = (source / 'main.fixups.tsv').read_text()
    if f'# BUILD_ID\t{common.BUILD_ID}' not in text or '# PATCH_OFF\t0x14c0000' not in text:
        raise ValueError('unexpected rewritten main identity/layout')
    data = (source / 'main.patched.bin').read_bytes()
    checks = {0x73de88: '1f2003d5', 0x96816c: '6b5595524bf5a772',
              0x415660: '200040f93bffff17', 0x41cad0: '200040f983fcff17',
              0x415120: '200040f923feff17', 0x415aa0: '200040f937ffff17', 0x415130: '200040f95bfdff17'}
    words_text = feedback_source.read_text().split('k_wall_context_words[] = {', 1)[1].split('};', 1)[0]
    words = [int(x, 16) for x in re.findall(r'0x[0-9a-f]+', words_text)]
    if len(words) < 20:
        raise ValueError('unexpected wall-jump guard definition')
    checks[0x42d5a0] = struct.pack('<' + 'I' * len(words), *words).hex()
    for address, expected in checks.items():
        if data[address:address + len(bytes.fromhex(expected))].hex() != expected:
            raise ValueError(f'rewritten camera/haptic guard changed at {address:#x}')
    if destination.exists():
        raise FileExistsError(destination)
    destination.mkdir(parents=True)
    for item in sorted(source.iterdir()):
        if item.name not in ('main.patched.bin', 'main.cuts.tsv'):
            (destination / item.name).symlink_to(item.resolve())
    output = bytearray(data)
    output[0x96816c:0x968174] = camera_bytes(aspect)
    (destination / 'main.patched.bin').write_bytes(output)
    cut = (source / 'main.cuts.tsv').read_text().replace('4:3 camera projection', f'{kind} camera projection')
    for i in range(2):
        off = 0x96816c + 4 * i
        cut += f'{off:#x}\t{data[off:off + 4].hex()}\t{output[off:off + 4].hex()}\t{kind}{aspect.numerator}:{aspect.denominator} aspect constructor immediate (SMO-AAR)\n'
    (destination / 'main.cuts.tsv').write_text(cut)
    changed = [i for i, (a, b) in enumerate(zip(data, output)) if a != b]
    if not changed or any(not 0x96816c <= i < 0x968174 for i in changed):
        raise ValueError('unexpected rewritten byte changes')
    return {'source': str(source), 'destination': str(destination), 'source_main_sha256': common.sha(data),
            'output_main_sha256': common.sha(output), 'changed_byte_offsets': [hex(x) for x in changed],
            'camera_original': data[0x96816c:0x968174].hex(), 'camera_replacement': camera_bytes(aspect).hex(),
            'verified_guards': {hex(k): v for k, v in checks.items()},
            'other_modules_and_tables': 'absolute read-only-use symlinks to original rewritten folder'}


def prepare_profile(source: Path, destination: Path) -> dict:
    if destination.exists():
        raise FileExistsError(destination)
    destination.mkdir(parents=True)
    for path in source.iterdir():
        if path.name != 'game.tsv':
            (destination / path.name).symlink_to(path.resolve())
    text = (source / 'game.tsv').read_text()
    text = re.sub(r'^display_aspect\t.*$', 'display_aspect\t239:110', text, flags=re.M)
    text = re.sub(r'^cloud_container\t.*\n?', '', text, flags=re.M)
    text += f'\n# Same CloudKit save container on both devices.\ncloud_container\t{CLOUD}\n'
    if 'display_aspect\t239:110' not in text or 'frame_generation\t2x' not in text:
        raise ValueError('missing phone aspect/frame-generation profile settings')
    (destination / 'game.tsv').write_text(text)
    return {'directory': str(destination), 'DM_GAMES_DIR': str(destination.parent), 'DM_GAMES_FIRST': '1',
            'GAME': TITLE, 'display_aspect': '239:110', 'cloud_container': CLOUD,
            'source_profile_sha256': common.sha((source / 'game.tsv').read_bytes()),
            'phone_profile_sha256': common.sha(text.encode())}


def prepare(args) -> dict:
    display = phone_display(args.display_evidence)
    original = args.main.read_bytes()
    if original[:4] != b'NSO0' or original[0x40:0x50].hex() != common.BUILD_ID or common.sha(original) != common.MAIN_SHA256:
        raise ValueError('not the exact supplied Odyssey1.4.1 main')
    if args.output.exists():
        raise FileExistsError(args.output)
    args.output.mkdir(parents=True)
    overlay = args.output / 'romfs-overlay'
    overlay.mkdir()
    archives, records = [], []
    for group in ('LayoutData', 'LocalizedData'):
        for path in sorted((args.source_romfs / group).rglob('*.szs')):
            before = path.read_bytes()
            unpacked = common.yaz0_decode(before) if before[:4] == b'Yaz0' else before
            if unpacked[:4] != b'SARC':
                continue
            patched = patch_archive(unpacked, str(path.relative_to(args.source_romfs)), records)
            if patched == unpacked:
                continue
            after = common.yaz0_literal(patched, before[:16]) if before[:4] == b'Yaz0' else patched
            if before[:4] == b'Yaz0' and common.yaz0_decode(after) != patched:
                raise ValueError('Yaz0 round-trip failed')
            target = overlay / path.relative_to(args.source_romfs)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(after)
            archives.append({'relative_path': str(path.relative_to(args.source_romfs)), 'source': str(path),
                             'destination': str(target), 'source_sha256': common.sha(before), 'output_sha256': common.sha(after)})
    if len(archives) != 211:
        raise ValueError(f'unexpected changed layout archive count {len(archives)}')
    camera = prepare_camera(args.rewritten, args.output / 'patched', args.feedback_source)
    profile = prepare_profile(args.profile, args.output / 'profiles' / TITLE)
    result = {'game': 'Super Mario Odyssey1.4.1', 'main_build_id': common.BUILD_ID, 'main_sha256': common.MAIN_SHA256,
              'aspect': '239:110', 'render_raster_preserved': [1600, 900], 'root_x_multiplier': float(SCALE_X),
              'display': display, 'camera': camera, 'profile': profile, 'overlay': str(overlay), 'archives': archives,
              'layouts': records, 'source_files_unchanged': all(common.sha(Path(a['source']).read_bytes()) == a['source_sha256'] for a in archives),
              'reference': 'https://github.com/fayaz12g/smo-aar/tree/e8fd670d1faeab3d8c4904177928bcfd14afb42c',
              'device_runtime_verified': False}
    if not result['source_files_unchanged'] or common.sha(args.main.read_bytes()) != common.MAIN_SHA256:
        raise ValueError('source files changed during preparation')
    (args.output / 'receipt.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('source-romfs', 'main', 'rewritten', 'profile', 'feedback-source', 'display-evidence', 'output'):
        p.add_argument('--' + name, type=Path, required=True)
    args = p.parse_args()
    for name, value in vars(args).items():
        setattr(args, name, value.resolve())
    result = prepare(args)
    print(json.dumps({k: v for k, v in result.items() if k not in ('layouts', 'archives')}, indent=2))


if __name__ == '__main__':
    main()
