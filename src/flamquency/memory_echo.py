"""«Эхо памяти» (Memory Echo) — подсказки из истории терминала.

FlamQuency смотрит, над чем вы на самом деле работаете, и предлагает
взять это под версионный контроль. Источники эха, по приоритету:

1. **zsh extended history** — ``~/.zsh_history`` (формат ``: ts:0;cmd``)
2. **bash history** — ``~/.bash_history``
3. **fish history** — ``~/.local/share/fish/fish_history``

Из истории вынимаются *пути* (абсолютные и ``~/...``), фильтруются шум
(домашний каталог, /tmp, системные пути) и кандидаты, которые уже
синкаются. Остальное — предложение: «вы часто правите ~/projects/app,
а он не в профиле».

Модуль **никогда не читает историю молча и не отправляет её наружу**:
всё вычисляется локально, а ``--scan`` только печатает предложения.
"""

from __future__ import annotations

import os
import re
from collections import Counter
from pathlib import Path

# Пути, которые никогда не предлагаем — они шумят или уже под защитой
NOISE_ROOTS = (
    "/tmp", "/var", "/etc", "/usr", "/bin", "/sbin", "/lib", "/lib64",
    "/opt/homebrew", "/proc", "/sys", "/dev", "/run",
)

# Минимальная длина пути, чтобы «/a» не считался кандидатом
MIN_PARTS = 2

_PATH_RE = re.compile(r"(?:~|/)[\w./+@%-]{2,}")


def history_files():
    """Существующие файлы истории оболочки в порядке приоритета."""
    home = Path.home()
    candidates = [
        home / ".zsh_history",
        home / ".bash_history",
        home / ".local" / "share" / "fish" / "fish_history",
    ]
    return [p for p in candidates if p.exists() and p.stat().st_size]


def _iter_commands(path, limit=20000):
    """Команды из файла истории — три формата, один итератор."""
    text = ""
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if i >= limit:
            return
        stripped = line.strip()
        if not stripped:
            continue
        # zsh: «: 1710000000:0;команда»
        if stripped.startswith(":") and ";" in stripped:
            stripped = stripped.split(";", 1)[1]
        # fish: «- cmd: команда»
        if stripped.startswith("- cmd:"):
            stripped = stripped[len("- cmd:"):]
        yield stripped.strip()


def extract_paths(commands, limit=400):
    """Пути из команд → Counter (путь → сколько раз упоминался)."""
    counter = Counter()
    seen = set()
    for command in commands:
        if command in seen:
            continue
        seen.add(command)
        for raw in _PATH_RE.findall(command):
            path = _normalize(raw)
            if path and _is_candidate(path):
                counter[path] += 1
            if len(counter) >= limit:
                return counter
    return counter


def _normalize(raw):
    """~/x → /home/u/x, лишние слэши и хвостовые знаки убрать."""
    raw = raw.rstrip(".,;:)]}\"'")
    if raw.startswith("~"):
        raw = str(Path.home()) + raw[1:]
    raw = os.path.normpath(raw)
    return raw


def _is_candidate(path):
    """Достоин ли путь предложения.

    Предлагаем **только существующие каталоги**: файл вроде
    ``hyprland.conf`` засинкается вместе со своим каталогом, а URL и
    путь к бинарнику в предложениях только шумят.
    """
    if not path.startswith("/"):
        return False
    if "://" in path or path.startswith("//"):
        return False
    if len(Path(path).parts) < MIN_PARTS + 1:
        return False
    for noise in NOISE_ROOTS:
        if path == noise or path.startswith(noise + "/"):
            return False
    # домашний каталог целиком — слишком широко, его корень и так в профиле
    if path == str(Path.home()):
        return False
    # служебные файлы Фламквенси не предлагаем
    if "/.flamquency" in path:
        return False
    # Слишком глубоко в чужом приложении — тоже шум
    if "/torbrowser/" in path or "/Downloads/" in path:
        return False
    try:
        return Path(path).is_dir()
    except OSError:
        return False


def tracked_prefixes(config):
    """Пути, которые уже синкаются (профили + активные корни)."""
    prefixes = set()
    for profile in (config.get("profiles") or {}).values():
        for p in profile.get("paths", []):
            prefixes.add(os.path.normpath(str(Path(str(p)).expanduser())))
    return prefixes


def suggestions(config, min_hits=3, limit=10):
    """[(путь, попаданий, уже_в_профиле)] — что стоит взять под синк."""
    paths = Counter()
    for history in history_files():
        commands = list(_iter_commands(history))
        paths.update(extract_paths(commands))

    known = tracked_prefixes(config)
    rows = []
    for path, hits in paths.items():
        if hits < min_hits:
            continue
        already = any(path == k or path.startswith(k + "/") for k in known)
        rows.append((path, hits, already))
    rows.sort(key=lambda r: (-r[1], r[0]))
    return rows[:limit]


def summary(config):
    """Что нашло «Эхо» — для CLI и TUI."""
    found = suggestions(config)
    files = history_files()
    return {
        "history_files": [str(p) for p in files],
        "suggestions": found,
        "new_candidates": [r for r in found if not r[2]],
        "already_tracked": [r for r in found if r[2]],
    }


def add_suggestion(config, path):
    """Добавить предложенный путь в активный профиль.

    Возвращает (ok, сообщение). Путь должен существовать — иначе профиль
    получит битую ссылку, которую синк будет ругать на каждом проходе.
    """
    from flamquency.profiles import (
        ensure_profiles, active_name, add_path,
    )
    ensure_profiles(config)
    target = Path(path).expanduser()
    if not target.exists():
        return False, f"Путь не существует: {target}"
    if not target.is_dir():
        return False, f"Это не каталог: {target}"
    name = active_name(config)
    add_path(config, name, str(target))
    return True, f"{target} добавлен в профиль «{name}»"
