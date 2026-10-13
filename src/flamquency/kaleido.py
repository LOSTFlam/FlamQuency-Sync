"""«Калейдоскоп» — цветовые вариации темы «Угольки».

Одна тема на все случая скучна. «Калейдоскоп» берёт базу «Угольков» и
поворачивает её цветовой тон, сохраняя структуру: тёмные поверхности,
светлый текст, огненный акцент. Получается семейство тем с одинаковой
читаемостью, но разным характером:

- **fire**      — исходные «Угольки» (акцент #FF6B1A)
- **magma**     — глубже и багровее (оттенок в side красного)
- **sunset**    — теплее, к янтарю
- **inferno**   — максимально горячий, кислотный акцент
- **ash**       — почти монохром, жар еле тлеет

Важно: поверхности остаются тёмными, а текст — светлым. «Калейдоскоп»
играет только с акцентной шкалой, поэтому контраст и доступность не
страдают. Вариация запоминается в конфиге (``ui.kaleido``) и
восстанавливается при следующем запуске TUI.
"""

from __future__ import annotations

import colorsys

# Базовые токены «Угольков» — источник правды для всех вариаций
BASE_SURFACES = {
    "surface": "#1A1210",
    "surface-raised": "#241814",
    "surface-overlay": "#2E1D18",
    "surface-sunken": "#120C0A",
    "surface-glass": "#261A16",
    "text": "#F5E6DC",
    "text-muted": "#A68B7B",
    "text-faint": "#6B534A",
    "text-contrast": "#1A1210",
    "success": "#4CAF50",
    "warning": "#FFC107",
    "error": "#E53935",
}

# Акцентная шкала каждой вариации: ember → deep → accent → glow → warm → hot
ACCENT_SCALES = {
    "fire":    ["#8A2500", "#B33C00", "#FF6B1A", "#FF8A50", "#FFB347", "#FF3D00"],
    "magma":   ["#6B1A00", "#931C00", "#E62E00", "#FF5A3C", "#FF8C42", "#FF1A00"],
    "sunset":  ["#7A3B00", "#A85200", "#FF8C1A", "#FFA657", "#FFC96B", "#FF6E00"],
    "inferno": ["#8C0D4F", "#C2115A", "#FF2D78", "#FF6FA5", "#FFA3C7", "#FF0055"],
    "ash":     ["#2E2A28", "#4A4340", "#9C8F86", "#BCAFA6", "#D8CCC4", "#C0562B"],
}

# Человеческие названия — для CLI и меню TUI
TITLES = {
    "fire": "Угольки — исходное пламя",
    "magma": "Магма — глубокая багровая лава",
    "sunset": "Закат — тёплый янтарь",
    "inferno": "Инферно — кислотный розовый жар",
    "ash": "Пепел — еле тлеющий монохром",
}

DEFAULT = "fire"


def variant_names():
    """Доступные вариации в стабильном порядке."""
    return list(ACCENT_SCALES)


def palette(name):
    """Полная палитра вариации: поверхности + акценты + семантика."""
    if name not in ACCENT_SCALES:
        raise ValueError(f"Неизвестная вариация: {name!r}")
    ember, deep, accent, glow, warm, hot = ACCENT_SCALES[name]
    palette = dict(BASE_SURFACES)
    palette.update({
        "accent-ember": ember,
        "accent-deep": deep,
        "accent": accent,
        "accent-glow": glow,
        "accent-warm": warm,
        "accent-hot": hot,
        # Акцентная семантика следует вариации
        "info": glow,
        "on-accent": "#1A1210",
        "on-primary": "#1A1210",
        "on-error": "#FFFFFF",
        "on-success": "#1A1210",
        "on-hot": "#FFFFFF",
        "on-warm": "#1A1210",
    })
    return palette


def gradient(name):
    """Шкала «угольки → ядро пламени» для прогресс-баров и графиков."""
    return list(ACCENT_SCALES.get(name, ACCENT_SCALES[DEFAULT]))


def _hex_to_hls(hex_color):
    r, g, b = (int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return colorsys.rgb_to_hls(r, g, b)


def _hls_to_hex(h, l, s):
    r, g, b = colorsys.hls_to_rgb(h % 1.0, max(0.0, min(1.0, l)),
                                  max(0.0, min(1.0, s)))
    return "#{:02X}{:02X}{:02X}".format(
        int(round(r * 255)), int(round(g * 255)), int(round(b * 255)))


def rotate(name, degrees):
    """Новая вариация: та же светлота/насыщенность, другой тон.

    Поворот на 180° даёт максимально далёкую, но так же читаемую тему.
    """
    if name not in ACCENT_SCALES:
        raise ValueError(f"Неизвестная вариация: {name!r}")
    shift = degrees / 360.0
    rotated = []
    for hex_color in ACCENT_SCALES[name]:
        h, l, s = _hex_to_hls(hex_color)
        rotated.append(_hls_to_hex(h + shift, l, s))
    return rotated


def random_variant(seed=None):
    """Случайная вариация: тон акцента повёрнут, читаемость сохранена.

    Поверхности остаются тёмными — меняется только акцент, поэтому
    случайная тема не может оказаться нечитаемой.
    """
    import random
    rng = random.Random(seed)
    name = rng.choice(variant_names())
    return name, rotate(name, rng.uniform(20, 340))


def describe():
    """[(имя, заголовок, акцент)] — для меню и CLI."""
    return [(name, TITLES.get(name, name), ACCENT_SCALES[name][2])
            for name in variant_names()]


def set_variant(config, name):
    """Запомнить выбранную вариацию в конфиге."""
    if name not in ACCENT_SCALES:
        raise ValueError(f"Неизвестная вариация: {name!r}")
    ui = config.setdefault("ui", {})
    ui["kaleido"] = name
    return name


def current(config):
    """Активная вариация из конфига (fire по умолчанию)."""
    name = (config.get("ui") or {}).get("kaleido") or DEFAULT
    return name if name in ACCENT_SCALES else DEFAULT
