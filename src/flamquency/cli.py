#!/usr/bin/env python3
"""CLI entry point for FlamQuency-Sync — no TUI, just commands."""
import sys
import os
import json
import argparse
from pathlib import Path
from datetime import datetime

from rich.panel import Panel
from rich.text import Text
from rich import box

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from flamquency.sync_engine import FlamQuencySync
from flamquency.config import load_config, save_config
from flamquency.cloud import get_backend, LocalBackend
from flamquency.encryption import (
    EncryptionManager, EncryptionError, WrongPasswordError,
    EncryptionLockedError, DecryptionError,
)
from flamquency.ignore import default_ignore_path
from flamquency.profiles import ProfileError
from flamquency.style import (
    get_console, banner, header, card, success_panel, error_panel,
    warning_panel, info_panel, key_value, make_table, fire_progress,
    human_size, human_time, PALETTE, diff_text,
)
from flamquency.icons import icon
from flamquency.scheduler import sync_command
from flamquency.updater import check_for_update, perform_update

ENV_PASSWORD = "FLAMQUENCY_PASSWORD"


def resolve_password(args_password=None):
    """Get the encryption password: CLI flag → env var → interactive prompt."""
    if args_password:
        return args_password
    import os
    env_pw = os.environ.get(ENV_PASSWORD)
    if env_pw:
        return env_pw
    try:
        import getpass
        pw = getpass.getpass(f"{icon('key')} Пароль хранилища: ")
        if pw:
            return pw
    except (EOFError, KeyboardInterrupt):
        pass
    return None


def get_sync_engine(config=None, password=None, backend_name=None):
    """Initialize sync engine with the configured (or requested) backend.

    Бэкенды v2.0 создаются через ``backends.create_backend`` — он честно
    падает с понятной ошибкой, если облаку не хватает библиотеки, настройки
    или секрета. ``local`` остаётся значением по умолчанию, поэтому старое
    поведение не меняется.
    """
    from flamquency.backends import create_backend, BackendError

    if config is None:
        config = load_config()

    try:
        backend = create_backend(config, name=backend_name)
        backend.authenticate()
    except BackendError:
        raise

    if password is None and (config.get("encryption") or {}).get("enabled"):
        # Only ask for a password when the store is actually encrypted
        password = resolve_password(None)
    return FlamQuencySync(config=config, backend=backend, password=password)


def cmd_sync(args):
    """Execute synchronization."""
    console = get_console()
    try:
        sync = get_sync_engine(password=getattr(args, "password", None))
    except (WrongPasswordError, EncryptionError) as e:
        console.print(error_panel(console, str(e), title="Хранилище зашифровано",
                                  icon_name="lock"))
        return 1

    source = Path(args.source) if args.source else None
    profile = getattr(args, "profile", None)
    console.print(header(console, "Синхронизация", icon_name="sync"))
    if profile:
        console.print(f"   [fq.label]Профиль:[/] [fq.warm]{profile}[/]")
    if source:
        console.print(f"   [fq.label]Источник:[/] [fq.warm]{source}[/]")
    elif profile:
        console.print("   [fq.label]Пути: из профиля[/]")
    else:
        console.print("   [fq.label]Пути: активный профиль (~/.flamquency)[/]")

    try:
        result = sync.sync(source=source, profile=profile)
    except EncryptionLockedError as e:
        console.print(error_panel(console, str(e), icon_name="lock"))
        return 1
    except DecryptionError as e:
        console.print(error_panel(console, str(e), icon_name="lock"))
        return 1
    except ProfileError as e:
        console.print(error_panel(console, str(e)))
        return 1

    if result.errors:
        console.print(error_panel(
            console,
            f"Файлов: {result.files_synced} · ошибок: {len(result.errors)}",
            title="Синхронизация с ошибками", icon_name="warning"))
        for e in result.errors[:5]:
            console.print(f"   [fq.error]{icon('error')} {e}[/]")
    else:
        rows = [
            ("Профиль", result.profile or "—"),
            ("Файлов синхронизировано", result.files_synced),
            ("Файлов изменено", result.files_changed),
            ("Файлов исключено", result.files_excluded),
            ("Блобов записано", result.blobs_stored),
        ]
        if result.paths:
            rows.append(("Путей", len(result.paths)))
        console.print(success_panel(
            console, key_value(rows),
            title="Синхронизация завершена", icon_name="success"))

    if result.paths:
        table = make_table(
            ["Путь", "Файлов"],
            [(f"{icon('folder')} {e['label']}", e["files_synced"])
             for e in result.paths],
        )
        console.print(table)

    # «Эволюция» наблюдает за синком: жар файлов + пост-хук
    _evolve_observe_sync(console, sync, result)

    hook_ok, hook_msg = sync.run_post_sync_hook()
    if hook_msg != "хук не задан":
        if hook_ok:
            console.print(f"[fq.faint]{icon('hook')} {hook_msg}[/]")
        else:
            console.print(warning_panel(
                console, hook_msg, title="Пост-синк хук", icon_name="hook"))

    return 0 if not result.errors else 1


def _evolve_observe_sync(console, sync, result):
    """Отметить запущенную команду в «Эволюции» (жар файлов копит движок).

    CLI знает то, чего не знает движок: какую команду вызвали. Жар файлов
    считается внутри ``sync_engine._finish_sync`` — здесь только команды.
    """
    try:
        from flamquency.evolution import Evolution
        evo = Evolution(config=sync.config)
        if not evo.enabled:
            return
        command = getattr(result, "profile", None) or "sync"
        evo.observe_command(command)
        evo.save()
    except Exception:
        pass


def cmd_rollback(args):
    """Rollback to snapshot."""
    console = get_console()
    sync = get_sync_engine()
    snapshots = sync.list_snapshots()

    if not snapshots:
        console.print(warning_panel(
            console, "Снапшотов нет. Сначала выполните синхронизацию: "
                      "flamquency sync",
            title="Нет снапшотов", icon_name="warning"))
        return 1

    if args.list:
        _print_snapshot_table(console, snapshots)
        return 0

    if args.snapshot is not None:
        if 0 <= args.snapshot < len(snapshots):
            snap = snapshots[args.snapshot]
            console.print(f"[fq.label]{icon('rollback')} Откат к снапшоту[/] "
                          f"[fq.warm]{snap['name']}[/]...")
            success, msg = sync.rollback_to_snapshot(snap["name"])
            if success:
                console.print(success_panel(console, msg, icon_name="success"))
            else:
                console.print(error_panel(console, msg))
            return 0 if success else 1
        else:
            console.print(error_panel(
                console, f"Неверный индекс снапшота: {args.snapshot}"))
            return 1

    _print_snapshot_table(console, snapshots)
    console.print("\n[fq.faint]Используйте: flamquency rollback --snapshot N[/]")
    return 0


def _print_snapshot_table(console, snapshots):
    """Единая таблица снапшотов (новые сверху) для CLI."""
    rows = []
    for i, snap in enumerate(reversed(snapshots)):
        ts = snap["timestamp"][:19].replace("T", " ")
        rows.append((f"[fq.accent]{i}[/]", ts, snap["file_count"]))
    table = make_table(["#", "Время", "Файлов"], rows)
    console.print(card(console, table, title=f"{icon('history')} Снапшоты"))


def cmd_rollback_file(args):
    """Rollback specific file."""
    console = get_console()
    try:
        sync = get_sync_engine(password=getattr(args, "password", None))
    except (WrongPasswordError, EncryptionError) as e:
        console.print(error_panel(console, str(e), title="Хранилище зашифровано",
                                  icon_name="lock"))
        return 1

    filepath = Path(args.file).expanduser()

    if args.list:
        success, info = sync.rollback_file(str(filepath))
        if not success:
            console.print(error_panel(console, str(info)))
            return 1

        if isinstance(info, dict):
            rows = [
                (v["index"], v["timestamp"][:19].replace("T", " "),
                 v["hash"][:12], human_size(v["size"]))
                for v in info["versions"]
            ]
            console.print(card(
                console, make_table(["Версия", "Время", "Хеш", "Размер"], rows),
                title=f"{icon('versions')} {info['rel_path']} "
                      f"— {info['version_count']} версий"))
        return 0

    if args.version is not None:
        success, msg = sync.rollback_file(str(filepath), version_index=args.version)
        if success:
            console.print(success_panel(console, msg, icon_name="success"))
        else:
            console.print(error_panel(console, msg))
        return 0 if success else 1

    # Show versions
    success, info = sync.rollback_file(str(filepath))
    if success and isinstance(info, dict):
        console.print(f"[fq.label]{icon('versions')} {info['rel_path']} — "
                      f"{info['version_count']} версий[/]")
        console.print("[fq.faint]Используйте: flamquency rollback-file FILE "
                      "--version N[/]")
        return 0
    console.print(error_panel(console, str(info)))
    return 1


