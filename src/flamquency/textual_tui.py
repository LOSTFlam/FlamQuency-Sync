"""Terminal User Interface for FlamQuency-Sync using Textual.

Visual language: «Угольки» design system — see docs/DESIGN.md.
All colors/spacing come from the flamquency-fire theme (theme.py).
"""
import sys
import json
from pathlib import Path
from datetime import datetime
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.widgets import (
    Header, Footer, Static, Button, Input, DataTable, Label, ProgressBar
)
from textual.binding import Binding
from textual.screen import Screen
from textual import work

from flamquency.theme import FLAMQUENCY_FIRE


# ── Переиспользуемые компоненты (DESIGN.md §4) ──────────────────────

class ResultPanel(Static):
    """Панель результата: фон surface-raised, рамка accent (§4.5)."""
    pass


class ScreenTitle(Static):
    """Заголовок экрана: bold, accent, с иконкой темы (§2)."""
    pass


class ScreenSubtitle(Static):
    """Подзаголовок: muted (§2)."""
    pass


# ── Статус-бар (дашборд, §4.2) ──────────────────────────────────────

class StatusBar(Static):
    """Прибитая к верху полоса с ключевыми метриками."""
    
    def __init__(self, sync_engine):
        super().__init__(classes="status-bar")
        self.sync = sync_engine
    
    def compose(self):
        status = self.sync.status()
        last = status.get("last_sync")
        if last and last != "None":
            last = last[:19].replace("T", " ")
        else:
            last = "никогда"
        
        storage_mb = status.get("storage_bytes", 0) / (1024 * 1024)
        
        enc = status.get("encryption", "disabled")
        enc_icons = {"enabled": "🔒", "locked": "🔐", "disabled": "🔓"}
        enc_colors = {"enabled": "success", "locked": "warning", "disabled": "warning"}
        
        profile = status.get("active_profile", "default")
        
        yield Static(
            f" [bold]Бэкенд:[/] {status.get('backend', 'local')}  "
            f"[bold]Файлов:[/] {status.get('tracked_files', 0)}  "
            f"[bold]Хранилище:[/] {storage_mb:.2f} MB  "
            f"[{enc_colors.get(enc, 'warning')}]{enc_icons.get(enc, '🔓')}[/]  "
            f"[bold]Профиль:[/] {profile}  "
            f"[bold]Синк:[/] {last}",
            classes="status-text",
        )
    
    def refresh_status(self):
        self.remove_children()
        for widget in self.compose():
            self.mount(widget)


# ── Боковая навигация (§4.1) ────────────────────────────────────────

class NavRail(Vertical):
    """Вертикальный rail с навигацией."""
    
    def compose(self):
        yield Static("🔥", classes="nav-logo")
        yield Static("FlamQuency", classes="nav-title")
        yield Static("", classes="spacer")
        yield Button("🔄  Синк", variant="primary", id="nav-sync", classes="nav-btn")
        yield Button("⏪  Откат", id="nav-rollback", classes="nav-btn")
        yield Button("📁  Версии", id="nav-versions", classes="nav-btn")
        yield Button("🔐  Шифр", id="nav-encryption", classes="nav-btn")
        yield Button("⚙️  Настройки", id="nav-settings", classes="nav-btn")
        yield Static("", classes="spacer")
        yield Button("❌  Выход", variant="error", id="nav-exit", classes="nav-btn-exit")


# ── Базовый экран: rail + контент ───────────────────────────────────

class BaseScreen(Screen):
    """Все экраны: статус-бар сверху, rail слева, контент справа (§5.1)."""
    
    BINDINGS = [Binding("escape", "go_dashboard", "Дашборд")]
    
    def __init__(self, sync_engine):
        super().__init__()
        self.sync = sync_engine
    
    def compose(self):
        yield StatusBar(self.sync)
        yield Horizontal(
            NavRail(),
            ScrollableContainer(*self.compose_content()),
        )
    
    def compose_content(self):
        """Переопределяется наследниками — контент правой панели."""
        return []
    
    def action_go_dashboard(self):
        self.app.push_screen(DashboardScreen(self.sync))


# ── Дашборд (§5.1) ──────────────────────────────────────────────────

