"""Terminal User Interface for FlamQuency-Sync using Textual."""
import sys
import json
from pathlib import Path
from datetime import datetime
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.widgets import (
    Header, Footer, Static, Button, Input, DataTable,
    Label, Select, TabbedContent, TabPane, ProgressBar
)
from textual.binding import Binding
from textual.screen import Screen
from textual import work
from textual.worker import Worker


class StatusBar(Static):
    """Status bar showing sync info."""
    
    def __init__(self, sync_engine):
        super().__init__()
        self.sync = sync_engine
    
    def compose(self):
        status = self.sync.status()
        last = status.get("last_sync", "Never")
        if last and last != "None":
            last = last[:19].replace("T", " ")

        storage_mb = status.get("storage_bytes", 0) / (1024 * 1024)

        enc = status.get("encryption", "disabled")
        enc_icons = {"enabled": "🔒", "locked": "🔐", "disabled": "🔓"}

        yield Static(
            f"  Backend: {status.get('backend', 'local')}  |  "
            f"Tracked: {status.get('tracked_files', 0)} files  |  "
            f"Storage: {storage_mb:.1f} MB  |  "
            f"Enc: {enc_icons.get(enc, '🔓')} {enc}  |  "
            f"Last sync: {last}",
            classes="status-text",
        )
    
    def refresh_status(self):
        """Refresh the status display."""
        self.remove_children()
        for widget in self.compose():
            self.mount(widget)


class SyncScreen(Screen):
    """Sync screen with options and results."""
    
    BINDINGS = [
        Binding("escape", "go_back", "Back"),
    ]
    
    def __init__(self, sync_engine):
        super().__init__()
        self.sync = sync_engine
    
    def compose(self):
        yield Container(
            Static("🔥 Sync", classes="screen-title"),
            Static("Select what to sync and start synchronization.", classes="screen-subtitle"),
            Horizontal(
                Button("Start Sync", variant="primary", id="btn-sync"),
                Button("Back", variant="default", id="btn-back"),
            ),
            Static("", id="sync-result", classes="result-box"),
        )
    
    def on_button_pressed(self, event):
        if event.button.id == "btn-sync":
            self.run_sync()
        elif event.button.id == "btn-back":
            self.app.pop_screen()
    
    @work(thread=True)
    def run_sync(self):
        """Run sync in background thread."""
        self.query_one("#sync-result", Static).update("⏳ Syncing...")
        
        result = self.sync.sync()
        
        output = (
            f"✅ Sync complete!\n\n"
            f"  Files synced:    {result.files_synced}\n"
            f"  Files changed:   {result.files_changed}\n"
            f"  Files excluded:  {result.files_excluded}\n"
            f"  Blobs stored:    {result.blobs_stored}\n"
            f"  Errors:          {len(result.errors)}\n"
        )
        
        if result.errors:
            output += "\n⚠️ Errors:\n"
            for e in result.errors[:5]:
                output += f"  {e}\n"
        
        self.query_one("#sync-result", Static).update(output)
    
    def action_go_back(self):
        self.app.pop_screen()


class RollbackScreen(Screen):
    """Rollback screen - snapshot and file rollback."""
    
    BINDINGS = [
        Binding("escape", "go_back", "Back"),
    ]
    
    def __init__(self, sync_engine):
        super().__init__()
        self.sync = sync_engine
    
    def compose(self):
        yield Container(
            Static("⏪ Rollback", classes="screen-title"),
            Static("Restore from snapshots or file versions.", classes="screen-subtitle"),
        )
        yield ScrollableContainer(id="snapshot-list")
        yield Container(
            Horizontal(
                Button("Refresh", id="btn-refresh"),
                Button("Back", variant="default", id="btn-back"),
            ),
            Static("", id="rollback-result", classes="result-box"),
        )
    
    def on_mount(self):
        self.load_snapshots()
    
    def load_snapshots(self):
        """Load and display available snapshots."""
        container = self.query_one("#snapshot-list", ScrollableContainer)
        container.remove_children()
        
        snapshots = self.sync.list_snapshots()
        
        if not snapshots:
            container.mount(Static("No snapshots available. Run a sync first.", classes="empty-msg"))
            return
        
        for i, snap in enumerate(reversed(snapshots)):
            ts = snap["timestamp"][:19].replace("T", " ")
            btn = Button(
                f"📸 {ts}  ({snap['file_count']} files)",
                id=f"snap-{len(snapshots)-1-i}",
                classes="snapshot-btn",
            )
            container.mount(btn)
    
    def on_button_pressed(self, event):
        btn_id = event.button.id or ""
        
        if btn_id == "btn-back":
            self.app.pop_screen()
        elif btn_id == "btn-refresh":
            self.load_snapshots()
        elif btn_id.startswith("snap-"):
            idx = int(btn_id.replace("snap-", ""))
            snapshots = self.sync.list_snapshots()
            if 0 <= idx < len(snapshots):
                self.rollback_snapshot(snapshots[idx])
    
    @work(thread=True)
    def rollback_snapshot(self, snapshot):
        """Rollback to snapshot in background."""
        self.query_one("#rollback-result", Static).update(f"⏳ Rolling back to {snapshot['name']}...")
        
        success, msg = self.sync.rollback_to_snapshot(snapshot["name"])
        
        icon = "✅" if success else "❌"
        self.query_one("#rollback-result", Static).update(f"{icon} {msg}")
    
    def action_go_back(self):
        self.app.pop_screen()