def cmd_restore_content(args):
    """Restore the *content* of a specific version to any path."""
    console = get_console()
    try:
        sync = get_sync_engine(password=getattr(args, "password", None))
    except (WrongPasswordError, EncryptionError) as e:
        console.print(error_panel(console, str(e), title="Хранилище зашифровано",
                                  icon_name="lock"))
        return 1

    filepath = Path(args.file).expanduser()
    output = Path(args.output).expanduser() if args.output else None

    if args.list:
        success, info = sync.rollback_file(str(filepath))
        if not success or not isinstance(info, dict):
            console.print(error_panel(console, str(info)))
            return 1
        rows = [
            (v["index"], v["timestamp"][:19].replace("T", " "),
             v["hash"][:12], human_size(v["size"]))
            for v in info["versions"]
        ]
        console.print(card(
            console, make_table(["Версия", "Время", "Хеш", "Размер"], rows),
            title=f"{icon('restore')} {info['rel_path']} — "
                  f"{info['version_count']} версий"))
        console.print(f"[fq.faint]Восстановить содержимое: "
                      f"flamquency restore-content {args.file} --version N "
                      f"[--output ПУТЬ][/]")
        return 0

    try:
        success, msg, info = sync.restore_file_content(
            str(filepath), version_index=args.version, output=output)
    except (EncryptionLockedError, DecryptionError) as e:
        console.print(error_panel(console, str(e), icon_name="lock"))
        return 1

    if success:
        body = msg
        body += (f"\nХеш: {info['hash'][:12]}... · "
                 f"размер: {human_size(info['size'])} · "
                 f"версий всего: {info['version_count']}")
        console.print(success_panel(console, body,
                                    title="Содержимое восстановлено",
                                    icon_name="restore"))
        return 0
    console.print(error_panel(console, msg, icon_name="error"))
    return 1


def cmd_view_content(args):
    """View the content of a specific version (without restoring it)."""
    console = get_console()
    try:
        sync = get_sync_engine(password=getattr(args, "password", None))
    except (WrongPasswordError, EncryptionError) as e:
        console.print(error_panel(console, str(e), title="Хранилище зашифровано",
                                  icon_name="lock"))
        return 1

    filepath = Path(args.file).expanduser()

    if args.list:
        success, info = sync.rollback_file(str(filepath))
        if not success or not isinstance(info, dict):
            console.print(error_panel(console, str(info)))
            return 1
        rows = [
            (v["index"], v["timestamp"][:19].replace("T", " "),
             v["hash"][:12], human_size(v["size"]))
            for v in info["versions"]
        ]
        console.print(card(
            console, make_table(["Версия", "Время", "Хеш", "Размер"], rows),
            title=f"{icon('content')} {info['rel_path']} — "
                  f"{info['version_count']} версий"))
        return 0

    try:
        success, msg, info = sync.view_file_content(
            str(filepath), version_index=args.version, max_bytes=args.max_bytes)
    except (EncryptionLockedError, DecryptionError) as e:
        console.print(error_panel(console, str(e), icon_name="lock"))
        return 1

    if not success:
        console.print(error_panel(console, msg, icon_name="error"))
        return 1

    meta = Text()
    meta.append(f"{icon('content')} {msg}\n", style="fq.label")
    meta.append(f"хеш: {info['hash'][:12]}... · версий всего: "
                f"{info['version_count']}", style="fq.faint")
    console.print(card(console, meta, title="Версия файла"))

    data = info["data"]
    try:
        text = data.decode("utf-8")
        if text:
            console.print(Panel(text.rstrip(),
                                box=box.SIMPLE_HEAD,
                                border_style=PALETTE["accent-deep"],
                                padding=(1, 2)))
        else:
            console.print("[fq.faint](файл пуст)[/]")
    except UnicodeDecodeError:
        console.print(warning_panel(
            console,
            "Это двоичный файл. Восстановите его через "
            "flamquency restore-content --output ПУТЬ.",
            title="Бинарное содержимое", icon_name="warning"))
    if info["truncated"]:
        console.print(f"[fq.faint]…показаны первые "
                      f"{human_size(args.max_bytes)} из {human_size(info['size'])} "
                      f"(--max-bytes чтобы увеличить)[/]")
    return 0


def cmd_restore_tree(args):
    """Restore a whole directory / the whole store / a profile at one version."""
    console = get_console()
    try:
        sync = get_sync_engine(password=getattr(args, "password", None))
    except (WrongPasswordError, EncryptionError) as e:
        console.print(error_panel(console, str(e), title="Хранилище зашифровано",
                                  icon_name="lock"))
        return 1

    dest_root = Path(args.output).expanduser() if args.output else None

    if args.list:
        keys = sync.version_store.tracked_keys()
        if not keys:
            console.print(warning_panel(
                console, "В хранилище нет отслеживаемых файлов.",
                title="Пусто", icon_name="warning"))
            return 0
        rows = [(i + 1, k) for i, k in enumerate(keys)]
        console.print(card(
            console, make_table(["#", "Файл в хранилище"], rows),
            title=f"{icon('folder')} {len(keys)} отслеживаемых файлов"))
        console.print("[fq.faint]Восстановить всё: flamquency restore-tree "
                      "[--output ПУТЬ] · каталог: restore-tree ПУТЬ[/]")
        return 0

    if args.profile:
        from flamquency.profiles import ProfileError
        try:
            result = sync.restore_profile(
                args.profile, version_index=args.version,
                dest_root=dest_root, progress=_tree_progress(console))
        except ProfileError as e:
            console.print(error_panel(console, str(e)))
            return 1
        scope = f"профиль «{args.profile}»"
    else:
        prefix = Path(args.path).expanduser() if args.path else None
        result = sync.restore_tree(
            prefix=prefix, dest_root=dest_root, version_index=args.version,
            progress=_tree_progress(console))
        scope = str(prefix) if prefix else "всё хранилище"

    if not result["total"]:
        console.print(warning_panel(
            console, f"Под «{scope}» нет файлов с версиями.",
            title="Нечего восстанавливать", icon_name="warning"))
        return 1

    body = (f"Восстановлено {result['restored']} из {result['total']}"
            + (f", ошибок: {result['failed']}" if result["failed"] else "")
            + f"\nОбласть: {scope}"
            + (f"\nКорень: {dest_root}" if dest_root else "\nКорень: исходные пути"))
    panel = (success_panel if not result["failed"] else warning_panel)(
        console, body, title="Восстановление завершено", icon_name="restore")
    console.print(panel)

    if args.verbose:
        rows = [(f["rel_path"], f.get("dest") or "—",
                 human_size(_safe_size(f["rel_path"], sync)))
                for f in result["files"]]
        console.print(card(console, make_table(
            ["Файл", "Куда", "Размер"], rows), title="Что восстановлено"))
    return 0 if not result["failed"] else 1


def _safe_size(rel_path, sync):
    info = sync.version_store.blob_store._index.get(
        sync.version_store.get_history(rel_path)[-1]["hash"], {})
    return info.get("size", 0)


def _tree_progress(console):
    """Прогресс-колбэк восстановления: огненный прогресс-бар."""
    state = {}

    def cb(done, total, rel_path):
        if "bar" not in state:
            state["bar"] = fire_progress(console, "Восстановление")
            state["bar"].start()
            state["task"] = state["bar"].add_task("restore", total=total)
        state["bar"].update(state["task"], completed=done,
                            description=f"Восстановление: {rel_path}")
        if done >= total:
            state["bar"].stop()

    return cb


def cmd_backend(args):
    """Управление бэкендами: список, выбор, проверка готовности.

    Принимает обе формы: ``backend check s3`` / ``backend use s3`` и
    флаговую ``backend --check s3`` / ``backend --use s3``.
    """
    from flamquency.backends import (
        BACKENDS, backend_names, describe_backend, create_backend,
        BackendError,
    )
    console = get_console()

    action = getattr(args, "action", None) or "list"
    target = (getattr(args, "name", None)
              or getattr(args, "check", None)
              or getattr(args, "use", None))
    if action == "check" or getattr(args, "check", None):
        action, target = "check", target
    elif action == "use" or getattr(args, "use", None):
        action, target = "use", target

    if action == "check":
        if not target:
            console.print(error_panel(
                console, "Укажите бэкенд: flamquency backend check ИМЯ",
                icon_name="error"))
            return 1
        config = load_config()
        if target not in BACKENDS:
            console.print(error_panel(
                console,
                f"Неизвестный бэкенд: {target!r}\n"
                f"Доступны: {', '.join(backend_names())}",
                icon_name="error"))
            return 1
        ok, problems, description = describe_backend(config, target)
        if ok:
            console.print(success_panel(
                console,
                f"{BACKENDS[target]['title']} готов к работе.\n{description}",
                title=f"{icon('cloud-on')} Бэкенд {target}",
                icon_name="cloud-on"))
            return 0
        console.print(error_panel(
            console, "\n".join(f"• {p}" for p in problems),
            title=f"{icon('cloud-off')} Бэкенд {target} не готов",
            icon_name="cloud-off"))
        return 1

    if action == "use":
        if not target:
            console.print(error_panel(
                console, "Укажите бэкенд: flamquency backend use ИМЯ",
                icon_name="error"))
            return 1
        config = load_config()
        if target not in BACKENDS:
            console.print(error_panel(
                console,
                f"Неизвестный бэкенд: {target!r}\n"
                f"Доступны: {', '.join(backend_names())}",
                icon_name="error"))
            return 1
        ok, problems, _ = describe_backend(config, target)
        if not ok:
            console.print(error_panel(
                console,
                "Бэкенд не готов, переключение отменено:\n"
                + "\n".join(f"• {p}" for p in problems),
                title=f"{icon('cloud-off')} {target}", icon_name="cloud-off"))
            return 1
        config["cloud_backend"] = target
        save_config(config)
        console.print(success_panel(
            console,
            f"Активный бэкенд: {target} — {BACKENDS[target]['title']}",
            title="Бэкенд переключён", icon_name="cloud-on"))
        return 0

    config = load_config()
    active = config.get("cloud_backend", "local")
    rows = []
    for name in backend_names():
        spec = BACKENDS[name]
        ok, problems, _ = describe_backend(config, name)
        mark = "→" if name == active else " "
        state = icon("cloud-on") if ok else icon("cloud-off")
        missing = "" if ok else f" ({len(problems)})"
        rows.append((mark, f"{state} {name}", spec["title"], missing))

    console.print(card(
        console, make_table(["", "Бэкенд", "Что это", "Не хватает"], rows),
        title=f"{icon('cloud')} Бэкенды — активен: {active}"))

    console.print("[fq.faint]Переключить: flamquency backend use ИМЯ · "
                  "проверить: flamquency backend check ИМЯ[/]")
    console.print("[fq.faint]Секреты — только в переменных окружения, "
                  "см. docs/BACKENDS.md[/]")

    # Живой статус активного бэкенда
    try:
        live = create_backend(config).get_status()
        console.print(key_value([
            (k, str(v)) for k, v in live.items() if v not in (None, "")
        ]))
    except BackendError as e:
        console.print(warning_panel(console, str(e),
                                    title="Активный бэкенд недоступен",
                                    icon_name="warning"))
    return 0


