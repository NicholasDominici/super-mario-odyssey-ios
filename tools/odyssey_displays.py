"""Resolve a display preset or iPhone/iPad model to the aspect its build prepares."""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
import re

TABLE = Path(__file__).with_name('ios_displays.tsv')
NATIVE = Fraction(16, 9)
# Only a 4:3 profile installs the exact-build live camera/HUD adapter, which then
# follows the real landscape scene from 1:1 through 16:9 (dm/host/hle_odyssey_display.c).
LIVE = Fraction(4, 3)


@dataclass(frozen=True)
class Display:
    preset: str
    model: str
    width: int   # native landscape pixels; 0 when the layout follows the scene live
    height: int
    aspect: Fraction  # prepared camera/HUD/profile aspect

    @property
    def ratio(self) -> str:
        return f'{self.aspect.numerator}:{self.aspect.denominator}'

    @property
    def wide(self) -> bool:
        """Wider than the game's 16:9 canvas: a static widened HUD preparation."""
        return self.aspect > NATIVE

    @property
    def live(self) -> bool:
        return self.aspect == LIVE


ALIASES = {
    'ipad': Display('ipad', 'tested 4:3 iPad layout (iPad Pro 13-inch M5), live 1:1-16:9', 2752, 2064, LIVE),
    'duo': Display('duo', 'iPhone Duo, live fold/unfold layouts 1:1-16:9', 0, 0, LIVE),
    'iphone': Display('iphone', 'tested 239:110 iPhone layout (iPhone 17 Pro Max)', 2868, 1320, Fraction(239, 110)),
}
# The Duo folds between screens, so its model name selects the live duo build.
ALIASES['iphone-duo'] = ALIASES['duo']


def slug(name: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')


def models(table: Path = TABLE) -> dict[str, Display]:
    """Load the model table: narrow screens use the live 4:3 build, wide ones their own aspect."""
    result = {}
    for line in table.read_text().splitlines():
        if not line.strip() or line.startswith('#'):
            continue
        model, width, height, _diagonal, _release = line.split('\t')
        short, long = sorted((int(width), int(height)))
        native = Fraction(long, short)
        preset = slug(model)
        if preset in result or preset in ALIASES:
            raise ValueError(f'{table.name}: duplicate preset {preset}')
        # Exactly 16:9 needs no correction; dm/games/game.py accepts up to 4:1.
        if native == NATIVE or native > 4:
            raise ValueError(f'{table.name}: {model} {native} cannot use a corrected layout')
        result[preset] = Display(preset, model, long, short, native if native > NATIVE else LIVE)
    return result


def resolve(name: str) -> Display:
    """Accept ipad, duo, iphone, a preset name, or the model name as listed."""
    key = slug(name)
    if key in ALIASES:
        return ALIASES[key]
    table = models()
    if key not in table:
        raise ValueError(f'Unknown display preset {name!r}; run tools/odyssey.py --list-presets')
    return table[key]


def listing() -> str:
    rows = [(name, d) for name, d in ALIASES.items()] + [(d.preset, d) for d in models().values()]
    width = max(len(name) for name, _ in rows)
    lines = [f'{"preset":<{width}}  {"build":>12}  {"screen":>9}  model']
    for name, d in rows:
        screen = f'{d.width}x{d.height}' if d.width else 'any'
        build = '4:3 + live' if d.live else d.ratio
        lines.append(f'{name:<{width}}  {build:>12}  {screen:>9}  {d.model}')
    return ('\n'.join(lines) + '\n\n"4:3 + live" builds fit the real screen at runtime (1:1 through 16:9).'
            f'\nModel resolutions from {TABLE.name} (source: https://www.ios-resolution.com).')
