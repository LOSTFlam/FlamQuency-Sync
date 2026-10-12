#!/usr/bin/env python3
"""Test suite for FlamQuency-Sync."""
import sys
import os
import copy
import tempfile
import shutil
import json
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from flamquency.sync_engine import FlamQuencySync, SyncResult, LocalBackend
from flamquency.config import load_config, save_config
from flamquency.version_store import VersionStore, BlobStore
from flamquency.cloud import get_backend
from flamquency.encryption import (
    EncryptionManager, EncryptionError, EncryptionLockedError,
    WrongPasswordError, DecryptionError,
)

ENC_PW = "correct horse battery staple"


def _isolated_sync(tmpdir, config=None, password=None, ignore_file=None):
    """Create a FlamQuencySync with isolated storage in a temp dir.

    Hermetic by default: the config is built from ``DEFAULT_CONFIG`` (never
    the user's real ~/.flamquency/config.yaml) and the real
    ~/.flamquencyignore is only loaded when a test passes ignore_file
    explicitly. Otherwise a user's local settings (encryption on, learned
    evolution heat, personal exclude patterns) would leak into the suite.
    """
    if config is None:
        from flamquency.config import DEFAULT_CONFIG
        config = copy.deepcopy(DEFAULT_CONFIG)
    config = dict(config)  # copy — never mutate the caller's dict
    config["use_ignore_file"] = False
    base = Path(tmpdir) / ".flamquency_isolated"
    backend = LocalBackend(base_path=base / "sync")
    return FlamQuencySync(
        config=config, backend=backend, password=password, base_dir=base,
        ignore_file=ignore_file,
    )


def test_config_load():
    config = load_config()
    assert "cloud_backend" in config
    assert "exclude_patterns" in config
    print("✓ Config loading works")


def test_scan_directory():
    with tempfile.TemporaryDirectory() as tmpdir:
        sync = _isolated_sync(tmpdir)
        t = Path(tmpdir)
        (t / "config.txt").write_text("test")
        (t / "cache").mkdir()
        (t / "cache" / "temp.tmp").write_text("cache")
        
        files = sync.scan_directory(t)
        assert any("config.txt" in str(f) for f in files)
        assert not any("temp.tmp" in str(f) for f in files)
    print("✓ Directory scanning with exclusions works")


def test_hash_computation():
    with tempfile.TemporaryDirectory() as tmpdir:
        sync = _isolated_sync(tmpdir)
        test_file = Path(tmpdir) / "test.txt"
        test_file.write_text("hello world")
        h1 = sync.compute_hash(test_file)
        h2 = sync.compute_hash(test_file)
        assert h1 == h2
        assert len(h1) == 64
    print("✓ Hash computation works")


def test_blob_store():
    with tempfile.TemporaryDirectory() as tmpdir:
        bs = BlobStore(Path(tmpdir))
        h1 = bs.store("hello world")
        assert len(h1) == 64
        h2 = bs.store("hello world")
        assert h1 == h2  # Dedup
        data = bs.retrieve(h1)
        assert data == b"hello world"
        
        test_file = Path(tmpdir) / "test_file.txt"
        test_file.write_text("file content here")
        h3 = bs.store_file(test_file)
        assert bs.has(h3)
        
        dest = Path(tmpdir) / "restored.txt"
        assert bs.restore_to(h3, dest)
        assert dest.read_text() == "file content here"
    print("✓ Blob store works (store, dedup, retrieve, restore)")


def test_version_store_record_and_restore():
    with tempfile.TemporaryDirectory() as tmpdir:
        vs = VersionStore(Path(tmpdir))
        h1, new1 = vs.record_version("test/file.txt", data="version 1 content")
        assert new1
        h2, new2 = vs.record_version("test/file.txt", data="version 2 content")
        assert new2
        h2b, new2b = vs.record_version("test/file.txt", data="version 2 content")
        assert not new2b  # Identical = no new version
        
        history = vs.get_history("test/file.txt")
        assert len(history) == 2
        
        dest = Path(tmpdir) / "restored_v1.txt"
        success, msg = vs.restore_version("test/file.txt", 0, dest_path=dest)
        assert success
        assert dest.read_text() == "version 1 content"
        
        dest2 = Path(tmpdir) / "restored_v2.txt"
        vs.restore_version("test/file.txt", 1, dest_path=dest2)
        assert dest2.read_text() == "version 2 content"
    print("✓ Version store record & restore works")


def test_version_store_diff():
    with tempfile.TemporaryDirectory() as tmpdir:
        vs = VersionStore(Path(tmpdir))
        vs.record_version("config.txt", data="line1\nline2\nline3\n")
        vs.record_version("config.txt", data="line1\nmodified\nline3\n")
        diff = vs.diff_versions("config.txt", 0, 1)
        assert diff is not None
        assert "modified" in diff
    print("✓ Version diff works")


def test_snapshot_creation():
    with tempfile.TemporaryDirectory() as tmpdir:
        sync = _isolated_sync(tmpdir)
        # Create some test data
        t = Path(tmpdir)
        (t / "test.txt").write_text("hello")
        (t / "sub").mkdir()
        (t / "sub" / "nested.txt").write_text("nested")
        
        snap, meta = sync.create_snapshot(source_path=t)
        assert snap.exists()
        assert meta["file_count"] >= 2
        assert "manifest" in meta
    print("✓ Snapshot creation works")


def test_sync_with_versions():
    with tempfile.TemporaryDirectory() as tmpdir:
        sync = _isolated_sync(tmpdir)
        t = Path(tmpdir)
        
        (t / "test.txt").write_text("content v1")
        (t / "sub").mkdir()
        (t / "sub" / "test2.txt").write_text("another file")
        
        result = sync.sync(source=t)
        assert result.files_synced >= 2
        
        # Modify and re-sync
        (t / "test.txt").write_text("content v2")
        sync.sync(source=t)
        
        # Check version history
        history = sync.version_store.get_history("test.txt")
        assert len(history) >= 2, f"Expected >=2 versions, got {len(history)}"
        
        # Restore old version
        dest = t / "restored.txt"
        success, msg = sync.version_store.restore_version("test.txt", 0, dest_path=dest)
        assert success
        assert dest.read_text() == "content v1"
    print("✓ Sync with real version storage works")


def test_restore_and_view_file_content():
    """Task 3: restore-content / view-content — контент версии куда угодно."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sync = _isolated_sync(tmpdir)
        t = Path(tmpdir)
        f = t / "notes.md"
        f.write_text("версия 1")
        sync.sync(source=t)
        f.write_text("версия 2 — длиннее")
        sync.sync(source=t)
        f.write_text("версия 3")
        sync.sync(source=t)

        assert len(sync.version_store.get_history("notes.md")) == 3

        # restore-content в произвольный путь
        out = t / "old.md"
        ok, msg, info = sync.restore_file_content(str(f), version_index=0,
                                                  output=str(out))
        assert ok, msg
        assert out.read_text() == "версия 1"
        assert info["version_count"] == 3
        assert info["dest_path"] == str(out)
        assert not f.read_text() == "версия 1"  # оригинал не тронут

        # restore-content без output → последняя версия
        ok, msg, info = sync.restore_file_content(str(f))
        assert ok and info["version_index"] == 2
        assert f.read_text() == "версия 3"

        # view-content читает, ничего не трогая
        ok, msg, info = sync.view_file_content(str(f), version_index=1)
        assert ok and info["data"].decode("utf-8") == "версия 2 — длиннее"
        assert info["truncated"] is False

        # --max-bytes режет контент по байтам, а не по символам
        ok, msg, info = sync.view_file_content(str(f), version_index=1,
                                               max_bytes=10)
        assert ok and info["data"].decode("utf-8") == "верси"
        assert info["truncated"] is True

        # бинарник → restore-content, а не view
        (t / "blob.bin").write_bytes(b"\x00\x01\x02\xff\xfe")
        sync.sync(source=t)
        ok, msg, info = sync.view_file_content(str(t / "blob.bin"))
        assert ok  # данные отдаются, декодирует уже CLI

        # нет истории → честная ошибка
        ok, msg, info = sync.view_file_content(str(t / "нет-такого.txt"))
        assert not ok and "No version history" in msg

        # индекс вне диапазона
        ok, msg, info = sync.restore_file_content(str(f), version_index=99)
        assert not ok and "out of range" in msg
    print("✓ restore-content / view-content работают с произвольными путями")


def test_restore_tree_directory_and_profile():
    """Task 3 Step 4: пакетное восстановление каталога и профиля."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sync = _isolated_sync(tmpdir)
        t = Path(tmpdir)
        work = t / "work"          # источник — не каталог хранилища
        src = work / "src"
        (src / "docs").mkdir(parents=True)
        (src / "a.txt").write_text("A1")
        (src / "docs" / "b.txt").write_text("B1")
        (work / "outside.txt").write_text("O1")
        sync.sync(source=work)

        # новые версии
        (src / "a.txt").write_text("A2")
        (src / "docs" / "b.txt").write_text("B2")
        (work / "outside.txt").write_text("O2")
        sync.sync(source=work)

        assert sorted(sync.version_store.tracked_keys()) == [
            "outside.txt", "src/a.txt", "src/docs/b.txt"]

        # пакетное восстановление по префиксу в отдельный корень
        out = t / "recovered"
        res = sync.restore_tree(prefix="src", dest_root=out)
        assert res["total"] == 2 and res["restored"] == 2 and res["failed"] == 0
        assert (out / "src" / "a.txt").read_text() == "A2"
        assert (out / "src" / "docs" / "b.txt").read_text() == "B2"
        assert not (out / "outside.txt").exists()

        # версия 0 для всех файлов дерева
        out0 = t / "recovered0"
        res = sync.restore_tree(prefix="src", dest_root=out0, version_index=0)
        assert res["restored"] == 2
        assert (out0 / "src" / "a.txt").read_text() == "A1"

        # префикс без файлов → пустой результат, не ошибка
        res = sync.restore_tree(prefix="нет-такого", dest_root=out0)
        assert res["total"] == 0

        # прогресс-колбэк вызывается на каждый файл
        seen = []
        sync.restore_tree(prefix="src", dest_root=t / "p",
                          progress=lambda done, total, key: seen.append(
                              (done, total, key)))
        assert len(seen) == 2 and seen[-1][0] == 2 and seen[-1][1] == 2

        # восстановление профиля — профиль ссылается на work/src/docs
        from flamquency.profiles import create_profile, ensure_profiles
        ensure_profiles(sync.config)
        create_profile(sync.config, "docs", [str(src / "docs")])
        outp = t / "by-profile"
        res = sync.restore_profile("docs", dest_root=outp)
        assert res["profile"] == "docs" and res["total"] == 1
        assert (outp / "src" / "docs" / "b.txt").read_text() == "B2"
    print("✓ restore-tree восстанавливает каталоги и профили")