def cmd_spark(args):
    """«Огниво»: быстрые действия одной командой."""
    from flamquency.spark import (
        BUILTIN_SPARKS, SparkError, describe_sparks, get_spark,
        remove_spark, run_spark, set_spark,
    )
    console = get_console()

    if args.list or (not args.action and not args.remove):
        rows = [(f"{icon('spark')} {name}", command, desc)
                for name, command, desc in describe_sparks(load_config())]
        console.print(card(
            console, make_table(["Искра", "Команда", "Что делает"], rows),
            title=f"{icon('spark')} «Огниво» — быстрые действия"))
        console.print("[fq.faint]Запустить: flamquency spark ИМЯ · "
                      "создать: flamquency spark set ИМЯ 'команда'[/]")
        return 0

    if args.action == "set":
        config = load_config()
        try:
            spec = set_spark(config, args.name, args.value,
                             description=getattr(args, "description", "") or "")
        except SparkError as e:
            console.print(error_panel(console, str(e)))
            return 1
        save_config(config)
        console.print(success_panel(
            console, f"«{args.name}» → {spec['command']}",
            title="Искра создана", icon_name="spark"))
        return 0

    if args.action == "remove":
        config = load_config()
        try:
            remove_spark(config, args.name)
        except SparkError as e:
            console.print(error_panel(console, str(e)))
            return 1
        save_config(config)
        console.print(success_panel(
            console, f"«{args.name}» удалена",
            title="Искра убрана", icon_name="spark"))
        return 0

    if args.action == "show":
        config = load_config()
        try:
            spec = get_spark(config, args.name)
        except SparkError as e:
            console.print(error_panel(console, str(e)))
            return 1
        console.print(card(
            console, key_value([
                ("Команда", spec.get("command", "")),
                ("Описание", spec.get("description", "") or "—"),
                ("Встроенная", "да" if args.name in BUILTIN_SPARKS else "нет"),
            ]),
            title=f"{icon('spark')} {args.name}"))
        return 0

    # Запуск
    config = load_config()
    if args.dry_run:
        ok, command = run_spark(config, args.action, dry_run=True)
        console.print(info_panel(console, command,
                                 title="Что выполнится", icon_name="spark"))
        return 0
    console.print(f"[fq.label]{icon('spark')} Запускаю «{args.action}»...[/]")
    ok, output = run_spark(config, args.action)
    if not ok:
        console.print(error_panel(console, output, title="Искра не вспыхнула"))
        return 1
    return 0


def cmd_echo(args):
    """«Эхо памяти»: что стоит взять под синк, судя по истории команд."""
    from flamquency import memory_echo
    console = get_console()
    summary = memory_echo.summary(load_config())

    if not summary["history_files"]:
        console.print(info_panel(
            console,
            "Не нашёл истории оболочки (~/.zsh_history, ~/.bash_history, "
            "fish). Всё вычисляется локально — ничего не отправляется.",
            title=f"{icon('memory')} «Эхо памяти»", icon_name="memory"))
        return 0

    files = ", ".join(str(Path(p).name) for p in summary["history_files"])
    rows = []
    for path, hits, tracked in summary["suggestions"]:
        mark = icon("success") if tracked else icon("lightbulb")
        rows.append((f"{hits}×", f"{mark} {path}",
                     "в профиле" if tracked else "можно добавить"))
    console.print(card(
        console, make_table(["Поподаний", "Путь", "Статус"], rows),
        title=f"{icon('memory')} «Эхо памяти» — {files}"))

    new = summary["new_candidates"]
    if not new:
        console.print("[fq.faint]Всё, над чем вы работаете, уже под синком.[/]")
        return 0

    if args.add:
        for path, _hits, _tracked in new[:args.add]:
            ok, msg = memory_echo.add_suggestion(load_config(), path)
            if ok:
                save_config(load_config())
                console.print(f"   [fq.success]{icon('success')}[/] {msg}")
            else:
                console.print(f"   [fq.error]{icon('error')}[/] {msg}")
        return 0

    console.print("[fq.faint]Добавить в активный профиль: "
                  "flamquency echo --add N (N — сколько штук)[/]")
    return 0


def cmd_kaleido(args):
    """«Калейдоскоп»: цветовые вариации темы «Угольки»."""
    from flamquency import kaleido
    console = get_console()
    config = load_config()
    active = kaleido.current(config)

    if args.random:
        name, scale = kaleido.random_variant(seed=args.seed)
        console.print(card(
            console, _kaleido_preview(name, scale),
            title=f"{icon('kaleido')} Случайная вариация — {name}"))
        console.print("[fq.faint]Сохранить: flamquency kaleido use "
                      f"{name}[/]")
        return 0

    if args.use:
        try:
            kaleido.set_variant(config, args.use)
        except ValueError as e:
            console.print(error_panel(console, str(e)))
            return 1
        save_config(config)
        console.print(success_panel(
            console, f"Тема «{kaleido.TITLES.get(args.use, args.use)}» "
                     f"будет применена при следующем запуске TUI.",
            title="Калейдоскоп повёрнут", icon_name="kaleido"))
        return 0

    rows = []
    for name, title, accent in kaleido.describe():
        mark = "→" if name == active else " "
        swatch = _swatch(kaleido.ACCENT_SCALES[name])
        rows.append((mark, f"{swatch} {name}", title, accent))
    console.print(card(
        console, make_table(["", "Вариация", "Характер", "Акцент"], rows),
        title=f"{icon('kaleido')} «Калейдоскоп» — активна: {active}"))
    console.print("[fq.faint]Переключить: flamquency kaleido use ИМЯ · "
                  "случайная: flamquency kaleido --random[/]")
    return 0


def _swatch(scale):
    """Цветные квадраты акцентной шкалы для таблицы."""
    return "".join(f"[{c}]██[/]" for c in scale[:4])


def _kaleido_preview(name, scale):
    """Текстовый предпросмотр вариации: шкала + пример панели."""
    ember, deep, accent, glow, warm, hot = scale
    text = Text()
    text.append("Шкала жары:  ", style="fq.label")
    for color in scale:
        text.append("█", style=color)
    text.append("\n\nПример:  ", style="fq.label")
    text.append("● активный элемент", style=accent)
    text.append("   ")
    text.append("успех", style=kaleido.BASE_SURFACES["success"])
    text.append("   ")
    text.append("ошибка", style=kaleido.BASE_SURFACES["error"])
    text.append(f"\n\nАкцент: {accent} · ядро: {hot} · угли: {ember}",
                style="fq.faint")
    return text


def cmd_help(args):
    """Подробная справка по команде — зачем, примеры, связи."""
    from flamquency.helptopics import HELP_TOPICS, topics
    console = get_console()

    if not args.topic:
        # Обзор: команды с человеческим «зачем»
        rows = []
        for name, (why, _examples, related) in HELP_TOPICS.items():
            rows.append((f"{icon('help')} {name}",
                         why.split(".")[0] + "."))
        console.print(card(
            console, make_table(["Команда", "Зачем она"], rows),
            title=f"{icon('help')} Справка FlamQuency-Sync"))
        console.print(f"[fq.faint]Подробнее: flamquency help КОМАНДА "
                      f"({len(topics())} команд описано)[/]")
        return 0

    topic = HELP_TOPICS.get(args.topic)
    if topic is None:
        known = ", ".join(topics())
        console.print(error_panel(
            console,
            f"Нет справки по «{args.topic}».\nОписанные команды: {known}",
            title="Неизвестная команда", icon_name="error"))
        return 1

    why, examples, related = topic
    console.print(banner(console, f"flamquency {args.topic}", why,
                         icon_name="help"))

    example_lines = Text()
    for example in examples:
        example_lines.append(f"{icon('terminal')} ", style="fq.accent")
        example_lines.append(example + "\n", style="fq.body")
    console.print(card(console, example_lines, title="Примеры"))

    if related:
        links = " · ".join(f"flamquency help {r}" for r in related)
        console.print(f"[fq.faint]{icon('arrow-right')} Смотри также: {links}[/]")
    return 0


