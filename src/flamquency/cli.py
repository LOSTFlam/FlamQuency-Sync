#!/usr/bin/env python3
"""CLI entry point for FlamQuency-Sync — no TUI, just commands."""
import sys
import os
import json
import argparse
from pathlib import Path
from datetime import datetime

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
        pw = getpass.getpass("🔐 Blob store password: ")
        if pw:
            return pw
    except (EOFError, KeyboardInterrupt):
        pass
    return None


def get_sync_engine(config=None, password=None):
    """Initialize sync engine with configured backend."""
    if config is None:
        config = load_config()

    backend_type = config.get("cloud_backend", "local")
    if backend_type == "local":
        backend = LocalBackend()
    elif backend_type == "github":
        backend = get_backend("github",
                             repo_name=config.get("cloud_repo_name"),
                             token=config.get("github_token"))
    else:
        backend = LocalBackend()

    backend.authenticate()
    if password is None and (config.get("encryption") or {}).get("enabled"):
        # Only ask for a password when the store is actually encrypted
        password = resolve_password(None)
    return FlamQuencySync(config=config, backend=backend, password=password)


def cmd_sync(args):
    """Execute synchronization."""
    try:
        sync = get_sync_engine(password=getattr(args, "password", None))
    except (WrongPasswordError, EncryptionError) as e:
        print(f"🔐 {e}")
        return 1

    source = Path(args.source) if args.source else None
    profile = getattr(args, "profile", None)
    print(f"🔥 Starting sync...")
    if profile:
        print(f"   Profile: {profile}")
    if source:
        print(f"   Source: {source}")
    elif profile:
        print("   Paths: from profile")
    else:
        print("   Paths: from active profile (~/.flamquency by default)")

    try:
        result = sync.sync(source=source, profile=profile)
    except EncryptionLockedError as e:
        print(f"🔐 {e}")
        return 1
    except DecryptionError as e:
        print(f"🔐 {e}")
        return 1
    except ProfileError as e:
        print(f"❌ {e}")
        return 1

    print(f"\n✅ Sync complete!")
    if result.profile:
        print(f"   Profile:      {result.profile}")
    print(f"   Files synced:   {result.files_synced}")
    print(f"   Files changed:  {result.files_changed}")
    print(f"   Files excluded: {result.files_excluded}")
    print(f"   Blobs stored:   {result.blobs_stored}")

    if result.paths:
        print("\n   Per path:")
        for entry in result.paths:
            print(f"      [{entry['label']}] {entry['files_synced']} file(s) — {entry['path']}")
    
    if result.errors:
        print(f"\n⚠️  {len(result.errors)} error(s):")
        for e in result.errors[:5]:
            print(f"   {e}")
    
    return 0 if not result.errors else 1


def cmd_rollback(args):
    """Rollback to snapshot."""
    sync = get_sync_engine()
    snapshots = sync.list_snapshots()
    
    if not snapshots:
        print("❌ No snapshots available")
        return 1
    
    if args.list:
        print("📸 Available snapshots:")
        for i, snap in enumerate(reversed(snapshots)):
            ts = snap["timestamp"][:19].replace("T", " ")
            print(f"   [{i}] {ts}  ({snap['file_count']} files)")
        return 0
    
    if args.snapshot is not None:
        if 0 <= args.snapshot < len(snapshots):
            snap = snapshots[args.snapshot]
            print(f"⏪ Rolling back to {snap['name']}...")
            success, msg = sync.rollback_to_snapshot(snap["name"])
            print(f"{'✅' if success else '❌'} {msg}")
            return 0 if success else 1
        else:
            print(f"❌ Invalid snapshot index: {args.snapshot}")
            return 1
    
    # No snapshot specified — show list
    print("Available snapshots:")
    for i, snap in enumerate(reversed(snapshots)):
        ts = snap["timestamp"][:19].replace("T", " ")
        print(f"   [{i}] {ts}  ({snap['file_count']} files)")
    print("\nUse: flamquency rollback --snapshot N")
    return 0