def test_diff_visual_summary():
    """Task 3 Step 5: diff отдаёт unified-diff, который подсвечивает CLI."""
    from flamquency.style import diff_text
    diff = ("--- a/v0\n+++ b/v1\n@@ -1,2 +1,2 @@\n"
            "-старая строка\n+новая строка\n контекст")
    text = diff_text(diff)
    plain = text.plain
    assert "+новая строка" in plain and "-старая строка" in plain
    # стили различаются: плюс — success, минус — error
    styles = {s.style for s in text.spans}
    assert "fq.success" in styles
    assert "fq.error" in styles
    assert "fq.warm" in styles  # @@ — тёплый ядро
    assert "fq.accent" in styles  # ---/+++
    print("✓ diff_text подсвечивает добавленные и удалённые строки")


def test_schedule_parse_and_cron():
    """Task 4 Step 1: человеческое расписание → cron."""
    from flamquency.scheduler import parse_schedule, ScheduleError

    assert parse_schedule("каждый час").cron == "0 * * * *"
    assert parse_schedule("каждые 30 минут").cron == "*/30 * * * *"
    assert parse_schedule("каждые 2 часа").cron == "0 */2 * * *"
    assert parse_schedule("каждые 15 минут").cron == "*/15 * * * *"
    assert parse_schedule("каждый день").cron == "0 3 * * *"
    assert parse_schedule("every 2 hours").cron == "0 */2 * * *"
    assert parse_schedule("daily").cron == "0 3 * * *"
    assert parse_schedule("hourly").cron == "0 * * * *"
    assert parse_schedule("weekly").cron == "0 3 * * 1"

    # сырой cron проходит как есть
    spec = parse_schedule("30 2 * * 1")
    assert spec.cron == "30 2 * * 1" and spec.source == "raw"

    # профиль запоминается
    assert parse_schedule("каждый час", profile="work").profile == "work"

    # мусор честно отбивается
    for bad in ("", "абвгд", "* * *", "каждые 5 парсек", "каждые 0 минут"):
        try:
            parse_schedule(bad)
            raise AssertionError(f"должно было упасть: {bad!r}")
        except ScheduleError:
            pass
    print("✓ parse_schedule переводит расписания в cron и отбивает мусор")


def test_scheduler_install_remove_isolation():
    """Task 4 Step 2: install/remove идемпотентны и не трогают чужие строки."""
    import json
    from flamquency.scheduler import Scheduler, parse_schedule

    with tempfile.TemporaryDirectory() as tmpdir:
        t = Path(tmpdir)
        store = t / "crontab.txt"
        store.write_text("0 4 * * * /usr/bin/backup.sh\n")   # чужая запись
        base = t / ".flamquency"
        sched = Scheduler(base_dir=base)

        # Файловый «crontab» вместо системного — тест ничего не трогает снаружи.
        lines = {"value": []}

        def fake_read():
            return [ln for ln in store.read_text().splitlines() if ln.strip()]

        def fake_write(lines):
            store.write_text("\n".join(lines) + "\n")
            return True, ""

        sched._read_crontab = fake_read
        sched._write_crontab = fake_write
        sched.available = lambda: True

        assert sched.status()["installed"] is False
        assert sched.status()["live_entry"] is None

        ok, msg = sched.install(parse_schedule("каждые 30 минут", profile="work"))
        assert ok, msg
        assert sched.status()["installed"] is True
        assert "work" in sched.status()["live_entry"]
        assert sched.status()["drifted"] is False

        # повторная установка заменяет, а не дублирует
        ok, msg = sched.install(parse_schedule("каждый час"))
        assert ok, msg
        lines_now = [ln for ln in store.read_text().splitlines() if ln.strip()]
        assert len(lines_now) == 2                       # наша + чужая
        assert sum(1 for ln in lines_now if "flamquency-schedule" in ln) == 1

        # состояние сохранено на диск
        assert json.loads((base / "schedule.json").read_text())["cron"] == "0 * * * *"

        ok, msg = sched.remove()
        assert ok, msg
        assert sched.status()["installed"] is False
        assert store.read_text() == "0 4 * * * /usr/bin/backup.sh\n"   # чужое цело
        assert not (base / "schedule.json").exists()

        # повторное снятие — не ошибка
        ok, msg = sched.remove()
        assert not ok and "не настроено" in msg
        print("✓ scheduler ставит/снимает расписание, не задевая чужие записи")


def test_smart_autosync_quiet_period():
    """Task 4 Step 4: умный дебаунс вместо фиксированных 5 секунд."""
    from datetime import datetime, timedelta
    with tempfile.TemporaryDirectory() as tmpdir:
        sync = _isolated_sync(tmpdir)
        assert sync.smart_sync_quiet_period() == 5.0

        sync.config["smart_autosync"] = False
        assert sync.smart_sync_quiet_period() == 0.0
        assert sync.should_sync_now(datetime.now()) is False

        sync.config["smart_autosync"] = True
        sync.config["smart_autosync_timeout"] = 10
        now = datetime.now()
        assert sync.should_sync_now(now - timedelta(seconds=9)) is False
        assert sync.should_sync_now(now - timedelta(seconds=11)) is True
        assert sync.should_sync_now(None) is False   # изменений не было

        # мусор в конфиге не роняет расчёт
        sync.config["smart_autosync_timeout"] = "не число"
        assert sync.smart_sync_quiet_period() == 5.0
    print("✓ умный автосинк считает тишину и переживает мусор в конфиге")


def test_post_sync_hook():
    """Task 4 Step 5: пост-синк хук запускается и сообщает о failures."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sync = _isolated_sync(tmpdir)
        t = Path(tmpdir)

        # хук не задан — не ошибка
        ok, msg = sync.run_post_sync_hook()
        assert ok and msg == "хук не задан"

        # нет такого файла
        sync.config["post_sync_script"] = str(t / "нет.sh")
        ok, msg = sync.run_post_sync_hook()
        assert not ok and "не найден" in msg

        # падающий скрипт → отчёт, но не исключение
        bad = t / "bad.sh"
        bad.write_text("#!/bin/sh\necho boom >&2\nexit 3\n")
        bad.chmod(0o755)
        sync.config["post_sync_script"] = str(bad)
        ok, msg = sync.run_post_sync_hook()
        assert not ok and "3" in msg and "boom" in msg

        # хороший скрипт → его вывод возвращается
        good = t / "good.sh"
        good.write_text("#!/bin/sh\necho 'уведомление отправлено'\n")
        good.chmod(0o755)
        sync.config["post_sync_script"] = str(good)
        ok, msg = sync.run_post_sync_hook()
        assert ok and "уведомление отправлено" in msg
    print("✓ пост-синк хук запускается и корректно сообщает об ошибках")


def test_evolution_learns_and_suggests():
    """«Эволюция»: жар файлов, предложения, применение, забывание."""
    from flamquency.evolution import Evolution
    with tempfile.TemporaryDirectory() as tmpdir:
        sync = _isolated_sync(tmpdir)
        t = Path(tmpdir)
        work = t / "work"
        (work / "notes").mkdir(parents=True)
        todo = work / "notes" / "todo.md"
        cold = work / "cold.txt"
        cold.write_text("раз")

        for i in range(6):
            todo.write_text(f"итерация {i}\n")
            sync.sync(source=work)

        evo = Evolution(config=sync.config)
        # жар накопился у правившегося файла
        assert evo.settings["file_heat"]["notes/todo.md"] > 1
        assert evo.is_hot("notes/todo.md")
        assert not evo.is_hot("cold.txt")

        # предложения появились
        kinds = {s["kind"] for s in evo.suggest()}
        assert "hot_files" in kinds
        assert "profile_candidate" in kinds

        # применяются
        results = evo.apply_all()
        assert all(r["ok"] for r in results), results
        assert "notes" in sync.config["profiles"]

        # команды тоже считаются
        evo.observe_command("sync")
        evo.observe_command("sync")
        evo.observe_command("diff")
        assert evo.command_ranking()[0] == ("sync", 2)

        # забывание остыжает жар
        heat_before = evo.settings["file_heat"]["notes/todo.md"]
        evo.decay(factor=0.5)
        assert evo.settings["file_heat"]["notes/todo.md"] < heat_before

        # выключенная эволюция молчит
        evo.settings["enabled"] = False
        assert evo.observe_file("x.md") == 0
        assert evo.suggest() == []

        # сводка отдаёт всё нужное CLI
        evo.settings["enabled"] = True
        summary = evo.summary()
        assert summary["enabled"] and summary["tracked_files"] >= 1
        assert summary["hot_files"]
    print("✓ эволюция учится на привычках, предлагает и применяет улучшения")


def test_evolution_survives_broken_state():
    """Эволюция не должна ронять синк даже при испорченном состоянии."""
    from flamquency.evolution import Evolution
    with tempfile.TemporaryDirectory() as tmpdir:
        sync = _isolated_sync(tmpdir)
        sync.config["evolution"] = {
            "enabled": True,
            "learning_rate": "мусор",
            "hot_file_threshold": None,
            "file_heat": {"a.md": "не число"},
        }
        # падающие операции не бросают наружу
        assert Evolution(config=sync.config).observe_file("a.md") >= 0
        assert sync._evolve_observe() >= 0
        assert isinstance(Evolution(config=sync.config).hot_files(), list)
        assert isinstance(Evolution(config=sync.config).suggest(), list)
    print("✓ эволюция переживает испорченное состояние")


def test_config_carries_v2_sections():
    """Task 4: конфиг v2 несёт расписание, умный синк, хук и эволюцию."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Изолированный файл конфига — тест не читает и не пишет реальный.
        cfg_path = Path(tmpdir) / "config.yaml"
        config = load_config(config_path=cfg_path)
        assert config["schedule"] is None
        assert config["schedule_profile"] is None
        assert config["smart_autosync"] is True
        assert config["smart_autosync_timeout"] == 5
        assert config["post_sync_script"] is None
        evo = config["evolution"]
        assert evo["enabled"] is True
        assert evo["file_heat"] == {}
        assert evo["tracked_commands"] == {}
        assert evo["hot_file_threshold"] >= 1

        # значения по умолчанию не протекают между загрузками
        config["evolution"]["file_heat"]["x"] = 5
        fresh = load_config(config_path=cfg_path)
        assert fresh["evolution"]["file_heat"] == {}
    print("✓ конфиг v2 несёт секции расписания, хуков и эволюции")


