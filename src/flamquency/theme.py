"""FlamQuency-Sync design system «Угольки» v3 — single source of truth.

Tokens mirror docs/DESIGN.md. Any visual change happens HERE first,
then in DESIGN.md. No hardcoded colors in widgets/CSS — reference the
theme variables registered below.
"""

from textual.theme import Theme

# ── «Угольки» (Ember v3) palette — docs/DESIGN.md §1 ──────────────────
FLAMQUENCY_FIRE = Theme(
    name="flamquency-fire",
    primary="#FF6B1A",          # accent — логотип, активные элементы
    secondary="#FFB347",        # accent-warm — hover, вторичный акцент
    accent="#FF8A50",           # accent-glow — тёплый ореол
    warning="#FFC107",
    error="#E53935",
    success="#4CAF50",
    background="#1A1210",       # surface — тёмный уголь
    surface="#241814",          # surface-raised — панели, rail
    panel="#2E1D18",            # surface-overlay — активные табы, поповеры
    boost="#FF6B1A",            # рамки фокуса
    dark=True,
    variables={
        # Поверхности
        "surface": "#1A1210",
        "surface-raised": "#241814",
        "surface-overlay": "#2E1D18",
        "surface-sunken": "#120C0A",
        "surface-glass": "#261A16",
        # Акценты (огонь)
        "accent": "#FF6B1A",
        "accent-hot": "#FF3D00",
        "accent-warm": "#FFB347",
        "accent-deep": "#B33C00",
        "accent-ember": "#8A2500",
        "accent-glow": "#FF8A50",
        # Текст
        "text": "#F5E6DC",
        "text-muted": "#A68B7B",
        "text-faint": "#6B534A",
        "text-contrast": "#1A1210",
        # Семантика
        "success": "#4CAF50",
        "warning": "#FFC107",
        "error": "#E53935",
        "info": "#FF8A50",
        # Текст на огненном фоне — всегда тёмный (DESIGN.md §1.3)
        "on-accent": "#1A1210",
        "on-primary": "#1A1210",
        "on-error": "#FFFFFF",
        "on-success": "#1A1210",
        "on-hot": "#FFFFFF",
        "on-warm": "#1A1210",
    },
)

# Для обратной совместимости со старым именем
EMBER = FLAMQUENCY_FIRE


def kaleido_theme(variant):
    """Textual-тема для вариации «Калейдоскопа».

    Вариации живут в kaleido.py, но Textual-тема строится здесь — рядом с
    основной, чтобы структура токенов не разъезжалась между файлами.
    Поверхности остаются тёмными: меняется только акцентная шкала.
    """
    from flamquency import kaleido
    scale = kaleido.ACCENT_SCALES.get(variant)
    if scale is None:
        raise ValueError(f"Неизвестная вариация: {variant!r}")
    ember, deep, accent, glow, warm, hot = scale
    base = kaleido.BASE_SURFACES
    return Theme(
        name=f"flamquency-{variant}",
        primary=accent,
        secondary=warm,
        accent=glow,
        warning=base["warning"],
        error=base["error"],
        success=base["success"],
        background=base["surface"],
        surface=base["surface-raised"],
        panel=base["surface-overlay"],
        boost=accent,
        dark=True,
        variables=kaleido.palette(variant),
    )
