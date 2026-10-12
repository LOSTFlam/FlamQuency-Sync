"""Планировщик FlamQuency-Sync — cron (Linux/macOS) и Task Scheduler (Windows).

Модуль не занимается «умным» дебаунсом (это ``smart_sync``) — он только
переводит человеческое расписание («каждый час», «по будням в 9:00»)
в системное задание и умеет его ставить/снимать/показывать.

Три уровня абстракции:

1. :func:`parse_schedule` — строка → структура ``ScheduleSpec``.
2. :func:`cron_expression` — ``ScheduleSpec`` → строка cron из 5 полей.
3. :class:`Scheduler` — бэкенд: ``install`` / ``remove`` / ``status``.

Кроссплатформенность: на Linux/macOS — crontab пользователя, на Windows —
``schtasks``. Всё, чего нет в системе (нет crontab, нет schtasks), честно
возвращает ошибку, а не молча «делает вид».
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

TAG = "# flamquency-schedule"          # метка в crontab — наши строки
UNIT_NAME = "flamquency-sync"          # имя задания schtasks
SCHEDULE_FILE = "schedule.json"        # что мы запомнили о себе


class ScheduleError(Exception):
    """Некорректное расписание или бэкенд недоступен."""


# ── человеческие интервалы ────────────────────────────────────

# «каждые N минут/часов/дней» → минуты. Только то, что cron выражает точно.
_INTERVAL_UNITS = {
    "минут": "minutes", "минуты": "minutes", "минуту": "minutes",
    "minute": "minutes", "minutes": "minutes", "min": "minutes",
    "час": "hours", "часа": "hours", "часов": "hours",
    "hour": "hours", "hours": "hours", "h": "hours",
    "день": "days", "дня": "days", "дней": "days",
    "day": "days", "days": "days", "d": "days",
    "недел": "weeks", "week": "weeks", "weeks": "weeks", "w": "weeks",
}

_MINUTES = {"minutes": 1, "hours": 60, "days": 1440, "weeks": 10080}

# Готовые именованные раскладки → cron.
_PRESETS = {
    "hourly":   ("0 * * * *", "каждый час"),
    "daily":    ("0 3 * * *", "каждый день в 03:00"),
    "nightly":  ("0 3 * * *", "каждую ночь в 03:00"),
    "weekly":   ("0 3 * * 1", "каждый понедельник в 03:00"),
    "monthly":  ("0 3 1 * *", "первого числа в 03:00"),
}


@dataclass
class ScheduleSpec:
    """Разобранное расписание: cron-выражение + человеческое описание."""

    cron: str
    description: str
    profile: str | None = None
    source: str = "preset"        # preset | interval | raw cron
    minutes: int | None = None    # период в минутах, если он известен

    def to_dict(self):
        return {
            "cron": self.cron,
            "description": self.description,
            "profile": self.profile,
            "source": self.source,
            "minutes": self.minutes,
        }

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict) or "cron" not in data:
            return None
        return cls(
            cron=data["cron"],
            description=data.get("description", data["cron"]),
            profile=data.get("profile"),
            source=data.get("source", "preset"),
            minutes=data.get("minutes"),
        )


# ── разбор строки ─────────────────────────────────────────────

def _normalize(text):
    return re.sub(r"\s+", " ", str(text).strip().lower())


def parse_schedule(text, profile=None):
    """«каждый час» / «каждые 30 минут» / «0 3 * * *» → ScheduleSpec.

    Порядок попыток: готовый пресет → интервал → сырой cron.
    """
    if text is None or not str(text).strip():
        raise ScheduleError("Расписание не задано")
    raw = str(text).strip()
    norm = _normalize(raw)

    # 1. Пресет
    if norm in _PRESETS:
        cron, desc = _PRESETS[norm]
        return ScheduleSpec(cron=cron, description=desc, profile=profile,
                            source="preset")

    # 2. Интервал: «каждые 30 минут», «every 2 hours», «каждый час»
    m = re.match(
        r"^(?:кажд(?:ые|ый|ая)|every)\s+(\d+)?\s*([a-zа-яё]+)", norm)
    if m:
        count = int(m.group(1) or 1)
        unit = m.group(2)
        key = _INTERVAL_UNITS.get(unit)
        if key is None:
            # «каждые 2 ч» / «каждые 3 дня» — короткая форма
            key = _INTERVAL_UNITS.get(unit[:3]) or _INTERVAL_UNITS.get(unit[:4])
        if key is None:
            raise ScheduleError(
                f"Не понимаю единицу времени: {unit!r} "
                f"(минуты, часы, дни, недели)")
        minutes = count * _MINUTES[key]
        if minutes < 1:
            raise ScheduleError("Интервал должен быть положительным")
        return ScheduleSpec(
            cron=_interval_to_cron(minutes),
            description=f"каждые {count} {_unit_word(key, count)}",
            profile=profile, source="interval", minutes=minutes)

    # 3. Сырой cron — 5 полей
    fields = raw.split()
    if len(fields) == 5 and all(_is_cron_field(f) for f in fields):
        return ScheduleSpec(cron=raw, description=f"cron: {raw}",
                            profile=profile, source="raw")

    raise ScheduleError(
        f"Не удалось разобрать расписание: {text!r}. "
        f"Примеры: «каждый час», «каждые 30 минут», «0 3 * * *»")


def _unit_word(key, count):
    words = {"minutes": ("минуту", "минуты", "минут"),
             "hours": ("час", "часа", "часов"),
             "days": ("день", "дня", "дней"),
             "weeks": ("неделю", "недели", "недель")}
    one, few, many = words[key]
    if count % 10 == 1 and count % 100 != 11:
        return one
    if 2 <= count % 10 <= 4 and not (12 <= count % 100 <= 14):
        return few
    return many


def _is_cron_field(field_text):
    """Поле cron: ``*``, число, список, диапазон, шаг — или комбинация."""
    if not field_text:
        return False
    for part in field_text.split(","):
        if not re.fullmatch(
            r"(\*|\d+)(-\d+)?(/\d+)?|(\*/\d+)", part.strip() or "x"
        ):
            return False
    return True


def _interval_to_cron(minutes):
    """Интервал в минутах → cron. Точные случаи → понятные выражения."""
    if minutes % 1440 == 0 and minutes >= 1440:
        days = minutes // 1440
        if days == 1:
            return "0 3 * * *"
        # раз в N дней — через шаг по дню месяца
        return f"0 3 */{days} * *" if days <= 28 else "0 3 1 * *"
    if minutes % 60 == 0 and minutes >= 60:
        hours = minutes // 60
        if hours == 1:
            return "0 * * * *"
        return f"0 */{hours} * * *" if hours <= 23 else "0 3 * * *"
    if minutes < 60:
        return f"*/{minutes} * * * *"
    # 90 минут и прочие некратные — ближайший honest-вариант: каждый час
    return "0 * * * *"


# ── команда, которую запускает планировщик ────────────────────

def sync_command(profile=None):
    """Команда синка для планировщика — тот же интерпретатор, что и мы."""
    python = sys.executable or "python3"
    parts = [python, "-m", "flamquency", "sync"]
    if profile:
        parts += ["--profile", profile]
    return " ".join(parts)


# ── бэкенды ───────────────────────────────────────────────────

class Scheduler:
    """Ставит и снимает расписание в системном планировщике."""

    def __init__(self, base_dir=None):
        self.base_dir = Path(base_dir) if base_dir else Path.home() / ".flamquency"
        self.state_path = self.base_dir / SCHEDULE_FILE

    # — состояние —

    def load_state(self):
        if self.state_path.exists():
            import json
            try:
                return json.loads(self.state_path.read_text())
            except Exception:
                return {}
        return {}

    def save_state(self, spec: ScheduleSpec):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        import json
        self.state_path.write_text(json.dumps(spec.to_dict(), indent=2))

    def clear_state(self):
        if self.state_path.exists():
            self.state_path.unlink()

    def current(self):
        """ScheduleSpec, который мы считаем установленным (или None)."""
        return ScheduleSpec.from_dict(self.load_state())

    # — бэкенд —

    @property
    def backend(self):
        if sys.platform.startswith("win"):
            return "schtasks"
        return "cron"

    def available(self):
        """Есть ли в системе чем управлять расписанием."""
        if self.backend == "schtasks":
            return shutil.which("schtasks") is not None
        return shutil.which("crontab") is not None

    def install(self, spec: ScheduleSpec):
        """Поставить расписание. Возвращает (ok, сообщение)."""
        if not self.available():
            tool = "schtasks" if self.backend == "schtasks" else "crontab"
            return False, (f"Планировщик недоступен: не найден {tool}. "
                           f"Поставьте его или запускайте sync вручную.")
        if self.backend == "schtasks":
            ok, msg = self._install_schtasks(spec)
        else:
            ok, msg = self._install_cron(spec)
        if ok:
            self.save_state(spec)
        return ok, msg

    def remove(self):
        """Снять расписание. Возвращает (ok, сообщение)."""
        spec = self.current()
        if not spec:
            return False, "Расписание не настроено"
        if self.backend == "schtasks":
            ok, msg = self._remove_schtasks()
        else:
            ok, msg = self._remove_cron()
        if ok:
            self.clear_state()
        return ok, msg

    def status(self):
        """Что стоит в системе прямо сейчас.

        Форма ответа всегда одинаковая: ключи ``installed``, ``live_entry``
        и ``drifted`` присутствуют независимо от того, настроено ли что-то.
        """
        live = self._live_entry()
        spec = self.current()
        status = {
            "installed": bool(spec),
            "backend": self.backend,
            "available": self.available(),
            "live_entry": live,
            "drifted": False,
        }
        if not spec:
            return status
        status.update({
            "spec": spec,
            "cron": spec.cron,
            "description": spec.description,
            "profile": spec.profile,
            "command": sync_command(spec.profile),
        })
        status["drifted"] = bool(live) and spec.cron not in str(live)
        return status

    # — cron —

    def _read_crontab(self):
        proc = subprocess.run(["crontab", "-l"], capture_output=True,
                              text=True)
        if proc.returncode != 0:
            return []          # нет crontab — это не ошибка
        return [ln for ln in proc.stdout.splitlines() if ln.strip()]

    def _write_crontab(self, lines):
        payload = "\n".join(lines) + "\n"
        proc = subprocess.run(["crontab", "-"], input=payload,
                              capture_output=True, text=True)
        return proc.returncode == 0, (proc.stderr or "").strip()

    def _cron_lines(self):
        return [ln for ln in self._read_crontab() if TAG in ln]

    def _install_cron(self, spec):
        lines = self._read_crontab()
        kept = [ln for ln in lines if TAG not in ln]
        entry = f"{spec.cron} {sync_command(spec.profile)} {TAG}"
        kept.append(entry)
        ok, err = self._write_crontab(kept)
        if not ok:
            return False, f"crontab отклонил запись: {err}"
        return True, (f"Расписание установлено: {spec.description} "
                      f"({spec.cron})")

    def _remove_cron(self):
        lines = self._read_crontab()
        kept = [ln for ln in lines if TAG not in ln]
        if len(kept) == len(lines):
            return True, "В crontab записей FlamQuency не было"
        ok, err = self._write_crontab(kept)
        if not ok:
            return False, f"crontab отклонил удаление: {err}"
        return True, "Расписание снято"

    def _live_entry(self):
        """Что реально стоит в системном планировщике (или None)."""
        if self.backend == "schtasks":
            proc = subprocess.run(
                ["schtasks", "/Query", "/TN", UNIT_NAME, "/FO", "LIST"],
                capture_output=True, text=True)
            return proc.stdout.strip() if proc.returncode == 0 else None
        entries = self._cron_lines()
        return entries[0] if entries else None

    # — schtasks —

    def _install_schtasks(self, spec):
        # Ежедневно/ежечасно выражается через /sc; сложные cron — не обещаем.
        if spec.source == "interval" and spec.minutes:
            if spec.minutes % 1440 == 0:
                sc, mod = "DAILY", str(spec.minutes // 1440)
            elif spec.minutes % 60 == 0:
                sc, mod = "HOURLY", str(spec.minutes // 60)
            else:
                sc, mod = "MINUTE", str(spec.minutes)
            cmd = ["schtasks", "/Create", "/TN", UNIT_NAME, "/TR",
                   sync_command(spec.profile), "/SC", sc, "/MO", mod, "/F"]
        else:
            cmd = ["schtasks", "/Create", "/TN", UNIT_NAME, "/TR",
                   sync_command(spec.profile), "/SC", "DAILY",
                   "/ST", "03:00", "/F"]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            return False, (proc.stderr or proc.stdout or "schtasks ошибся").strip()
        return True, f"Задание {UNIT_NAME} создано ({spec.description})"

    def _remove_schtasks(self):
        proc = subprocess.run(["schtasks", "/Delete", "/TN", UNIT_NAME, "/F"],
                              capture_output=True, text=True)
        if proc.returncode != 0:
            return False, (proc.stderr or proc.stdout or "").strip()
        return True, f"Задание {UNIT_NAME} удалено"


def describe_next(spec: ScheduleSpec):
    """Человеческое описание того, как часто будет синк."""
    if spec is None:
        return "расписание выключено"
    return spec.description
