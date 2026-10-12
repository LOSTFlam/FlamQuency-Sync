"""FlamQuency-Sync — icon set «Угольки».

Единственный источник иконок для CLI и TUI. Используются глифы
Nerd Font (U+F0001–U+F2FFFD); при отсутствии патченного шрифта
автоматически включается ASCII-fallback — символы остаются читаемыми.

Правила (docs/DESIGN.md §4):
- Иконки только отсюда. Никаких эмодзи в коде.
- Выбирать через icon("fire") — не хардкодить "\uf06d" в виджетах.
- Размер/цвет задаёт контекст, не иконка.
"""

import os

_NERD_FONT_CACHE = None

# ── Nerd Font codepoints (VictorMono Nerd Font Mono проверен) ──
_GLYPHS = {
    # Бренд и навигация
    "fire":       "",  # f06d — логотип, синк
    "sync":       "",  # f021 — синхронизация
    "rollback":   "",  # f0e2 — откат (undo)
    "versions":   "",  # f0f6 — версии файлов
    "lock":       "",  # f023 — шифрование
    "settings":   "",  # f013 — настройки
    "status":     "",  # f015 — статус/дашборд
    "profiles":   "",  # f0c0 — профили
    "cloud":      "",  # f0c2 — облако/бэкенд
    "update":     "",  # f093 — обновление
    # Семантика результата
    "success":    "",  # f00c — успех
    "error":      "",  # f00d — ошибка
    "warning":    "",  # f071 — предупреждение
    "info":       "",  # f05a — информация
    "spark":      "",  # f0e7 — молния/энергия
    # Действия
    "download":   "",  # f019 — скачать
    "upload":     "",  # f093 — (алиас см. update)
    "trash":      "",  # f1f8 — удалить
    "search":     "",  # f002 — поиск
    "shield":     "",  # f132 — проверка целостности
    "clock":      "",  # f017 — время/расписание
    "calendar":   "",  # f073 — календарь
    "chart":      "",  # f080 — статистика
    "history":    "",  # f1da — история
    "folder":     "",  # f07c — папка/файлы
    "eye":        "",  # f06e — просмотр
    "rocket":     "",  # f135 — быстрое действие
    "star":       "",  # f006 — избранное
    "key":        "",  # f084 — ключ/пароль
    "refresh":    "",  # f021 — обновить
    "branch":     "",  # f126 — ветка/git
    "tag":        "",  # f02b — тег
    "external":   "",  # f08e — внешняя ссылка
    "terminal":   "",  # f120 — терминал/CLI
    "flame":      "",  # алиас fire
}

# ── ASCII-fallback — когда Nerd Font не установлен ──
_FALLBACK = {
    "fire": "🔥", "sync": ">", "rollback": "<", "versions": "#",
    "lock": "[L]", "settings": "*", "status": "=", "profiles": "@",
    "cloud": "~", "update": "^", "success": "+", "error": "x",
    "warning": "!", "info": "i", "spark": "*", "download": "v",
    "upload": "^", "trash": "X", "search": "?", "shield": "S",
    "clock": "T", "calendar": "C", "chart": "%", "history": "H",
    "folder": "/", "eye": "o", "rocket": ">>", "star": "*",
    "key": "K", "refresh": "R", "branch": "|-", "tag": "=",
    "external": "->", "terminal": "$", "flame": "🔥",
}


def nerd_font_available(force=None):
    """Есть ли в окружении шрифт с глифами Nerd Font.

    Проверка кэшируется в модульной переменной. force=True/False — для тестов.
    Эвристика: U+F06D (fire) есть в любом патченном Nerd Font.
    """
    global _NERD_FONT_CACHE
    if force is not None:
        _NERD_FONT_CACHE = bool(force)
        return _NERD_FONT_CACHE
    if _NERD_FONT_CACHE is not None:
        return _NERD_FONT_CACHE
    result = False
    try:
        import subprocess
        out = subprocess.run(
            ["fc-list", ":charset=f06d", "family"],
            capture_output=True, text=True, timeout=5,
        )
        result = bool(out.stdout.strip())
    except Exception:
        result = False
    _NERD_FONT_CACHE = result
    return result


def icon(name, force_font=None):
    """Вернуть глиф иконки по имени (или ASCII-fallback)."""
    use_nerd = nerd_font_available() if force_font is None else force_font
    if use_nerd and name in _GLYPHS:
        return _GLYPHS[name]
    return _FALLBACK.get(name, "?")


def all_icons():
    """Словарь всех иконок (для тестов и документации)."""
    return dict(_GLYPHS)
