#!/usr/bin/env python3
"""Create a 4:3 Odyssey HUD overlay from supplied game files, without editing them.

Paired with nxnative's exact-build camera cut and display_aspect 4:3. Based on
SMO-AAR's documented narrow-aspect RootPane correction (fayaz12g/smo-aar,
script.py), but parses SARC / FLYT boundaries and retains all other bytes.
Yaz0 is re-encoded as literal groups: valid lossless compression with a modest
size cost on this small set of layout archives, requiring no external packer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import struct

BUILD_ID = 'b424be150a8e7d78701cbe7a439d9ebf'
MAIN_SHA256 = '47ac74a66234bc1eb717b18e01fe7c880d2dd50cf1115fd046f5e5878be5f85f'
SCALE_Y = 0.75
SKIP = frozenset({'FooterParts', 'MapBG', 'FadeBlack', 'FadeWhite', 'CommonBgParts'})
PANE_TAGS = frozenset({b'pan1', b'pic1', b'txt1', b'wnd1', b'bnd1', b'prt1'})
# BFLYT coordinates are centered, with positive Y upwards. Keeping RootPane's
# Y scale at .75 preserves shapes, but the original +/-360 screen edges then
# land at +/-270. A static root translation of +/-90 restores edge padding,
# without changing the animated All pane or any sprite / text scale.
# Each row carries one exact anchor coordinate measured from the supplied game.
EDGE_ANCHORS = {
    'CounterCoin': (90.0, 'All', -600.0, 296.0),
    # The regional coin counter is its own layout beside CounterCoin; it must
    # follow the same top-left edge or the gap between them changes.
    'CounterCollectCoin': (90.0, 'All', -475.0, 302.5),
    'CounterLife': (90.0, 'All', 556.0, 284.0),
    'CounterLifeKids': (90.0, 'All', 556.0, 284.0),
    'CounterLifeUp': (90.0, 'All', 556.0, 284.0),
    'CounterShine': (90.0, 'All', -596.0, 266.0),
    'MapMini': (90.0, 'All', 556.0, 157.0),
    'PlayGuideMenu': (90.0, 'PicCaptureUse', 556.0, 220.0),
    'PlayGuideCamera': (90.0, 'All', 546.0, 94.0),
    'PlayGuideSkip': (90.0, 'PicCaptureUse', 382.0, 312.0),
    'SaveMessage': (-90.0, 'All', -600.0, -320.0),
    'KidsMode': (-90.0, 'All', 598.0, -334.0),
    'PlayGuide': (-90.0, 'PicBase', 0.0, -360.0),
    'PlayGuideMap': (-90.0, 'TxtGuide', -586.0, -316.0),
    'PlayGuideBgm': (-90.0, 'PicSh', 0.0, -324.0),
    'TalkMessage': (-90.0, 'PicBase', 0.0, -360.0),
    # Map screen footer: its embedded FooterParts sits on the bottom edge. Left
    # at 16:9 it stretched the button guides on every non-16:9 display.
    'MapFooter': (-90.0, 'ParFooter', 0.0, -360.0),
}
# Explicit full-frame background / live-capture surfaces. Image artwork and
# reference photographs are deliberately absent: their proportions must remain.
# All these entries are required to be centered pic1 panes, 1280x720, scale1.
FULL_FRAME_PANES = {
    'BootLoading': {'PicFade'},
    'ClosetHead': {'PicBG'},
    'Menu': {'PicCaptureUse', 'PicBG00', 'PicBG01'},
    'MiniGameMenu': {'PicCaptureUse', 'PicBG00', 'PicBG01'},
    'MiniGameRaceResult': {'PicCaptureUse'},
    'ModeSelect': {'PicFade'},
    'RankList': {'PicBase'},
    'ShopBG': {'PicCaptureUse', 'PicBG00', 'PicBG01'},
    'TalkMessageOver': {'PicBase'},
    'WindowConfirm': {'PicCaptureUse'},
    'WindowConfirmData': {'PicCaptureUse'},
    'WindowConfirmLanguage': {'PicCaptureUse'},
    'WindowConfirmWait': {'PicCaptureUse'},
    'WindowConfirmWaitBlack': {'PicBG'},
    'WindowInfo': {'PicCaptureUse'},
    **{name: {'PicCaptureUse00', 'PicCaptureUse01', 'PicBG00', 'PicBG01'}
       for name in ('OptionConfig', 'OptionData', 'OptionLanguage', 'OptionMode', 'OptionProcess', 'OptionSelect')},
}
# These parts embed CommonBgParts, whose own root is already a full-frame
# exception. Compensate the parent's .75 once, rather than changing the image.
FULL_FRAME_PARTS = {'BootLoading': {'ParBG'}, 'ContinueLoading': {'ParBG'}, 'Menu': {'ParBG'}}
# Full-screen filters drawn over the picture (Moe-Eye glasses): centered 1000-tall
# surfaces that overscan the 720 panel. Each preparation compensates the axis its
# root narrows (height here, width on phones), so every display keeps the authored
# framing instead of a squashed or narrowed filter.
SCREEN_FILTERS = {'FilterGlasses': {'PicCaptureUse': (0.0, 0.0, 1280.0, 1000.0),
                                    'PicFilter': (0.0, 0.0, 1280.0, 1000.0)}}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def yaz0_decode(data: bytes) -> bytes:
    """Decode a bounded Yaz0 stream, rejecting invalid references / truncation."""
    if len(data) < 16 or data[:4] != b'Yaz0':
        raise ValueError('not a Yaz0 stream')
    size = struct.unpack_from('>I', data, 4)[0]
    if size > 256 * 1024 * 1024:
        raise ValueError('unexpectedly large layout archive')
    out = bytearray()
    pos = 16
    while len(out) < size:
        control = data[pos]
        pos += 1
        for bit in range(7, -1, -1):
            if control & (1 << bit):
                out.append(data[pos])
                pos += 1
            else:
                a, b = data[pos:pos + 2]
                pos += 2
                distance, length = ((a & 15) << 8 | b) + 1, a >> 4
                if length:
                    length += 2
                else:
                    length = data[pos] + 0x12
                    pos += 1
                if distance > len(out) or len(out) + length > size:
                    raise ValueError('invalid Yaz0 back-reference')
                start = len(out) - distance
                if distance >= length:
                    out += out[start:start + length]
                else:
                    out += (out[start:] * (length // distance + 1))[:length]
            if len(out) == size:
                return bytes(out)
    return bytes(out)


def yaz0_literal(data: bytes, header: bytes) -> bytes:
    """Emit valid literal-only Yaz0 groups, retaining alignment/header metadata."""
    if len(header) != 16 or header[:4] != b'Yaz0':
        raise ValueError('invalid source Yaz0 header')
    out = bytearray(header)
    struct.pack_into('>I', out, 4, len(data))
    for pos in range(0, len(data), 8):
        out.append(0xff)
        out += data[pos:pos + 8]
    return bytes(out)


def endian(data: bytes) -> str:
    if data[4:6] == b'\xff\xfe':
        return '<'
    if data[4:6] == b'\xfe\xff':
        return '>'
    raise ValueError('invalid layout BOM')


def animation_tracks(data: bytes, label: str) -> list[dict]:
    """Read named FLAN animation channels so static corrections cannot be reset."""
    if len(data) < 20 or data[:4] != b'FLAN':
        raise ValueError(f'{label}: invalid FLAN header')
    order = endian(data)
    pos = struct.unpack_from(order + 'H', data, 6)[0]
    size, count = struct.unpack_from(order + 'IH', data, 12)
    if size != len(data):
        raise ValueError(f'{label}: inconsistent FLAN size')
    tracks = []
    for _ in range(count):
        if pos + 8 > size:
            raise ValueError(f'{label}: truncated FLAN section')
        tag, length = struct.unpack_from(order + '4sI', data, pos)
        end = pos + length
        if length < 8 or end > size:
            raise ValueError(f'{label}: invalid FLAN section')
        if tag == b'pai1':
            if length < 20:
                raise ValueError(f'{label}: short animation section')
            contents = struct.unpack_from(order + 'H', data, pos + 14)[0]
            table = pos + struct.unpack_from(order + 'I', data, pos + 16)[0]
            if table < pos + 20 or table + contents * 4 > end:
                raise ValueError(f'{label}: invalid animation target table')
            for i in range(contents):
                content = pos + struct.unpack_from(order + 'I', data, table + 4 * i)[0]
                if not pos + 20 <= content <= end - 32:
                    raise ValueError(f'{label}: invalid animation target')
                target = data[content:content + 28].split(b'\0', 1)[0].decode('utf-8')
                tags = data[content + 28]
                if content + 32 + tags * 4 > end:
                    raise ValueError(f'{label}: invalid target tag table')
                for j in range(tags):
                    animation = content + struct.unpack_from(order + 'I', data, content + 32 + j * 4)[0]
                    if not content + 32 <= animation <= end - 8:
                        raise ValueError(f'{label}: invalid target tag')
                    kind = data[animation:animation + 4].decode('ascii')
                    entries = data[animation + 4]
                    if animation + 8 + entries * 4 > end:
                        raise ValueError(f'{label}: invalid track table')
                    for k in range(entries):
                        entry = animation + struct.unpack_from(order + 'I', data, animation + 8 + k * 4)[0]
                        if not animation + 8 <= entry <= end - 12:
                            raise ValueError(f'{label}: invalid animation channel')
                        tracks.append({'file': label, 'target': target, 'kind': kind,
                                       'channel': data[entry + 1], 'offset': entry})
        pos = end
    if pos != size:
        raise ValueError(f'{label}: trailing FLAN bytes')
    return tracks


def patch_layout(data: bytes, label: str, records: list[dict], tracks: list[dict] | None = None) -> bytes:
    """Scale the RootPane's vertical transform, leaving all sections intact."""
    if len(data) < 20 or data[:4] != b'FLYT':
        raise ValueError(f'{label}: invalid FLYT header')
    order = endian(data)
    header_size = struct.unpack_from(order + 'H', data, 6)[0]
    file_size, section_count = struct.unpack_from(order + 'IH', data, 12)
    if file_size != len(data) or header_size < 20:
        raise ValueError(f'{label}: inconsistent FLYT file size')
    pos = header_size
    found = []
    panes = {}
    for _ in range(section_count):
        if pos + 8 > len(data):
            raise ValueError(f'{label}: truncated FLYT section')
        tag, section_size = struct.unpack_from(order + '4sI', data, pos)
        if section_size < 8 or pos + section_size > len(data):
            raise ValueError(f'{label}: invalid FLYT section length')
        if tag in PANE_TAGS and section_size >= 0x54:
            name = data[pos + 0xc:pos + 0x24].split(b'\0', 1)[0]
            panes.setdefault(name.decode('utf-8'), []).append((pos, tag))
            if name == b'RootPane':
                found.append(pos)
        pos += section_size
    if pos != len(data) or len(found) != 1:
        raise ValueError(f'{label}: expected exactly one structural RootPane; found {len(found)}')
    root = found[0]
    offset = root + 0x48
    before = struct.unpack_from(order + 'f', data, offset)[0]
    if not math.isfinite(before) or before <= 0 or before > 10:
        raise ValueError(f'{label}: invalid RootPane Y scale {before}')
    layout_name = Path(label).stem
    if layout_name in SKIP:
        records.append({'member': label, 'action': 'preserve_full_frame', 'offset': offset, 'scale_y': before})
        return data
    after = before * SCALE_Y
    output = bytearray(data)
    struct.pack_into(order + 'f', output, offset, after)
    changes = [{'pane': 'RootPane', 'field': 'scale_y', 'offset': offset, 'before': before, 'after': after}]
    tracks = tracks or []

    def pane(name):
        matches = panes.get(name, [])
        if len(matches) != 1:
            raise ValueError(f'{label}: expected exactly one {name} pane, found {len(matches)}')
        return matches[0]

    def static(name, channels):
        matches = [t for t in tracks if t['target'] == name and
                   (channels is None or (t['kind'] in ('FLPA', 'RLPA') and t['channel'] in channels))]
        if matches:
            raise ValueError(f'{label}: correction conflicts with animated fields: {matches}')

    def write_float(name, field, position, expected, replacement):
        original = struct.unpack_from(order + 'f', data, position)[0]
        if original != expected:
            raise ValueError(f'{label}: {name}.{field} expected {expected}, found {original}')
        struct.pack_into(order + 'f', output, position, replacement)
        changes.append({'pane': name, 'field': field, 'offset': position, 'before': original, 'after': replacement})

    if layout_name in EDGE_ANCHORS:
        dy, anchor, expected_x, expected_y = EDGE_ANCHORS[layout_name]
        anchor_pos, _ = pane(anchor)
        actual_xy = struct.unpack_from(order + '2f', data, anchor_pos + 0x2c)
        if actual_xy != (expected_x, expected_y):
            raise ValueError(f'{label}: unexpected {anchor} anchor {actual_xy}')
        # No RootPane animation of any kind is allowed for these edge layouts.
        static('RootPane', None)
        if struct.unpack_from(order + '2f', data, root + 0x4c) != (1280.0, 720.0):
            raise ValueError(f'{label}: expected the measured 1280x720 root')
        write_float('RootPane', 'translation_y', root + 0x30, 0.0, dy)

    for name in sorted(FULL_FRAME_PANES.get(layout_name, set()) | FULL_FRAME_PARTS.get(layout_name, set())):
        position, tag = pane(name)
        part = name in FULL_FRAME_PARTS.get(layout_name, ())
        if tag != (b'prt1' if part else b'pic1'):
            raise ValueError(f'{label}: wrong full-frame pane type for {name}')
        if struct.unpack_from(order + '2f', data, position + 0x2c) != (0.0, 0.0):
            raise ValueError(f'{label}: {name} is not centered')
        if struct.unpack_from(order + '4f', data, position + 0x44) != (1.0, 1.0, 1280.0, 720.0):
            raise ValueError(f'{label}: {name} is not the measured unit-scale 1280x720 surface')
        # Full-frame surfaces must have no rotated geometry or off-center pivot.
        if struct.unpack_from(order + '3f', data, position + 0x38) != (0.0, 0.0, 0.0) or data[position + 9] != 0:
            raise ValueError(f'{label}: {name} has an unexpected orientation')
        if part:
            static(name, {7})
            write_float(name, 'scale_y', position + 0x48, 1.0, 1.0 / SCALE_Y)
        else:
            static(name, {9})
            write_float(name, 'height', position + 0x50, 720.0, 720.0 / SCALE_Y)
    for name, expected in SCREEN_FILTERS.get(layout_name, {}).items():
        position, tag = pane(name)
        actual = struct.unpack_from(order + '2f', data, position + 0x2c) + struct.unpack_from(order + '2f', data, position + 0x4c)
        if tag != b'pic1' or actual != expected or struct.unpack_from(order + '2f', data, position + 0x44) != (1.0, 1.0):
            raise ValueError(f'{label}: measured screen filter {name} changed')
        if struct.unpack_from(order + '3f', data, position + 0x38) != (0.0, 0.0, 0.0) or data[position + 9] != 0:
            raise ValueError(f'{label}: {name} has an unexpected orientation')
        static(name, {9})
        write_float(name, 'height', position + 0x50, expected[3], expected[3] / SCALE_Y)
    records.append({'member': label, 'action': 'scale_y', 'offset': offset,
                    'before': before, 'after': after, 'source_sha256': sha(data),
                    'output_sha256': sha(output), 'changes': changes,
                    'animation_tracks_checked': len(tracks)})
    return bytes(output)