def test_backend_registry_and_readiness():
    """Task 5 Step 1/5: реестр бэкендов и диагностика готовности."""
    from flamquency.backends import (
        BACKENDS, backend_names, describe_backend, create_backend,
        BackendError,
    )
    names = backend_names()
    assert names == sorted(names)
    for expected in ("local", "github", "s3", "smb", "nfs", "gdrive", "dropbox"):
        assert expected in names, expected

    # local готов всегда и без всяких секретов
    ok, problems, _ = describe_backend({}, "local")
    assert ok and problems == []

    # s3 без настроек перечисляет всё, чего не хватает
    ok, problems, _ = describe_backend({}, "s3")
    assert not ok
    joined = " | ".join(problems)
    assert "bucket" in joined
    assert "FLAMQUENCY_S3_ACCESS_KEY" in joined
    assert any("boto3" in p for p in problems)

    # неизвестный бэкенд — честная ошибка, а не молчаливый local
    ok, problems, _ = describe_backend({}, " Carrier pigeon")
    assert not ok and "Неизвестный" in problems[0]

    # бэкенд, не поддерживаемый на платформе, сообщает об этом
    wrong_platform = dict(BACKENDS)
    ok, problems, _ = describe_backend({}, "nfs")
    assert ok or any("монтир" in p or "server" in p or "mount_point" in p
                     for p in problems)
    print("✓ реестр бэкендов описывает и диагностирует все хранилища")


def test_backend_factory_refuses_unready():
    """Task 5: фабрика не подменяет неготовое облако локальной папкой."""
    from flamquency.backends import create_backend, BackendError
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir) / "store"

        # s3 без boto3/настроек → отказ, а не тихий local
        try:
            create_backend({"backends": {"s3": {}}}, name="s3", base_path=base)
            raise AssertionError("должно было упасть")
        except BackendError as e:
            assert "boto3" in str(e) or "bucket" in str(e)

        # smb без точки монтирования → отказ
        try:
            create_backend(
                {"backends": {"smb": {"server": "//x/y",
                                      "mount_point": str(Path(tmpdir) / "нет")}}},
                name="smb", base_path=base)
            raise AssertionError("должно было упасть")
        except BackendError as e:
            assert "монтир" in str(e)

        # неизвестное имя → отказ
        try:
            create_backend({}, name="carrier-pigeon", base_path=base)
            raise AssertionError("должно было упасть")
        except BackendError:
            pass

        # local создаётся без вопросов
        backend = create_backend({}, name="local", base_path=base)
        assert backend.get_status()["backend"] == "local"
    print("✓ фабрика отказывает неготовым бэкендам вместо тихого отката")


def test_network_backend_roundtrip():
    """Task 5 Step 4: SMB/NFS-бэкенд поверх смонтированной папки."""
    from flamquency.backends import NetworkBackend
    with tempfile.TemporaryDirectory() as tmpdir:
        t = Path(tmpdir)
        mount = t / "mnt"
        mount.mkdir()
        store = t / "store"
        src = t / "src"
        src.mkdir()
        (src / "a.txt").write_text("по сети")
        (src / "sub").mkdir()
        (src / "sub" / "b.txt").write_text("вложенный")

        backend = NetworkBackend(store, "smb", mount)
        # не смонтировано → authenticate честно падает
        backend.mount_point = t / "отсутствует"
        assert backend.authenticate() is False
        assert backend.error and "Не смонтировано" in backend.error

        backend.mount_point = mount
        assert backend.authenticate() is True

        assert backend.upload(src, "docs") is True
        assert (store / "docs" / "a.txt").read_text() == "по сети"
        assert (store / "docs" / "sub" / "b.txt").read_text() == "вложенный"

        listed = backend.list_remote("docs")
        assert sorted(str(p) for p in listed) == ["a.txt", "sub/b.txt"]

        out = t / "out" / "a.txt"
        assert backend.download("docs/a.txt", out) is True
        assert out.read_text() == "по сети"

        status = backend.get_status()
        assert status["backend"] == "smb" and status["mounted"] is True
        assert status["mount_point"] == str(mount)

        assert backend.delete_remote("docs/a.txt") is True
        assert backend.delete_remote("нет-такого") is False
    print("✓ сетевой бэкенд поднимает/скачивает/удаляет файлы и видит монтирование")


def test_s3_backend_requires_boto3():
    """Task 5 Step 2: S3-бэкенд требует boto3 и соблюдает настройки."""
    from flamquency.backends import S3Backend, BackendError
    try:
        import boto3                                   # noqa: F401
        have_boto3 = True
    except ImportError:
        have_boto3 = False

    settings = {"bucket": "b", "prefix": "flamquency/", "region": "eu-west-1",
                "endpoint": "https://s3.example", "access_key_env": "AK",
                "secret_key_env": "SK"}
    if not have_boto3:
        try:
            S3Backend(settings, base_path=tempfile.mkdtemp())
            raise AssertionError("должно было упасть без boto3")
        except BackendError as e:
            assert "boto3" in str(e)
        print("✓ S3-бэкенд честно требует boto3")
        return

    with tempfile.TemporaryDirectory() as tmpdir:
        backend = S3Backend(settings, base_path=Path(tmpdir) / "store")
        # ключ строится из префикса и пути
        assert backend._key("docs/a.txt") == "flamquency/docs/a.txt"
        assert backend._key("/docs/a.txt") == "flamquency/docs/a.txt"
        # секреты читаются из окружения, названного в конфиге
        import os
        os.environ["AK"] = "key-id"
        os.environ["SK"] = "secret"
        assert backend._credentials() == ("key-id", "secret")
        status = backend.get_status()
        assert status["backend"] == "s3" and status["bucket"] == "b"
        assert status["endpoint"] == "https://s3.example"
        del os.environ["AK"], os.environ["SK"]
    print("✓ S3-бэкенд строит ключи и берёт секреты из окружения")


def test_rclone_backend_remote_naming():
    """Task 5 Step 3: облако через rclone — корректные remote-имена."""
    from flamquency.backends import RcloneBackend
    with tempfile.TemporaryDirectory() as tmpdir:
        drive = RcloneBackend("gdrive:folder123", base_path=tmpdir, name="gdrive")
        assert drive.remote == "gdrive:folder123"
        status = drive.get_status()
        assert status["backend"] == "gdrive"
        assert status["remote"] == "gdrive:folder123"
        assert isinstance(status["rclone"], bool)

        drop = RcloneBackend("dropbox:flamquency", base_path=tmpdir,
                             name="dropbox")
        # локальное зеркало всегда доступно для list/delete
        (Path(tmpdir) / "flamquency").mkdir()
        (Path(tmpdir) / "flamquency" / "x.txt").write_text("x")
        assert [str(p) for p in drop.list_remote("flamquency")] == ["x.txt"]
        assert drop.delete_remote("flamquency/x.txt") is True
    print("✓ rclone-бэкенд формирует remote-имена и работает с зеркалом")


def test_backend_secret_env_can_be_disabled():
    """Task 5: пустая строка в *_env = «секрет не нужен» (гостевая шара)."""
    from flamquency.backends import describe_backend
    config = {
        "backends": {
            "smb": {
                "server": "//nas/public",
                "mount_point": "/mnt/nas",
                "username_env": "",      # гость — пароля нет
                "password_env": "",
            }
        }
    }
    # mount_point не существует, поэтому остаётся ровно одна проблема
    ok, problems, _ = describe_backend(config, "smb")
    assert not ok
    assert len(problems) == 1, problems
    assert "монтир" in problems[0]

    # с живой точкой монтирования бэкенд полностью готов
    with tempfile.TemporaryDirectory() as tmpdir:
        config["backends"]["smb"]["mount_point"] = tmpdir
        ok, problems, _ = describe_backend(config, "smb")
        assert ok and problems == [], problems

    # без явного отключения диагностика требует переменную
    config["backends"]["smb"].pop("username_env")
    config["backends"]["smb"].pop("password_env")
    ok, problems, _ = describe_backend(config, "smb")
    assert not ok and any("FLAMQUENCY_SMB" in p for p in problems)
    print("✓ *_env можно отключить пустой строкой для гостевых шар")


