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
    "fire":       "\uf06d",  # f06d — логотип, синк
    "sync":       "\uf021",  # f021 — синхронизация
    "rollback":   "\uf0e2",  # f0e2 — откат (undo)
    "versions":   "\uf0f6",  # f0f6 — версии файлов
    "lock":       "\uf023",  # f023 — шифрование
    "settings":   "\uf013",  # f013 — настройки
    "status":     "\uf015",  # f015 — статус/дашборд
    "profiles":   "\uf0c0",  # f0c0 — профили
    "cloud":      "\uf0c2",  # f0c2 — облако/бэкенд
    "update":     "\uf093",  # f093 — обновление
    # Семантика результата
    "success":    "\uf00c",  # f00c — успех
    "error":      "\uf00d",  # f00d — ошибка
    "warning":    "\uf071",  # f071 — предупреждение
    "info":       "\uf05a",  # f05a — информация
    "spark":      "\uf0e7",  # f0e7 — молния/энергия
    # Действия
    "download":   "\uf019",  # f019 — скачать
    "upload":     "\uf093",  # f093 — загрузить
    "trash":      "\uf1f8",  # f1f8 — удалить
    "search":     "\uf002",  # f002 — поиск
    "shield":     "\uf132",  # f132 — проверка целостности
    "clock":      "\uf017",  # f017 — время/расписание
    "calendar":   "\uf073",  # f073 — календарь
    "chart":      "\uf080",  # f080 — статистика
    "history":    "\uf1da",  # f1da — история
    "folder":     "\uf07c",  # f07c — папка/файлы
    "eye":        "\uf06e",  # f06e — просмотр
    "rocket":     "\uf135",  # f135 — быстрое действие
    "star":       "\uf006",  # f006 — избранное
    "key":        "\uf084",  # f084 — ключ/пароль
    "refresh":    "\uf021",  # f021 — обновить
    "branch":     "\uf126",  # f126 — ветка/git
    "tag":        "\uf02b",  # f02b — тег
    "external":   "\uf08e",  # f08e — внешняя ссылка
    "terminal":   "\uf120",  # f120 — терминал/CLI
    "flame":      "\uf06d",  # алиас fire
    # ── Новые фичи v2.0 ──
    "graph":      "\uf201",  # f201 — график роста хранилища
    "pie":        "\uf200",  # f200 — круговая диаграмма
    "schedule":   "\uf017",  # f017 — планировщик (алиас clock)
    "cron":       "\uf0f6",  # f0f6 — cron-задание (алиас versions)
    "cloud-on":   "\uf0c2",  # f0c2 — облако подключено
    "cloud-off":  "\uf0eb",  # f0eb — облако отключено (цвет = warning)
    "network":    "\uf0ac",  # f0ac — сетевое хранилище
    "s3":         "\uf1c0",  # f1c0 — S3-совместимое хранилище
    "drive":      "\uf1c0",  # f1c0 — облачный диск
    "diff":       "\uf044",  # f044 — визуальный diff
    "restore":    "\uf0e2",  # f0e2 — восстановление контента (алиас rollback)
    "content":    "\uf15b",  # f15b — содержимое файла
    "ignore":     "\uf05e",  # f05e — ignore-правила
    "filter":     "\uf0b0",  # f0b0 — фильтрация
    "sort":       "\uf0dc",  # f0dc — сортировка
    "menu":       "\uf0c9",  # f0c9 — контекстное меню
    "toast":      "\uf0f3",  # f0f3 — уведомление
    "hook":       "\uf0e7",  # f0e7 — хук после синка (алиас spark)
    "autosync":   "\uf021",  # f021 — автосинк (алиас sync)
    "backup":     "\uf013",  # f013 — резервное копирование (алиас settings)
    "prune":      "\uf1f8",  # f1f8 — очистка старых версий (алиас trash)
    "check":      "\uf132",  # f132 — проверка целостности (алиас shield)
    "rollback-to": "\uf0e2",  # f0e2 — откат к снапшоту
    "spark-hot":  "\uf0e7",  # f0e7 — «Огниво» (быстрое действие)
    "memory":     "\uf1da",  # f1da — «Эхо памяти» (алиас history)
    "kaleido":    "\uf1fb",  # f1fb — «Калейдоскоп»
    "lightbulb":  "\uf0eb",  # f0eb — подсказка
    "cloud-sync": "\uf0c2",  # f0c2 — облачный синк
    "local":      "\uf07c",  # f07c — локальный бэкенд (алиас folder)
    "config":     "\uf013",  # f013 — конфигурация (алиас settings)
    "help":       "\uf059",  # f059 — помощь
    "arrow-up":   "\uf062",  # f062 — вверх
    "arrow-down": "\uf063",  # f063 — вниз
    "arrow-right": "\uf061",  # f061 — вправо
    "arrow-left": "\uf060",  # f060 — влево
    "close":      "\uf00d",  # f00d — закрыть (алиас error)
    "maximize":   "\uf065",  # f065 — развернуть
    "minimize":   "\uf066",  # f066 — свернуть
    "grid":       "\uf00a",  # f00a — таблица/сетка
    "list":       "\uf03a",  # f03a — список
    "table":      "\uf0ce",  # f0ce — таблица
    "file":       "\uf15b",  # f15b — файл (алиас content)
    "gear":       "\uf013",  # f013 — шестерёнка (алиас settings)
    "globe":      "\uf0ac",  # f0ac — глобус (алиас network)
    "home":       "\uf015",  # f015 — домой (алиас status)
    "user":       "\uf007",  # f007 — пользователь
    "unlock":     "\uf09c",  # f09c — разблокировать
    "sign-out":   "\uf08b",  # f08b — выход
    "power":      "\uf011",  # f011 — питание
    "zap":        "\uf0e7",  # f0e7 — молния (алиас spark)
    "tachometer": "\uf0e4",  # f0e4 — скорость
    "dashboard":  "\uf0e4",  # f0e4 — панель (алиас tachometer)
    "widget":     "\uf1e6",  # f1e6 — виджет
    "layout":     "\uf0db",  # f0db — макет
    "borders":    "\uf187",  # f187 — границы
    "focus":      "\uf192",  # f192 — фокус
    "target":     "\uf140",  # f140 — цель
    "flag":       "\uf024",  # f024 — флаг
    "flag-checkered": "\uf11e",  # f11e — финиш
    "trophy":     "\uf091",  # f091 — трофей
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
    # v2.0
    "graph": "G", "pie": "O", "schedule": "T",
    "cron": "#", "cloud-on": "~", "cloud-off": "!", "network": "N",
    "s3": "S3", "drive": "D", "diff": "+-", "restore": "<",
    "content": "F", "ignore": "I", "filter": "Y", "sort": "Z",
    "menu": "M", "toast": "!", "hook": "H", "autosync": ">",
    "backup": "*", "prune": "X", "check": "S", "rollback-to": "<",
    "spark-hot": "*", "memory": "H", "kaleido": "K",
    "lightbulb": "i", "cloud-sync": "~",
    "local": "/", "config": "*", "help": "?", "arrow-up": "^",
    "arrow-down": "v", "arrow-right": ">", "arrow-left": "<",
    "close": "x", "maximize": "[+]", "minimize": "[-]", "grid": "#",
    "list": "-", "table": "=", "file": "F", "gear": "*",
    "globe": "N", "home": "=", "user": "@",
    "unlock": "[u]", "sign-out": "->", "power": "!", "zap": "*",
    "tachometer": "%", "dashboard": "%",
    "widget": "w", "layout": "#", "borders": "[]",
    "focus": "*",
    "target": "()", "flag": "!", "flag-checkered": "!",
    "trophy": "T",
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
