"""Format / build safety checks for Odyssey's corrected 4:3 output."""
import ast
import importlib.util
import json
from pathlib import Path
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import prepare_odyssey_aspect as aspect


def layout(name='RootPane', scale_y=1.0, order='<'):
    pane = bytearray(0x54)
    pane[:4] = b'pan1'
    struct.pack_into(order + 'I', pane, 4, len(pane))
    pane[12:12 + len(name)] = name.encode()
    struct.pack_into(order + '2f', pane, 0x44, 1.0, scale_y)
    header = bytearray(20)
    header[:4] = b'FLYT'
    header[4:6] = b'\xff\xfe' if order == '<' else b'\xfe\xff'
    struct.pack_into(order + 'H', header, 6, 20)
    struct.pack_into(order + 'IH', header, 12, 20 + len(pane), 1)
    return bytes(header + pane)


def with_child(name, x=0.0, y=0.0, width=1280.0, height=720.0, tag=b'pic1'):
    root = bytearray(layout())
    struct.pack_into('<2f', root, 20 + 0x4c, 1280.0, 720.0)
    child = bytearray(layout(name)[20:])
    child[:4] = tag
    struct.pack_into('<2f', child, 0x2c, x, y)
    struct.pack_into('<2f', child, 0x4c, width, height)
    result = root + child
    struct.pack_into('<IH', result, 12, len(result), 2)
    return bytes(result)


def animation(target='RootPane', channel=1):
    key = struct.pack('<3f', 0.0, 0.0, 0.0)
    entry = struct.pack('<4BHHI', 0, channel, 2, 0, 1, 0, 12) + key
    tag = b'FLPA' + bytes([1, 0, 0, 0]) + struct.pack('<I', 12) + entry
    content = target.encode().ljust(28, b'\0') + bytes([1, 0, 0, 0]) + struct.pack('<I', 36) + tag
    pai = b'pai1' + struct.pack('<I', 24 + len(content)) + struct.pack('<HBBHHI', 0, 0, 0, 0, 1, 20) + struct.pack('<I', 24) + content
    return b'FLAN\xff\xfe' + struct.pack('<HIIHH', 20, 0x08020000, 20 + len(pai), 1, 0) + pai


