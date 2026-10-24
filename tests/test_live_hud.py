"""Compile the actual exact-build HUD adapter against synthetic game-free peers."""
from pathlib import Path
import platform
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(platform.system() == 'Darwin', 'Native receiving adapter requires Darwin')
class LiveHudTests(unittest.TestCase):
    def test_actual_guard_transform_and_restore(self):
        with tempfile.TemporaryDirectory(prefix='odyssey-live-hud-') as temporary:
            path = Path(temporary)
            (path / 'game_profile.h').write_text('#pragma once\n#define DM_GAME_DISPLAY_ASPECT (4.0/3.0)\n')
            binary = path / 'hud'
            compile_result = subprocess.run([
                'xcrun', 'clang', '-std=gnu11', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                '-fsanitize=address,undefined,float-divide-by-zero', '-I', str(path),
                '-I', str(ROOT / 'dm/host'), str(ROOT / 'dm/host/tests/t_odyssey_display_hud.c'),
                '-o', str(binary),
            ], capture_output=True, text=True, timeout=60)
            self.assertEqual(compile_result.returncode, 0, compile_result.stdout + compile_result.stderr)
            run_result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
            self.assertEqual(run_result.returncode, 0, run_result.stdout + run_result.stderr)
            self.assertIn('1000 folds', run_result.stdout)

    def test_map_screen_rule_for_phone_and_ipad_profiles(self):
        for name, aspect in [('phone', '2622.0/1206.0'), ('4:3', '4.0/3.0')]:
            with self.subTest(profile=name), tempfile.TemporaryDirectory(prefix='odyssey-map-hud-') as temporary:
                path = Path(temporary)
                (path / 'game_profile.h').write_text(f'#pragma once\n#define DM_GAME_DISPLAY_ASPECT ({aspect})\n')
                binary = path / 'map'
                compile_result = subprocess.run([
                    'xcrun', 'clang', '-std=gnu11', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined,float-divide-by-zero', '-I', str(path),
                    '-I', str(ROOT / 'dm/host'), str(ROOT / 'dm/host/tests/t_odyssey_display_map.c'),
                    '-o', str(binary),
                ], capture_output=True, text=True, timeout=60)
                self.assertEqual(compile_result.returncode, 0, compile_result.stdout + compile_result.stderr)
                run_result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
                self.assertEqual(run_result.returncode, 0, run_result.stdout + run_result.stderr)
                self.assertIn(f'map-screen rule ({name})', run_result.stdout)


if __name__ == '__main__':
    unittest.main()