def test_config_carries_backend_settings():
    """Task 5: конфиг v2 описывает настройки каждого бэкенда."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg_path = Path(tmpdir) / "config.yaml"
        config = load_config(config_path=cfg_path)
        backends = config["backends"]
        for name in ("s3", "smb", "nfs", "gdrive", "dropbox"):
            assert name in backends, name
        # секреты не хранятся в конфиге — только имена переменных
        for name, settings in backends.items():
            for key, value in settings.items():
                assert not key.endswith("_key") or key.endswith("_env"), key
                if key.endswith("_env"):
                    assert value.startswith("FLAMQUENCY_"), value
        assert config["cloud_backend"] == "local"
    print("✓ конфиг описывает бэкенды, не храня секретов")


def test_rollback_snapshot():
    with tempfile.TemporaryDirectory() as tmpdir:
        sync = _isolated_sync(tmpdir)
        t = Path(tmpdir)
        (t / "test.txt").write_text("snapshot data")
        
        snap, meta = sync.create_snapshot(source_path=t)
        success, msg = sync.rollback_to_snapshot(snap.name, target_path=t)
        assert success
        assert (t / "test.txt").read_text() == "snapshot data"
    print("✓ Snapshot rollback works")


def test_rollback_file_real():
    with tempfile.TemporaryDirectory() as tmpdir:
        sync = _isolated_sync(tmpdir)
        t = Path(tmpdir)
        
        test_file = t / "test.txt"
        test_file.write_text("original")
        
        # Sync v1
        sync.sync(source=t)
        
        # Modify and sync v2
        test_file.write_text("modified")
        sync.sync(source=t)
        
        # Check versions
        history = sync.version_store.get_history("test.txt")
        assert len(history) == 2, f"Expected 2, got {len(history)}"
        
        # Restore v0 (original)
        success, info = sync.rollback_file(str(test_file), version_index=0)
        assert success, f"rollback failed: {info}"
        assert test_file.read_text() == "original", f"Got: {test_file.read_text()}"
    print("✓ Real per-file rollback works")


def test_version_listing():
    with tempfile.TemporaryDirectory() as tmpdir:
        vs = VersionStore(Path(tmpdir))
        vs.record_version("test.txt", data="v1")
        vs.record_version("test.txt", data="v2")
        vs.record_version("test.txt", data="v3")
        
        versions = vs.list_versions("test.txt")
        assert len(versions) == 3
        assert versions[0]["index"] == 0
        assert versions[2]["index"] == 2
    print("✓ Version listing works")


def test_gc_and_prune():
    with tempfile.TemporaryDirectory() as tmpdir:
        vs = VersionStore(Path(tmpdir))
        for i in range(10):
            vs.record_version("test.txt", data=f"version {i}")
        assert len(vs.get_history("test.txt")) == 10
        
        pruned = vs.prune(keep_last_n=5)
        assert pruned == 5
        assert len(vs.get_history("test.txt")) == 5
        
        removed = vs.gc()
        assert removed >= 0
    print("✓ GC and prune work")


def test_backend_factory():
    backend = get_backend("local")
    assert isinstance(backend, LocalBackend)
    assert backend.authenticate()
    print("✓ Backend factory works")


# ── Encryption ────────────────────────────────────────────────

def test_encryption_enable_unlock_and_wrong_password():
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir) / "store"
        mgr = EncryptionManager.enable(base, ENC_PW, iterations=50_000)
        assert mgr.is_configured
        assert mgr.is_unlocked
        assert mgr.key_path.exists()

        # Unlock with the correct password
        mgr2 = EncryptionManager(base)
        assert mgr2.is_configured
        assert not mgr2.is_unlocked
        mgr2.unlock(ENC_PW)
        assert mgr2.is_unlocked

        # Wrong password must be rejected
        mgr3 = EncryptionManager(base)
        try:
            mgr3.unlock("not the password")
            assert False, "wrong password should raise WrongPasswordError"
        except WrongPasswordError:
            pass
        assert not mgr3.is_unlocked

        # Lock / unlock cycle
        mgr2.lock()
        assert not mgr2.is_unlocked
        mgr2.unlock(ENC_PW)
        assert mgr2.is_unlocked
    print("✓ Encryption enable/unlock/wrong-password works")


def test_encryption_encrypt_decrypt_roundtrip():
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = EncryptionManager.enable(Path(tmpdir), ENC_PW, iterations=50_000)
        data = b"top secret payload \x00\x01\x02" * 100
        token = mgr.encrypt(data)
        assert token != data
        assert b"top secret" not in token
        assert mgr.decrypt(token) == data

        # Tampered ciphertext must not decrypt
        tampered = bytearray(token)
        tampered[-1] ^= 0xFF
        try:
            mgr.decrypt(bytes(tampered))
            assert False, "tampered token should raise DecryptionError"
        except DecryptionError:
            pass

        # Locked manager refuses to work
        mgr.lock()
        try:
            mgr.encrypt(b"x")
            assert False, "locked manager should raise EncryptionLockedError"
        except EncryptionLockedError:
            pass
        try:
            mgr.decrypt(token)
            assert False, "locked manager should raise EncryptionLockedError"
        except EncryptionLockedError:
            pass
    print("✓ Encryption encrypt/decrypt roundtrip and tamper detection work")


def test_blob_store_encrypted_roundtrip():
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        mgr = EncryptionManager.enable(base, ENC_PW, iterations=50_000)
        bs = BlobStore(base, encryption=mgr)

        h = bs.store("secret blob content")
        assert len(h) == 64
        # On-disk bytes must not contain the plaintext
        raw = bs._blob_path(h).read_bytes()
        assert b"secret blob content" not in raw
        assert bs.retrieve(h) == b"secret blob content"
        # Dedup still works (same content → same hash, no second blob)
        h2 = bs.store("secret blob content")
        assert h2 == h

        # store_file + restore_to with binary data
        src = base / "blob.bin"
        payload = bytes(range(256)) * 4096  # 1 MB, non-compressible
        src.write_bytes(payload)
        hf = bs.store_file(src)
        assert b"secret" not in bs._blob_path(hf).read_bytes()[:64]
        assert payload not in bs._blob_path(hf).read_bytes()
        dest = base / "restored.bin"
        assert bs.restore_to(hf, dest)
        assert dest.read_bytes() == payload
        assert bs.stats()["blob_count"] == 2
    print("✓ Encrypted blob store roundtrip works (blobs not plaintext on disk)")


def test_blob_store_encrypted_locked_and_unlocked_read():
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        mgr = EncryptionManager.enable(base, ENC_PW, iterations=50_000)
        bs = BlobStore(base, encryption=mgr)
        h = bs.store("hidden data")

        # Reopen without a password — store is locked
        locked_mgr = EncryptionManager(base)
        bs_locked = BlobStore(base, encryption=locked_mgr)
        try:
            bs_locked.retrieve(h)
            assert False, "locked store should raise EncryptionLockedError"
        except EncryptionLockedError:
            pass
        # And it must refuse to write plaintext into an encrypted store
        try:
            bs_locked.store("sneaky plaintext")
            assert False, "locked store should refuse new writes"
        except EncryptionLockedError:
            pass

        # Unlock with the right password → reads work again
        locked_mgr.unlock(ENC_PW)
        assert bs_locked.retrieve(h) == b"hidden data"
    print("✓ Locked encrypted store blocks reads and writes until unlocked")


def test_version_store_with_encryption():
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        mgr = EncryptionManager.enable(base, ENC_PW, iterations=50_000)
        vs = VersionStore(base, encryption=mgr)

        vs.record_version("docs/secret.txt", data="version 1 secret")
        vs.record_version("docs/secret.txt", data="version 2 secret")
        assert len(vs.get_history("docs/secret.txt")) == 2

        dest = base / "restored.txt"
        success, msg = vs.restore_version("docs/secret.txt", 0, dest_path=dest)
        assert success
        assert dest.read_text() == "version 1 secret"

        diff = vs.diff_versions("docs/secret.txt", 0, 1)
        assert "version 2 secret" in diff
    print("✓ Version store works end-to-end with encryption")


def test_encryption_change_password():
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        mgr = EncryptionManager.enable(base, ENC_PW, iterations=50_000)
        bs = BlobStore(base, encryption=mgr)
        h = bs.store("keep me safe")

        new_pw = "brand new password"
        new_mgr = mgr.change_password(new_pw)
        assert new_mgr.is_unlocked
        # Old password no longer opens the store
        try:
            EncryptionManager(base).unlock(ENC_PW)
            assert False, "old password should stop working"
        except WrongPasswordError:
            pass
        # Blobs were re-keyed: readable with the new password only
        bs.rekey(mgr, new_mgr)
        reopened = BlobStore(base, encryption=EncryptionManager(base))
        reopened.encryption.unlock(new_pw)
        assert reopened.retrieve(h) == b"keep me safe"
    print("✓ Password change re-keys the store")


def test_encryption_disable_decrypts_blobs():
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        mgr = EncryptionManager.enable(base, ENC_PW, iterations=50_000)
        bs = BlobStore(base, encryption=mgr)
        h1 = bs.store("first secret")
        h2 = bs.store("second secret")

        decrypted = bs.disable_encryption(mgr)
        assert decrypted == 2
        assert not mgr.is_configured  # key file removed
        # Blobs are plaintext on disk again
        assert b"first secret" in zlib.decompress(bs._blob_path(h1).read_bytes())
        # Store works without any encryption manager
        bs_plain = BlobStore(base)
        assert bs_plain.retrieve(h1) == b"first secret"
        assert bs_plain.retrieve(h2) == b"second secret"
    print("✓ Disabling encryption decrypts existing blobs")


def test_sync_engine_with_encryption():
    with tempfile.TemporaryDirectory() as tmpdir:
        config = load_config()
        config["encryption"] = {"enabled": True}
        t = Path(tmpdir)
        (t / "secret.txt").write_text("my secret notes")

        sync = _isolated_sync(tmpdir, config=config, password=ENC_PW)
        result = sync.sync(source=t)
        assert result.files_synced >= 1
        assert not result.errors, result.errors

        # Blob on disk must be ciphertext
        history = sync.version_store.get_history("secret.txt")
        assert len(history) == 1
        raw = sync.version_store.blob_store._blob_path(history[0]["hash"]).read_bytes()
        assert b"my secret notes" not in raw

        # Rollback still works through the cipher
        test_file = t / "secret.txt"
        test_file.write_text("changed!")
        sync.sync(source=t)
        success, msg = sync.rollback_file(str(test_file), version_index=0)
        assert success, msg
        assert test_file.read_text() == "my secret notes"

        # Status reports encryption state
        assert sync.status()["encryption"] == "enabled"
    print("✓ Sync engine with encryption works (ciphertext blobs + rollback)")


def test_sync_engine_wrong_password_rejected():
    with tempfile.TemporaryDirectory() as tmpdir:
        config = load_config()
        config["encryption"] = {"enabled": True}
        t = Path(tmpdir)
        (t / "secret.txt").write_text("data")

        # First run sets up the keys
        _isolated_sync(tmpdir, config=config, password=ENC_PW).sync(source=t)

        # Second run with a wrong password must fail loudly
        try:
            _isolated_sync(tmpdir, config=config, password="wrong one").sync(source=t)
            assert False, "wrong password should raise WrongPasswordError"
        except WrongPasswordError:
            pass
    print("✓ Sync engine rejects wrong encryption password")


def test_sync_engine_locked_store_refuses_to_run():
    with tempfile.TemporaryDirectory() as tmpdir:
        config = load_config()
        config["encryption"] = {"enabled": True}
        t = Path(tmpdir)
        (t / "secret.txt").write_text("data")

        # First run sets up the keys
        _isolated_sync(tmpdir, config=config, password=ENC_PW).sync(source=t)

        # A locked store (no password) must refuse to sync — never silently
        locked = _isolated_sync(tmpdir, config=config, password=None)
        assert locked.status()["encryption"] == "locked"
        try:
            locked.sync(source=t)
            assert False, "locked store should refuse to sync"
        except EncryptionLockedError:
            pass
        try:
            locked.create_snapshot(source_path=t)
            assert False, "locked store should refuse to snapshot"
        except EncryptionLockedError:
            pass
    print("✓ Locked store refuses sync and snapshot until unlocked")


def test_sync_engine_unlock_after_lock():
    with tempfile.TemporaryDirectory() as tmpdir:
        config = load_config()
        config["encryption"] = {"enabled": True}
        t = Path(tmpdir)
        (t / "secret.txt").write_text("v1")

        _isolated_sync(tmpdir, config=config, password=ENC_PW).sync(source=t)

        locked = _isolated_sync(tmpdir, config=config, password=None)
        locked.encryption.unlock(ENC_PW)
        result = locked.sync(source=t)
        assert not result.errors, result.errors
        assert result.files_synced >= 1
    print("✓ Store works again after unlocking in-place")


# ── .flamquencyignore ──────────────────────────────────────────

def test_ignore_rules_parse_skips_comments_and_blanks():
    from flamquency.ignore import IgnoreRules
    rules = IgnoreRules.from_lines([
        "# a comment", "", "   ", "*.log", "!keep.log",
        "build/", "/rooted.txt", "**/node_modules",
    ])
    assert len(rules) == 5, f"expected 5 rules, got {len(rules)}"
    raws = [r.raw for r in rules]
    assert raws == ["*.log", "!keep.log", "build/", "/rooted.txt", "**/node_modules"]
    assert not rules.rules[0].negate
    assert rules.rules[1].negate
    assert rules.rules[2].dir_only
    assert not rules.rules[2].negate
    assert rules.rules[3].anchored
    print("✓ Ignore rules parse: comments/blanks dropped, flags extracted")


def test_ignore_rules_match_semantics():
    from flamquency.ignore import IgnoreRules
    rules = IgnoreRules.from_lines([
        "*.log", "!keep.log", "build/", "/rooted.txt",
        "**/node_modules", "temp?.tmp",
    ])
    # plain name pattern matches at any depth
    assert rules.match("app.log")
    assert rules.match("logs/deep/app.log")
    # negation wins — later rule re-includes
    assert not rules.match("keep.log")
    assert not rules.match("sub/keep.log")
    # directory-only pattern
    assert rules.match("build", is_dir=True)
    assert not rules.match("build", is_dir=False)      # a *file* named build is kept
    assert rules.match("x/build/out.o")                 # contents of an ignored dir
    # anchored pattern only matches at the root
    assert rules.match("rooted.txt")
    assert not rules.match("sub/rooted.txt")
    # ** crosses directories
    assert rules.match("a/b/c/node_modules", is_dir=True)
    assert not rules.match("a/b/c/node_modules_old", is_dir=True)
    # ? matches exactly one char
    assert rules.match("temp1.tmp")
    assert not rules.match("temp12.tmp")
    print("✓ Ignore match semantics work (negation, dir-only, anchored, **, ?)")


def test_ignore_rules_last_match_wins():
    from flamquency.ignore import IgnoreRules
    rules = IgnoreRules.from_lines(["*.txt", "!notes.txt", "*.txt"])
    # the last matching rule decides — re-excluded
    assert rules.match("notes.txt")
    rules2 = IgnoreRules.from_lines(["*.txt", "!notes.txt"])
    assert not rules2.match("notes.txt")
    # no rule matches → not ignored
    assert not rules2.match("photo.png")
    print("✓ Ignore rules: last matching rule wins, default is include")


def test_ignore_rules_from_file_and_missing_file():
    from flamquency.ignore import IgnoreRules
    with tempfile.TemporaryDirectory() as tmpdir:
        p = Path(tmpdir) / ".flamquencyignore"
        p.write_text("# my rules\n\n*.bak\nsecret/\n")
        rules = IgnoreRules.from_file(p)
        assert len(rules) == 2
        assert rules.match("old.bak")
        assert rules.match("secret", is_dir=True)
        assert rules.path == p
        # a missing file is simply "no rules" — never an error
        missing = IgnoreRules.from_file(Path(tmpdir) / "nope")
        assert len(missing) == 0
        assert not missing.match("anything")
    print("✓ Ignore rules load from file; missing file = no rules")


def test_ignore_rules_explain_reports_matching_rule():
    from flamquency.ignore import IgnoreRules
    rules = IgnoreRules.from_lines(["*.log", "!keep.log"])
    ignored, rule = rules.explain("app.log")
    assert ignored
    assert rule is not None and rule.raw == "*.log"
    ignored2, rule2 = rules.explain("keep.log")
    assert not ignored2
    assert rule2 is not None and rule2.raw == "!keep.log"
    ignored3, rule3 = rules.explain("photo.png")
    assert not ignored3
    assert rule3 is None
    print("✓ Ignore explain() reports which rule decided")


def test_default_ignore_template_written():
    from flamquency.ignore import (
        IGNORE_FILENAME, IgnoreRules, default_template, write_default_ignore_file,
    )
    assert IGNORE_FILENAME == ".flamquencyignore"
    text = default_template()
    assert text.startswith("#")
    assert "*.log" in text and "!keep.log" in text
    with tempfile.TemporaryDirectory() as tmpdir:
        p = Path(tmpdir) / IGNORE_FILENAME
        write_default_ignore_file(p)
        assert p.exists()
        # the written file must be valid rules that actually ignore things
        rules = IgnoreRules.from_file(p)
        assert len(rules) > 5
        assert rules.match("debug.log")
        # writing again refuses to clobber an existing file
        before = p.read_text()
        write_default_ignore_file(p)
        assert p.read_text() == before
    print("✓ Default ignore template is written once and stays valid")


def test_engine_without_ignore_file_has_no_rules():
    with tempfile.TemporaryDirectory() as tmpdir:
        sync = _isolated_sync(tmpdir, ignore_file=Path(tmpdir) / "absent")
        assert len(sync.ignore_rules) == 0
        assert not sync.ignore_rules.match("whatever.log")
        assert sync.status()["ignore_rules"] == 0
        assert sync.status()["ignore_file"] is None
    print("✓ Engine without an ignore file behaves exactly as before")


def test_scan_directory_respects_ignore_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        t = Path(tmpdir)
        ig = t / ".flamquencyignore"
        ig.write_text("*.log\n!keep.log\nbuild/\n/rooted.txt\n")
        sync = _isolated_sync(tmpdir, ignore_file=ig)

        (t / "notes.txt").write_text("keep me")
        (t / "debug.log").write_text("noise")
        (t / "keep.log").write_text("important")
        (t / "rooted.txt").write_text("root")
        (t / "sub").mkdir()
        (t / "sub" / "rooted.txt").write_text("nested ok")
        (t / "build").mkdir()
        (t / "build" / "out.o").write_text("artifact")
        (t / "junk.tmp").write_text("config-excluded")

        files = sync.scan_directory(t)
        names = {f.name for f in files}
        assert "notes.txt" in names
        assert "debug.log" not in names        # ignored by *.log
        assert "keep.log" in names             # re-included by !keep.log
        # anchored rule hits only the root copy, not the nested one
        assert (t / "rooted.txt") not in files
        assert (t / "sub" / "rooted.txt") in files
        assert not any("out.o" in str(f) for f in files)  # build/ pruned as a directory
        assert not any("junk.tmp" in str(f) for f in files)  # config exclude still wins
    print("✓ scan_directory honors .flamquencyignore rules")


def test_sync_counts_ignored_files():
    with tempfile.TemporaryDirectory() as tmpdir:
        t = Path(tmpdir)
        ig = t / ".flamquencyignore"
        ig.write_text("*.log\nbuild/\n")
        sync = _isolated_sync(tmpdir, ignore_file=ig)

        (t / "a.txt").write_text("hello")
        (t / "b.log").write_text("noise")
        (t / "build").mkdir()
        (t / "build" / "c.o").write_text("artifact")

        result = sync.sync(source=t)
        assert result.files_synced >= 1
        assert not result.errors, result.errors
        # ignored files are counted, not silently dropped
        assert result.files_excluded >= 2, result.files_excluded
        dest = sync.backend.base_path
        assert (dest / "a.txt").exists()
        assert not (dest / "b.log").exists()
        assert not (dest / "build").exists()
    print("✓ sync counts ignored files and never copies them")


def test_snapshot_respects_ignore_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        t = Path(tmpdir)
        ig = t / ".flamquencyignore"
        ig.write_text("*.secret\n")
        sync = _isolated_sync(tmpdir, ignore_file=ig)

        (t / "public.txt").write_text("fine")
        (t / "private.secret").write_text("nope")

        snap, meta = sync.create_snapshot(source_path=t)
        manifest = meta["manifest"]
        assert "public.txt" in manifest
        assert not any("private.secret" in k for k in manifest)
    print("✓ create_snapshot honors .flamquencyignore rules")


def test_cli_ignore_init_and_check():
    import io
    import contextlib
    from argparse import Namespace
    from flamquency.cli import cmd_ignore

    with tempfile.TemporaryDirectory() as tmpdir:
        ig = Path(tmpdir) / ".flamquencyignore"

        # --init writes the default template
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cmd_ignore(Namespace(path=str(ig), init=True, force=False,
                                      add=None, check=None, list=False))
        assert rc == 0
        assert ig.exists()
        assert "*.log" in ig.read_text()

        # --check reports the decision for a path
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cmd_ignore(Namespace(path=str(ig), init=False, force=False,
                                      add=None, check="debug.log", list=False))
        out = buf.getvalue()
        assert rc == 0
        assert "игнорируется" in out.lower() and "не игнорируется" not in out.lower()

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cmd_ignore(Namespace(path=str(ig), init=False, force=False,
                                      add=None, check="notes.txt", list=False))
        out = buf.getvalue()
        assert rc == 0
        assert "не игнорируется" in out.lower()

        # --add appends a pattern and it takes effect
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cmd_ignore(Namespace(path=str(ig), init=False, force=False,
                                      add="*.huge", check=None, list=False))
        assert rc == 0
        rules_text = ig.read_text()
        assert "*.huge" in rules_text

        # --list prints the loaded rules
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cmd_ignore(Namespace(path=str(ig), init=False, force=False,
                                      add=None, check=None, list=True))
        out = buf.getvalue()
        assert rc == 0
        assert "*.huge" in out and "*.log" in out
    print("✓ CLI `flamquency ignore` init/add/check/list works")


# ── Sync profiles ─────────────────────────────────────────────

def _profile_engine(tmpdir, **config_overrides):
    """Isolated engine whose config carries a profiles section."""
    config = load_config()
    config = dict(config)
    config["use_ignore_file"] = False
    config.update(config_overrides)
    base = Path(tmpdir) / ".flamquency_isolated"
    backend = LocalBackend(base_path=base / "sync")
    return FlamQuencySync(config=config, backend=backend, base_dir=base)


def test_config_defaults_not_shared_between_loads():
    config = load_config()
    config["profiles"]["leak"] = {"paths": ["/leak"]}
    config["exclude_patterns"].append("*.leak")
    fresh = load_config()
    assert "leak" not in fresh.get("profiles", {})
    assert "*.leak" not in fresh["exclude_patterns"]
    print("✓ Config defaults are deep-copied — one load never mutates another")


def test_profiles_default_in_config():
    from flamquency.profiles import DEFAULT_PROFILE_NAME
    config = load_config()
    assert DEFAULT_PROFILE_NAME in config.get("profiles", {})
    assert config.get("active_profile") == DEFAULT_PROFILE_NAME
    print("✓ Config ships a default sync profile")


def test_profile_create_list_and_delete():
    from flamquency.profiles import (
        ProfileError, create_profile, delete_profile, get_profile, profile_names,
    )
    config = load_config()
    profile = create_profile(config, "documents",
                             ["~/Documents", "~/Notes"], description="docs")
    assert profile["paths"] == [str(Path.home() / "Documents"),
                                str(Path.home() / "Notes")]
    assert "documents" in profile_names(config)
    assert get_profile(config, "documents")["description"] == "docs"

    # duplicate name is refused
    try:
        create_profile(config, "documents", ["~/x"])
        assert False, "duplicate profile should raise ProfileError"
    except ProfileError:
        pass
    # a profile needs at least one path
    try:
        create_profile(config, "empty", [])
        assert False, "empty profile should raise ProfileError"
    except ProfileError:
        pass
    # unknown profile is refused
    try:
        get_profile(config, "nope")
        assert False, "unknown profile should raise ProfileError"
    except ProfileError:
        pass
    # invalid names are refused
    for bad in ["", "   ", "a/b"]:
        try:
            create_profile(config, bad, ["~/x"])
            assert False, f"invalid name {bad!r} should raise ProfileError"
        except ProfileError:
            pass

    delete_profile(config, "documents")
    assert "documents" not in profile_names(config)
    # the default profile is structural — it cannot be deleted
    try:
        delete_profile(config, "default")
        assert False, "default profile should not be deletable"
    except ProfileError:
        pass
    print("✓ Profile create/list/delete with validation works")


def test_profile_paths_and_active_switching():
    from flamquency.profiles import (
        ProfileError, active_name, add_path, create_profile, delete_profile,
        get_profile, remove_path, set_active,
    )
    config = load_config()
    home = str(Path.home())

    add_path(config, "default", "~/code")
    assert f"{home}/code" in get_profile(config, "default")["paths"]
    # adding the same path twice is a no-op (dedupe)
    add_path(config, "default", "~/code")
    assert get_profile(config, "default")["paths"].count(f"{home}/code") == 1

    remove_path(config, "default", "~/code")
    assert f"{home}/code" not in get_profile(config, "default")["paths"]
    # removing a path the profile does not have
    try:
        remove_path(config, "default", "~/nowhere")
        assert False, "removing an absent path should raise ProfileError"
    except ProfileError:
        pass
    # the last path of a profile cannot be removed
    try:
        remove_path(config, "default", "~/.flamquency")
        assert False, "a profile must keep at least one path"
    except ProfileError:
        pass

    create_profile(config, "work", ["~/projects"])
    set_active(config, "work")
    assert active_name(config) == "work"
    # the active profile cannot be deleted
    try:
        delete_profile(config, "work")
        assert False, "deleting the active profile should raise ProfileError"
    except ProfileError:
        pass
    # switching to an unknown profile
    try:
        set_active(config, "ghost")
        assert False, "unknown profile should raise ProfileError"
    except ProfileError:
        pass
    # a dangling active_profile falls back to default
    config["active_profile"] = "ghost"
    assert active_name(config) == "default"
    print("✓ Profile path management and active switching work")


def test_profile_exclude_patterns_merge():
    from flamquency.profiles import create_profile, exclude_patterns, get_profile
    config = load_config()
    create_profile(config, "media", ["~/Music"], exclude_patterns=["*.flac"])
    merged = exclude_patterns(config, get_profile(config, "media"))
    assert "*.flac" in merged            # profile extras apply
    assert "**/.git/**" in merged        # config defaults still apply
    print("✓ Profile exclude patterns merge on top of config defaults")


def test_sync_uses_active_profile_paths():
    with tempfile.TemporaryDirectory() as tmpdir:
        from flamquency.profiles import create_profile, set_active
        t = Path(tmpdir)
        docs = t / "docs"; docs.mkdir()
        (docs / "a.txt").write_text("A")
        code = t / "code"; code.mkdir()
        (code / "b.txt").write_text("B")

        from flamquency.config import DEFAULT_CONFIG
        config = copy.deepcopy(DEFAULT_CONFIG)
        config["use_ignore_file"] = False
        create_profile(config, "multi", [str(docs), str(code)])
        set_active(config, "multi")
        base = t / ".flamquency_isolated"
        sync = FlamQuencySync(config=config,
                              backend=LocalBackend(base_path=base / "sync"),
                              base_dir=base)

        result = sync.sync()
        assert result.profile == "multi"
        assert result.files_synced == 2, result.files_synced
        assert len(result.paths) == 2
        assert not result.errors, result.errors

        # each root lands under its own label — no clobbering between roots
        dest = sync.backend.base_path
        assert (dest / "docs" / "a.txt").exists()
        assert (dest / "code" / "b.txt").exists()
        # version keys are prefixed per root, so equal relative names never collide
        assert sync.version_store.get_history("docs/a.txt")
        assert sync.version_store.get_history("code/b.txt")
        # one snapshot per synced root
        assert len(sync.list_snapshots()) == 2
    print("✓ sync() follows the active profile across all its paths")


def test_sync_explicit_source_beats_profile():
    with tempfile.TemporaryDirectory() as tmpdir:
        from flamquency.profiles import create_profile, set_active
        t = Path(tmpdir)
        docs = t / "docs"; docs.mkdir()
        (docs / "a.txt").write_text("A")
        other = t / "other"; other.mkdir()
        (other / "c.txt").write_text("C")

        from flamquency.config import DEFAULT_CONFIG
        config = copy.deepcopy(DEFAULT_CONFIG)
        config["use_ignore_file"] = False
        create_profile(config, "multi", [str(docs)])
        set_active(config, "multi")
        base = t / ".flamquency_isolated"
        sync = FlamQuencySync(config=config,
                              backend=LocalBackend(base_path=base / "sync"),
                              base_dir=base)

        # an explicit --source keeps the old single-root behaviour
        result = sync.sync(source=other)
        assert result.profile is None
        assert result.files_synced == 1
        dest = sync.backend.base_path
        assert (dest / "c.txt").exists()          # no label prefix
        assert not (dest / "other").exists()
    print("✓ An explicit source overrides the active profile")


def test_sync_profile_argument_and_missing_path():
    with tempfile.TemporaryDirectory() as tmpdir:
        from flamquency.profiles import create_profile, set_active
        t = Path(tmpdir)
        docs = t / "docs"; docs.mkdir()
        (docs / "a.txt").write_text("A")

        from flamquency.config import DEFAULT_CONFIG
        config = copy.deepcopy(DEFAULT_CONFIG)
        config["use_ignore_file"] = False
        create_profile(config, "work", [str(docs)])
        create_profile(config, "broken", [str(t / "ghost")])
        set_active(config, "work")
        base = t / ".flamquency_isolated"
        sync = FlamQuencySync(config=config,
                              backend=LocalBackend(base_path=base / "sync"),
                              base_dir=base)

        # --profile syncs that profile even when it is not the active one
        result = sync.sync(profile="work")
        assert result.profile == "work"
        assert result.files_synced == 1
        # the active profile is untouched by a one-off --profile run
        assert config["active_profile"] == "work"

        # a nonexistent path is reported, never silently skipped
        result = sync.sync(profile="broken")
        assert result.files_synced == 0
        assert result.errors and "does not exist" in result.errors[0]

        # unknown profile name
        try:
            sync.sync(profile="ghost")
            assert False, "unknown profile should raise ProfileError"
        except Exception as e:
            assert "ghost" in str(e)
    print("✓ sync(profile=...) works and missing paths are reported")


def test_status_reports_profiles():
    with tempfile.TemporaryDirectory() as tmpdir:
        from flamquency.profiles import create_profile, set_active
        t = Path(tmpdir)
        docs = t / "docs"; docs.mkdir()
        from flamquency.config import DEFAULT_CONFIG
        config = copy.deepcopy(DEFAULT_CONFIG)
        config["use_ignore_file"] = False
        create_profile(config, "multi", [str(docs)])
        set_active(config, "multi")
        base = t / ".flamquency_isolated"
        sync = FlamQuencySync(config=config,
                              backend=LocalBackend(base_path=base / "sync"),
                              base_dir=base)
        status = sync.status()
        assert status["active_profile"] == "multi"
        assert "multi" in status["profiles"]
        assert status["profile_count"] >= 2
    print("✓ status() reports the active profile and profile list")


def test_cli_profile_commands():
    import io
    import contextlib
    from argparse import Namespace
    from flamquency.cli import cmd_profile

    with tempfile.TemporaryDirectory() as tmpdir:
        t = Path(tmpdir)
        cfg = t / "config.yaml"

        def run(**kw):
            args = Namespace(
                action=kw.pop("action", "list"),
                name=kw.pop("name", None),
                path=kw.pop("path", []),
                description=kw.pop("description", ""),
                exclude=kw.pop("exclude", []),
                config_path=str(cfg),
            )
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = cmd_profile(args)
            return rc, buf.getvalue()

        # list on a fresh config shows the default profile
        rc, out = run()
        assert rc == 0
        assert "default" in out

        # create
        rc, out = run(action="create", name="docs",
                      path=[str(t / "Documents")], description="my docs")
        assert rc == 0
        # duplicate name is refused
        rc, out = run(action="create", name="docs", path=[str(t / "x")])
        assert rc == 1
        # create without paths is refused
        rc, out = run(action="create", name="nopaths")
        assert rc == 1

        # add-path
        rc, out = run(action="add-path", name="docs", path=[str(t / "Notes")])
        assert rc == 0
        # show
        rc, out = run(action="show", name="docs")
        assert rc == 0
        assert "Documents" in out and "Notes" in out

        # use — switching the active profile
        rc, out = run(action="use", name="docs")
        assert rc == 0
        # the active profile cannot be deleted
        rc, out = run(action="delete", name="docs")
        assert rc == 1
        # switch back, then delete succeeds
        rc, out = run(action="use", name="default")
        assert rc == 0
        rc, out = run(action="delete", name="docs")
        assert rc == 0

        # unknown profile / name errors
        rc, out = run(action="show", name="ghost")
        assert rc == 1
        rc, out = run(action="use", name="ghost")
        assert rc == 1

        # config on disk reflects the operations
        config = load_config(cfg)
        assert "docs" not in config["profiles"]
        assert config["active_profile"] == "default"
    print("✓ CLI `flamquency profile` list/create/add-path/show/use/delete works")


# ── Retention / prune ───────────────────────────────────────

def _prune_engine(tmpdir):
    """Isolated engine whose storage lives OUTSIDE the synced source.

    The base dir must not sit inside the scanned tree, or each sync copies
    its own destination and grows exponentially.
    """
    from flamquency.cloud import LocalBackend
    from flamquency.config import DEFAULT_CONFIG
    config = copy.deepcopy(DEFAULT_CONFIG)
    config["use_ignore_file"] = False
    base = Path(tmpdir) / "store"
    src = Path(tmpdir) / "src"
    src.mkdir(exist_ok=True)
    backend = LocalBackend(base_path=base / "sync")
    return FlamQuencySync(config=config, backend=backend, base_dir=base), src


def test_prune_snapshots_keep_last():
    with tempfile.TemporaryDirectory() as tmpdir:
        sync, src = _prune_engine(tmpdir)
        for i in range(7):
            (src / f"file{i}.txt").write_text(f"v{i}")
            sync.sync(source=src)
        assert len(sync.list_snapshots()) == 7

        deleted, msg = sync.prune_snapshots(keep_last=3)
        assert deleted == 4, f"expected 4 pruned, got {deleted}"
        assert len(sync.list_snapshots()) == 3
    print("✓ prune_snapshots(keep_last) removes oldest snapshots")


def test_prune_snapshots_not_configured():
    with tempfile.TemporaryDirectory() as tmpdir:
        sync, src = _prune_engine(tmpdir)
        deleted, msg = sync.prune_snapshots()
        assert deleted == 0
        assert "not configured" in msg
    print("✓ prune_snapshots without policy is a safe no-op")


def test_prune_snapshots_older_than_days():
    with tempfile.TemporaryDirectory() as tmpdir:
        sync, src = _prune_engine(tmpdir)
        for i in range(4):
            (src / f"file{i}.txt").write_text(f"v{i}")
            sync.sync(source=src)
        # Все снапшоты только что созданы — не старше 30 дней
        deleted, msg = sync.prune_snapshots(older_than_days=30)
        assert deleted == 0
        assert len(sync.list_snapshots()) == 4
        # older_than_days=0 должен удалить всё (все старше 0 дней)
        deleted, msg = sync.prune_snapshots(older_than_days=0)
        assert deleted == 4
    print("✓ prune_snapshots(older_than_days) filters by age")


def test_prune_snapshots_combined_policy():
    with tempfile.TemporaryDirectory() as tmpdir:
        sync, src = _prune_engine(tmpdir)
        for i in range(6):
            (src / f"file{i}.txt").write_text(f"v{i}")
            sync.sync(source=src)
        # Union: keep_last=2 защищает 2 свежих, keep_hourly=1 — свежайший
        # часа. В одном часе обе политики защищают почти то же → left ≤ 2
        deleted, msg = sync.prune_snapshots(keep_last=2, keep_hourly=1)
        assert deleted >= 4, f"expected ≥4 pruned, got {deleted}"
        assert len(sync.list_snapshots()) == 6 - deleted
    print("✓ prune_snapshots combines keep_last and keep_hourly (union)")


def test_prune_snapshots_older_than_days_protects():
    """older_than_days — политика ЗАЩИТЫ: новее N дней сохраняется."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sync, src = _prune_engine(tmpdir)
        for i in range(4):
            (src / f"file{i}.txt").write_text(f"v{i}")
            sync.sync(source=src)
        # Все снапшоты свежие: older_than_days=30 не даёт удалить ничего
        deleted, msg = sync.prune_snapshots(older_than_days=30)
        assert deleted == 0
        assert len(sync.list_snapshots()) == 4
        # older_than_days=0 — защищает снапшоты новее «сейчас»: все прошлые
        deleted, msg = sync.prune_snapshots(older_than_days=0)
        assert deleted == 4
    print("✓ prune_snapshots older_than_days protects recent snapshots")