def patch_sarc(data: bytes, label: str, records: list[dict], depth: int = 0) -> bytes:
    """Walk exact SARC member ranges recursively; no archive repacking needed."""
    if depth > 5 or len(data) < 40 or data[:4] != b'SARC':
        raise ValueError(f'{label}: invalid / overly nested SARC')
    # SARC stores its BOM at +6, unlike FLYT's +4.
    bom = data[6:8]
    if bom not in (b'\xff\xfe', b'\xfe\xff'):
        raise ValueError(f'{label}: invalid SARC BOM')
    order = '<' if bom == b'\xff\xfe' else '>'
    header_size = struct.unpack_from(order + 'H', data, 4)[0]
    file_size, data_offset = struct.unpack_from(order + 'II', data, 8)
    if file_size != len(data) or not 20 <= header_size < data_offset <= len(data):
        raise ValueError(f'{label}: inconsistent SARC header')
    if data[header_size:header_size + 4] != b'SFAT':
        raise ValueError(f'{label}: missing SFAT')
    sfat_size, count = struct.unpack_from(order + 'HH', data, header_size + 4)
    if sfat_size != 12:
        raise ValueError(f'{label}: unsupported SFAT length')
    nodes = header_size + sfat_size
    sfnt = nodes + 16 * count
    if data[sfnt:sfnt + 4] != b'SFNT' or sfnt + 8 > data_offset:
        raise ValueError(f'{label}: missing SFNT')
    sfnt_size = struct.unpack_from(order + 'H', data, sfnt + 4)[0]
    if sfnt_size != 8:
        raise ValueError(f'{label}: unsupported SFNT length')
    names = sfnt + sfnt_size
    output = bytearray(data)
    ranges = []
    # All animation members are inspected before touching a layout member,
    # independent of the archive's hash-sorted member order.
    tracks = []
    for i in range(count):
        _, attr, start, end = struct.unpack_from(order + 'IIII', data, nodes + 16 * i)
        body = data[data_offset + start:data_offset + end]
        if body[:4] == b'FLAN':
            name_pos = names + (attr & 0xffffff) * 4
            name_end = data.find(b'\0', name_pos, data_offset)
            if not names <= name_pos < name_end < data_offset:
                raise ValueError(f'{label}: invalid animation member name')
            tracks.extend(animation_tracks(body, label + '/' + data[name_pos:name_end].decode('utf-8')))
    for i in range(count):
        _, attr, start, end = struct.unpack_from(order + 'IIII', data, nodes + 16 * i)
        if attr >> 24 != 1 or not 0 <= start <= end <= len(data) - data_offset:
            raise ValueError(f'{label}: invalid named SARC member')
        name_pos = names + (attr & 0xffffff) * 4
        if not names <= name_pos < data_offset:
            raise ValueError(f'{label}: name outside SARC string table')
        name_end = data.find(b'\0', name_pos, data_offset)
        if name_end < 0:
            raise ValueError(f'{label}: unterminated SARC member name')
        name = data[name_pos:name_end].decode('utf-8')
        lo, hi = data_offset + start, data_offset + end
        ranges.append((lo, hi))
        body = data[lo:hi]
        child = label + '/' + name
        if name.endswith('.bflyt'):
            body = patch_layout(body, child, records, tracks)
        elif body[:4] == b'SARC':
            body = patch_sarc(body, child, records, depth + 1)
        elif body[:4] == b'Yaz0':
            raise ValueError(f'{child}: unexpected nested compression; needs explicit repacking')
        if len(body) != hi - lo:
            raise ValueError(f'{child}: layout patch unexpectedly changed member length')
        output[lo:hi] = body
    for (lo, hi), (next_lo, _) in zip(sorted(ranges), sorted(ranges)[1:]):
        if hi > next_lo:
            raise ValueError(f'{label}: overlapping SARC members')
    return bytes(output)


