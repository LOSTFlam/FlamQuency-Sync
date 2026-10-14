"""Terminal User Interface for FlamQuency-Sync using Rich."""
import sys
import time
import json
from pathlib import Path
from datetime import datetime
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from flamquency import __version__

console = Console()

class FlamQuencyTUI:
    """TUI interface for FlamQuency-Sync."""
    
    def __init__(self, sync_engine):
        self.sync = sync_engine
        self.running = True
    
    def clear(self):
        console.clear()
    
    def draw_header(self):
        from flamquency.icons import icon as _icon
        title = Text(f"{_icon('fire')} FlamQuency-Sync", style="bold cyan")
        version = Text(
            f"v{self.sync.config.get('__version__', __version__)}",
            style="dim")
        header = Panel(title + " " + version, border_style="cyan")
        console.print(header)
        console.print()
    
    def draw_status(self):
        status = self.sync.status()
        table = Table(show_header=False, box=None)
        table.add_row("Last sync:", status.get("last_sync", "Never"))
        table.add_row("Backend:", status.get("backend", "local"))
        table.add_row("Files synced:", str(status.get("files_synced", 0)))
        table.add_row("Tracked files:", str(status.get("tracked_files", 0)))
        table.add_row("Stored blobs:", str(status.get("blob_count", 0)))
        storage_mb = status.get("storage_bytes", 0) / (1024*1024)
        table.add_row("Storage:", f"{storage_mb:.2f} MB")
        active = status.get("active_profile", "default")
        profiles = status.get("profiles", [])
        table.add_row("Profile:", f"{active} ({len(profiles)} total)")
        panel = Panel(table, title=" Status ", border_style="green")
        console.print(panel)
    
    def draw_main_menu(self):
        self.clear()
        self.draw_header()
        
        options = [
            ("1", "Sync Now", "Start synchronization"),
            ("2", "Rollback", "Restore previous state"),
            ("3", "File Versions", "Per-file version history"),
            ("4", "Settings", "Configure options"),
            ("5", "About", "About FlamQuency-Sync"),
            ("6", "Exit", "Exit"),
        ]
        
        table = Table(show_header=False, box=None)
        for key, title, desc in options:
            table.add_row(f"[{key}]", title, desc)
        
        console.print(Panel(table, title=" Main Menu ", border_style="blue"))
        console.print()
    
    def handle_input(self, choice):
        if choice == "1":
            self.do_sync()
        elif choice == "2":
            self.do_rollback()
        elif choice == "3":
            self.do_file_versions()
        elif choice == "4":
            self.do_settings()
        elif choice == "5":
            self.do_about()
        elif choice == "6":
            self.running = False
            console.clear()
            console.print("Goodbye! ✨")
            time.sleep(0.5)
            sys.exit(0)
        else:
            console.print("[red]Invalid choice[/red]")
            time.sleep(1)
    
    def do_sync(self):
        self.clear()
        self.draw_header()
        console.print("[bold cyan]Starting synchronization...[/bold cyan]\n")
        
        result = self.sync.sync()
        
        table = Table(show_header=False, box=None)
        table.add_row("Files synced:", str(result.files_synced))
        table.add_row("Files changed:", str(result.files_changed))
        table.add_row("Files excluded:", str(result.files_excluded))
        table.add_row("Blobs stored:", str(result.blobs_stored))
        table.add_row("Errors:", str(len(result.errors)))
        
        console.print(Panel(table, title=" Sync Results ", border_style="green"))
        
        if result.errors:
            console.print("\n[red]Errors:[/red]")
            for e in result.errors[:5]:
                console.print(f"  {e}")
        
        console.print("\nPress Enter to continue...")
        input()
    
    def do_rollback(self):
        self.clear()
        self.draw_header()
        
        # List snapshots
        snapshots = self.sync.list_snapshots()
        
        if snapshots:
            table = Table(show_header=True, header_style="bold cyan")
            table.add_column("#", style="dim")
            table.add_column("Name")
            table.add_column("Timestamp")
            table.add_column("Files", justify="right")
            
            for i, snap in enumerate(snapshots):
                table.add_row(
                    str(i+1),
                    snap["name"],
                    snap["timestamp"][:19],
                    str(snap["file_count"]),
                )
            
            console.print(Panel(table, title=" Available Snapshots ", border_style="red"))
        else:
            console.print("[red]No snapshots available[/red]")
        
        console.print("\nEnter snapshot number to rollback (0 = cancel): ", end="")
        choice = input().strip()
        
        if choice.isdigit() and int(choice) > 0 and int(choice) <= len(snapshots):
            snap = snapshots[int(choice) - 1]
            console.print(f"\n[yellow]Rolling back to {snap['name']}...[/yellow]")
            success, msg = self.sync.rollback_to_snapshot(snap["name"])
            console.print(f"[{'green' if success else 'red'}]{msg}[/]")
            console.print("\nPress Enter to continue...")
            input()
    
    def do_file_versions(self):
        self.clear()
        self.draw_header()
        
        console.print("[bold cyan]Per-File Version History[/bold cyan]\n")
        
        # List tracked files
        versions_dir = self.sync.version_dir
        tracked = []
        if versions_dir.exists():
            for vf in versions_dir.glob("*.json"):
                try:
                    history = json.loads(vf.read_text())
                    rel_name = vf.stem.replace("__", "/")
                    tracked.append((rel_name, len(history)))
                except:
                    pass
        
        if tracked:
            table = Table(show_header=True, header_style="bold cyan")
            table.add_column("File")
            table.add_column("Versions", justify="right")
            
            for name, count in sorted(tracked)[:20]:
                table.add_row(name, str(count))
            
            console.print(Panel(table, title=f" Tracked Files ({len(tracked)} total) ", border_style="magenta"))
        else:
            console.print("[dim]No tracked files yet. Run a sync first.[/dim]")
        
        console.print("\nEnter file path to view versions (empty = back): ", end="")
        filepath = input().strip()
        
        if filepath:
            fp = Path(filepath).expanduser()
            success, info = self.sync.rollback_file(str(fp))
            
            if success and isinstance(info, dict):
                console.print(f"\n[bold]Versions of {info['rel_path']}:[/bold]")
                
                vtable = Table(show_header=True, header_style="bold cyan")
                vtable.add_column("#")
                vtable.add_column("Hash")
                vtable.add_column("Timestamp")
                vtable.add_column("Size")
                vtable.add_column("Message")
                
                for v in info["versions"]:
                    vtable.add_row(
                        str(v["index"]),
                        v["hash"],
                        v["timestamp"][:19],
                        str(v["size"]),
                        v["message"][:30],
                    )
                
                console.print(vtable)
                console.print("\nEnter version number to restore (empty = cancel): ", end="")
                vchoice = input().strip()
                if vchoice.isdigit():
                    vnum = int(vchoice)
                    success2, msg2 = self.sync.rollback_file(str(fp), version_index=vnum)
                    console.print(f"\n[{'green' if success2 else 'red'}]{msg2}[/]")
            else:
                console.print(f"\n[red]{info}[/red]")
            
            console.print("\nPress Enter to continue...")
            input()
    
    def do_settings(self):
        self.clear()
        self.draw_header()
        console.print("[bold]Settings[/bold]")
        console.print(f"Config file: {Path.home() / '.flamquency' / 'config.yaml'}")
        console.print("\nEdit the YAML config file to change settings.")
        console.print("\nPress Enter to continue...")
        input()
    
    def do_about(self):
        self.clear()
        self.draw_header()
        console.print(f"[bold]{_icon('fire')} FlamQuency-Sync[/bold]")
        console.print(f"Version {__version__}")
        console.print("Terminal-based file synchronization with real versioning")
        console.print("\nFeatures:")
        console.print("  • Content-addressable blob storage (SHA256)")
        console.print("  • Per-file version history with real restore")
        console.print("  • Full system snapshots")
        console.print("  • Exclusion patterns")
        console.print("  • zlib compression & deduplication")
        console.print("\n© 2026 LOSTFlam")
        console.print("\nPress Enter to continue...")
        input()
    
    def run(self):
        while self.running:
            self.draw_main_menu()
            try:
                choice = input("Choose option (1-6): ").strip()
                self.handle_input(choice)
            except (KeyboardInterrupt, EOFError):
                self.running = False
                sys.exit(0)

def run_tui(sync_engine):
    tui = FlamQuencyTUI(sync_engine)
    tui.run()