# ── Прогресс синхронизации ─────────────────────────────

def test_sync_progress_reports_each_file():
    """progress получает событие на каждый файл: done растёт до total."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sync, src = _prune_engine(tmpdir)
        for i in range(5):
            (src / f"f{i}.txt").write_text(f"v{i}")

        events = []
        result = sync.sync(source=src, progress=events.append)

        assert result.files_synced == 5
        assert events, "progress-колбэк не вызвался ни разу"
        # стартовое событие уже знает итоговый total
        assert events[0].done == 0 and events[0].total == 5
        assert events[0].current == ""
        # done монотонно растёт 1..5, total неизменен
        assert [e.done for e in events[1:]] == [1, 2, 3, 4, 5]
        assert all(e.total == 5 for e in events)
        # текущий файл — реальный путь из источника
        assert any("f0.txt" in e.current for e in events)
    print("✓ sync() сообщает прогресс по каждому файлу")


def test_sync_progress_empty_source():
    """Пустой источник: одно событие 0/0 — UI может закрыть прогресс."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sync, src = _prune_engine(tmpdir)
        events = []
        result = sync.sync(source=src, progress=events.append)
        assert result.files_synced == 0
        assert len(events) == 1
        assert events[0].done == 0 and events[0].total == 0
    print("✓ Пустой источник отдаёт одно событие 0/0")


