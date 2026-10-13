"""«Огниво» (FlamQuency Spark) — настраиваемые быстрые действия.

Идея: частые действия не должны быть командой из пяти слов. «Огниво» —
именованный ярлык, который запускает готовую команду одной строкой:

    flamquency spark daily        # → flamquency sync --profile work && ...
    flamquency spark now          # → sync прямо сейчас, без вопросов

Ярлыки живут в конфиге (секция ``spark.actions``), поэтому переживают
перезапуски и попадают в «Эволюцию» — она умеет предложить ярлык для
самой частой команды.

Команда задаётся строкой оболочки, поэтому можно связывать несколько
шагов: синк, затем бэкап, затем уведомление.
"""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path


class SparkError(Exception):
    """Некорректное или отсутствующее действие «Огнива»."""


# Готовые искры — чтобы «Огниво» было полезно сразу после установки.
# Пользователь может переопределить любую из них в конфиге.
BUILTIN_SPARKS = {
    "now": {
        "command": "flamquency sync",
        "description": "Синхронизировать прямо сейчас",
    },
    "check": {
        "command": "flamquency check && flamquency stats",
        "description": "Проверить целостность и показать статистику",
    },
    "daily": {
        "command": "flamquency sync && flamquency prune --keep-last 7",
        "description": "Синк плюс уборка старых снапшотов",
    },
}


def spark_actions(config):
    """Все доступные искры: встроенные + пользовательские (переопределяют)."""
    actions = {name: dict(spec) for name, spec in BUILTIN_SPARKS.items()}
    user = (config.get("spark") or {}).get("actions") or {}
    for name, spec in user.items():
        if isinstance(spec, str):
            spec = {"command": spec, "description": ""}
        actions[name] = spec
    return actions


def get_spark(config, name):
    """Искра по имени — raises SparkError если такой нет."""
    actions = spark_actions(config)
    if name not in actions:
        known = ", ".join(sorted(actions))
        raise SparkError(f"Неизвестное «Огниво»: {name!r} (есть: {known})")
    return actions[name]


def describe_sparks(config):
    """[(имя, команда, описание)] — для вывода в CLI/TUI."""
    actions = spark_actions(config)
    return [(name, spec.get("command", ""), spec.get("description", ""))
            for name, spec in sorted(actions.items())]


def set_spark(config, name, command, description=""):
    """Сохранить ярлык в конфиг (встроенные переопределяются)."""
    if not name or not name.strip():
        raise SparkError("Имя искры не может быть пустым")
    if "/" in name or name in (".", ".."):
        raise SparkError(f"Некорректное имя искры: {name!r}")
    if not command or not command.strip():
        raise SparkError("Команда искры не может быть пустой")
    spark = config.setdefault("spark", {})
    actions = spark.setdefault("actions", {})
    actions[name.strip()] = {
        "command": command.strip(),
        "description": description or "",
    }
    return actions[name.strip()]


def remove_spark(config, name):
    """Удалить ярлык. Встроенную искру удалить нельзя."""
    if name in BUILTIN_SPARKS:
        raise SparkError(
            f"«{name}» — встроенная искра, её нельзя удалить (можно "
            f"переопределить: flamquency spark set {name} '...')")
    actions = (config.get("spark") or {}).get("actions") or {}
    if name not in actions:
        raise SparkError(f"Нет такой искры: {name!r}")
    del actions[name]
    return True


def run_spark(config, name, dry_run=False, capture=False):
    """Выполнить искру. Возвращает (ok, сообщение).

    ``dry_run`` только печатает команду. ``capture`` собирает вывод
    (полезно для тестов и TUI), иначе он льётся в терминал пользователя.
    """
    spec = get_spark(config, name)
    command = spec["command"]
    if dry_run:
        return True, command

    try:
        argv = shlex.split(command)
    except ValueError as e:
        return False, f"Не разбирается команда: {e}"

    # «flamquency ...» выполняем текущим интерпретатором, а не через PATH
    if argv and Path(argv[0]).name == "flamquency":
        import sys
        argv = [sys.executable, "-m", "flamquency"] + argv[1:]

    proc = subprocess.run(argv, capture_output=capture, text=True)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip() if capture else ""
        return False, (f"Команда вернула {proc.returncode}"
                       + (f": {detail}" if detail else ""))
    return True, (proc.stdout or "").strip() if capture else command