def cmd_schedule(args):
    """Manage the sync schedule: show / set / remove."""
    from flamquency.scheduler import (
        Scheduler, parse_schedule, ScheduleError, describe_next,
    )
    console = get_console()
    scheduler = Scheduler()

    if args.remove:
        ok, msg = scheduler.remove()
        if ok:
            config = load_config()
            config["schedule"] = None
            config["schedule_profile"] = None
            save_config(config)
            console.print(success_panel(console, msg,
                                        title="Расписание снято",
                                        icon_name="clock"))
            return 0
        console.print(error_panel(console, msg, icon_name="error"))
        return 1

    if not args.interval:
        status = scheduler.status()
        if not status.get("installed"):
            console.print(info_panel(
                console,
                "Расписание не настроено.\n"
                "Поставить: flamquency schedule «каждый час» [--profile ИМЯ]\n"
                "Примеры: «каждые 30 минут», «daily», «0 3 * * *»",
                title=f"{icon('clock')} Расписание", icon_name="clock"))
            if not status.get("available"):
                console.print(warning_panel(
                    console,
                    f"В системе нет {status['backend']} — ставить нечего.",
                    title="Планировщик недоступен", icon_name="warning"))
            return 0
        spec = status["spec"]
        body = [
            f"Описание: {status['description']}",
            f"Cron: {status['cron']}",
            f"Профиль: {status['profile'] or '— активный —'}",
            f"Команда: {status['command']}",
            f"Бэкенд: {status['backend']}",
        ]
        if status.get("drifted"):
            body.append("\n⚠ Запись в системе отличается от сохранённой — "
                        "переустановите: schedule <интервал>")
        console.print(card(console, Text("\n".join(body), style="fq.body"),
                           title=f"{icon('clock')} Расписание",
                           icon_name="clock"))
        return 0

    try:
        spec = parse_schedule(args.interval, profile=args.profile)
    except ScheduleError as e:
        console.print(error_panel(console, str(e), icon_name="error"))
        return 1

    ok, msg = scheduler.install(spec)
    if not ok:
        console.print(error_panel(console, msg, icon_name="error"))
        return 1

    config = load_config()
    config["schedule"] = spec.cron
    config["schedule_profile"] = spec.profile or config.get("active_profile")
    save_config(config)

    console.print(success_panel(
        console,
        f"{msg}\nПрофиль: {spec.profile or 'активный'}\n"
        f"Команда: {sync_command(spec.profile)}",
        title="Расписание установлено", icon_name="clock"))
    console.print(f"[fq.faint]Снять: flamquency schedule --remove · "
                  f"показать: flamquency schedule[/]")
    return 0


def cmd_evolve(args):
    """«Эволюция»: показать или применить самообученные улучшения."""
    from flamquency.evolution import Evolution
    console = get_console()
    evo = Evolution()

    if args.decay:
        cooled = evo.decay()
        evo.save()
        console.print(success_panel(
            console, f"Остыло и забыто записей: {cooled}",
            title="Жар охлаждён", icon_name="memory"))
        return 0

    if args.forget:
        for rel_path in args.forget:
            evo.settings["file_heat"].pop(rel_path, None)
        evo.save()
        console.print(success_panel(
            console, f"Забыто файлов: {len(args.forget)}",
            title="Память очищена", icon_name="memory"))
        return 0

    if args.apply:
        results = evo.apply_all()
        if not results:
            console.print(info_panel(
                console, "Эволюции пока нечего предложить — "
                         "поработайте с программой ещё немного.",
                title="Пусто", icon_name="memory"))
            return 0
        evo.save()
        rows = []
        failed = 0
        for r in results:
            glyph = icon("success") if r["ok"] else icon("error")
            failed += 0 if r["ok"] else 1
            rows.append((glyph, r["kind"], r["message"]))
        console.print(card(console, make_table(
            ["", "Тип", "Результат"], rows),
            title=f"{icon('kaleido')} Эволюция применилась"))
        return 1 if failed else 0

    # Показ: сводка + предложения
    summary = evo.summary()
    if not summary["enabled"]:
        console.print(info_panel(
            console, "Эволюция выключена в конфиге (evolution.enabled: false).",
            title="Эволюция спит", icon_name="memory"))
        return 0

    lines = [
        f"Отслежено файлов: {summary['tracked_files']}",
        f"Отслежено команд: {summary['tracked_commands']}",
        f"Выученных исключений: {summary['learned_excludes']}",
    ]
    if summary["hot_files"]:
        hot = ", ".join(f"{p} ({h:.1f})" for p, h in summary["hot_files"])
        lines.append(f"\nСамые горячие: {hot}")
    if summary["hot_directories"]:
        dirs = ", ".join(f"{d} ({h:.1f})" for d, h in summary["hot_directories"])
        lines.append(f"Горячие каталоги: {dirs}")
    if summary["command_ranking"]:
        cmds = ", ".join(f"{c}×{n}" for c, n in summary["command_ranking"])
        lines.append(f"Частые команды: {cmds}")
    console.print(card(console, Text("\n".join(lines), style="fq.body"),
                       title=f"{icon('kaleido')} Эволюция",
                       icon_name="kaleido"))

    suggestions = evo.suggest()
    if not suggestions:
        console.print("[fq.faint]Пока нечего предложить — жар ещё не набран.[/]")
        return 0

    rows = [(icon("lightbulb"), s["title"], s["detail"]) for s in suggestions]
    console.print(card(console, make_table(["", "Предложение", "Почему"], rows),
                       title=f"{icon('kaleido')} {len(suggestions)} предложение(й)"))
    console.print("[fq.faint]Применить всё: flamquency evolve --apply[/]")
    return 0


def cmd_status(args):
    """Show sync status."""
    console = get_console()
    sync = get_sync_engine()
    status = sync.status()

    storage = status.get("storage_bytes", 0)
    enc = status.get("encryption", "disabled")
    enc_glyph = {"enabled": icon("lock"), "locked": icon("key"),
                 "disabled": icon("warning")}[enc]
    enc_color = {"enabled": "fq.success", "locked": "fq.warning",
                 "disabled": "fq.faint"}[enc]

    snapshots = sync.list_snapshots()

    rows = [
        ("Бэкенд", f"[fq.warm]{status.get('backend', 'local')}[/]"),
        ("Последний синк", human_time(status.get("last_sync"))),
        ("Отслеживается файлов", f"[bold]{status.get('tracked_files', 0)}[/]"),
        ("Блобов", status.get("blob_count", 0)),
        ("Хранилище", f"[bold]{human_size(storage)}[/]"),
        ("Шифрование", f"[{enc_color}]{enc_glyph} {enc}[/]"),
        ("Снапшотов", f"[bold]{len(snapshots)}[/]"),
    ]
    ig_file = status.get("ignore_file")
    rows.append(("Ignore-файл", ig_file or "[fq.faint]~/.flamquencyignore "
                                       f"({icon('warning')} не создан)[/]"))
    if ig_file:
        rows[-1] = ("Ignore-файл",
                    f"{ig_file} ([fq.warm]{status.get('ignore_rules', 0)}[/] правил)")
    profiles = status.get("profiles", [])
    active = status.get("active_profile", "default")
    rows.append(("Профиль", f"[fq.warm]{active}[/] "
                            f"[fq.faint]({len(profiles)} шт)[/]"))

    console.print(banner(console, "FlamQuency-Sync", "статус системы",
                         icon_name="status"))
    console.print(card(console, key_value(rows),
                       title=f"{icon('chart')} Состояние"))


def cmd_diff(args):
    """Diff two versions of a file."""
    console = get_console()
    sync = get_sync_engine()
    filepath = Path(args.file).expanduser()

    success, diff = sync.diff_file(str(filepath), args.v1, args.v2)
    if not success:
        console.print(error_panel(console, str(diff)))
        return 1

    console.print(card(console, diff_text(diff),
                       title=f"{icon('eye')} {filepath.name}: "
                             f"v{args.v1} → v{args.v2}",
                       icon_name="eye"))
    added = sum(1 for l in diff.splitlines() if l.startswith("+")
                and not l.startswith("+++"))
    removed = sum(1 for l in diff.splitlines() if l.startswith("-")
                  and not l.startswith("---"))
    console.print(f"[fq.faint]{icon('plus')} {added} добавлено · "
                  f"{icon('minus')} {removed} удалено[/]")
    return 0


def cmd_snapshots(args):
    """List snapshots."""
    console = get_console()
    sync = get_sync_engine()
    snapshots = sync.list_snapshots()

    if not snapshots:
        console.print(warning_panel(
            console, "Снапшотов нет. Сначала выполните синхронизацию: "
                      "flamquency sync",
            title="Нет снапшотов", icon_name="warning"))
        return 0

    _print_snapshot_table(console, snapshots)
    return 0


def cmd_watch(args):
    """Watch mode — auto-sync on file changes."""
    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler
    except ImportError:
        console.print(error_panel(console, "Режим watch требует watchdog: pip install watchdog"))
        return 1
    
    sync = get_sync_engine()
    
    watch_paths = [Path(p).expanduser() for p in (args.paths or ["~/.flamquency"])]
    
    class SyncHandler(FileSystemEventHandler):
        def __init__(self):
            self.last_sync = None
        
        def on_any_event(self, event):
            if event.is_directory:
                return
            
            # Debounce — sync at most every 5 seconds
            now = datetime.now()
            if self.last_sync and (now - self.last_sync).total_seconds() < 5:
                return
            self.last_sync = now
            
            print(f"🔄 Change detected: {event.src_path}")
            result = sync.sync()
            console.print(f"   [fq.success]{icon('success')}[/] Синхронизировано {result.files_synced} файлов")
    
    observer = Observer()
    handler = SyncHandler()
    
    for path in watch_paths:
        if path.exists():
            observer.schedule(handler, str(path), recursive=True)
            print(f"👁 Watching: {path}")
        else:
            console.print(f"   [fq.warning]{icon('warning')}[/] Путь не найден: {path}")
    
    observer.start()
    console.print(f"\n[bold]{icon('sync')} Watch-режим активен. Ctrl+C — стоп.[/]\n")
    
    try:
        while True:
            import time
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        console.print(f"\n[fq.label]{icon('error')} Watch-режим остановлен[/]")
    
    observer.join()
    return 0