class FileVersionsScreen(Screen):
    """File version history and per-file rollback."""
    
    BINDINGS = [
        Binding("escape", "go_back", "Back"),
    ]
    
    def __init__(self, sync_engine):
        super().__init__()
        self.sync = sync_engine
    
    def compose(self):
        yield Container(
            Static("📁 File Versions", classes="screen-title"),
            Static("View and restore individual file versions.", classes="screen-subtitle"),
            Input(placeholder="Enter file path (e.g. ~/.config/hypr/hyprland.conf)", id="file-input"),
            Button("Load Versions", variant="primary", id="btn-load"),
            Static("", id="versions-result", classes="result-box"),
        )
        yield Container(
            Horizontal(
                Button("Back", variant="default", id="btn-back"),
            ),
        )
    
    def on_mount(self):
        self.load_versions()
    
    def load_versions(self):
        """Load version history for entered file."""
        file_input = self.query_one("#file-input", Input)
        filepath = file_input.value.strip()
        
        if not filepath:
            self.query_one("#versions-result", Static).update("⚠️ Enter a file path first")
            return
        
        # Expand path
        if filepath.startswith("~"):
            filepath = str(Path(filepath).expanduser())
        
        success, info = self.sync.rollback_file(filepath)
        
        result_widget = self.query_one("#versions-result", Static)
        
        if not success:
            result_widget.update(f"❌ {info}")
            return
        
        if isinstance(info, dict):
            output = f"📄 {info['rel_path']}\n"
            output += f"   {info['version_count']} version(s)\n\n"
            
            table = DataTable()
            table.add_columns("#", "Hash", "Timestamp", "Size")
            for v in info["versions"]:
                table.add_row(
                    str(v["index"]),
                    v["hash"],
                    v["timestamp"][:19].replace("T", " "),
                    str(v["size"]),
                )
            
            result_widget.update(output)
            
            # Show table
            container = self.query_one("#versions-table-container", Container) if self.query("#versions-table-container") else None
            if container:
                container.remove_children()
                container.mount(table)
            else:
                new_container = Container(table, id="versions-table-container")
                self.mount(new_container)
            
            # Add rollback buttons
            restore_container = self.query_one("#restore-container") if self.query("#restore-container") else None
            if not restore_container:
                restore_container = Container(id="restore-container")
                self.mount(restore_container)
            restore_container.remove_children()
            
            for v in info["versions"]:
                btn = Button(
                    f"⏪ Restore v{v['index']} ({v['timestamp'][:10]})",
                    id=f"restore-{v['index']}",
                    classes="restore-btn",
                )
                restore_container.mount(btn)
    
    def on_button_pressed(self, event):
        btn_id = event.button.id or ""
        if btn_id.startswith("restore-"):
            idx = int(btn_id.replace("restore-", ""))
            file_input = self.query_one("#file-input", Input)
            filepath = file_input.value.strip()
            if filepath.startswith("~"):
                filepath = str(Path(filepath).expanduser())
            
            success, msg = self.sync.rollback_file(filepath, version_index=idx)
            icon = "✅" if success else "❌"
            self.query_one("#versions-result", Static).update(f"{icon} {msg}")
    
    def action_go_back(self):
        self.app.pop_screen()