class DashboardScreen(BaseScreen):
    """Главный экран."""
    
    def compose_content(self):
        return [
            Static("🔥 FlamQuency-Sync", classes="app-title"),
            Static("Синхронизация файлов с контролем версий", classes="app-subtitle"),
            Static("", classes="spacer"),
            Static("Выбери действие в панели слева →", classes="app-hint"),
        ]


# ── Экран синка (§5.2) ──────────────────────────────────────────────

class SyncScreen(BaseScreen):
    """Синк: выбор источника, прогресс, результат."""
    
    def compose_content(self):
        return [
            ScreenTitle("🔥 Синхронизация", classes="screen-title"),
            ScreenSubtitle("Запусти синхронизацию файлов и конфигов.", classes="screen-subtitle"),
            Static("", classes="spacer"),
            Static("Источник:", classes="field-label"),
            Input(placeholder="~/.flamquency (по умолчанию)", id="source-input"),
            Static("", classes="spacer"),
            Button("▶  Синхронизировать", variant="primary", id="btn-sync"),
            Static("", classes="spacer"),
            ProgressBar(total=100, show_eta=False, id="sync-progress"),
            ResultPanel("", id="sync-result", classes="result-box"),
        ]
    
    def on_button_pressed(self, event):
        if event.button.id == "btn-sync":
            self.run_sync()
    
    @work(thread=True)
    def run_sync(self):
        result_widget = self.query_one("#sync-result", ResultPanel)
        progress = self.query_one("#sync-progress", ProgressBar)
        
        result_widget.update("⏳ Синхронизация...")
        self.app.call_from_thread(progress.update, progress=10)
        
        source_input = self.query_one("#source-input", Input)
        source_val = source_input.value.strip()
        source = Path(source_val).expanduser() if source_val else None
        
        result = self.sync.sync(source=source)
        
        self.app.call_from_thread(progress.update, progress=100)
        
        output = (
            f"[bold success]✅ Синхронизация завершена![/]\n\n"
            f"  Файлов синхронизировано:  [bold]{result.files_synced}[/]\n"
            f"  Изменено:                 [bold]{result.files_changed}[/]\n"
            f"  Исключено:                {result.files_excluded}\n"
            f"  Блобов сохранено:         [bold]{result.blobs_stored}[/]\n"
            f"  Ошибок:                   {len(result.errors)}\n"
        )
        
        if result.errors:
            output += "\n[warning]⚠️ Ошибки:[/]\n"
            for e in result.errors[:5]:
                output += f"  [error]{e}[/]\n"
        
        result_widget.update(output)
        
        # Обновить статус-бар
        try:
            status_bar = self.app.query_one(StatusBar)
            self.app.call_from_thread(status_bar.refresh_status)
        except Exception:
            pass


# ── Экран откатa (§5.3) ─────────────────────────────────────────────

class RollbackScreen(BaseScreen):
    """Откат: таблица снапшотов."""
    
    def __init__(self, sync_engine):
        super().__init__(sync_engine)
    
    def compose_content(self):
        return [
            ScreenTitle("⏪ Откат", classes="screen-title"),
            ScreenSubtitle("Восстанови систему до снапшота.", classes="screen-subtitle"),
            Static("", classes="spacer"),
            DataTable(id="snapshots-table", cursor_type="row"),
            Static("", classes="spacer"),
            Horizontal(
                Button("↻  Обновить", id="btn-refresh"),
                Button("⏪  Откатить", variant="primary", id="btn-rollback"),
            ),
            ResultPanel("", id="rollback-result", classes="result-box"),
        ]
    
    def on_mount(self):
        table = self.query_one("#snapshots-table", DataTable)
        table.add_columns("Время", "Файлов")
        self.load_snapshots()
    
    def load_snapshots(self):
        table = self.query_one("#snapshots-table", DataTable)
        table.clear()
        
        snapshots = self.sync.list_snapshots()
        
        if not snapshots:
            table.add_row("— нет снапшотов —", "")
            return
        
        for snap in reversed(snapshots):
            ts = snap["timestamp"][:19].replace("T", " ")
            table.add_row(ts, str(snap["file_count"]), key=snap["name"])
    
    def on_button_pressed(self, event):
        if event.button.id == "btn-refresh":
            self.load_snapshots()
        elif event.button.id == "btn-rollback":
            self.rollback_selected()
    
    def rollback_selected(self):
        table = self.query_one("#snapshots-table", DataTable)
        result_widget = self.query_one("#rollback-result", ResultPanel)
        
        if table.row_count == 0:
            result_widget.update("[warning]⚠️ Нет снапшотов для откатa[/]")
            return
        
        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        snap_name = str(row_key.value)
        
        result_widget.update(f"⏳ Откат к {snap_name}...")
        self._do_rollback(snap_name)
    
    @work(thread=True)
    def _do_rollback(self, snap_name):
        success, msg = self.sync.rollback_to_snapshot(snap_name)
        result_widget = self.query_one("#rollback-result", ResultPanel)
        
        if success:
            result_widget.update(f"[bold success]✅ {msg}[/]")
        else:
            result_widget.update(f"[bold error]❌ {msg}[/]")
        
        self.app.call_from_thread(self.load_snapshots)