def cmd_encryption(args):
    """Manage blob encryption: status / enable / disable / change-password."""
    config = load_config()
    action = args.action
    store_dir = Path.home() / ".flamquency" / "versions"

    if action == "status":
        mgr = EncryptionManager(store_dir)
        if not mgr.is_configured:
            console.print(f"   {icon('warning')} Шифрование: ВЫКЛЮЧЕНО (блобы в открытом виде)")
        elif mgr.is_unlocked:
            console.print(f"   {icon('lock')} Шифрование: ВКЛЮЧЕНО и РАЗБЛОКИРОВАНО")
        else:
            console.print(f"   {icon('key')} Шифрование: ВКЛЮЧЕНО, но ЗАБЛОКИРОВАНО (нужен пароль)")
        print(f"   Key file: {mgr.key_path}")
        return 0

    if action == "enable":
        mgr = EncryptionManager(store_dir)
        if mgr.is_configured:
            console.print(error_panel(console, "Шифрование уже включено"))
            return 1
        password = resolve_password(args.password)
        if not password:
            console.print(error_panel(console, "Для включения шифрования нужен пароль"))
            return 1
        mgr = EncryptionManager.enable(store_dir, password)
        config["encryption"] = {"enabled": True}
        save_config(config)
        console.print(success_panel(console, "Шифрование включено!", title="Шифрование", icon_name="lock"))
        console.print("   [fq.faint]Новые блобы будут шифроваться AES-128 (Fernet).[/]")
        print(f"   Key file: {mgr.key_path} (keep it safe — no password, no data)")
        return 0

    if action == "disable":
        mgr = EncryptionManager(store_dir)
        if not mgr.is_configured:
            console.print(error_panel(console, "Шифрование не включено"))
            return 1
        password = resolve_password(args.password)
        if not password:
            console.print(error_panel(console, "Для отключения шифрования нужен пароль"))
            return 1
        try:
            mgr.unlock(password)
        except WrongPasswordError:
            console.print(error_panel(console, "Неверный пароль"))
            return 1
        sync = get_sync_engine(config=config, password=password)
        decrypted = sync.version_store.blob_store.disable_encryption(mgr)
        config["encryption"] = {"enabled": False}
        save_config(config)
        console.print(success_panel(console, f"Шифрование отключено — {decrypted} блобов расшифровано на месте", title="Шифрование", icon_name="key"))
        return 0

    if action == "change-password":
        mgr = EncryptionManager(store_dir)
        if not mgr.is_configured:
            console.print(error_panel(console, "Шифрование не включено"))
            return 1
        old_pw = resolve_password(args.password)
        if not old_pw:
            console.print(error_panel(console, "Требуется текущий пароль"))
            return 1
        try:
            mgr.unlock(old_pw)
        except WrongPasswordError:
            console.print(error_panel(console, "Неверный пароль"))
            return 1
        import getpass
        new_pw = args.new_password or getpass.getpass(f"{icon('key')} Новый пароль: ")
        if not new_pw:
            console.print(error_panel(console, "Новый пароль не может быть пустым"))
            return 1
        if not args.new_password:
            confirm = getpass.getpass(f"{icon('key')} Подтвердите пароль: ")
            if new_pw != confirm:
                console.print(error_panel(console, "Пароли не совпадают"))
                return 1
        new_mgr = mgr.change_password(new_pw)
        sync = get_sync_engine(config=config, password=new_pw)
        rekeyed = sync.version_store.blob_store.rekey(mgr, new_mgr)
        console.print(success_panel(console, f"Пароль изменён — {rekeyed} блобов перешифровано", title="Шифрование", icon_name="key"))
        return 0

    console.print(error_panel(console, f"Неизвестное действие: {action}"))
    return 1


def cmd_ignore(args):
    """Manage ~/.flamquencyignore — init / add / check / list."""
    console = get_console()
    from flamquency.ignore import (
        IgnoreRules, IGNORE_FILENAME, default_ignore_path,
        default_template, write_default_ignore_file,
    )

    path = Path(args.path).expanduser() if getattr(args, "path", None) \
        else default_ignore_path()

    # ── --init: write the starter file ─────────────────────────
    if getattr(args, "init", False):
        written = write_default_ignore_file(path, force=getattr(args, "force", False))
        if written is None:
            console.print(warning_panel(console, f"{path} уже существует — ничего не записано"))
            console.print("   [fq.faint]Используйте --force для перезаписи шаблоном[/]")
            return 1
        rules = IgnoreRules.from_file(written)
        print(f"📝 Created {written} ({len(rules)} rules)")
        console.print("   [fq.faint]Синтаксис как у .gitignore — редактируйте когда угодно[/]")
        return 0

    # ── --add: append one pattern ──────────────────────────────
    if getattr(args, "add", None):
        if not path.exists():
            # start from the template so the user gets the comments too
            write_default_ignore_file(path)
        with open(path, "a") as f:
            f.write(f"\n{args.add.strip()}\n")
        rules = IgnoreRules.from_file(path)
        console.print(success_panel(console, f"Добавлено '{args.add.strip()}' → {path}", icon_name="success"))
        console.print(f"   [fq.faint]Всего правил: {len(rules)}[/]")
        return 0

    # ── --check: explain one path ──────────────────────────────
    if getattr(args, "check", None):
        config = load_config()
        rules = IgnoreRules.from_config(config, path)
        target = args.check
        size = None
        if Path(target).expanduser().is_file():
            try:
                size = Path(target).expanduser().stat().st_size
            except OSError:
                size = None
        ignored, rule = rules.explain(target, size=size)
        if ignored:
            console.print(f"   [fq.warning]{icon('warning')}[/] ИГНОРИРУЕТСЯ: {target}")
            if rule is not None:
                console.print(f"   [fq.faint]по правилу: {rule.raw}[/]")
        elif rule is not None:
            console.print(f"   [fq.success]{icon('success')}[/] НЕ ИГНОРИРУЕТСЯ: {target}")
            console.print(f"   [fq.faint]возвращено правилом: {rule.raw}[/]")
        else:
            console.print(f"   [fq.success]{icon('success')}[/] НЕ ИГНОРИРУЕТСЯ: {target}")
            console.print(f"   [fq.faint](правило не найдено — проверено {len(rules)} правил)[/]")
        return 0

    # ── --size-gt / --size-lt / --types / --clear-global (v2.0) ──
    if (getattr(args, "size_gt", None) or getattr(args, "size_lt", None)
            or getattr(args, "types", None)
            or getattr(args, "clear_global", False)):
        return _apply_global_rules(console, args)

    # ── --list / default: show the rules ───────────────────────
    rules = IgnoreRules.from_config(load_config(), path)
    if not path.exists() and not rules.global_rules:
        console.print(f"   {icon('versions')} Ignore-файла ещё нет: {path}")
        console.print("   [fq.faint]Создать: flamquency ignore --init[/]")
        return 0
    console.print(card(console, "\n".join(f"   {r}" for r in rules),
                       title=f"{icon('versions')} {path} — {len(rules)} правил"))
    if rules.global_rules:
        rows = [(f"{icon('filter')} {r.kind}", r.describe())
                for r in rules.global_rules]
        console.print(card(console, make_table(["Правило", "Условие"], rows),
                           title=f"{icon('filter')} Глобальные правила из конфига"))
        console.print("[fq.faint]Синтаксис файла: size>1GB · type=mp4,avi[/]")
    if not rules:
        return 0
    for rule in rules.rules:
        flags = []
        if rule.negate:
            flags.append("negate")
        if rule.dir_only:
            flags.append("dir")
        if rule.anchored:
            flags.append("anchored")
        tag = f"  [{', '.join(flags)}]" if flags else ""
        print(f"   {rule.raw}{tag}")
    return 0


def _apply_global_rules(console, args):
    """Записать глобальные size/type-правила в конфиг (Task 6)."""
    from flamquency.ignore import parse_size, _global_rules_from_config
    config = load_config()
    changed = []

    if getattr(args, "size_gt", None):
        if parse_size(args.size_gt) is None:
            console.print(error_panel(
                console, f"Не понимаю размер: {args.size_gt!r} (например 1GB)",
                icon_name="error"))
            return 1
        config["ignore_size_gt"] = args.size_gt
        changed.append(f"файлы больше {args.size_gt}")

    if getattr(args, "size_lt", None):
        if parse_size(args.size_lt) is None:
            console.print(error_panel(
                console, f"Не понимаю размер: {args.size_lt!r} (например 10KB)",
                icon_name="error"))
            return 1
        config["ignore_size_lt"] = args.size_lt
        changed.append(f"файлы меньше {args.size_lt}")

    if getattr(args, "types", None):
        types = [t.strip() for t in args.types.replace(",", " ").split() if t.strip()]
        if not types:
            console.print(error_panel(
                console, "Не указан ни один тип", icon_name="error"))
            return 1
        existing = config.get("ignore_types") or []
        if isinstance(existing, str):
            existing = existing.replace(",", " ").split()
        for t in types:
            if t.lower().lstrip(".") not in [e.lower().lstrip(".") for e in existing]:
                existing.append(t)
        config["ignore_types"] = existing
        changed.append(f"типы: {', '.join(types)}")

    if getattr(args, "clear_global", False):
        for key in ("ignore_size_gt", "ignore_size_lt", "ignore_types"):
            config.pop(key, None)
        console.print(success_panel(
            console, "Глобальные правила сброшены",
            title="Очищено", icon_name="success"))
        save_config(config)
        return 0

    save_config(config)
    active = _global_rules_from_config(config)
    rows = [(r.kind, r.describe()) for r in active]
    console.print(success_panel(
        console, "Применено: " + "; ".join(changed),
        title="Глобальные правила обновлены", icon_name="success"))
    console.print(card(console, make_table(["Правило", "Условие"], rows),
                       title=f"{icon('filter')} Активные правила"))
    return 0