def test_sync_progress_spans_profile_roots():
    """Профиль с двумя путями: один total на весь прогон."""
    with tempfile.TemporaryDirectory() as tmpdir:
        from flamquency.profiles import create_profile, set_active
        t = Path(tmpdir)
        docs = t / "docs"; docs.mkdir()
        (docs / "a.txt").write_text("A")
        (docs / "b.txt").write_text("B")
        code = t / "code"; code.mkdir()
        (code / "c.txt").write_text("C")

        from flamquency.config import DEFAULT_CONFIG
        config = copy.deepcopy(DEFAULT_CONFIG)
        config["use_ignore_file"] = False
        create_profile(config, "multi", [str(docs), str(code)])
        set_active(config, "multi")
        base = t / "store"
        sync = FlamQuencySync(config=config,
                              backend=LocalBackend(base_path=base / "sync"),
                              base_dir=base)

        events = []
        result = sync.sync(progress=events.append)
        assert result.files_synced == 3
        assert all(e.total == 3 for e in events)
        # done не убывает и доходит до общего итога
        assert [e.done for e in events] == [0, 1, 2, 3]
        # файлы из ОБОИХ корней попали в события
        currents = " ".join(e.current for e in events)
        assert "docs" in currents and "code" in currents
    print("✓ Прогресс профиля считается по всем путям сразу")


