"""iPhone/iPad model presets: live 4:3 builds for narrow screens, widened phone builds."""
import contextlib
from fractions import Fraction
import importlib.util
import io
from pathlib import Path
import struct
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'tests'))
import odyssey_displays as displays
from odyssey import make_profile, parse_args
import prepare_odyssey_phone as phone
from test_phone_layout import layout


class DisplayPresetTests(unittest.TestCase):
    def test_table_holds_only_iphone_and_ipad_models(self):
        table = displays.models()
        self.assertGreater(len(table), 50)
        for display in table.values():
            self.assertRegex(display.model, r'^iP(hone|ad)\b')
            self.assertNotIn('duo', display.preset)
            self.assertGreater(display.width, display.height)

    def test_narrow_models_use_the_live_4_3_build(self):
        # The host installs its live camera/HUD adapter only for a 4:3 profile.
        for display in displays.models().values():
            native = Fraction(display.width, display.height)
            if native < displays.NATIVE:
                self.assertTrue(display.live, display.model)
                self.assertEqual(display.ratio, '4:3')
                self.assertGreaterEqual(native, 1)
            else:
                self.assertTrue(display.wide, display.model)
                self.assertEqual(display.aspect, native)

    def test_duo_names_select_the_upstream_duo_build(self):
        for name in ('duo', 'iphone-duo', 'iPhone Duo'):
            self.assertEqual(displays.resolve(name).preset, 'duo')
            self.assertEqual(parse_args(['--nsp-dir', '/private/game', '--preset', name]).preset, 'duo')
        self.assertTrue(displays.resolve('duo').live)

    def test_tested_devices_match_the_original_presets(self):
        self.assertEqual(displays.resolve('iPad Pro (8th gen 13")').aspect, displays.resolve('ipad').aspect)
        self.assertEqual(displays.resolve('iphone-17-pro-max').aspect, displays.resolve('iphone').aspect)

    def test_models_resolve_by_name_or_preset(self):
        self.assertEqual(displays.resolve('iPhone 16 Pro').preset, 'iphone-16-pro')
        self.assertEqual(displays.resolve('iphone-16-pro').ratio, '437:201')
        self.assertEqual(parse_args(['--nsp-dir', '/private/game', '--preset', 'iPhone 13 mini']).preset, 'iphone-13-mini')
        with self.assertRaises(ValueError):
            displays.resolve('iphone-3g')
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            parse_args(['--nsp-dir', '/private/game', '--preset', 'pixel-9'])

    def test_model_profile_uses_prepared_aspect(self):
        spec = importlib.util.spec_from_file_location('game', ROOT / 'dm/games/game.py')
        game = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(game)
        for preset, aspect in [('ipad-pro-8th-gen-11', '4:3'), ('iphone-duo', '4:3'), ('iphone-13-mini', '13:6')]:
            with tempfile.TemporaryDirectory() as temp:
                profile = game.Game(make_profile(Path(temp), preset, '', True) / '0100000000010000')
                self.assertEqual(profile.get('display_aspect'), aspect)

    def test_default_aspect_keeps_the_tested_phone_bytes(self):
        wide = layout([('All', b'pan1', -600., 296., 30., 40.)])
        self.assertEqual(phone.patch_layout(wide, 'CounterCoin.bflyt', [], [], Fraction(2868, 1320)),
                         phone.patch_layout(wide, 'CounterCoin.bflyt', [], []))

    def test_wide_model_keeps_shapes_and_camera_aspect(self):
        aspect = displays.resolve('iphone-16').aspect
        after = phone.patch_layout(layout([('All', b'pan1', 556., 284., 30., 40.)]), 'CounterLife.bflyt', [], [], aspect)
        sx, tx = struct.unpack_from('<f', after, 20 + 0x44)[0], struct.unpack_from('<f', after, 20 + 0x2c)[0]
        self.assertAlmostEqual(sx * 2556 / 1280, 1179 / 720, places=6)
        self.assertAlmostEqual(640 * sx + tx, 640.0, places=4)
        low, high = struct.unpack('<2I', phone.camera_bytes(aspect))
        bits = ((low >> 5) & 0xffff) | (((high >> 5) & 0xffff) << 16)
        self.assertAlmostEqual(struct.unpack('<f', struct.pack('<I', bits))[0], 2556 / 1179, places=6)
        with self.assertRaises(ValueError):
            phone.wide_scale(Fraction(4, 3))


if __name__ == '__main__':
    unittest.main()