def cmd_profile(args):
    console = get_console()
    from flamquency.profiles import (
        ProfileError, add_path, active_name, create_profile, delete_profile,
        ensure_profiles, get_profile, profile_names, remove_path,
        set_active, set_description,
    )

    config_path = getattr(args, "config_path", None)
    config = load_config(config_path)
    ensure_profiles(config)
    action = args.action

    def profile_paths_arg():
        """Paths come either positionally or via repeatable --path."""
        return list(getattr(args, "paths", None) or []) + \
               list(getattr(args, "path", None) or [])

    def save():
        save_config(config, config_path=config_path)

    try:
        if action == "list":
            names = profile_names(config)
            active = active_name(config)
            print(f"🗂  {len(names)} profile(s):\n")
            for name in names:
                prof = config["profiles"][name]
                marker = "→" if name == active else " "
                desc = f"  — {prof.get('description')}" if prof.get("description") else ""
                print(f" {marker} {name}{desc}")
                for p in prof["paths"]:
                    exists = "✓" if Path(p).exists() else "✗"
                    print(f"      {exists} {p}")
                extra = prof.get("exclude_patterns") or []
                if extra:
                    print(f"      excludes: {', '.join(extra)}")
            print(f"\n   Active: {active}")
            console.print("   [fq.faint]Переключить: flamquency profile use ИМЯ[/]")
            return 0

        if action == "create":
            name = args.name
            paths = profile_paths_arg()
            if not paths:
                console.print(error_panel(console, "Для создания профиля нужен хотя бы один путь"))
                return 1
            prof = create_profile(config, name, paths,
                                  description=getattr(args, "description", ""),
                                  exclude_patterns=getattr(args, "exclude", None))
            save()
            print(f"🗂  Created profile '{name}' with {len(prof['paths'])} path(s):")
            for p in prof["paths"]:
                print(f"      {p}")
            print(f"\n   Use it: flamquency profile use {name}")
            return 0

        if action == "delete":
            name = args.name
            delete_profile(config, name)
            save()
            print(f"🗑  Deleted profile '{name}'")
            return 0

        if action == "use":
            name = args.name
            set_active(config, name)
            save()
            console.print(success_panel(console, f"Активный профиль: {name}", icon_name="profiles"))
            console.print("   [fq.faint]`flamquency sync` теперь следует этому профилю[/]")
            return 0

        if action == "add-path":
            name = args.name
            paths = profile_paths_arg()
            if not paths:
                console.print(error_panel(console, "Нужен хотя бы один путь"))
                return 1
            for p in paths:
                add_path(config, name, p)
            save()
            prof = get_profile(config, name)
            console.print(f"   {icon('profiles')} Профиль '{name}' — "
                          f"{len(prof['paths'])} путей:")
            for p in prof["paths"]:
                console.print(f"      [fq.warm]{p}[/]")
            return 0

        if action == "remove-path":
            name = args.name
            paths = profile_paths_arg()
            if not paths:
                console.print(error_panel(console, "Нужен хотя бы один путь"))
                return 1
            for p in paths:
                remove_path(config, name, p)
            save()
            prof = get_profile(config, name)
            print(f"➖ Profile '{name}' now has {len(prof['paths'])} path(s):")
            for p in prof["paths"]:
                print(f"      {p}")
            return 0

        if action == "show":
            name = args.name
            prof = get_profile(config, name)
            active = active_name(config)
            marker = " (active)" if name == active else ""
            print(f"🗂  Profile '{name}'{marker}")
            if prof.get("description"):
                print(f"   Description: {prof['description']}")
            print(f"   Paths ({len(prof['paths'])}):")
            for p in prof["paths"]:
                exists = "✓" if Path(p).exists() else "✗ (missing)"
                print(f"      {exists} {p}")
            extra = prof.get("exclude_patterns") or []
            if extra:
                print(f"   Extra excludes: {', '.join(extra)}")
            return 0

        if action == "describe":
            name = args.name
            set_description(config, name, getattr(args, "description", ""))
            save()
            print(f"📝 Profile '{name}' description updated")
            return 0

        console.print(error_panel(console, f"Неизвестное действие профиля: {action}"))
        return 1

    except ProfileError as e:
        console.print(error_panel(console, str(e)))
        return 1


def cmd_config(args):
    """Show or edit configuration."""
    config = load_config()
    
    if args.edit:
        config_path = Path.home() / ".flamquency" / "config.yaml"
        editor = os.environ.get("EDITOR", "nano")
        os.system(f"{editor} {config_path}")
        return 0
    
    console.print(banner(console, "Конфигурация", icon_name="settings"))
    print(f"   Config file: ~/.flamquency/config.yaml\n")
    print(json.dumps(config, indent=2, default=str))
    return 0


def cmd_init(args):
    """Quick setup: create config, ignore file, and (optionally) repo."""
    config_dir = Path.home() / ".flamquency"
    config_dir.mkdir(parents=True, exist_ok=True)

    config = load_config()

    # 1. Ignore file
    ignore_path = default_ignore_path()
    if not ignore_path.exists() and not args.skip_ignore:
        from flamquency.ignore import default_template
        ignore_path.write_text(default_template())
        console.print(success_panel(console, f"Создан {ignore_path}", icon_name="folder"))
    elif ignore_path.exists():
        console.print(info_panel(console, f"Ignore-файл существует: {ignore_path}"))

    # 2. Retention defaults (если не заданы)
    retention = config.get("retention")
    if not retention:
        config["retention"] = {"keep_last": args.keep_last}
        save_config(config)
        console.print(success_panel(console, f"Хранение: последние {args.keep_last} снапшотов", icon_name="clock"))

    # 3. Опционально: git-репозиторий для снапшотов
    if args.git:
        snapshots_dir = config_dir / "snapshots"
        if not (snapshots_dir / ".git").exists():
            import subprocess
            subprocess.run(["git", "init", "-q"], cwd=snapshots_dir, check=False)
            console.print(success_panel(console, f"Git-репозиторий создан в {snapshots_dir}", icon_name="branch"))
        else:
            console.print(info_panel(console, f"Git-репозиторий уже существует в {snapshots_dir}"))

    console.print(banner(console, "FlamQuency-Sync", "инициализация завершена", icon_name="fire"))
    print(f"   Config:  {config_dir / 'config.yaml'}")
    print(f"   Ignore:  {ignore_path}")
    print(f"   Snapshots: {config_dir / 'snapshots'}")
    console.print("\n[fq.section]Что дальше:[/]")
    console.print(f"   [fq.accent]1.[/] flamquency status          — проверить состояние")
    console.print(f"   [fq.accent]2.[/] flamquency sync            — первый синк")
    console.print(f"   [fq.accent]3.[/] flamquency-tui             — запустить TUI")
    return 0


def cmd_prune(args):
    """Prune old snapshots (restic-style retention policy)."""
    console = get_console()
    sync = get_sync_engine()

    # Параметры из CLI или конфига
    policy = {}
    for key, attr in (
        ("keep_last", "keep_last"),
        ("older_than_days", "older_than"),
        ("keep_hourly", "keep_hourly"),
        ("keep_daily", "keep_daily"),
        ("keep_weekly", "keep_weekly"),
        ("keep_monthly", "keep_monthly"),
        ("keep_yearly", "keep_yearly"),
        ("keep_within", "keep_within"),
    ):
        val = getattr(args, attr, None)
        if val is not None:
            policy[key] = val

    if not policy:
        policy = dict(sync.config.get("retention") or {})

    if not policy:
        console.print(error_panel(
            console,
            "Политика хранения не задана.\n"
            "Используйте: flamquency prune --keep-last 5 --keep-daily 7 "
            "--keep-weekly 4 --keep-monthly 12\n"
            "или задайте retention в ~/.flamquency/config.yaml",
            title="Нет политики хранения", icon_name="warning"))
        return 1

    snapshots = sync.list_snapshots()
    policy_rows = [(k.replace("_", " "), v) for k, v in policy.items()]

    console.print(banner(console, "Очистка снапшотов",
                         f"всего на диске: {len(snapshots)}",
                         icon_name="trash"))
    console.print(card(console, key_value(policy_rows),
                       title=f"{icon('clock')} Политика хранения"))

    if args.dry_run:
        console.print(info_panel(
            console, "Режим предпросмотра — ничего не удалено. "
                      "Повторите без --dry-run для применения.",
            title="Dry-run", icon_name="info"))
        if not args.yes:
            confirm = input("Применить политику? [y/N] ")
            if confirm.lower() != "y":
                console.print("[fq.faint]Отменено[/]")
                return 0
        deleted, msg = sync.prune_snapshots(**policy)
    else:
        if not args.yes:
            confirm = input(f"Удалить снапшоты по политике? [y/N] ")
            if confirm.lower() != "y":
                console.print("[fq.faint]Отменено[/]")
                return 0
        deleted, msg = sync.prune_snapshots(**policy)

    if deleted:
        console.print(success_panel(console, msg, icon_name="trash"))
    else:
        console.print(info_panel(console, msg, icon_name="info"))
    return 0


def cmd_check(args):
    """Проверка целостности хранилища (аналог restic check)."""
    console = get_console()
    sync = get_sync_engine()

    console.print(banner(console, "Проверка целостности", icon_name="shield"))
    ok, problems = sync.check_integrity()

    if ok:
        stats = sync.version_store.stats()
        console.print(success_panel(
            console,
            key_value([
                ("Блобов проверено", stats.get("blob_count", 0)),
                ("Битых блобов", 0),
                ("Размер хранилища", human_size(stats.get("stored_bytes", 0))),
            ]),
            title="Хранилище целостно", icon_name="success"))
        return 0

    console.print(error_panel(
        console,
        "\n".join(f"{icon('error')} {p}" for p in problems[:20]),
        title=f"Найдено проблем: {len(problems)}",
        icon_name="error"))
    return 1


