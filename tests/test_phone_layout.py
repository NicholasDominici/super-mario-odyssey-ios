"""Camera, aspect, animation, and source-preservation checks for phone staging."""
import importlib.util
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import prepare_odyssey_phone as phone
import prepare_odyssey_aspect as common



def layout(children=()):
    result = bytearray(20)
    result[:6] = b'FLYT\xff\xfe'
    struct.pack_into('<H', result, 6, 20)
    for name, tag, x, y, width, height in [('RootPane', b'pan1', 0., 0., 1280., 720.), *children]:
        pane = bytearray(0x54)
        pane[:4] = tag
        struct.pack_into('<I', pane, 4, len(pane))
        pane[12:12+len(name)] = name.encode()
        struct.pack_into('<2f', pane, 0x2c, x, y)
        struct.pack_into('<4f', pane, 0x44, 1., 1., width, height)
        result.extend(pane)
    struct.pack_into('<IH', result, 12, len(result), len(children) + 1)
    return bytes(result)


def archived_member(path, target):
    data = path.read_bytes()
    if data[:4] == b'Yaz0':
        data = common.yaz0_decode(data)
    def search(body):
        for name, lo, hi in phone.members(body, str(path)):
            member = body[lo:hi]
            if name.endswith(target):
                return member
            if member[:4] == b'SARC':
                found = search(member)
                if found is not None:
                    return found
        return None
    found = search(data)
    if found is None:
        raise AssertionError(target)
    return found


