#!/usr/bin/env python3
"""Build a private Odyssey IPA from the player's own verified game files."""
from __future__ import annotations

import argparse
import fcntl
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys

from odyssey_assets import TITLE, outside_repo, prepare_assets, verify_extraction
import odyssey_displays

REPO = Path(__file__).resolve().parents[1]


def make_profile(work: Path, preset: str, cloud: str, framegen: bool) -> Path:
    """Create a local profile while preserving the pinned shader metadata."""
    source = REPO / 'dm/games' / TITLE
    target = work / 'profiles' / TITLE
    target.mkdir(parents=True, exist_ok=True)
    for path in source.iterdir():
        if path.name != 'game.tsv' and not (target / path.name).exists():
            (target / path.name).symlink_to(path.resolve())
    text = (source / 'game.tsv').read_text()
    aspect = odyssey_displays.resolve(preset).ratio
    text = re.sub(r'^display_aspect\t.*$', f'display_aspect\t{aspect}', text, flags=re.M)
    text = re.sub(r'^frame_generation\t.*$', 'frame_generation\t' + ('2x' if framegen else 'off'), text, flags=re.M)
    text = re.sub(r'^cloud_container\t.*\n?', '', text, flags=re.M)
    if cloud:
        if not re.fullmatch(r'iCloud\.[A-Za-z0-9][A-Za-z0-9.-]+', cloud):
            raise ValueError('Use your own CloudKit container ID, such as iCloud.com.yourname.odyssey')
        text += f'\ncloud_container\t{cloud}\n'
    (target / 'game.tsv').write_text(text)
    return target.parent


def check_tools() -> None:
    """Report missing build tools before touching multi-gigabyte game inputs."""
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        raise ValueError('An Apple Silicon Mac is required.')
    missing = [name for name in ('xcodebuild', 'xcodegen', 'dotnet', 'spirv-cross', 'zstd') if not shutil.which(name)]
    if missing:
        raise ValueError('Missing tools: ' + ', '.join(missing) + '. See README installation steps.')
    for module in ('lz4.block', 'capstone', 'fontTools'):
        try:
            __import__(module)
        except ImportError as error:
            raise ValueError('Activate .venv and run: python -m pip install -r requirements.txt') from error
    version = subprocess.check_output(['xcodebuild', '-version'], text=True)
    match = re.search(r'Xcode (\d+)', version)
    if not match or int(match[1]) < 27:
        raise ValueError('This fork is built with Xcode 27 or newer. Select it with xcode-select.')


def preset_name(value: str) -> str:
    try:
        return odyssey_displays.resolve(value).preset
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error


class ListPresets(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        print(odyssey_displays.listing())
        parser.exit()


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--list-presets', nargs=0, action=ListPresets, help='print every display preset and iPhone/iPad model, then exit')
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument('--nsp-dir', type=Path, help='folder with base-game NSP or XCI and update 1.4.1 NSP')
    inputs.add_argument('--extracted-dir', type=Path, help='already merged 1.4.1 folder containing ExeFS and RomFS')
    parser.add_argument('--keys', type=Path, help='your prod.keys; required with --nsp-dir')
    parser.add_argument('--preset', type=preset_name, default='ipad',
                        help='ipad/duo=4:3 preparation with live narrow display; iphone=239:110 (17 Pro Max); '
                             'or an iPhone/iPad model such as iphone-16-pro (see --list-presets)')
    parser.add_argument('--bundle-id', default='org.nxnative.odyssey', help='keep the same ID when updating to preserve saves')
    parser.add_argument('--cloud-container', default='', help='opt into your own CloudKit container; see docs/ICLOUD.md')
    parser.add_argument('--frame-generation', choices=('on', 'off'), default='on')
    parser.add_argument('--show-fps', action='store_true')
    parser.add_argument('--output', type=Path, help='private unsigned IPA path, outside this repository')
    parser.add_argument('--shaders', type=Path, help='existing iOS shader cache; required with --extracted-dir unless --prepare-only')
    parser.add_argument('--rewritten', type=Path, help='existing exact-build rewritten modules; otherwise rewrite locally')
    parser.add_argument('--work', type=Path, help='private work directory, outside this repository')
    parser.add_argument('--prepare-only', action='store_true', help='validate/rewrite/HUD preparation only; use --extracted-dir')
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    if not re.fullmatch(r'[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+', args.bundle_id):
        raise ValueError('Invalid bundle ID')
    source = outside_repo(args.nsp_dir or args.extracted_dir, REPO)
    if not source.is_dir():
        raise ValueError(f'No input folder: {source}')
    if args.nsp_dir and not args.keys:
        raise ValueError('--nsp-dir requires --keys /path/to/prod.keys')
    if args.prepare_only and not args.extracted_dir:
        raise ValueError('--prepare-only requires --extracted-dir')
    if args.extracted_dir and not args.shaders and not args.prepare_only:
        raise ValueError('--extracted-dir requires --shaders, or use --nsp-dir to generate shaders automatically')
    work = outside_repo(args.work or source.parent / (source.name + '-odyssey-ios-' + args.preset), REPO)
    output = outside_repo(args.output or work / f'SuperMarioOdyssey-{args.preset}-unsigned.ipa', REPO)
    if args.keys:
        outside_repo(args.keys, REPO)
    work.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    check_tools()
    profiles = make_profile(work, args.preset, args.cloud_container, args.frame_generation == 'on')
    env = dict(os.environ, DM_GAMES_DIR=str(profiles), DM_GAMES_FIRST='1', GAME=TITLE,
               DM_BUNDLE_ID=args.bundle_id, DM_DISPLAY_NAME='Super Mario Odyssey', DM_APP_VERSION='1.4.1',
               DM_SHOW_FPS='1' if args.show_fps else '0', ODYSSEY_PRESET=args.preset, ODYSSEY_CLOUD_CONTAINER=args.cloud_container)
    with (REPO / '.odyssey-build.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError('Another build is using this checkout; wait for it to finish.') from error
        if args.nsp_dir:
            command = [sys.executable, str(REPO / 'scripts/build_ipa_from_nsp.py'), str(source), '-k', str(args.keys.resolve()),
                       '-p', 'v393216', '--bundle-id', args.bundle_id, '--out', str(output)]
            if args.show_fps:
                command.append('--show-fps')
            subprocess.run(command, env=env, check=True)
        else:
            verify_extraction(source)
            rewritten = outside_repo(args.rewritten, REPO) if args.rewritten else work / 'rewritten'
            if not args.rewritten:
                for module in ('main', 'subsdk0', 'sdk'):
                    subprocess.run([sys.executable, str(REPO / 'dm/tools/patch_nso.py'), str(source / 'ExeFS' / module), str(rewritten), module], env=env, check=True)
            prepared = prepare_assets(REPO, source, rewritten, work / 'display', args.preset)
            if args.prepare_only:
                print(f'Verified private assets: {prepared["receipt"]}')
                return 0
            shaders = outside_repo(args.shaders, REPO)
            env.update(W=str(work / 'ipa'), PATCHED=str(prepared['patched']), ROMFS=str(prepared['romfs']),
                       MSL_IOS=str(shaders), FONT_PY=sys.executable, DM_ICON=str(source / 'icon.jpg'))
            subprocess.run(['bash', str(REPO / 'dm/ios/tools/build_ipa.sh'), str(output)], env=env, check=True)
    print(f'Unsigned IPA: {output}\nNext: python tools/sign_install.py --help')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f'Build stopped: {error}', file=sys.stderr)
        raise SystemExit(1)
