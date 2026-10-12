"""FlamQuency-Sync — единый слой оформления CLI на rich.

CLI и TUI наследуют ОДНУ палитру (docs/DESIGN.md). Здесь — rich-примитивы,
которые повторяют визуальный язык TUI:
- Панели с двойными рамками (имитация свечения accent-deep)
- Заголовки с Nerd Font иконками (icons.py)
- Прогресс-бары в огненных градиентах
- Прозрачные «стеклянные» блоки (surface-raised на background)
- Тени: имитация через панели с акцентной рамкой + отступ

Никаких хардкод-цветов — всё через tokens(), которые дублируют
theme.py и DESIGN.md §1.
"""

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.theme import Theme as RichTheme
from rich.progress import (
    Progress, BarColumn, TextColumn, SpinnerColumn,
    TimeRemainingColumn, TaskProgressColumn,
)
from rich import box

from flamquency.icons import icon

_CONSOLE_CACHE = None


# ── Палитра «Угольки» v3 — зеркало theme.py / DESIGN.md §1 ──
PALETTE = {
    "surface":         "#1A1210",
    "surface-raised":  "#241814",
    "surface-overlay": "#2E1D18",
    "surface-sunken":  "#120C0A",
    "surface-glass":   "#261A16",
    "accent":          "#FF6B1A",
    "accent-hot":      "#FF3D00",
    "accent-warm":     "#FFB347",
    "accent-deep":     "#B33C00",
    "accent-ember":    "#8A2500",
    "accent-glow":     "#FF8A50",
    "text":            "#F5E6DC",
    "text-muted":      "#A68B7B",
    "text-faint":      "#6B534A",
    "text-contrast":   "#1A1210",
    "success":         "#4CAF50",
    "warning":         "#FFC107",
    "error":           "#E53935",
    "info":            "#FF8A50",
    "on-accent":       "#1A1210",
    "on-hot":          "#FFFFFF",
    "on-warm":         "#1A1210",
}


# ── Огненные градиенты (DESIGN.md §2) ──────────────────────
# Порядок «от углей к ядру пламени» — используется в прогресс-барах,
# баннерах и графиках. CLI и TUI ссылаются на одну шкалу.
GRADIENT_EMBER = [
    "#8A2500",  # accent-ember — глубокий уголь
    "#B33C00",  # accent-deep — тлеющие угли
    "#FF6B1A",  # accent — пламя
    "#FF8A50",  # accent-glow — ореол
    "#FFB347",  # accent-warm — тёплое ядро
    "#FF3D00",  # accent-hot — ядро пламени
]

# Градиент для визуальных бар-чартов (рост хранилища, дедупликация)
GRADIENT_FIRE = ["#B33C00", "#FF6B1A", "#FFB347"]


def _build_theme():
    """Rich-тема с именованными стилями «Угольки»."""
    return RichTheme({
        "fq.title":     f"bold {PALETTE['accent']}",
        "fq.subtitle":  PALETTE["text-muted"],
        "fq.section":   f"bold {PALETTE['text']}",
        "fq.body":      PALETTE["text"],
        "fq.label":     PALETTE["text-muted"],
        "fq.faint":     f"dim {PALETTE['text-faint']}",
        "fq.accent":    f"bold {PALETTE['accent']}",
        "fq.warm":      PALETTE["accent-warm"],
        "fq.hot":       f"bold {PALETTE['accent-hot']}",
        "fq.success":   f"bold {PALETTE['success']}",
        "fq.warning":   PALETTE["warning"],
        "fq.error":     f"bold {PALETTE['error']}",
        "fq.info":      PALETTE["info"],
        "fq.on-accent": f"bold {PALETTE['on-accent']}",
        "fq.muted":     PALETTE["text-muted"],
    })


def get_console(force_terminal=None):
    """Консоль rich с темой «Угольки».

    Пересоздаётся, если сменился sys.stdout (важно для piping
    и redirect_stdout в тестах) или force_terminal.
    """
    import sys
    global _CONSOLE_CACHE
    cached = _CONSOLE_CACHE
    current_out = sys.stdout
    if cached is not None and force_terminal is None:
        if getattr(cached, "file", None) is current_out:
            return cached
    console = Console(
        theme=_build_theme(),
        force_terminal=force_terminal,
        file=current_out,
        highlight=False,
        soft_wrap=False,
    )
    _CONSOLE_CACHE = console
    return console


# ── Компоненты ──────────────────────────────────────────────

def header(console, title, subtitle=None, icon_name="fire"):
    """Шапка: огненная иконка + заголовок + подзаголовок."""
    ic = icon(icon_name)
    head = Text()
    head.append(f"{ic}  ", style="fq.accent")
    head.append(title, style="fq.title")
    if subtitle:
        head.append(f"\n   {subtitle}", style="fq.subtitle")
    return head