def cmd_rollback_file(args):
    """Rollback specific file."""
    try:
        sync = get_sync_engine(password=getattr(args, "password", None))
    except (WrongPasswordError, EncryptionError) as e:
        print(f"🔐 {e}")
        return 1

    filepath = Path(args.file).expanduser()
    
    if args.list:
        success, info = sync.rollback_file(str(filepath))
        if not success:
            print(f"❌ {info}")
            return 1
        
        if isinstance(info, dict):
            print(f"📄 {info['rel_path']}")
            print(f"   {info['version_count']} version(s):\n")
            for v in info["versions"]:
                ts = v["timestamp"][:19].replace("T", " ")
                print(f"   [{v['index']}] {ts}  hash:{v['hash']}  size:{v['size']}")
        return 0
    
    if args.version is not None:
        success, msg = sync.rollback_file(str(filepath), version_index=args.version)
        print(f"{'✅' if success else '❌'} {msg}")
        return 0 if success else 1
    
    # Show versions
    success, info = sync.rollback_file(str(filepath))
    if success and isinstance(info, dict):
        print(f"📄 {info['rel_path']} — {info['version_count']} version(s)")
        print("Use: flamquency rollback-file FILE --version N")
        return 0
    print(f"❌ {info}")
    return 1


def cmd_status(args):
    """Show sync status."""
    sync = get_sync_engine()
    status = sync.status()
    
    print("🔥 FlamQuency-Sync Status")
    print(f"   Backend:      {status.get('backend', 'local')}")
    print(f"   Last sync:    {status.get('last_sync', 'Never')}")
    print(f"   Tracked:      {status.get('tracked_files', 0)} files")
    print(f"   Blobs:        {status.get('blob_count', 0)}")
    storage_mb = status.get("storage_bytes", 0) / (1024 * 1024)
    print(f"   Storage:      {storage_mb:.2f} MB")

    # Encryption
    enc = status.get("encryption", "disabled")
    enc_icons = {"enabled": "🔒", "locked": "🔐", "disabled": "🔓"}
    print(f"   Encryption:   {enc_icons.get(enc, '🔓')} {enc}")

    # Snapshots
    snapshots = sync.list_snapshots()
    print(f"   Snapshots:    {len(snapshots)}")

    # Ignore rules
    ig_file = status.get("ignore_file")
    if ig_file:
        print(f"   Ignore file:  {ig_file} ({status.get('ignore_rules', 0)} rules)")
    else:
        print(f"   Ignore file:  ~/.flamquencyignore (not created yet)")

    # Profiles
    profiles = status.get("profiles", [])
    active = status.get("active_profile", "default")
    print(f"   Profile:      {active} ({len(profiles)} total: {', '.join(profiles)})")

    return 0


def cmd_diff(args):
    """Diff two versions of a file."""
    sync = get_sync_engine()
    filepath = Path(args.file).expanduser()
    
    success, diff = sync.diff_file(str(filepath), args.v1, args.v2)
    if not success:
        print(f"❌ {diff}")
        return 1
    
    print(diff)
    return 0


def cmd_snapshots(args):
    """List snapshots."""
    sync = get_sync_engine()
    snapshots = sync.list_snapshots()
    
    if not snapshots:
        print("No snapshots available")
        return 0
    
    print(f"📸 {len(snapshots)} snapshot(s):")
    for i, snap in enumerate(reversed(snapshots)):
        ts = snap["timestamp"][:19].replace("T", " ")
        print(f"   [{i}] {ts}  ({snap['file_count']} files)")
    
    return 0