# ── Экран версий файла (§5.4) ───────────────────────────────────────

class FileVersionsScreen(BaseScreen):
    """Версии файла: история и пофайловый откат."""
    
    def compose_content(self):
        return [
            ScreenTitle("📁 Версии файлов", classes="screen-title"),
            ScreenSubtitle("Посмотри историю файла и откати к любой версии.", classes="screen-subtitle"),
            Static("", classes="spacer"),
            Static("Путь к файлу:", classes="field-label"),
            Input(placeholder="~/.config/hypr/hyprland.conf", id="file-input"),
            Static("", classes="spacer"),
            Button("🔍  Загрузить версии", variant="primary", id="btn-load"),
            Static("", classes="spacer"),
            DataTable(id="versions-table", cursor_type="row"),
            Static("", classes="spacer"),
            Button("⏪  Откатить выбранную", variant="primary", id="btn-restore"),
            ResultPanel("", id="versions-result", classes="result-box"),
        ]
    
    def on_mount(self):
        table = self.query_one("#versions-table", DataTable)
        table.add_columns("#", "Хеш", "Время", "Размер")
    
    def on_button_pressed(self, event):
        if event.button.id == "btn-load":
            self.load_versions()
        elif event.button.id == "btn-restore":
            self.restore_selected()
    
    def _get_filepath(self):
        file_input = self.query_one("#file-input", Input)
        filepath = file_input.value.strip()
        if not filepath:
            return None
        return str(Path(filepath).expanduser())
    
    def load_versions(self):
        filepath = self._get_filepath()
        result_widget = self.query_one("#versions-result", ResultPanel)
        table = self.query_one("#versions-table", DataTable)
        table.clear()
        
        if not filepath:
            result_widget.update("[warning]⚠️ Сначала введи путь к файлу[/]")
            return
        
        success, info = self.sync.rollback_file(filepath)
        
        if not success:
            result_widget.update(f"[error]❌ {info}[/]")
            return
        
        if isinstance(info, dict):
            result_widget.update(
                f"📄 [bold]{info['rel_path']}[/] — "
                f"{info['version_count']} версия(й)"
            )
            for v in info["versions"]:
                table.add_row(
                    str(v["index"]),
                    v["hash"],
                    v["timestamp"][:19].replace("T", " "),
                    str(v["size"]),
                )
    
    def restore_selected(self):
        filepath = self._get_filepath()
        result_widget = self.query_one("#versions-result", ResultPanel)
        table = self.query_one("#versions-table", DataTable)
        
        if not filepath:
            result_widget.update("[warning]⚠️ Сначала введи путь к файлу[/]")
            return
        
        if table.row_count == 0:
            result_widget.update("[warning]⚠️ Сначала загрузи версии[/]")
            return
        
        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        try:
            idx = int(str(row_key.value))
        except (ValueError, TypeError):
            result_widget.update("[error]❌ Не удалось определить версию[/]")
            return
        
        success, msg = self.sync.rollback_file(filepath, version_index=idx)
        
        if success:
            result_widget.update(f"[bold success]✅ {msg}[/]")
            self.load_versions()
        else:
            result_widget.update(f"[bold error]❌ {msg}[/]")


# ── Экран шифрования (§5.5) ─────────────────────────────────────────