def banner(console, title, subtitle=None, icon_name="fire"):
    """Полноширинный баннер-панель: свечение через двойную рамку.

    Внешняя рамка — accent-deep (угли), внутренний контент — на surface.
    Имитация «свечения»: цветная рамка вокруг тёмной панели.
    """
    content = header(console, title, subtitle, icon_name)
    return Panel(
        content,
        box=box.DOUBLE_EDGE,
        border_style=PALETTE["accent-deep"],
        padding=(0, 2),
        style=f"on {PALETTE['surface']}",
    )


def card(console, content, title=None, icon_name=None, border=None):
    """Карточка/панель результата — «стекло» на surface-raised.

    Тень имитируется рамкой accent-deep + отступом padding.
    """
    border_color = border or PALETTE["accent-deep"]
    if title:
        ic = icon(icon_name) if icon_name else ""
        prefix = f"{ic}  " if ic else ""
        title_text = Text()
        title_text.append(prefix, style="fq.accent")
        title_text.append(title, style="fq.section")
    else:
        title_text = None
    return Panel(
        content,
        title=title_text,
        box=box.ROUNDED,
        border_style=border_color,
        padding=(1, 2),
        style=f"on {PALETTE['surface-raised']}",
    )


def _as_text(content):
    """Контент панели: строка → Text, renderable → как есть."""
    if isinstance(content, str):
        return Text(content, style="fq.body")
    return content


def success_panel(console, content, title="Готово", icon_name="success"):
    """Зелёная панель успеха с glow-рамкой."""
    return card(
        console, _as_text(content),
        title=title, icon_name=icon_name,
        border=PALETTE["success"],
    )


def error_panel(console, content, title="Ошибка", icon_name="error"):
    """Красная панель ошибки."""
    return card(
        console, _as_text(content),
        title=title, icon_name=icon_name,
        border=PALETTE["error"],
    )


def warning_panel(console, content, title="Внимание", icon_name="warning"):
    return card(
        console, _as_text(content),
        title=title, icon_name=icon_name,
        border=PALETTE["warning"],
    )


def info_panel(console, content, title=None, icon_name="info"):
    return card(
        console, _as_text(content),
        title=title, icon_name=icon_name,
        border=PALETTE["info"],
    )


def key_value(pairs, key_style="fq.label", value_style="fq.body"):
    """Строки «ключ: значение» — для статуса и настроек."""
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("key", style=key_style, no_wrap=True)
    table.add_column("value", style=value_style)
    for k, v in pairs:
        table.add_row(str(k), str(v))
    return table


def make_table(columns, rows, title=None, icon_name=None):
    """Таблица в стиле TUI: заголовки muted, зебра surface-raised."""
    table = Table(
        title=title,
        box=box.SIMPLE_HEAD,
        header_style="fq.label",
        row_styles=["", f"on {PALETTE['surface-raised']}"],
        border_style=PALETTE["accent-deep"],
        title_style="fq.section",
        pad_edge=True,
    )
    for col in columns:
        table.add_column(col, overflow="fold")
    for row in rows:
        table.add_row(*[str(c) for c in row])
    return table


def fire_progress(console, description="Синхронизация"):
    """Прогресс-бар с огненным градиентом: угли → пламя → ядро.

    complete_style=accent-hot (ядро пламени), finished=success.
    """
    return Progress(
        SpinnerColumn(style=PALETTE["accent-warm"]),
        TextColumn("[fq.label]{task.description}"),
        BarColumn(
            bar_width=40,
            style=PALETTE["accent-deep"],
            complete_style=PALETTE["accent-hot"],
            finished_style=PALETTE["success"],
        ),
        TaskProgressColumn(),
        TimeRemainingColumn(),
        console=console,
        transient=False,
    )


def human_size(num):
    """Байты → человекочитаемо (12.4 MB)."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num) < 1024.0:
            return f"{num:.1f} {unit}"
        num /= 1024.0
    return f"{num:.1f} PB"


def human_time(iso_str):
    """ISO-время → «2 часа назад»."""
    from datetime import datetime
    if not iso_str:
        return "никогда"
    try:
        ts = datetime.fromisoformat(iso_str)
    except (ValueError, TypeError):
        return str(iso_str)
    delta = datetime.now() - ts
    secs = int(delta.total_seconds())
    if secs < 60:
        return "только что"
    if secs < 3600:
        return f"{secs // 60} мин назад"
    if secs < 86400:
        return f"{secs // 3600} ч назад"
    return f"{secs // 86400} дн назад"


# ── Символы статуса (через icons.py — без эмодзи) ───────────
def status_glyphs():
    """Три глифа статуса: ок / ошибка / ждёт."""
    return {
        "ok": icon("success"),
        "fail": icon("error"),
        "warn": icon("warning"),
    }
