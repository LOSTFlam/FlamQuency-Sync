"""«Эволюция» FlamQuency-Sync — самообучение на привычках владельца.

Идея: программа не просто хранит версии, а **замечает**, как ей пользуются,
и предлагает (или сама применяет) улучшения:

- **Жар файлов** (``file_heat``) — какие файлы правишь чаще всего. Горячий
  файл заслуживает более частого синка и никогда не должен попадать в ignore.
- **Тёплые профили** — по путям горячих файлов подсказываем, какой профиль
  имеет смысл сделать активным.
- **Выученные исключения** (``learned_excludes``) — паттерны, которые
  наблюдались как мусор (временные файлы, логи) и которые безопасно игнорировать.
- **Тепловая карта команд** — какие команды запускают, чтобы предлагать
  следующее действие («часто зовёшь diff — повесить горячую клавишу?»).

Всё состояние живёт в ``config.yaml`` → секция ``evolution``, поэтому оно
переживает перезапуски и не требует отдельной базы. Модуль **никогда не
меняет конфиг молча**: ``suggest()`` возвращает предложения, ``apply()``
применяет их явно.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from flamquency.config import load_config, save_config


class Evolution:
    """Наблюдатель привычек + генератор предложений по улучшению себя."""

    def __init__(self, config=None, config_path=None):
        self.config_path = config_path
        self.config = config if config is not None else load_config(config_path)
        self.settings = self.config.setdefault("evolution", {})
        self.settings.setdefault("file_heat", {})
        self.settings.setdefault("tracked_commands", {})
        self.settings.setdefault("learned_excludes", [])
        self.settings.setdefault("enabled", True)

    # ── наблюдение ────────────────────────────────────────────

    @property
    def enabled(self):
        return bool(self.settings.get("enabled", True))

    def _learning_rate(self):
        try:
            rate = float(self.settings.get("learning_rate", 0.3))
        except (TypeError, ValueError):
            rate = 0.3
        return min(1.0, max(0.0, rate))

    def _heat_of(self, rel_path):
        """Жар файла, безопасно к мусору в состоянии (0.0 если не число)."""
        try:
            return float(self.settings.get("file_heat", {}).get(str(rel_path), 0))
        except (TypeError, ValueError):
            return 0.0

    def observe_file(self, rel_path, weight=1):
        """Файл изменился — растим его «жару».

        Жар — накопительный счётчик правок, но с забыванием: старое
        значение слегка остывает (``1 - learning_rate``), поэтому файл,
        который перестали править, со временем перестаёт быть горячим.
        При learning_rate=0.3 шесть правок дают ≈1.2, что пересекает
        стандартный порог 3 только после ~13 правок — намеренно: «горячим»
        должен стать файл, который правят регулярно, а не один раз.
        """
        if not self.enabled or not rel_path:
            return 0
        heat = self.settings["file_heat"]
        current = self._heat_of(rel_path)
        updated = current * (1 - self._learning_rate()) + weight
        updated = round(updated, 3)
        if updated <= 0:
            heat.pop(str(rel_path), None)
            return 0
        heat[str(rel_path)] = updated
        return updated

    def observe_command(self, command):
        """Команду запустили — растим счётчик использования."""
        if not self.enabled or not command:
            return 0
        commands = self.settings["tracked_commands"]
        commands[str(command)] = int(commands.get(str(command), 0)) + 1
        return commands[str(command)]

    def observe_excludes(self, patterns):
        """Запомнить паттерны, которые уже есть в ignore как «проверенные»."""
        if not self.enabled:
            return 0
        known = self.settings["learned_excludes"]
        added = 0
        for p in patterns or []:
            p = str(p).strip()
            if p and p not in known:
                known.append(p)
                added += 1
        return added

    # ── анализ ────────────────────────────────────────────────

    def hot_files(self, limit=5):
        """Самые горячие файлы: [(rel_path, heat), ...] по убыванию."""
        heat = self.settings.get("file_heat", {})
        ranked = sorted(
            ((k, self._heat_of(k)) for k in heat),
            key=lambda kv: (-kv[1], kv[0]))
        return [(k, v) for k, v in ranked[:limit] if v > 0]

    def hot_threshold(self):
        try:
            return float(self.settings.get("hot_file_threshold", 3))
        except (TypeError, ValueError):
            return 3.0

    def is_hot(self, rel_path):
        """Файл «горячий» — его жар перерос порог."""
        return self._heat_of(rel_path) >= self.hot_threshold()

    def hot_directories(self, limit=3):
        """Каталоги, где копится жар: [(директория, суммарный жар), ...]."""
        buckets = Counter()
        for rel_path in self.settings.get("file_heat", {}):
            heat = self._heat_of(rel_path)
            if heat <= 0:
                continue
            parent = str(Path(rel_path).parent)
            buckets[parent if parent not in (".", "") else "(корень)"] += heat
        return buckets.most_common(limit)

    def command_ranking(self, limit=5):
        """[(команда, счётчик), ...] — что запускают чаще всего."""
        ranking = Counter(self.settings.get("tracked_commands", {}))
        return ranking.most_common(limit)

    def decay(self, factor=0.9):
        """Остудить всё тепло — вызывать перед длительным простоем.

        Возвращает сколько записей остыло ниже нуля и было удалено.
        """
        if not self.enabled:
            return 0
        heat = self.settings["file_heat"]
        cooled = 0
        for key in list(heat):
            heat[key] = round(heat[key] * factor, 3)
            if heat[key] < 0.05:
                del heat[key]
                cooled += 1
        return cooled

    # ── предложения ───────────────────────────────────────────

    def suggest(self):
        """Список предложений по улучшению себя.

        Каждое предложение — словарь с ``kind``, ``title``, ``detail`` и
        ``action`` (что именно применит ``apply_one``).
        """
        suggestions = []
        if not self.enabled:
            return suggestions

        threshold = self.hot_threshold()

        # 1. Горячие файлы — кандидаты в приоритетный синк
        hot = [(p, h) for p, h in self.hot_files(limit=10) if h >= threshold]
        if hot:
            names = ", ".join(f"{p} ({h:.1f})" for p, h in hot[:3])
            suggestions.append({
                "kind": "hot_files",
                "title": f"{len(hot)} файл(а) стали горячими",
                "detail": f"Чаще всего правятся: {names}. "
                          f"Стоит синкаться чаще или не исключать их.",
                "action": {"type": "priority_sync", "files": [p for p, _ in hot]},
            })

        # 2. Каталог с максимальным жаром — кандидат в свой профиль
        dirs = self.hot_directories(limit=1)
        if dirs and dirs[0][1] >= threshold:
            directory, heat = dirs[0]
            suggestions.append({
                "kind": "profile_candidate",
                "title": f"Каталог «{directory}» набирает жар",
                "detail": f"Суммарный жар {heat:.1f}. "
                          f"Отдельный профиль ускорит его синк.",
                "action": {"type": "create_profile",
                           "directory": directory, "heat": heat},
            })

        # 3. Выученные исключения, которые ещё не в ignore
        learned = [p for p in self.settings.get("learned_excludes", []) if p]
        if learned and self.settings.get("auto_ignore_learned"):
            suggestions.append({
                "kind": "learned_excludes",
                "title": f"{len(learned)} паттерн(а) можно игнорировать",
                "detail": "Паттерны: " + ", ".join(learned[:5]),
                "action": {"type": "ignore_patterns", "patterns": learned},
            })

        # 4. Частая команда — кандидат в ярлык/скрипт
        ranking = self.command_ranking(limit=1)
        if ranking and ranking[0][1] >= 5:
            command, count = ranking[0]
            suggestions.append({
                "kind": "frequent_command",
                "title": f"«{command}» запускают чаще всего",
                "detail": f"{count} запуск(ов). "
                          f"Хороший кандидат в «Огниво» (быстрое действие).",
                "action": {"type": "spark_action", "command": command,
                           "count": count},
            })

        return suggestions

    def apply_one(self, suggestion):
        """Применить одно предложение. Возвращает (ok, сообщение)."""
        action = suggestion.get("action", {})
        kind = action.get("type")

        if kind == "priority_sync":
            # приоритетный синк = понизить порог «горячего» до этих файлов
            files = action.get("files", [])
            if not files:
                return False, "Нет файлов для приоритета"
            lowest = min(self.settings["file_heat"].get(f, 0) for f in files)
            self.settings["hot_file_threshold"] = round(max(0.5, lowest), 3)
            return True, (f"Порог горячих файлов понижен до "
                          f"{self.settings['hot_file_threshold']} — "
                          f"{len(files)} файл(а) теперь в приоритете")

        if kind == "create_profile":
            directory = action.get("directory")
            if not directory or directory == "(корень)":
                return False, "Не из чего собирать профиль"
            from flamquency.profiles import create_profile, ProfileError
            name = _profile_name_for(directory)
            try:
                create_profile(self.config, name, [str(Path(directory))])
            except ProfileError as e:
                return False, str(e)
            return True, f"Профиль «{name}» создан для {directory}"

        if kind == "ignore_patterns":
            patterns = [p for p in action.get("patterns", []) if p]
            if not patterns:
                return False, "Нечего игнорировать"
            existing = self.config.setdefault("exclude_patterns", [])
            added = [p for p in patterns if p not in existing]
            existing.extend(added)
            return True, f"Добавлено в исключения: {', '.join(added)}"

        if kind == "spark_action":
            command = action.get("command")
            if not command:
                return False, "Нет команды для «Огнива»"
            spark = self.config.setdefault("spark", {}).setdefault(
                "actions", {})
            spark[f"evolved_{command}"] = f"flamquency {command}"
            return True, f"«Огниво» получило действие evolved_{command}"

        return False, f"Неизвестное действие: {kind}"

    def apply_all(self):
        """Применить все предложения. Возвращает список результатов."""
        results = []
        for suggestion in self.suggest():
            ok, msg = self.apply_one(suggestion)
            results.append({"ok": ok, "message": msg,
                            "kind": suggestion.get("kind")})
        return results

    # ── персистентность ───────────────────────────────────────

    def save(self):
        """Записать накопленное знание обратно в конфиг."""
        save_config(self.config, config_path=self.config_path)
        return True

    def summary(self):
        """Короткая сводка для CLI/TUI."""
        return {
            "enabled": self.enabled,
            "tracked_files": len(self.settings.get("file_heat", {})),
            "tracked_commands": len(self.settings.get("tracked_commands", {})),
            "learned_excludes": len(self.settings.get("learned_excludes", [])),
            "hot_files": self.hot_files(limit=5),
            "hot_directories": self.hot_directories(limit=3),
            "command_ranking": self.command_ranking(limit=5),
            "suggestions": len(self.suggest()),
        }


def _profile_name_for(directory):
    """Каталог → безопасное имя профиля: /home/u/work → work."""
    name = Path(directory).name.strip().lower()
    name = "".join(c if c.isalnum() or c in "-_" else "-" for c in name)
    return name.strip("-") or "evolved"