def cmd_watch(args):
    """Watch mode — auto-sync on file changes."""
    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler
    except ImportError:
        print("❌ Watch mode requires 'watchdog'. Install: pip install watchdog")
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
            print(f"   ✅ Synced {result.files_synced} files")
    
    observer = Observer()
    handler = SyncHandler()
    
    for path in watch_paths:
        if path.exists():
            observer.schedule(handler, str(path), recursive=True)
            print(f"👁 Watching: {path}")
        else:
            print(f"⚠️ Path not found: {path}")
    
    observer.start()
    print("\n🔥 Watch mode active. Press Ctrl+C to stop.\n")
    
    try:
        while True:
            import time
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        print("\n👋 Watch mode stopped")
    
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
            print("🔓 Encryption: DISABLED (blobs stored in plaintext)")
        elif mgr.is_unlocked:
            print("🔒 Encryption: ENABLED and UNLOCKED")
        else:
            print("🔒 Encryption: ENABLED but LOCKED (password required)")
        print(f"   Key file: {mgr.key_path}")
        return 0

    if action == "enable":
        mgr = EncryptionManager(store_dir)
        if mgr.is_configured:
            print("❌ Encryption is already enabled")
            return 1
        password = resolve_password(args.password)
        if not password:
            print("❌ A password is required to enable encryption")
            return 1
        mgr = EncryptionManager.enable(store_dir, password)
        config["encryption"] = {"enabled": True}
        save_config(config)
        print("🔒 Encryption enabled!")
        print("   New blobs will be encrypted with AES-128 (Fernet).")
        print(f"   Key file: {mgr.key_path} (keep it safe — no password, no data)")
        return 0

    if action == "disable":
        mgr = EncryptionManager(store_dir)
        if not mgr.is_configured:
            print("❌ Encryption is not enabled")
            return 1
        password = resolve_password(args.password)
        if not password:
            print("❌ A password is required to disable encryption")
            return 1
        try:
            mgr.unlock(password)
        except WrongPasswordError:
            print("❌ Wrong password")
            return 1
        sync = get_sync_engine(config=config, password=password)
        decrypted = sync.version_store.blob_store.disable_encryption(mgr)
        config["encryption"] = {"enabled": False}
        save_config(config)
        print(f"🔓 Encryption disabled — {decrypted} blob(s) decrypted in place")
        return 0

    if action == "change-password":
        mgr = EncryptionManager(store_dir)
        if not mgr.is_configured:
            print("❌ Encryption is not enabled")
            return 1
        old_pw = resolve_password(args.password)
        if not old_pw:
            print("❌ Current password is required")
            return 1
        try:
            mgr.unlock(old_pw)
        except WrongPasswordError:
            print("❌ Wrong password")
            return 1
        import getpass
        new_pw = args.new_password or getpass.getpass("🔐 New password: ")
        if not new_pw:
            print("❌ New password must not be empty")
            return 1
        if not args.new_password:
            confirm = getpass.getpass("🔐 Confirm new password: ")
            if new_pw != confirm:
                print("❌ Passwords do not match")
                return 1
        new_mgr = mgr.change_password(new_pw)
        sync = get_sync_engine(config=config, password=new_pw)
        rekeyed = sync.version_store.blob_store.rekey(mgr, new_mgr)
        print(f"🔑 Password changed — {rekeyed} blob(s) re-encrypted")
        return 0

    print(f"❌ Unknown encryption action: {action}")
    return 1


def cmd_ignore(args):
    """Manage ~/.flamquencyignore — init / add / check / list."""
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
            print(f"⚠️  {path} already exists — nothing written")
            print("   Use --force to overwrite with the default template")
            return 1
        rules = IgnoreRules.from_file(written)
        print(f"📝 Created {written} ({len(rules)} rules)")
        print("   Syntax works like .gitignore — edit it any time")
        return 0

    # ── --add: append one pattern ──────────────────────────────
    if getattr(args, "add", None):
        if not path.exists():
            # start from the template so the user gets the comments too
            write_default_ignore_file(path)
        with open(path, "a") as f:
            f.write(f"\n{args.add.strip()}\n")
        rules = IgnoreRules.from_file(path)
        print(f"➕ Added '{args.add.strip()}' → {path}")
        print(f"   {len(rules)} rule(s) total")
        return 0

    # ── --check: explain one path ──────────────────────────────
    if getattr(args, "check", None):
        rules = IgnoreRules.from_file(path)
        target = args.check
        ignored, rule = rules.explain(target)
        if ignored:
            print(f"🚫 IGNORED:    {target}")
            if rule is not None:
                print(f"   by rule: {rule.raw}")
        elif rule is not None:
            print(f"✅ NOT IGNORED: {target}")
            print(f"   re-included by: {rule.raw}")
        else:
            print(f"✅ NOT IGNORED: {target}")
            print(f"   (no rule matches — {len(rules)} rule(s) checked)")
        return 0

    # ── --list / default: show the rules ───────────────────────
    rules = IgnoreRules.from_file(path)
    if not path.exists():
        print(f"📄 No ignore file yet at {path}")
        print("   Create one with: flamquency ignore --init")
        return 0
    print(f"📄 {path} — {len(rules)} rule(s)")
    if not rules:
        return 0
    for rule in rules:
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


def cmd_profile(args):
    """Manage sync profiles — named sets of paths for different scenarios."""
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
            print("   Switch with: flamquency profile use NAME")
            return 0

        if action == "create":
            name = args.name
            paths = profile_paths_arg()
            if not paths:
                print("❌ At least one path is required to create a profile")
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
            print(f"✅ Active profile: {name}")
            print("   `flamquency sync` now follows this profile")
            return 0

        if action == "add-path":
            name = args.name
            paths = profile_paths_arg()
            if not paths:
                print("❌ At least one path is required")
                return 1
            for p in paths:
                add_path(config, name, p)
            save()
            prof = get_profile(config, name)
            print(f"➕ Profile '{name}' now has {len(prof['paths'])} path(s):")
            for p in prof["paths"]:
                print(f"      {p}")
            return 0

        if action == "remove-path":
            name = args.name
            paths = profile_paths_arg()
            if not paths:
                print("❌ At least one path is required")
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

        print(f"❌ Unknown profile action: {action}")
        return 1

    except ProfileError as e:
        print(f"❌ {e}")
        return 1