class SettingsScreen(Screen):
    """Settings and configuration screen."""
    
    BINDINGS = [
        Binding("escape", "go_back", "Back"),
    ]
    
    def __init__(self, sync_engine):
        super().__init__()
        self.sync = sync_engine
    
    def compose(self):
        config = self.sync.config
        
        yield Container(
            Static("⚙️ Settings", classes="screen-title"),
            ScrollableContainer(
                Static("[bold]Cloud Backend[/bold]"),
                Static(f"Current: {config.get('cloud_backend', 'local')}"),
                Static(""),
                Static("[bold]Exclusion Patterns[/bold]"),
                *[Static(f"  • {p}") for p in config.get("exclude_patterns", [])[:15]],
                Static(""),
                Static("[bold]Auto Sync[/bold]"),
                Static(f"Enabled: {config.get('auto_sync', False)}"),
                Static(f"Interval: {config.get('sync_interval_hours', 24)}h"),
                Static(""),
                Static("[bold].flamquencyignore[/bold]"),
                Static(f"File: {self.sync.ignore_rules.path or '~/.flamquencyignore (not created yet)'}"),
                Static(f"Rules: {len(self.sync.ignore_rules)}"),
                Static("[dim]Manage with: flamquency ignore --init|--list|--add|--check[/dim]"),
                Static(""),
                Static("[bold]Encryption[/bold]"),
                Static(f"Enabled: {(config.get('encryption') or {}).get('enabled', False)}"),
                Static("[dim]Manage with: flamquency encryption status|enable|disable[/dim]"),
                Static(""),
                Static("[dim]Edit ~/.flamquency/config.yaml for advanced settings[/dim]"),
            ),
            Horizontal(
                Button("Back", variant="default", id="btn-back"),
            ),
        )
    
    def on_button_pressed(self, event):
        if event.button.id == "btn-back":
            self.app.pop_screen()
    
    def action_go_back(self):
        self.app.pop_screen()


class MainScreen(Screen):
    """Main menu screen."""
    
    def __init__(self, sync_engine):
        super().__init__()
        self.sync = sync_engine
    
    def compose(self):
        yield Header()
        yield StatusBar(self.sync)
        yield Container(
            Static("🔥 FlamQuency-Sync", classes="app-title"),
            Static("File synchronization with version control", classes="app-subtitle"),
            Static(""),
            Button("🔄  Sync Now", variant="primary", id="btn-sync", classes="menu-btn"),
            Button("⏪  Rollback", variant="default", id="btn-rollback", classes="menu-btn"),
            Button("📁  File Versions", variant="default", id="btn-versions", classes="menu-btn"),
            Button("⚙️  Settings", variant="default", id="btn-settings", classes="menu-btn"),
            Button("❌  Exit", variant="error", id="btn-exit", classes="menu-btn"),
        )
        yield Footer()
    
    def on_button_pressed(self, event):
        btn_id = event.button.id or ""
        
        if btn_id == "btn-sync":
            self.app.push_screen(SyncScreen(self.sync))
        elif btn_id == "btn-rollback":
            self.app.push_screen(RollbackScreen(self.sync))
        elif btn_id == "btn-versions":
            self.app.push_screen(FileVersionsScreen(self.sync))
        elif btn_id == "btn-settings":
            self.app.push_screen(SettingsScreen(self.sync))
        elif btn_id == "btn-exit":
            self.app.exit()


class FlamQuencyApp(App):
    """FlamQuency-Sync Textual application."""
    
    TITLE = "FlamQuency-Sync"
    SUB_TITLE = "File Sync with Version Control"
    
    CSS = """
    Screen {
        background: $surface;
    }
    
    .app-title {
        text-align: center;
        text-style: bold;
        color: $accent;
        width: 100%;
        padding: 1;
    }
    
    .app-subtitle {
        text-align: center;
        color: $text-muted;
        width: 100%;
        padding-bottom: 1;
    }
    
    .screen-title {
        text-style: bold;
        color: $accent;
        padding: 1;
        width: 100%;
    }
    
    .screen-subtitle {
        color: $text-muted;
        padding: 0 1 1 1;
        width: 100%;
    }
    
    .menu-btn {
        width: 100%;
        margin: 0 2 1 2;
    }
    
    .status-text {
        background: $panel;
        color: $text;
        padding: 0 1;
        width: 100%;
        dock: top;
    }
    
    .result-box {
        margin: 1 2;
        padding: 1;
        background: $panel;
        border: solid $primary;
        min-height: 5;
    }
    
    .snapshot-btn {
        width: 100%;
        margin: 0 1;
    }
    
    .restore-btn {
        width: 100%;
        margin: 0 1;
    }
    
    .empty-msg {
        color: $text-muted;
        padding: 2;
        text-align: center;
        width: 100%;
    }
    
    Input {
        margin: 0 2;
    }
    
    DataTable {
        margin: 1 2;
        max-height: 15;
    }
    """
    
    def __init__(self, sync_engine):
        super().__init__()
        self.sync = sync_engine
    
    def on_mount(self):
        self.push_screen(MainScreen(self.sync))


def run_textual_tui(sync_engine):
    """Run the Textual TUI."""
    app = FlamQuencyApp(sync_engine)
    app.run()