class PhoneAspectTests(unittest.TestCase):

    def test_constructor_immediates_encode_exact_float(self):
        low, high = struct.unpack('<2I', phone.camera_bytes())
        self.assertEqual(low & 0xffe0001f, 0x5280000b)
        self.assertEqual(high & 0xffe0001f, 0x72a0000b)
        bits = ((low >> 5) & 0xffff) | (((high >> 5) & 0xffff) << 16)
        actual = struct.unpack('<f', struct.pack('<I', bits))[0]
        self.assertAlmostEqual(actual, float(phone.ASPECT), places=6)
        self.assertEqual(phone.camera_bytes().hex(), 'ebbe81526b01a872')



    def test_hud_anchor_shape_and_animated_child_preserved(self):
        for name, x, y in [('CounterCoin', -600., 296.), ('CounterCollectCoin', -475., 302.5), ('CounterLife', 556., 284.)]:
            before = layout([('All', b'pan1', x, y, 30., 40.)])
            records = []
            after = phone.patch_layout(before, name+'.bflyt', records, [])
            self.assertEqual(after[20+0x54:], before[20+0x54:])
            sx = struct.unpack_from('<f', after, 20+0x44)[0]
            tx = struct.unpack_from('<f', after, 20+0x2c)[0]
            side = 1 if x > 0 else -1
            self.assertAlmostEqual(side * 640 * sx + tx, side * 640, places=4)
            self.assertAlmostEqual(sx * 2868 / 1280, 1320 / 720, places=6)

    def test_wipes_stay_round_and_fullframe_surfaces_cover_panel(self):
        after = phone.patch_layout(layout(), 'WipeCircle.bflyt', [], [])
        sx, sy = struct.unpack_from('<2f', after, 20+0x44)
        self.assertEqual(sx, 1.)
        self.assertAlmostEqual(sx * 2868 / 1280, sy * 1320 / 720, places=6)
        before = layout([('PicBase', b'pic1', 0., 0., 1280., 720.)])
        after = phone.patch_layout(before, 'TalkMessageOver.bflyt', [], [])
        order, index = phone.panes(after, 'TalkMessageOver')
        width = struct.unpack_from(order + 'f', after, index['PicBase'][0] + 0x4c)[0]
        self.assertAlmostEqual(width * float(phone.SCALE_X), 1280., places=4)

    def test_glasses_filter_covers_the_wider_panel(self):
        surfaces = [(pane, b'pic1', 0., 0., 1280., 1000.) for pane in ('PicCaptureUse', 'PicFilter')]
        after = phone.patch_layout(layout(surfaces), 'FilterGlasses.bflyt', [], [])
        order, index = phone.panes(after, 'FilterGlasses')
        sx = struct.unpack_from(order + 'f', after, index['RootPane'][0] + 0x44)[0]
        for pane in ('PicCaptureUse', 'PicFilter'):
            width, height = struct.unpack_from(order + '2f', after, index[pane][0] + 0x4c)
            self.assertAlmostEqual(width * sx, 1280., places=3)
            self.assertEqual(height, 1000.)
        with self.assertRaisesRegex(ValueError, 'PicFilter'):
            phone.patch_layout(layout([surfaces[0], ('PicFilter', b'pic1', 0., 0., 1280., 720.)]), 'FilterGlasses.bflyt', [], [])

    def test_footer_bars_reach_both_edges_and_map_footer_keeps_its_shape(self):
        bars = [('PicBaseB', b'pic1', 0., 0., 1280., 58.), ('PicBaseT', b'pic1', 0., 58., 1280., 4.),
                ('TxtDevice', b'txt1', -576., 27., 300., 50.)]
        before = layout(bars)
        after = phone.patch_layout(before, 'FooterParts.bflyt', [], [])
        order, index = phone.panes(after, 'FooterParts')
        self.assertEqual(after[20:20 + 0x54], before[20:20 + 0x54])  # the parent narrows the part
        for pane in ('PicBaseB', 'PicBaseT'):
            width = struct.unpack_from(order + 'f', after, index[pane][0] + 0x4c)[0]
            self.assertAlmostEqual(width * float(phone.SCALE_X), 1280., places=3)
        guide = index['TxtDevice'][0]
        self.assertEqual(after[guide:guide + 0x54], before[guide:guide + 0x54])
        footer = phone.patch_layout(layout([('ParFooter', b'prt1', 0., -360., 1280., 120.)]), 'MapFooter.bflyt', [], [])
        self.assertAlmostEqual(struct.unpack_from('<f', footer, 20 + 0x44)[0], float(phone.SCALE_X), places=6)
        self.assertEqual(phone.patch_layout(layout(), 'MapBG.bflyt', [], []), layout())

    def test_animation_conflict_and_format_bounds_rejected(self):
        before = layout([('All',b'pan1',-600.,296.,30.,40.)])
        with self.assertRaisesRegex(ValueError, 'animation'):
            phone.patch_layout(before,'CounterCoin.bflyt',[],[{'target':'RootPane','kind':'FLPA','channel':6}])
        bad = bytearray(before)
        struct.pack_into('<I',bad,24,len(bad)+100)
        with self.assertRaises(ValueError):
            phone.patch_layout(bytes(bad),'CounterCoin.bflyt',[],[])

    def test_sarc_boundaries_and_recursive_patch(self):
        body=layout()
        sarc=(b'SARC'+struct.pack('<H',20)+b'\xff\xfe'+struct.pack('<IIHH',64+len(body),64,0x100,0)
              +b'SFAT'+struct.pack('<HHI',12,1,0x65)+struct.pack('<4I',0,0x01000000,0,len(body))
              +b'SFNT'+struct.pack('<HH',8,0)+b'x.bflyt\0'+body)
        self.assertEqual(phone.members(sarc,'test'),[('x.bflyt',64,len(sarc))])
        records=[]
        patched=phone.patch_archive(sarc,'test',records)
        self.assertEqual(len(patched),len(sarc))
        self.assertAlmostEqual(struct.unpack_from('<f',patched,64+20+0x44)[0],float(phone.SCALE_X),places=7)
        bad=bytearray(sarc);struct.pack_into('<I',bad,44,len(body)+1)
        with self.assertRaises(ValueError):
            phone.patch_archive(bytes(bad),'bad',[])




if __name__ == '__main__':
    unittest.main()
