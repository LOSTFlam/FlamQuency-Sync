"""FlamQuency-Sync design system «Угольки» — single source of truth.

Tokens mirror docs/DESIGN.md. Any visual change happens HERE first,
then in DESIGN.md. No hardcoded colors in widgets/CSS — reference the
theme variables registered below.
"""
from textual.theme import Theme

# ── «Угольки» (Ember) palette — docs/DESIGN.md §1 ──────────────────
FLAMQUENCY_FIRE = Theme(
    name="flamquency-fire",
    primary="#FF6B1A",          # accent — логотип, активные элементы
    secondary="#FFB347",        # accent-warm — hover, вторичный акцент
    accent="#FF8A50",           # info — тёплый
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
        # Акценты (огонь)
        "accent": "#FF6B1A",
        "accent-hot": "#FF3D00",
        "accent-warm": "#FFB347",
        "accent-deep": "#B33C00",
        # Текст
        "text": "#F5E6DC",
        "text-muted": "#A68B7B",
        "text-faint": "#6B534A",
        # Семантика
        "success": "#4CAF50",
        "warning": "#FFC107",
        "error": "#E53935",
        "info": "#FF8A50",
        # Текст на огненном фоне — всегда тёмный (DESIGN.md §4.3)
        "on-accent": "#1A1210",
        "on-primary": "#1A1210",
        "on-error": "#FFFFFF",
        "on-success": "#1A1210",
    },
)

# Для обратной совместимости со старым именем
EMBER = FLAMQUENCY_FIRE