def cmd_config(args):
    """Show or edit configuration."""
    config = load_config()
    
    if args.edit:
        config_path = Path.home() / ".flamquency" / "config.yaml"
        editor = os.environ.get("EDITOR", "nano")
        os.system(f"{editor} {config_path}")
        return 0
    
    print("🔥 FlamQuency-Sync Configuration")
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
        print(f"✅ Created {ignore_path}")
    elif ignore_path.exists():
        print(f"ℹ️  Ignore file exists: {ignore_path}")

    # 2. Retention defaults (если не заданы)
    retention = config.get("retention")
    if not retention:
        config["retention"] = {"keep_last": args.keep_last}
        save_config(config)
        print(f"✅ Retention: keep last {args.keep_last} snapshots")

    # 3. Опционально: git-репозиторий для снапшотов
    if args.git:
        snapshots_dir = config_dir / "snapshots"
        if not (snapshots_dir / ".git").exists():
            import subprocess
            subprocess.run(["git", "init", "-q"], cwd=snapshots_dir, check=False)
            print(f"✅ Git repo initialized in {snapshots_dir}")
        else:
            print(f"ℹ️  Git repo already exists in {snapshots_dir}")

    print("\n🔥 FlamQuency-Sync initialized!")
    print(f"   Config:  {config_dir / 'config.yaml'}")
    print(f"   Ignore:  {ignore_path}")
    print(f"   Snapshots: {config_dir / 'snapshots'}")
    print("\nNext steps:")
    print("   1. flamquency status          — проверить состояние")
    print("   2. flamquency sync            — первый синк")
    print("   3. flamquency-tui             — запустить TUI")
    return 0


def cmd_prune(args):
    """Prune old snapshots (retention policy)."""
    sync = get_sync_engine()

    keep_last = args.keep_last
    older_than = args.older_than

    if keep_last is None and older_than is None:
        retention = (sync.config.get("retention") or {})
        keep_last = retention.get("keep_last")
        older_than = retention.get("older_than_days")

    if keep_last is None and older_than is None:
        print("❌ No retention policy set. Use --keep-last N or --older-than DAYS")
        print("   Or set retention in ~/.flamquency/config.yaml")
        return 1

    if args.dry_run:
        snapshots = sync.list_snapshots()
        total = len(snapshots)
        print(f"📸 {total} snapshot(s) on disk")
        if keep_last is not None:
            excess = max(0, total - keep_last)
            print(f"   Would prune {excess} (keeping last {keep_last})")
        if older_than is not None:
            print(f"   Would prune older than {older_than} days")
        if not args.yes:
            confirm = input("Continue? [y/N] ")
            if confirm.lower() != "y":
                print("Cancelled")
                return 0
        deleted, msg = sync.prune_snapshots(keep_last, older_than)
    else:
        deleted, msg = sync.prune_snapshots(keep_last, older_than)

    print(f"🧹 {msg}")
    return 0


def main():
    parser = argparse.ArgumentParser(
        prog="flamquency",
        description="🔥 Terminal-based file synchronization with version control",
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
    p_prune = subparsers.add_parser("prune", help="Prune old snapshots (retention)")
    p_prune.add_argument("--keep-last", type=int, help="Keep last N snapshots")
    p_prune.add_argument("--older-than", type=int, metavar="DAYS",
                         help="Delete snapshots older than DAYS")
    p_prune.add_argument("--dry-run", action="store_true", help="Show what would be deleted")
    p_prune.add_argument("--yes", "-y", action="store_true", help="Skip confirmation")
    
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

    args = parser.parse_args()
    
    if not args.command:
        # Default to TUI
        from flamquency.main import main
        main()
        return
    
    commands = {
        "sync": cmd_sync,
        "rollback": cmd_rollback,
        "rollback-file": cmd_rollback_file,
        "status": cmd_status,
        "diff": cmd_diff,
        "snapshots": cmd_snapshots,
        "init": cmd_init,
        "prune": cmd_prune,
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
