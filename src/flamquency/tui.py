"""Terminal User Interface for FlamQuency-Sync using Rich."""
import sys
import time
from datetime import datetime
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

console = Console()

class FlamQuencyTUI:
    """TUI interface for FlamQuency-Sync."""
    
    def __init__(self, sync_engine):
        self.sync = sync_engine
        self.running = True
    
    def clear(self):
        """Clear terminal screen."""
        console.clear()
    
    def draw_header(self):
        """Draw the application header."""
        title = Text("FlamQuency-Sync", style="bold cyan")
        version = Text(f"v{self.sync.config.get('__version__', '0.1.0')}", style="dim")
        subtitle = Text("File Synchronization with Rollback", style="dim")
        
        header = Panel(title + " " + version, subtitle_align="right", border_style="cyan")
        console.print(header)
        console.print()  # spacer
    
    def draw_status(self):
        """Draw current sync status."""
        status = self.sync.status()
        
        table = Table(show_header=False, box=None)
        table.add_row("Last sync:", status.get("last_sync", "Never"))
        table.add_row("Backend:", status.get("backend", "local"))
        table.add_row("Files synced:", str(status.get("files_synced", 0)))
        
        panel = Panel(table, title=" Status ", border_style="green")
        console.print(panel)
    
    def draw_main_menu(self):
        """Draw the main menu."""
        self.clear()
        self.draw_header()
        
        options = [
            ("1", "Sync Now", "Start a new synchronization"),
            ("2", "Rollback", "Restore previous state"),
            ("3", "Settings", "Configure sync options"),
            ("4", "About", "About FlamQuency-Sync"),
            ("5", "Exit", "Exit the application"),
        ]
        
        table = Table(show_header=False, box=None)
        for key, title, desc in options:
            table.add_row(f"[{key}]", title, desc)
        
        panel = Panel(table, title=" Main Menu ", border_style="blue")
        console.print(panel)
        console.print()
    
    def draw_sync_options(self):
        """Draw sync configuration options."""
        self.clear()
        self.draw_header()
        
        # Exclusion patterns
        exclude = self.sync.config.get("exclude_patterns", [])
        
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("Pattern", style="white")
        table.add_column("Status", style="green")
        
        for pattern in exclude[:10]:  # Show first 10
            table.add_row(pattern, "[x]" if pattern else "[ ]")
        
        # Add add pattern input note
        table.add_row("[ADD PATTERN]", "Add custom exclusion pattern", "")
        table.add_row("[REMOVE PATTERN]", "Remove selected pattern", "")
        
        panel = Panel(table, title=" Exclusion Patterns ", border_style="magenta")
        console.print(panel)
        console.print()
        
        # Action buttons
        table2 = Table(show_header=False, box=None)
        table2.add_row(">", "   Sync Now                 <")
        table2.add_row(">", "   Cancel                   <")
        
        panel2 = Panel(table2, title=" Actions ", border_style="yellow")
        console.print(panel2)
    
    def draw_rollback_menu(self):
        """Draw rollback options."""
        self.clear()
        self.draw_header()
        
        # Get snapshots
        snapshots_dir = self.sync.snapshot_dir
        if snapshots_dir.exists():
            snapshots = sorted(snapshots_dir.iterdir(), key=lambda p: p.name)
            snapshots = [p.name for p in snapshots if p.is_dir() and p.name.startswith("snapshot_")]
        else:
            snapshots = []
        
        # Get file versions info
        version_dir = self.sync.version_dir
        version_info = "No version history"
        if version_dir.exists():
            version_counts = []
            for item in version_dir.rglob('*'):
                if item.is_file() and item.name == ".version.json":
                    try:
                        count = len(json.loads(item.read_text()))
                        version_counts.append(f"{item.parent.relative_to(version_dir)}: {count} versions")
                    except:
                        pass
            version_info = "\n".join(version_counts[:5]) if version_counts else "No version data"
        
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("Type", style="white")
        table.add_column("Details", style="green")
        
        if snapshots:
            table.add_row("System Snapshots:", f"{len(snapshots)} available")
            for s in snapshots[-3:]:  # Show last 3
                date = s.replace("snapshot_", "").replace("_", " ")[:16]
                table.add_row(f"  {date}", "")
        else:
            table.add_row("System Snapshots:", "No snapshots found")
        
        table.add_row("Per-File Versions:", str(version_info)[:50] if version_info else "")
        
        panel = Panel(table, title=" Rollback Options ", border_style="red")
        console.print(panel)
        
        # Action buttons
        table2 = Table(show_header=False, box=None)
        table2.add_row(">", "   Rollback to Snapshot     <")
        table2.add_row(">", "   Rollback Per-File         <")
        table2.add_row(">", "   Cancel                   <")
        
        panel2 = Panel(table2, title=" Actions ", border_style="red")
        console.print(panel2)
    
    def handle_input(self, choice):
        """Handle menu selection."""
        if choice == "1":
            self.do_sync()
        elif choice == "2":
            self.do_rollback()
        elif choice == "3":
            self.do_settings()
        elif choice == "4":
            self.do_about()
        elif choice == "5":
            self.running = False
            console.clear()
            console.print("Goodbye! ✨")
            time.sleep(0.5)
            sys.exit(0)
        else:
            console.print("[red]Invalid choice, please try again.[/red]")
            time.sleep(1)
    
    def do_sync(self):
        """Execute synchronization."""
        console.print("[cyan]Starting sync...[/cyan]")
        result = self.sync.sync()
        
        console.print(f"[green]Sync complete![/green]")
        console.print(f"Files synced: {result.files_synced}")
        console.print(f"Files changed: {result.files_changed}")
        console.print(f"Files excluded: {result.files_excluded}")
        if result.errors:
            console.print(f"Errors: {len(result.errors)}")
            for e in result.errors[:3]:
                console.print(f"  - {e}")
        
        # Wait for user
        console.print("\nPress Enter to return to menu...")
        input()
    
    def do_rollback(self):
        """Show rollback options."""
        self.draw_rollback_menu()
        console.print("\nSelect rollback type:")
        console.print("1. Full system snapshot")
        console.print("2. Per-file version")
        console.print("0. Cancel")
        
        choice = input("> ")
        if choice == "1":
            snapshots_dir = self.sync.snapshot_dir
            if snapshots_dir.exists():
                snapshots = sorted(snapshots_dir.iterdir(), key=lambda p: p.name)
                snapshots = [p.name for p in snapshots if p.is_dir() and p.name.startswith("snapshot_")]
                if snapshots:
                    # Show last 3
                    for i, s in enumerate(snapshots[-3:], 1):
                        date = s.replace("snapshot_", "").replace("_", " ")[:16]
                        console.print(f"{i}. {date}")
                    
                    sel = input("Select snapshot (number): ")
                    try:
                        idx = int(sel) - 1
                        if 0 <= idx < len(snapshots[-3:]):
                            success, msg = self.sync.rollback_to_snapshot(snapshots[-3:][idx])
                            console.print(f"[{'green' if success else 'red'}] {msg} [/]")
                    except:
                        pass
                else:
                    console.print("[red]No snapshots available[/red]")
            else:
                console.print("[red]No snapshots directory[/red]")
            input("\nPress Enter to return...")
        elif choice == "2":
            console.print("Per-file rollback selected")
            file_path = input("Enter file path to rollback: ")
            success, msg = self.sync.rollback_file(file_path)
            console.print(f"[{'green' if success else 'red'}] {msg} [/]")
            input("\nPress Enter to return...")
    
    def do_settings(self):
        """Show settings menu."""
        self.clear()
        self.draw_header()
        console.print("[bold]Settings (placeholder)[/bold]")
        console.print("Configuration handled via ~/.flamquency/config.yaml")
        console.print("\nPress Enter to return...")
        input()
    
    def do_about(self):
        """Show about dialog."""
        self.clear()
        self.draw_header()
        console.print("About FlamQuency-Sync")
        console.print("Version 0.1.0")
        console.print("Terminal-based file synchronization with rollback")
        console.print("\n© 2026 LOSTFlam")
        console.print("\nPress Enter to return...")
        input()
    
    def run(self):
        """Main TUI loop."""
        while self.running:
            self.draw_main_menu()
            
            # Simple input - read one line
            try:
                choice = input("Choose option (1-5): ").strip()
                self.handle_input(choice)
            except (KeyboardInterrupt, EOFError):
                self.running = False
                sys.exit(0)

def run_tui(sync_engine):
    """Run the TUI interface."""
    tui = FlamQuencyTUI(sync_engine)
    tui.run()