def cmd_stats(args):
    """Статистика хранилища: дедупликация, размер, шифрование, графики."""
    from flamquency.style import bar_chart, sparkline
    console = get_console()
    sync = get_sync_engine()
    stats = sync.version_store.stats()

    saved = stats.get("uncompressed_bytes", 0) - stats.get("stored_bytes", 0)
    saved_pct = 0
    if stats.get("uncompressed_bytes"):
        saved_pct = 100.0 * saved / stats["uncompressed_bytes"]
    # На крошечных файлах метаданные блобов весят больше содержимого —
    # отрицательная экономия честная, но подаём её нейтрально
    if saved >= 0:
        saved_label = f"[fq.success]{human_size(saved)} ({saved_pct:.1f}%)[/]"
    else:
        saved_label = (f"[fq.warning]{human_size(saved)} "
                       f"({saved_pct:.1f}%)[/] [fq.faint]файлы мельче метаданных[/]")

    console.print(banner(console, "Статистика хранилища",
                         "дедупликация и использование места",
                         icon_name="chart"))

    dedup = sync.dedup_report()
    rows = [
        ("Блобов", f"[bold]{stats.get('blob_count', 0)}[/]"),
        ("Версий всего", dedup["versions"]),
        ("Дублей схлопнуто", f"[fq.success]{dedup['duplicate_versions']}[/]"),
        ("Исходный размер", human_size(stats.get("uncompressed_bytes", 0))),
        ("На диске", f"[bold]{human_size(stats.get('stored_bytes', 0))}[/]"),
        ("Сэкономлено", saved_label),
        ("Коэффициент", f"{stats.get('ratio', 0):.2f}x"),
        ("Зашифровано блобов", stats.get("encrypted_blobs", 0)),
    ]
    console.print(card(console, key_value(rows),
                       title=f"{icon('chart')} Blob store"))

    by_type = sync.stats_by_type(limit=8)
    if by_type:
        console.print(card(
            console,
            bar_chart([(ext, size) for ext, _files, size in by_type]),
            title=f"{icon('pie')} По типам файлов", icon_name="pie"))
        console.print(card(
            console, make_table(
                ["Тип", "Файлов", "Размер"],
                [(f"{icon('file')} {ext}", files, human_size(size))
                 for ext, files, size in by_type]),
            title="Детализация по типам"))

    # Фокусные режимы: показываем только запрошенное и выходим
    if args.by_type:
        return 0

    top_limit = args.top or 10
    top = sync.top_changed_files(limit=top_limit)
    if top:
        console.print(card(
            console, make_table(
                ["Файл", "Версий", "Размер"],
                [(path, count, human_size(size)) for path, count, size in top]),
            title=f"{icon('history')} Топ изменяемых", icon_name="history"))
    if args.top:
        return 0

    if args.graphs:
        timeline = sync.storage_timeline()
        if timeline:
            console.print(card(
                console, sparkline([size for _t, _f, size in timeline]),
                title=f"{icon('graph')} Рост хранилища", icon_name="graph"))
            console.print(card(
                console, make_table(
                    ["Снапшот", "Файлов", "Размер"],
                    [(stamp, files, human_size(size))
                     for stamp, files, size in timeline]),
                title="Хронология снапшотов"))
        else:
            console.print(info_panel(
                console, "Снапшотов пока нет — график появится после синков.",
                title="Нечего рисовать", icon_name="info"))
    return 0


def cmd_update(args):
    """Проверка и установка обновлений."""
    console = get_console()
    from flamquency import __version__

    console.print(banner(console, "Обновление",
                         f"установлена версия {__version__}",
                         icon_name="update"))

    if args.check:
        console.print(f"[fq.label]{icon('cloud')} Проверяю GitHub...[/]")
        info = check_for_update(__version__, use_cache=not args.no_cache)
        _print_update_info(console, info)
        return 0

    # Полная проверка + установка
    console.print(f"[fq.label]{icon('cloud')} Проверяю обновления...[/]")
    info = check_for_update(__version__, use_cache=not args.no_cache)
    _print_update_info(console, info)

    if not info.available:
        return 0

    if not args.yes:
        confirm = input(f"\nОбновить {info.current} → {info.latest}? [y/N] ")
        if confirm.lower() != "y":
            console.print("[fq.faint]Отменено[/]")
            return 0

    console.print(f"[fq.label]{icon('download')} Скачиваю {info.latest}...[/]")
    ok, msg = perform_update(dry_run=args.dry_run)
    if ok:
        console.print(success_panel(console, msg, icon_name="update"))
    else:
        console.print(error_panel(console, msg, icon_name="error"))
    return 0 if ok else 1


def _print_update_info(console, info):
    """Единый вывод результата проверки обновлений."""
    # Репо доступен, но релизов ещё нет — это не ошибка
    if info.error == "релизов ещё не опубликовано":
        console.print(success_panel(
            console,
            f"Установлена последняя версия [bold]{info.current}[/]\n"
            f"[fq.faint]релизов в репозитории ещё не опубликовано — "
            f"обновиться можно через git pull[/]",
            title="Обновлений нет", icon_name="success"))
        return
    if info.error:
        console.print(warning_panel(
            console, f"{info.error}\n\nПроверьте соединение или обновите "
                      f"вручную:\n{info.url}",
            title="Не удалось проверить", icon_name="warning"))
        return
    if info.available:
        notes = ""
        if info.release_notes:
            notes = f"\n\n[fq.label]Что нового:[/]\n{info.release_notes}"
        console.print(info_panel(
            console,
            f"Доступна версия [bold]{info.latest}[/] "
            f"(у вас {info.current})\n"
            f"Источник: {info.source}{notes}\n\n"
            f"Обновить: flamquency update --yes",
            title=f"{icon('update')} Новая версия",
            icon_name="update"))
    else:
        console.print(success_panel(
            console, f"Установлена последняя версия "
                      f"[bold]{info.current}[/]\n"
                      f"Источник: {info.source}",
            title="Обновлений нет", icon_name="success"))


