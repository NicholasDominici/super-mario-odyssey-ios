"""Title/pause menu without Playing in VR and Action Guide; title logo edge."""
import ast
from pathlib import Path
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'tests'))
import prepare_odyssey_aspect as common
import prepare_odyssey_phone as phone
from test_phone_layout import layout

ODYSSEY = 'b424be150a8e7d78701cbe7a439d9ebf'
VR, HELP, SAVE, OPTIONS = 6, 3, 4, 5


def cuts():
    """Read patch_nso.py's CUTS literal without running the rewriter."""
    tree = ast.parse((ROOT / 'dm/tools/patch_nso.py').read_text())
    node = next(n for n in tree.body if isinstance(n, ast.Assign) and getattr(n.targets[0], 'id', '') == 'CUTS')
    return {offset: (bytes.fromhex(old), bytes.fromhex(new)) for offset, old, new, _ in ast.literal_eval(node.value)[ODYSSEY]}


def table(raw):
    return list(struct.unpack('<6i', raw))


class MenuItemTests(unittest.TestCase):
    def test_cuts_keep_shape_and_drop_vr_and_help(self):
        found = cuts()
        for offset, (old, new) in found.items():
            self.assertEqual(len(old), len(new), hex(offset))
        title_old, title_new = map(table, found[0xec8270])
        pause_old, pause_new = map(table, found[0xec8288])
        self.assertEqual(title_old[:6], [0, 1, 2, VR, HELP, OPTIONS])
        self.assertEqual(title_new[:4], [0, 1, 2, OPTIONS])
        self.assertEqual(pause_old, [0, 1, VR, HELP, SAVE, OPTIONS])
        self.assertEqual(pause_new[:4], [0, 1, SAVE, OPTIONS])
        # Special mode deactivates logical 2/4/5 through the pause table: same parts.
        self.assertEqual({pause_new[i] for i in (2, 4, 5)}, {pause_old[i] for i in (2, 4, 5)})
        # Both item counts become four (mov w1, #6 -> mov w1, #4).
        for offset in (0x49723c, 0x49609c):
            self.assertEqual(found[offset], (bytes.fromhex('e1071f32'), bytes.fromhex('81008052')))

    def test_menu_files_are_hash_guarded(self):
        records = []
        with self.assertRaisesRegex(ValueError, 'menu layout'):
            common.patch_menu_member('blyt/Menu.bflyt', layout(), 'Menu.bflyt', records)
        with self.assertRaisesRegex(ValueError, 'menu animation'):
            common.patch_menu_member('anim/Menu_SelectTitle.bflan', b'FLAN', 'Menu_SelectTitle.bflan', records)
        self.assertEqual(common.patch_menu_member('blyt/MenuGuide.bflyt', b'unchanged', 'x', records), b'unchanged')
        self.assertEqual(records, [])

    def test_boot_logo_follows_the_menu_logo_edge(self):
        # Menu's ParLogo uses the same CHILD_EDGES rule; BootLoading's must match it.
        self.assertEqual(phone.CHILD_EDGES['BootLoading']['ParLogo'], phone.CHILD_EDGES['Menu']['ParLogo'])
        before = layout([('ParLogo', b'prt1', -510., 270., 192., 120.), ('PicFade', b'pic1', 0., 0., 1280., 720.),
                         ('ParBG', b'prt1', 0., 0., 1280., 720.)])
        after = phone.patch_layout(before, 'BootLoading.bflyt', [], [])
        order, index = phone.panes(after, 'BootLoading')
        scale = float(phone.SCALE_X)
        expected = -510. - 640 * (1 - scale) / scale
        self.assertAlmostEqual(struct.unpack_from(order + 'f', after, index['ParLogo'][0] + 0x2c)[0], expected, places=3)
        self.assertEqual(len(before), len(after))


if __name__ == '__main__':
    unittest.main()