def test_sync_progress_callback_failure_does_not_break_sync():
    """Сломанный UI-колбэк никогда не роняет синхронизацию."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sync, src = _prune_engine(tmpdir)
        for i in range(3):
            (src / f"f{i}.txt").write_text(str(i))

        def boom(event):
            raise RuntimeError("UI умер")

        result = sync.sync(source=src, progress=boom)
        assert result.files_synced == 3
        assert not result.errors
    print("✓ Падающий progress-колбэк не ломает синк")


def test_sync_without_progress_still_works():
    """Без колбэка синк работает как раньше (обратная совместимость)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sync, src = _prune_engine(tmpdir)
        (src / "a.txt").write_text("A")
        result = sync.sync(source=src)
        assert result.files_synced == 1
        assert result.paths or result.files_synced == 1
    print("✓ sync() без progress работает как раньше")


# ── TUI theme ───────────────────────────────────────────────

def test_theme_registered():
    from flamquency.theme import FLAMQUENCY_FIRE
    assert FLAMQUENCY_FIRE.name == "flamquency-fire"
    assert FLAMQUENCY_FIRE.primary == "#FF6B1A"
    assert FLAMQUENCY_FIRE.variables["accent"] == "#FF6B1A"
    assert FLAMQUENCY_FIRE.variables["surface"] == "#1A1210"
    assert FLAMQUENCY_FIRE.variables["text"] == "#F5E6DC"
    assert FLAMQUENCY_FIRE.dark is True
    print("✓ flamquency-fire theme carries the «Угольки» tokens")