class AspectTests(unittest.TestCase):
    def test_yaz0_roundtrip_and_metadata(self):
        data = bytes(range(256)) * 5 + b'ending'
        header = b'Yaz0' + struct.pack('>III', len(data), 0x2000, 0)
        packed = aspect.yaz0_literal(data, header)
        self.assertEqual(packed[:16], header)
        self.assertEqual(aspect.yaz0_decode(packed), data)

    def test_yaz0_invalid_backreference_rejected(self):
        with self.assertRaises(ValueError):
            aspect.yaz0_decode(b'Yaz0' + struct.pack('>III', 3, 0, 0) + bytes([0, 0x10, 0]))

    def test_root_transform_only_changes_one_float(self):
        for order in ('<', '>'):
            before = layout(order=order)
            records = []
            after = aspect.patch_layout(before, 'layout/Unanchored.bflyt', records)
            self.assertEqual(before[:20 + 0x48], after[:20 + 0x48])
            self.assertEqual(before[20 + 0x4c:], after[20 + 0x4c:])
            self.assertEqual(struct.unpack_from(order + 'f', after, 20 + 0x48)[0], 0.75)
            self.assertEqual(records[0]['action'], 'scale_y')

    def test_full_frame_background_not_scaled(self):
        before = layout()
        self.assertEqual(aspect.patch_layout(before, 'layout/FadeBlack.bflyt', []), before)

    def test_missing_root_and_corrupt_sections_rejected(self):
        with self.assertRaises(ValueError):
            aspect.patch_layout(layout('Impostor'), 'bad.bflyt', [])
        bad = bytearray(layout())
        struct.pack_into('<I', bad, 24, 0x1000)
        with self.assertRaises(ValueError):
            aspect.patch_layout(bytes(bad), 'bad.bflyt', [])

    def test_hud_root_shift_preserves_animated_child_and_sprite_scale(self):
        before = with_child('All', -600.0, 296.0, 30.0, 40.0, b'pan1')
        records = []
        after = aspect.patch_layout(before, 'CounterCoin.bflyt', records)
        self.assertEqual(struct.unpack_from('<f', after, 20 + 0x30)[0], 90.0)
        self.assertEqual(struct.unpack_from('<f', after, 20 + 0x48)[0], 0.75)
        self.assertEqual(after[20 + 0x54:], before[20 + 0x54:])
        self.assertEqual(360.0 * 0.75 + 90.0, 360.0)
        self.assertEqual(-360.0 * 0.75 - 90.0, -360.0)

    def test_regional_coin_counter_follows_the_coin_counter_edge(self):
        for name, x, y in [('CounterCoin', -600.0, 296.0), ('CounterCollectCoin', -475.0, 302.5)]:
            after = aspect.patch_layout(with_child('All', x, y, 30.0, 40.0, b'pan1'), f'{name}.bflyt', [])
            self.assertEqual(struct.unpack_from('<f', after, 20 + 0x30)[0], 90.0)
            self.assertEqual(struct.unpack_from('<f', after, 20 + 0x48)[0], 0.75)

    def test_glasses_filter_keeps_its_authored_framing(self):
        before = bytearray(with_child('PicCaptureUse', height=1000.0))
        second = bytearray(before[20 + 0x54:])
        second[12:12 + 24] = b'PicFilter'.ljust(24, b'\0')
        before += second
        struct.pack_into('<IH', before, 12, len(before), 3)
        after = aspect.patch_layout(bytes(before), 'FilterGlasses.bflyt', [])
        self.assertEqual(struct.unpack_from('<f', after, 20 + 0x48)[0], 0.75)
        for position in (20 + 0x54, 20 + 2 * 0x54):
            height = struct.unpack_from('<f', after, position + 0x50)[0]
            self.assertAlmostEqual(height * 0.75, 1000.0, places=3)
            self.assertEqual(struct.unpack_from('<f', after, position + 0x4c)[0], 1280.0)
        with self.assertRaisesRegex(ValueError, 'PicFilter'):
            aspect.patch_layout(with_child('PicCaptureUse', height=1000.0), 'FilterGlasses.bflyt', [])

    def test_map_footer_keeps_its_shape_on_the_bottom_edge(self):
        before = with_child('ParFooter', 0.0, -360.0, 1280.0, 120.0, b'prt1')
        after = aspect.patch_layout(before, 'MapFooter.bflyt', [])
        self.assertEqual(struct.unpack_from('<f', after, 20 + 0x48)[0], 0.75)
        self.assertEqual(struct.unpack_from('<f', after, 20 + 0x30)[0], -90.0)
        self.assertEqual(after[20 + 0x54:], before[20 + 0x54:])

    def test_wrong_anchor_and_animated_root_are_rejected(self):
        with self.assertRaises(ValueError):
            aspect.patch_layout(with_child('All', -600, 295, 30, 40), 'CounterCoin.bflyt', [])
        before = with_child('All', -600, 296, 30, 40)
        tracks = aspect.animation_tracks(animation(), 'CounterCoin_Appear.bflan')
        self.assertEqual((tracks[0]['target'], tracks[0]['kind'], tracks[0]['channel']), ('RootPane', 'FLPA', 1))
        with self.assertRaises(ValueError):
            aspect.patch_layout(before, 'CounterCoin.bflyt', [], tracks)

    def test_full_frame_mask_height_and_animated_height_guard(self):
        before = with_child('PicBase')
        child_pos = 20 + 0x54
        after = aspect.patch_layout(before, 'TalkMessageOver.bflyt', [])
        self.assertEqual(struct.unpack_from('<f', after, child_pos + 0x50)[0], 960.0)
        self.assertEqual(struct.unpack_from('<2f', after, child_pos + 0x44), (1.0, 1.0))
        self.assertEqual(960.0 * 0.75, 720.0)
        tracks = aspect.animation_tracks(animation('PicBase', 9), 'TalkMessageOver_Appear.bflan')
        with self.assertRaises(ValueError):
            aspect.patch_layout(before, 'TalkMessageOver.bflyt', [], tracks)

    def test_full_frame_background_part_compensates_outer_root(self):
        before = with_child('ParBG', tag=b'prt1')
        after = aspect.patch_layout(before, 'ContinueLoading.bflyt', [])
        scale = struct.unpack_from('<f', after, 20 + 0x54 + 0x48)[0]
        self.assertAlmostEqual(scale * 0.75, 1.0)





if __name__ == '__main__':
    unittest.main()