class EncryptionScreen(BaseScreen):
    """Шифрование: статус, управление."""
    
    def compose_content(self):
        return [
            ScreenTitle("🔐 Шифрование", classes="screen-title"),
            ScreenSubtitle("Fernet/AES шифрование блобов с паролем.", classes="screen-subtitle"),
            Static("", classes="spacer"),
            Static("Статус:", classes="field-label"),
            Static("", id="enc-status"),
            Static("", classes="spacer"),
            Static("Пароль:", classes="field-label"),
            Input(placeholder="Введи пароль для шифрования", password=True, id="enc-password"),
            Static("", classes="spacer"),
            Horizontal(
                Button("🔒  Включить", variant="primary", id="btn-enc-on"),
                Button("🔓  Выключить", variant="default", id="btn-enc-off"),
            ),
            ResultPanel("", id="enc-result", classes="result-box"),
        ]
    
    def on_mount(self):
        self.update_status()
    
    def update_status(self):
        status = self.sync.status()
        enc = status.get("encryption", "disabled")
        widget = self.query_one("#enc-status", Static)
        
        if enc == "enabled":
            widget.update("[bold success]🔒 Шифрование включено[/]")
        elif enc == "locked":
            widget.update("[bold warning]🔐 Заблокировано — нужен пароль[/]")
        else:
            widget.update("[dim]🔓 Шифрование выключено[/]")
    
    def on_button_pressed(self, event):
        if event.button.id == "btn-enc-on":
            self.enable_encryption()
        elif event.button.id == "btn-enc-off":
            self.disable_encryption()
    
    def enable_encryption(self):
        password = self.query_one("#enc-password", Input).value
        result_widget = self.query_one("#enc-result", ResultPanel)
        
        if not password:
            result_widget.update("[warning]⚠️ Введи пароль[/]")
            return
        
        success, msg = self.sync.enable_encryption(password)
        if success:
            result_widget.update(f"[bold success]✅ {msg}[/]")
        else:
            result_widget.update(f"[bold error]❌ {msg}[/]")
        self.update_status()
    
    def disable_encryption(self):
        result_widget = self.query_one("#enc-result", ResultPanel)
        success, msg = self.sync.disable_encryption()
        if success:
            result_widget.update(f"[bold success]✅ {msg}[/]")
        else:
            result_widget.update(f"[bold error]❌ {msg}[/]")
        self.update_status()


# ── Экран настроек (§5.6) ───────────────────────────────────────────

class SettingsScreen(BaseScreen):
    """Настройки: только чтение + ссылки на CLI."""
    
    def compose_content(self):
        config = self.sync.config
        
        return [
            ScreenTitle("⚙️ Настройки", classes="screen-title"),
            ScreenSubtitle("Конфигурация FlamQuency-Sync.", classes="screen-subtitle"),
            Static("", classes="spacer"),
            Static("[bold]Облачный бэкенд[/]", classes="settings-section"),
            Static(f"  Текущий: {config.get('cloud_backend', 'local')}", classes="settings-value"),
            Static(""),
            Static("[bold]Исключения[/]", classes="settings-section"),
            *[Static(f"  • {p}", classes="settings-value") for p in config.get("exclude_patterns", [])[:15]],
            Static(""),
            Static("[bold]Автосинк[/]", classes="settings-section"),
            Static(f"  Включён: {config.get('auto_sync', False)}", classes="settings-value"),
            Static(f"  Интервал: {config.get('sync_interval_hours', 24)}ч", classes="settings-value"),
            Static(""),
            Static("[bold].flamquencyignore[/]", classes="settings-section"),
            Static(f"  Файл: {self.sync.ignore_rules.path or '~/.flamquencyignore (не создан)'}", classes="settings-value"),
            Static(f"  Правил: {len(self.sync.ignore_rules)}", classes="settings-value"),
            Static("[dim]  Управление: flamquency ignore --init|--list|--add|--check[/]"),
            Static(""),
            Static("[bold]Шифрование[/]", classes="settings-section"),
            Static(f"  Включено: {(config.get('encryption') or {}).get('enabled', False)}", classes="settings-value"),
            Static("[dim]  Управление: flamquency encryption status|enable|disable[/]"),
            Static(""),
            Static("[dim]Редактируй ~/.flamquency/config.yaml для продвинутых настроек[/]"),
        ]


# ── Приложение ──────────────────────────────────────────────────────