def build_parser():
    """Построить argparse-парсер CLI.

    Вынесено из ``main()``, чтобы генератор completion-скриптов и любой
    другой инструмент могли получить тот же список команд и флагов, не
    запуская саму программу.
    """
    parser = argparse.ArgumentParser(
        prog="flamquency",
        description=f"{icon('fire')} Terminal-based file synchronization with version control",
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # sync
    p_sync = subparsers.add_parser("sync", help="Synchronize files")
    p_sync.add_argument("--source", "-s", help="Source directory (bypasses profiles)")
    p_sync.add_argument("--profile", "-P", metavar="NAME",
                        help="Sync this profile instead of the active one")
    p_sync.add_argument("--password", "-p", help="Blob store password (else env FLAMQUENCY_PASSWORD)")
    
    # rollback
    p_rb = subparsers.add_parser("rollback", help="Rollback to snapshot")
    p_rb.add_argument("--snapshot", "-s", type=int, help="Snapshot index")
    p_rb.add_argument("--list", "-l", action="store_true", help="List snapshots")
    
    # rollback-file
    p_rbf = subparsers.add_parser("rollback-file", help="Rollback specific file")
    p_rbf.add_argument("file", help="File path")
    p_rbf.add_argument("--version", "-v", type=int, help="Version index")
    p_rbf.add_argument("--list", "-l", action="store_true", help="List versions")
    
    # restore-content
    p_rc = subparsers.add_parser(
        "restore-content",
        help="Restore the content of a specific version to any path")
    p_rc.add_argument("file", help="File path (as tracked in the store)")
    p_rc.add_argument("--version", "-v", type=int,
                      help="Version index (default: latest)")
    p_rc.add_argument("--output", "-o", metavar="PATH",
                      help="Destination path (default: original location)")
    p_rc.add_argument("--list", "-l", action="store_true", help="List versions")
    p_rc.add_argument("--password", "-p", help="Blob store password")

    # view-content
    p_vc = subparsers.add_parser(
        "view-content",
        help="Print the content of a specific version (no restore)")
    p_vc.add_argument("file", help="File path (as tracked in the store)")
    p_vc.add_argument("--version", "-v", type=int,
                      help="Version index (default: latest)")
    p_vc.add_argument("--max-bytes", type=int, default=1_048_576,
                      metavar="N", help="Content cap in bytes (default: 1 MiB)")
    p_vc.add_argument("--list", "-l", action="store_true", help="List versions")
    p_vc.add_argument("--password", "-p", help="Blob store password")

    # restore-tree
    p_rt = subparsers.add_parser(
        "restore-tree",
        help="Restore a whole directory, a profile, or the entire store")
    p_rt.add_argument("path", nargs="?",
                      help="Directory prefix to restore (default: everything)")
    p_rt.add_argument("--profile", "-P", metavar="NAME",
                      help="Restore only files belonging to this profile")
    p_rt.add_argument("--version", "-v", type=int,
                      help="Version index per file (default: latest of each)")
    p_rt.add_argument("--output", "-o", metavar="DIR",
                      help="Root the files are restored under")
    p_rt.add_argument("--list", "-l", action="store_true",
                      help="List tracked files instead of restoring")
    p_rt.add_argument("--verbose", action="store_true",
                      help="Print a table of restored files")
    p_rt.add_argument("--password", "-p", help="Blob store password")

    # schedule
    p_sched = subparsers.add_parser(
        "schedule", help="Set up a recurring sync schedule (cron / Task Scheduler)")
    p_sched.add_argument("interval", nargs="?",
                         help="«каждый час», «каждые 30 минут», «daily», "
                              "или cron из 5 полей")
    p_sched.add_argument("--profile", "-P", metavar="NAME",
                         help="Profile to sync on schedule")
    p_sched.add_argument("--remove", action="store_true",
                         help="Remove the current schedule")

    # backend
    p_be = subparsers.add_parser(
        "backend", help="Manage storage backends: list / use / check")
    p_be.add_argument("action", nargs="?",
                      choices=["list", "use", "check"], default="list",
                      help="What to do (default: list)")
    p_be.add_argument("name", nargs="?",
                      help="Backend name for use/check")
    p_be.add_argument("--use", metavar="NAME",
                      help="Switch the active backend to NAME")
    p_be.add_argument("--check", metavar="NAME",
                      help="Check whether NAME is ready to use")

    # evolve
    p_evo = subparsers.add_parser(
        "evolve", help="«Эволюция»: самообучение на привычках и предложения")
    p_evo.add_argument("--apply", action="store_true",
                       help="Apply every suggestion")
    p_evo.add_argument("--decay", action="store_true",
                       help="Cool down all file heat")
    p_evo.add_argument("--forget", nargs="+", metavar="PATH",
                       help="Forget these files' heat")

    # spark
    p_spark = subparsers.add_parser(
        "spark", help="«Огниво» — run your own quick actions")
    p_spark.add_argument("action", nargs="?",
                         help="Spark name to run, or set/remove/show")
    p_spark.add_argument("name", nargs="?", help="Spark name (for set/remove/show)")
    p_spark.add_argument("value", nargs="?", help="Command (for set)")
    p_spark.add_argument("--description", "-d", default="",
                         help="Description for set")
    p_spark.add_argument("--list", "-l", action="store_true",
                         help="List all sparks")
    p_spark.add_argument("--dry-run", action="store_true",
                         help="Print the command without running it")

    # echo
    p_echo = subparsers.add_parser(
        "echo", help="«Эхо памяти» — suggest paths to sync from shell history")
    p_echo.add_argument("--add", type=int, metavar="N", default=0,
                        help="Add the top N new candidates to the active profile")

    # kaleido
    p_kal = subparsers.add_parser(
        "kaleido", help="«Калейдоскоп» — colour variations of the «Угольки» theme")
    p_kal.add_argument("use", nargs="?", metavar="NAME",
                       help="Activate this variation")
    p_kal.add_argument("--random", action="store_true",
                       help="Preview a random variation")
    p_kal.add_argument("--seed", type=int,
                       help="Seed for --random (reproducible)")

    # help
    p_help = subparsers.add_parser(
        "help", help="Rich, detailed help for one command")
    p_help.add_argument("topic", nargs="?", help="Command to explain")

    # status
    subparsers.add_parser("status", help="Show sync status")
    
    # diff
    p_diff = subparsers.add_parser("diff", help="Diff two versions of a file")
    p_diff.add_argument("file", help="File path")
    p_diff.add_argument("--v1", type=int, required=True, help="First version")
    p_diff.add_argument("--v2", type=int, required=True, help="Second version")
    
    # snapshots
    subparsers.add_parser("snapshots", help="List snapshots")
    
    # init
    p_init = subparsers.add_parser("init", help="Quick setup: config, ignore file, retention")
    p_init.add_argument("--keep-last", type=int, default=10,
                        help="Keep last N snapshots (default: 10)")
    p_init.add_argument("--git", action="store_true",
                        help="Init git repo in snapshots dir")
    p_init.add_argument("--skip-ignore", action="store_true",
                        help="Don't create .flamquencyignore")
    
    # prune
    p_prune = subparsers.add_parser("prune", help="Prune old snapshots (restic-style retention)")
    p_prune.add_argument("--keep-last", type=int, help="Keep last N snapshots")
    p_prune.add_argument("--older-than", type=int, metavar="DAYS",
                         help="Keep snapshots newer than DAYS")
    p_prune.add_argument("--keep-hourly", type=int, help="Keep last snapshot of each of last N hours")
    p_prune.add_argument("--keep-daily", type=int, help="Keep last snapshot of each of last N days")
    p_prune.add_argument("--keep-weekly", type=int, help="Keep last snapshot of each of last N weeks")
    p_prune.add_argument("--keep-monthly", type=int, help="Keep last snapshot of each of last N months")
    p_prune.add_argument("--keep-yearly", type=int, help="Keep last snapshot of each of last N years")
    p_prune.add_argument("--keep-within", metavar="DUR",
                         help="Keep snapshots newer than DUR (e.g. 1y6m2w4d)")
    p_prune.add_argument("--dry-run", action="store_true", help="Preview without deleting")
    p_prune.add_argument("--yes", "-y", action="store_true", help="Skip confirmation")

    # check
    subparsers.add_parser("check", help="Verify blob store integrity")

    # stats
    p_stats = subparsers.add_parser("stats", help="Storage statistics and charts")
    p_stats.add_argument("--graphs", "-g", action="store_true",
                         help="Show the storage growth sparkline and snapshot "
                              "timeline")
    p_stats.add_argument("--by-type", action="store_true",
                         help="Only the per-file-type breakdown")
    p_stats.add_argument("--top", type=int, metavar="N",
                         help="Only the top N most-changed files")
    p_stats.add_argument("--password", "-p", help="Blob store password")

    # update
    p_update = subparsers.add_parser("update", help="Check and install updates")
    p_update.add_argument("--check", action="store_true",
                          help="Only check, don't install")
    p_update.add_argument("--yes", "-y", action="store_true",
                          help="Install without confirmation")
    p_update.add_argument("--no-cache", action="store_true",
                          help="Ignore cached check result")
    p_update.add_argument("--dry-run", action="store_true",
                          help="Show update command without running it")
    
    # watch
    p_watch = subparsers.add_parser("watch", help="Watch mode — auto-sync")
    p_watch.add_argument("paths", nargs="*", help="Paths to watch")
    
    # config
    p_config = subparsers.add_parser("config", help="Show/edit configuration")
    p_config.add_argument("--edit", "-e", action="store_true", help="Edit config")

    # encryption
    p_enc = subparsers.add_parser("encryption", help="Manage blob encryption")
    p_enc.add_argument(
        "action",
        choices=["status", "enable", "disable", "change-password"],
        help="What to do with encryption",
    )
    p_enc.add_argument("--password", "-p", help="Password (else env FLAMQUENCY_PASSWORD or prompt)")
    p_enc.add_argument("--new-password", help="New password for change-password (else prompt)")

    # ignore
    p_ign = subparsers.add_parser(
        "ignore", help="Manage ~/.flamquencyignore (gitignore-style rules)"
    )
    p_ign.add_argument("--path", help="Ignore file path (default: ~/.flamquencyignore)")
    p_ign.add_argument("--init", action="store_true", help="Create the default ignore file")
    p_ign.add_argument("--force", action="store_true", help="Overwrite with --init even if it exists")
    p_ign.add_argument("--add", metavar="PATTERN", help="Append a pattern to the file")
    p_ign.add_argument("--check", metavar="PATH", help="Explain whether a path is ignored")
    p_ign.add_argument("--list", "-l", action="store_true", help="List the loaded rules")
    # ── глобальные правила по размеру и типу (v2.0) ──
    p_ign.add_argument("--size-gt", metavar="SIZE",
                       help="Ignore files larger than SIZE (e.g. 1GB)")
    p_ign.add_argument("--size-lt", metavar="SIZE",
                       help="Ignore files smaller than SIZE (e.g. 10KB)")
    p_ign.add_argument("--types", metavar="LIST",
                       help="Ignore these extensions (e.g. mp4,avi,mkv)")
    p_ign.add_argument("--clear-global", action="store_true",
                       help="Drop all global size/type rules")

    # profile
    p_prof = subparsers.add_parser(
        "profile", help="Manage sync profiles (named sets of paths)"
    )
    p_prof.add_argument(
        "action",
        choices=["list", "create", "delete", "use", "show",
                 "add-path", "remove-path", "describe"],
        nargs="?",
        default="list",
        help="What to do (default: list)",
    )
    p_prof.add_argument("name", nargs="?", help="Profile name")
    p_prof.add_argument("paths", nargs="*", metavar="PATH",
                        help="Paths (positional form: remove-path NAME PATH...)")
    p_prof.add_argument("--path", action="append", default=[], metavar="PATH",
                        help="Path (repeatable) — used by create/add-path/remove-path")
    p_prof.add_argument("--description", "-d", default="",
                        help="Profile description (create / describe)")
    p_prof.add_argument("--exclude", action="append", default=[],
                        metavar="PATTERN",
                        help="Extra exclude pattern for the profile (repeatable)")

    return parser


def main():
    """Точка входа CLI: разобрать аргументы и запустить команду."""
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        # Default to TUI
        from flamquency.main import main as tui_main
        tui_main()
        return

    commands = {
        "sync": cmd_sync,
        "rollback": cmd_rollback,
        "rollback-file": cmd_rollback_file,
        "restore-content": cmd_restore_content,
        "view-content": cmd_view_content,
        "restore-tree": cmd_restore_tree,
        "schedule": cmd_schedule,
        "backend": cmd_backend,
        "evolve": cmd_evolve,
        "spark": cmd_spark,
        "echo": cmd_echo,
        "kaleido": cmd_kaleido,
        "help": cmd_help,
        "status": cmd_status,
        "diff": cmd_diff,
        "snapshots": cmd_snapshots,
        "init": cmd_init,
        "prune": cmd_prune,
        "check": cmd_check,
        "stats": cmd_stats,
        "update": cmd_update,
        "watch": cmd_watch,
        "config": cmd_config,
        "encryption": cmd_encryption,
        "ignore": cmd_ignore,
        "profile": cmd_profile,
    }

    handler = commands.get(args.command)
    if handler:
        sys.exit(handler(args))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