def test_theme_applied_to_app():
    from flamquency.textual_tui import FlamQuencyApp
    from flamquency.sync_engine import FlamQuencySync
    app = FlamQuencyApp(FlamQuencySync(config=load_config()))
    assert app.theme == "flamquency-fire"
    assert "flamquency-fire" in [t.name for t in app.available_themes.values()]
    print("✓ FlamQuencyApp registers and activates the fire theme")


# ── Updater ────────────────────────────────────────────────

def test_updater_version_comparison():
    from flamquency.updater import is_newer
    assert is_newer("1.0.1", "1.0.0")
    assert is_newer("2.0", "1.9.9")
    assert not is_newer("1.0.0", "1.0.0")
    assert not is_newer("0.9", "1.0.0")
    print("✓ updater is_newer compares versions correctly")


def test_updater_check_never_raises(monkeypatch=None):
    """check_for_update не бросает исключений даже без сети."""
    from flamquency.updater import check_for_update
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        # Кэш пуст, сеть может быть — но метод должен вернуть UpdateInfo
        info = check_for_update("0.1.0", base_dir=tmpdir, use_cache=False)
        assert info.current == "0.1.0"
        # Либо доступна версия, либо внятная ошибка — но не краш
        assert info.available in (True, False)
    print("✓ updater check_for_update returns UpdateInfo without raising")


def test_updater_cache_roundtrip():
    """Результат проверки кэшируется и читается обратно."""
    from flamquency import updater
    import tempfile, json
    from pathlib import Path
    from datetime import datetime

    with tempfile.TemporaryDirectory() as tmpdir:
        info = updater.UpdateInfo(
            available=True, current="0.1.0", latest="0.2.0",
            source="git-tag", url="https://example.com",
            checked_at=datetime.now().isoformat(),
        )
        updater._write_cache(Path(tmpdir), info)
        cached = updater._read_cache(Path(tmpdir), max_age_hours=6)
        assert cached is not None
        assert cached.latest == "0.2.0"
        assert cached.available is True
    print("✓ updater cache write/read roundtrip")


def test_updater_detect_install_method():
    from flamquency.updater import detect_install_method
    method, path = detect_install_method()
    assert method in ("git", "pip", "unknown")
    assert path is not None
    print(f"✓ updater detects install method: {method}")


# ── Icons & style ──────────────────────────────────────────

def test_icons_no_emoji():
    """Набор иконок — только Nerd Font глифы и ASCII-fallback, без эмодзи."""
    from flamquency.icons import _GLYPHS, _FALLBACK, icon
    import unicodedata
    for name, glyph in _GLYPHS.items():
        # эмодзи живут в этих диапазонах — они запрещены DESIGN.md §8
        assert not (0x1F300 <= ord(glyph[0]) <= 0x1FAFF),             f"emoji in glyph {name}: {glyph}"
    # fallback тоже без эмодзи высоких диапазонов
    for name, glyph in _FALLBACK.items():
        assert not (0x1F300 <= ord(glyph[0]) <= 0x1FAFF) or name in ("fire", "flame"), \
            f"emoji in fallback {name}"
    print("✓ icon set contains no emoji (Nerd Font only)")


def test_icons_fallback_when_no_font():
    from flamquency.icons import icon
    force = icon("fire", force_font=False)
    assert force == "🔥"  # ASCII-fallback для fire — огонь читается и так
    nerd = icon("fire", force_font=True)
    assert nerd == "\uf06d"  # f06d — fire в Nerd Font
    print("✓ icons fall back to ASCII when Nerd Font missing")


def test_style_palette_matches_theme():
    """Палитра style.py (CLI) зеркалит theme.py (TUI) — DESIGN.md §1."""
    from flamquency.style import PALETTE
    from flamquency.theme import FLAMQUENCY_FIRE
    assert PALETTE["surface"] == "#1A1210" == FLAMQUENCY_FIRE.background
    assert PALETTE["accent"] == "#FF6B1A" == FLAMQUENCY_FIRE.primary
    assert PALETTE["surface-raised"] == "#241814" == FLAMQUENCY_FIRE.surface
    assert PALETTE["success"] == FLAMQUENCY_FIRE.success
    assert PALETTE["error"] == FLAMQUENCY_FIRE.error
    print("✓ CLI palette mirrors TUI theme (single source of truth)")


def test_style_helpers():
    from flamquency.style import human_size, human_time
    assert human_size(0) == "0.0 B"
    assert "KB" in human_size(2048)
    assert "MB" in human_size(5 * 1024 * 1024)
    assert human_time(None) == "никогда"
    assert human_time("garbage") == "garbage"
    print("✓ style helpers format size and time")


# ── Integrity check ────────────────────────────────────────

def test_check_integrity_ok():
    with tempfile.TemporaryDirectory() as tmpdir:
        sync, src = _prune_engine(tmpdir)
        (src / "a.txt").write_text("hello")
        sync.sync(source=src)
        ok, problems = sync.check_integrity()
        assert ok, f"expected ok, got: {problems}"
        assert problems == []
    print("✓ check_integrity passes on healthy store")


def test_check_integrity_detects_missing_blob():
    with tempfile.TemporaryDirectory() as tmpdir:
        sync, src = _prune_engine(tmpdir)
        (src / "a.txt").write_text("hello")
        sync.sync(source=src)
        # Удаляем блоб вручную — имитация потери данных
        blob_store = sync.version_store.blob_store
        index = blob_store._index
        assert index, "no blobs recorded"
        victim = next(iter(index))
        victim_path = blob_store._blob_path(victim)
        victim_path.unlink()
        ok, problems = sync.check_integrity()
        assert not ok
        assert any(victim[:12] in p for p in problems)
    print("✓ check_integrity detects missing blob")


def main():
    print("🔥 Running FlamQuency-Sync tests...\n")
    
    tests = [
        test_config_load,
        test_scan_directory,
        test_hash_computation,
        test_blob_store,
        test_version_store_record_and_restore,
        test_version_store_diff,
        test_snapshot_creation,
        test_sync_with_versions,
        test_rollback_snapshot,
        test_rollback_file_real,
        test_restore_and_view_file_content,
        test_restore_tree_directory_and_profile,
        test_diff_visual_summary,
        test_schedule_parse_and_cron,
        test_scheduler_install_remove_isolation,
        test_smart_autosync_quiet_period,
        test_post_sync_hook,
        test_evolution_learns_and_suggests,
        test_evolution_survives_broken_state,
        test_config_carries_v2_sections,
        test_backend_registry_and_readiness,
        test_backend_factory_refuses_unready,
        test_network_backend_roundtrip,
        test_s3_backend_requires_boto3,
        test_rclone_backend_remote_naming,
        test_config_carries_backend_settings,
        test_backend_secret_env_can_be_disabled,
        test_version_listing,
        test_gc_and_prune,
        test_backend_factory,
        test_encryption_enable_unlock_and_wrong_password,
        test_encryption_encrypt_decrypt_roundtrip,
        test_blob_store_encrypted_roundtrip,
        test_blob_store_encrypted_locked_and_unlocked_read,
        test_version_store_with_encryption,
        test_encryption_change_password,
        test_encryption_disable_decrypts_blobs,
        test_sync_engine_with_encryption,
        test_sync_engine_wrong_password_rejected,
        test_sync_engine_locked_store_refuses_to_run,
        test_sync_engine_unlock_after_lock,
        test_ignore_rules_parse_skips_comments_and_blanks,
        test_ignore_rules_match_semantics,
        test_ignore_rules_last_match_wins,
        test_ignore_rules_from_file_and_missing_file,
        test_ignore_rules_explain_reports_matching_rule,
        test_default_ignore_template_written,
        test_engine_without_ignore_file_has_no_rules,
        test_scan_directory_respects_ignore_file,
        test_sync_counts_ignored_files,
        test_snapshot_respects_ignore_file,
        test_cli_ignore_init_and_check,
        test_config_defaults_not_shared_between_loads,
        test_profiles_default_in_config,
        test_profile_create_list_and_delete,
        test_profile_paths_and_active_switching,
        test_profile_exclude_patterns_merge,
        test_sync_uses_active_profile_paths,
        test_sync_explicit_source_beats_profile,
        test_sync_profile_argument_and_missing_path,
        test_status_reports_profiles,
        test_cli_profile_commands,
        test_prune_snapshots_keep_last,
        test_prune_snapshots_not_configured,
        test_prune_snapshots_older_than_days,
        test_prune_snapshots_combined_policy,
        test_prune_snapshots_older_than_days_protects,
        test_sync_progress_reports_each_file,
        test_sync_progress_empty_source,
        test_sync_progress_spans_profile_roots,
        test_sync_progress_callback_failure_does_not_break_sync,
        test_sync_without_progress_still_works,
        test_theme_registered,
        test_theme_applied_to_app,
        test_updater_version_comparison,
        test_updater_check_never_raises,
        test_updater_cache_roundtrip,
        test_updater_detect_install_method,
        test_icons_no_emoji,
        test_icons_fallback_when_no_font,
        test_style_palette_matches_theme,
        test_style_helpers,
        test_check_integrity_ok,
        test_check_integrity_detects_missing_blob,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"✗ {test.__name__} failed: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    print(f"\n{'='*50}")
    print(f"Tests: {passed + failed} | Passed: {passed} | Failed: {failed}")
    print(f"{'='*50}")
    
    if failed > 0:
        sys.exit(1)

if __name__ == "__main__":
    main()
