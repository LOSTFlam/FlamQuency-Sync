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
    print(f"🔥 Starting sync...")
    if source:
        print(f"   Source: {source}")
    else:
        print(f"   Source: ~/.flamquency (default)")

    try:
        result = sync.sync(source=source)
    except EncryptionLockedError as e:
        print(f"🔐 {e}")
        return 1
    except DecryptionError as e:
        print(f"🔐 {e}")
        return 1
    
    print(f"\n✅ Sync complete!")
    print(f"   Files synced:   {result.files_synced}")
    print(f"   Files changed:  {result.files_changed}")
    print(f"   Files excluded: {result.files_excluded}")
    print(f"   Blobs stored:   {result.blobs_stored}")
    
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


def main():
    parser = argparse.ArgumentParser(
        prog="flamquency",
        description="🔥 Terminal-based file synchronization with version control",
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # sync
    p_sync = subparsers.add_parser("sync", help="Synchronize files")
    p_sync.add_argument("--source", "-s", help="Source directory (default: ~/.flamquency)")
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
        "watch": cmd_watch,
        "config": cmd_config,
        "encryption": cmd_encryption,
    }
    
    handler = commands.get(args.command)
    if handler:
        sys.exit(handler(args))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