class FlamQuencyApp(App):
    """FlamQuency-Sync Textual application — тема «Угольки»."""
    
    TITLE = "FlamQuency-Sync"
    SUB_TITLE = "File Sync with Version Control"
    
    CSS = """
    /* Базовые поверхности (§3) */
    Screen {
        background: $surface;
    }
    
    /* Статус-бар (§4.2) */
    .status-bar {
        dock: top;
        width: 100%;
        background: $surface-sunken;
        height: 1;
    }
    
    .status-text {
        padding: 0 1;
        width: 100%;
    }
    
    /* Заголовки экранов (§2) */
    .screen-title {
        text-style: bold;
        color: $accent;
        padding: 1 2 0 2;
        width: 100%;
    }
    
    .screen-subtitle {
        color: $text-muted;
        padding: 0 2;
        width: 100%;
    }
    
    /* Главный экран (§5.1) */
    .app-title {
        text-align: center;
        text-style: bold;
        color: $accent;
        width: 100%;
        padding: 2 0 0 0;
    }
    
    .app-subtitle {
        text-align: center;
        color: $text-muted;
        width: 100%;
        padding-bottom: 1;
    }
    
    .app-hint {
        text-align: center;
        color: $text-faint;
        width: 100%;
    }
    
    /* Боковая навигация (§4.1) */
    NavRail {
        width: 22;
        background: $surface-raised;
        border-right: solid $accent-deep;
        padding: 1;
    }
    
    .nav-logo {
        text-align: center;
        width: 100%;
    }
    
    .nav-title {
        text-align: center;
        text-style: bold;
        color: $accent;
        width: 100%;
        padding-bottom: 1;
    }
    
    .nav-btn {
        width: 100%;
        margin: 0 0 1 0;
        background: $surface-raised;
        color: $text;
    }
    
    .nav-btn:hover {
        background: $surface-overlay;
    }
    
    .nav-btn-exit {
        width: 100%;
        margin: 0;
    }
    
    /* Панель результата (§4.5) */
    .result-box {
        margin: 1 2;
        padding: 1;
        background: $surface-raised;
        border: solid $accent;
        min-height: 5;
    }
    
    /* Поля ввода */
    Input {
        margin: 0 2;
        background: $surface-sunken;
        border: solid $accent-deep;
    }
    
    Input:focus {
        border: solid $accent;
    }
    
    /* Подписи полей */
    .field-label {
        padding: 0 2;
        color: $text-muted;
    }
    
    /* Таблицы (§4.4) */
    DataTable {
        margin: 1 2;
        background: $surface-raised;
        max-height: 20;
    }
    
    DataTable > .datatable--header {
        background: $surface-overlay;
        color: $text-muted;
        text-style: bold;
    }
    
    DataTable > .datatable--cursor {
        background: $accent-deep;
    }
    
    /* Кнопки (§4.3) */
    Button {
        margin: 0 1;
    }
    
    .spacer {
        height: 1;
    }
    
    /* Настройки */
    .settings-section {
        color: $accent;
        text-style: bold;
        padding: 0 2;
    }
    
    .settings-value {
        color: $text;
        padding: 0 2;
    }
    
    /* Прогресс */
    ProgressBar {
        margin: 0 2;
    }
    """
    
    BINDINGS = [
        Binding("ctrl+q", "quit", "Выход"),
    ]
    
    def __init__(self, sync_engine):
        super().__init__()
        self.sync = sync_engine
        # Тема регистрируется ДО парсинга CSS (иначе $surface-sunken не разрешится)
        self.register_theme(FLAMQUENCY_FIRE)
        self.theme = "flamquency-fire"
    
    def on_mount(self):
        self.push_screen(DashboardScreen(self.sync))
    
    def on_button_pressed(self, event):
        btn_id = event.button.id or ""
        
        if btn_id == "nav-sync":
            self._switch_screen(SyncScreen(self.sync))
        elif btn_id == "nav-rollback":
            self._switch_screen(RollbackScreen(self.sync))
        elif btn_id == "nav-versions":
            self._switch_screen(FileVersionsScreen(self.sync))
        elif btn_id == "nav-encryption":
            self._switch_screen(EncryptionScreen(self.sync))
        elif btn_id == "nav-settings":
            self._switch_screen(SettingsScreen(self.sync))
        elif btn_id == "nav-exit":
            self.exit()
    
    def _switch_screen(self, screen):
        """Заменить текущий экран (swap — не стек)."""
        if isinstance(self.screen, DashboardScreen):
            self.push_screen(screen)
        else:
            self.pop_screen()
            self.push_screen(screen)


def run_textual_tui(sync_engine):
    """Run the Textual TUI."""
    app = FlamQuencyApp(sync_engine)
    app.run()