def create_overlay(source: Path, output: Path, main: Path, manifest: Path) -> dict:
    """Validate the exact NSO and write only changed layout archive copies."""
    main_data = main.read_bytes()
    if main_data[:4] != b'NSO0' or main_data[0x40:0x50].hex() != BUILD_ID or sha(main_data) != MAIN_SHA256:
        raise ValueError('source main is not the verified Odyssey 1.4.1 NSO')
    if not (source / 'LayoutData').is_dir() or not (source / 'LocalizedData').is_dir():
        raise ValueError('RomFS does not have expected layout directories')
    if output.exists() or manifest.exists():
        raise FileExistsError('refusing to replace an existing overlay or manifest')
    output.mkdir(parents=True)
    archives, records = [], []
    candidates = sorted(p for group in ('LayoutData', 'LocalizedData') for p in (source / group).rglob('*.szs'))
    for path in candidates:
        before = path.read_bytes()
        if before[:4] == b'Yaz0':
            unpacked = yaz0_decode(before)
        else:
            unpacked = before
        if unpacked[:4] != b'SARC':
            continue
        count = len(records)
        patched = patch_sarc(unpacked, str(path.relative_to(source)), records)
        if patched == unpacked:
            continue
        after = yaz0_literal(patched, before[:16]) if before[:4] == b'Yaz0' else patched
        if before[:4] == b'Yaz0' and yaz0_decode(after) != patched:
            raise ValueError(f'{path}: Yaz0 round-trip failed')
        destination = output / path.relative_to(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(after)
        archives.append({'relative_path': str(path.relative_to(source)), 'source': str(path), 'destination': str(destination),
                         'source_sha256': sha(before), 'output_sha256': sha(after),
                         'source_bytes': len(before), 'output_bytes': len(after),
                         'layout_records': len(records) - count})
    changed = sum(r['action'] == 'scale_y' for r in records)
    if changed < 100:
        raise ValueError(f'only {changed} layouts changed; refusing incomplete Odyssey overlay')
    result = {'game': 'Super Mario Odyssey 1.4.1', 'main_build_id': BUILD_ID,
              'main_sha256': MAIN_SHA256, 'aspect': '4:3', 'root_y_multiplier': SCALE_Y, 'overlay_revision': 4,
              'source_romfs': str(source), 'output_overlay': str(output),
              'camera_cut': {'offset': '0x73de88', 'expected': '1aa90894', 'replacement': '1f2003d5'},
              'reference': 'https://github.com/fayaz12g/smo-aar',
              'source_archives_unchanged': all(sha(Path(a['source']).read_bytes()) == a['source_sha256'] for a in archives),
              'changed_archives': len(archives), 'changed_layouts': changed,
              'preserved_full_frame_layouts': sum(r['action'] != 'scale_y' for r in records),
              'edge_anchored_layouts': sum(any(c['field'] == 'translation_y' for c in r.get('changes', [])) for r in records),
              'full_frame_surfaces': sum(c['pane'] != 'RootPane' for r in records for c in r.get('changes', [])),
              'archives': archives, 'layouts': records}
    if not result['source_archives_unchanged']:
        raise ValueError('source archive changed during overlay preparation')
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(result, indent=2) + '\n')
    return result


def main_cli() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-romfs', type=Path, required=True)
    parser.add_argument('--main', type=Path, required=True)
    parser.add_argument('--output-overlay', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    args = parser.parse_args()
    result = create_overlay(args.source_romfs.resolve(), args.output_overlay.resolve(), args.main.resolve(), args.manifest.resolve())
    print(json.dumps({k: v for k, v in result.items() if k not in ('archives', 'layouts')}, indent=2))


if __name__ == '__main__':
    main_cli()
