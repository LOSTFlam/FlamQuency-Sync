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
from flamquency.icons import icon
from flamquency.style import human_size, human_time


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
            last = human_time(last)
        else:
            last = "никогда"

        storage = human_size(status.get("storage_bytes", 0))

        enc = status.get("encryption", "disabled")
        enc_glyph = {"enabled": icon("lock"), "locked": icon("key"),
                     "disabled": icon("warning")}[enc]
        enc_colors = {"enabled": "success", "locked": "warning",
                      "disabled": "warning"}

        profile = status.get("active_profile", "default")

        yield Static(
            f" {icon('cloud')} [bold]Бэкенд:[/] {status.get('backend', 'local')}  "
            f"{icon('folder')} [bold]Файлов:[/] {status.get('tracked_files', 0)}  "
            f"{icon('chart')} [bold]Хранилище:[/] {storage}  "
            f"[{enc_colors.get(enc, 'warning')}]{enc_glyph}[/]  "
            f"{icon('profiles')} [bold]Профиль:[/] {profile}  "
            f"{icon('clock')} [bold]Синк:[/] {last}",
            classes="status-text",
        )
    
    def refresh_status(self):
        self.remove_children()
        for widget in self.compose():
            self.mount(widget)


# ── Боковая навигация (§4.1) ────────────────────────────────────────

class NavRail(Vertical):
    """Вертикальный rail с навигацией (иконки — Nerd Font, DESIGN.md §2)."""

    def compose(self):
        yield Static(icon("fire"), classes="nav-logo")
        yield Static("FlamQuency", classes="nav-title")
        yield Static("", classes="spacer")
        yield Button(f"{icon('sync')}  Синк", variant="primary",
                     id="nav-sync", classes="nav-btn")
        yield Button(f"{icon('rollback')}  Откат", id="nav-rollback",
                     classes="nav-btn")
        yield Button(f"{icon('versions')}  Версии", id="nav-versions",
                     classes="nav-btn")
        yield Button(f"{icon('shield')}  Проверка", id="nav-check",
                     classes="nav-btn")
        yield Button(f"{icon('update')}  Обновление", id="nav-update",
                     classes="nav-btn")
        yield Button(f"{icon('lock')}  Шифр", id="nav-encryption",
                     classes="nav-btn")
        yield Button(f"{icon('settings')}  Настройки", id="nav-settings",
                     classes="nav-btn")
        yield Static("", classes="spacer")
        yield Button(f"{icon('error')}  Выход", variant="error",
                     id="nav-exit", classes="nav-btn-exit")


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
            Static(f"{icon('fire')} FlamQuency-Sync", classes="app-title"),
            Static("Синхронизация файлов с контролем версий", classes="app-subtitle"),
            Static("", classes="spacer"),
            Static("Выбери действие в панели слева →", classes="app-hint"),
        ]


# ── Экран синка (§5.2) ──────────────────────────────────────────────

class SyncScreen(BaseScreen):
    """Синк: выбор источника, прогресс, результат."""
    
    def compose_content(self):
        return [
            ScreenTitle(f"{icon('sync')} Синхронизация", classes="screen-title"),
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
            f"[bold success]{icon('success')} Синхронизация завершена![/]\n\n"
            f"  Файлов синхронизировано:  [bold]{result.files_synced}[/]\n"
            f"  Изменено:                 [bold]{result.files_changed}[/]\n"
            f"  Исключено:                {result.files_excluded}\n"
            f"  Блобов сохранено:         [bold]{result.blobs_stored}[/]\n"
            f"  Ошибок:                   {len(result.errors)}\n"
        )
        
        if result.errors:
            output += f"\n[warning]{icon('warning')} Ошибки:[/]\n"
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
            ScreenTitle(f"{icon('rollback')} Откат", classes="screen-title"),
            ScreenSubtitle("Восстанови систему до снапшота.", classes="screen-subtitle"),
            Static("", classes="spacer"),
            DataTable(id="snapshots-table", cursor_type="row"),
            Static("", classes="spacer"),
            Horizontal(
                Button("↻  Обновить", id="btn-refresh"),
                Button(f"{icon('rollback')}  Откатить", variant="primary", id="btn-rollback"),
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
            result_widget.update(f"[warning]{icon('warning')} Нет снапшотов для откатa[/]")
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
            result_widget.update(f"[bold success]{icon('success')} {msg}[/]")
        else:
            result_widget.update(f"[bold error]{icon('error')} {msg}[/]")
        
        self.app.call_from_thread(self.load_snapshots)


# ── Экран версий файла (§5.4) ───────────────────────────────────────

class FileVersionsScreen(BaseScreen):
    """Версии файла: история и пофайловый откат."""
    
    def compose_content(self):
        return [
            ScreenTitle(f"{icon('versions')} Версии файлов", classes="screen-title"),
            ScreenSubtitle("Посмотри историю файла и откати к любой версии.", classes="screen-subtitle"),
            Static("", classes="spacer"),
            Static("Путь к файлу:", classes="field-label"),
            Input(placeholder="~/.config/hypr/hyprland.conf", id="file-input"),
            Static("", classes="spacer"),
            Button("🔍  Загрузить версии", variant="primary", id="btn-load"),
            Static("", classes="spacer"),
            DataTable(id="versions-table", cursor_type="row"),
            Static("", classes="spacer"),
            Button(f"{icon('rollback')}  Откатить выбранную", variant="primary", id="btn-restore"),
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
            result_widget.update(f"[warning]{icon('warning')} Сначала введи путь к файлу[/]")
            return
        
        success, info = self.sync.rollback_file(filepath)
        
        if not success:
            result_widget.update(f"[error]{icon('error')} {info}[/]")
            return
        
        if isinstance(info, dict):
            result_widget.update(
                f"{icon('versions')} [bold]{info['rel_path']}[/] — "
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
            result_widget.update(f"[warning]{icon('warning')} Сначала введи путь к файлу[/]")
            return
        
        if table.row_count == 0:
            result_widget.update(f"[warning]{icon('warning')} Сначала загрузи версии[/]")
            return
        
        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        try:
            idx = int(str(row_key.value))
        except (ValueError, TypeError):
            result_widget.update(f"[error]{icon('error')} Не удалось определить версию[/]")
            return
        
        success, msg = self.sync.rollback_file(filepath, version_index=idx)
        
        if success:
            result_widget.update(f"[bold success]{icon('success')} {msg}[/]")
            self.load_versions()
        else:
            result_widget.update(f"[bold error]{icon('error')} {msg}[/]")


# ── Экран шифрования (§5.5) ─────────────────────────────────────────

class EncryptionScreen(BaseScreen):
    """Шифрование: статус, управление."""
    
    def compose_content(self):
        return [
            ScreenTitle(f"{icon('lock')} Шифрование", classes="screen-title"),
            ScreenSubtitle("Fernet/AES шифрование блобов с паролем.", classes="screen-subtitle"),
            Static("", classes="spacer"),
            Static("Статус:", classes="field-label"),
            Static("", id="enc-status"),
            Static("", classes="spacer"),
            Static("Пароль:", classes="field-label"),
            Input(placeholder="Введи пароль для шифрования", password=True, id="enc-password"),
            Static("", classes="spacer"),
            Horizontal(
                Button(f"{icon('lock')}  Включить", variant="primary", id="btn-enc-on"),
                Button(f"{icon('key')}  Выключить", variant="default", id="btn-enc-of"),
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
            widget.update(f"[bold success]{icon('lock')} Шифрование включено[/]")
        elif enc == "locked":
            widget.update(f"[bold warning]{icon('key')} Заблокировано — нужен пароль[/]")
        else:
            widget.update(f"[dim]{icon('key')} Шифрование выключено[/]")
    
    def on_button_pressed(self, event):
        if event.button.id == "btn-enc-on":
            self.enable_encryption()
        elif event.button.id == "btn-enc-of":
            self.disable_encryption()
    
    def enable_encryption(self):
        password = self.query_one("#enc-password", Input).value
        result_widget = self.query_one("#enc-result", ResultPanel)
        
        if not password:
            result_widget.update(f"[warning]{icon('warning')} Введи пароль[/]")
            return
        
        success, msg = self.sync.enable_encryption(password)
        if success:
            result_widget.update(f"[bold success]{icon('success')} {msg}[/]")
        else:
            result_widget.update(f"[bold error]{icon('error')} {msg}[/]")
        self.update_status()
    
    def disable_encryption(self):
        result_widget = self.query_one("#enc-result", ResultPanel)
        success, msg = self.sync.disable_encryption()
        if success:
            result_widget.update(f"[bold success]{icon('success')} {msg}[/]")
        else:
            result_widget.update(f"[bold error]{icon('error')} {msg}[/]")
        self.update_status()


# ── Экран настроек (§5.6) ───────────────────────────────────────────

class SettingsScreen(BaseScreen):
    """Настройки: только чтение + ссылки на CLI."""
    
    def compose_content(self):
        config = self.sync.config
        
        return [
            ScreenTitle(f"{icon('settings')} Настройки", classes="screen-title"),
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


class CheckScreen(BaseScreen):
    """Проверка целостности хранилища (аналог restic check)."""

    def compose_content(self):
        return [
            ScreenTitle(f"{icon('shield')} Проверка целостности",
                        classes="screen-title"),
            ScreenSubtitle("Проверка блобов на битость и потери.",
                           classes="screen-subtitle"),
            Static("", classes="spacer"),
            Button(f"{icon('shield')}  Проверить хранилище",
                   variant="primary", id="btn-run-check"),
            Static("", classes="spacer"),
            ResultPanel(id="check-result"),
        ]

    def on_button_pressed(self, event):
        if event.button.id == "btn-run-check":
            ok, problems = self.sync.check_integrity()
            panel = self.query_one("#check-result", ResultPanel)
            if ok:
                stats = self.sync.version_store.stats()
                panel.update(
                    f"[success]{icon('success')} Хранилище целостно[/]\n\n"
                    f"  Блобов проверено:  [bold]{stats.get('blob_count', 0)}[/]\n"
                    f"  Битых блобов:      0\n"
                    f"  Размер:            {human_size(stats.get('stored_bytes', 0))}"
                )
            else:
                lines = "\n".join(f"  {icon('error')} {p}" for p in problems[:15])
                panel.update(
                    f"[error]{icon('error')} Найдено проблем: "
                    f"{len(problems)}[/]\n\n{lines}"
                )


class UpdateScreen(BaseScreen):
    """Проверка и установка обновлений."""

    def compose_content(self):
        from flamquency import __version__
        return [
            ScreenTitle(f"{icon('update')} Обновление",
                        classes="screen-title"),
            ScreenSubtitle(f"Установлена версия: {__version__}",
                           classes="screen-subtitle"),
            Static("", classes="spacer"),
            Button(f"{icon('cloud')}  Проверить обновления",
                   variant="primary", id="btn-check-update"),
            Static("", classes="spacer"),
            ResultPanel(
                f"[muted]{icon('info')} Нажми «Проверить» — сравню версию "
                f"с GitHub.\nПроверка кэшируется на 6 часов.[/]",
                id="update-result",
            ),
        ]

    def on_button_pressed(self, event):
        if event.button.id != "btn-check-update":
            return
        panel = self.query_one("#update-result", ResultPanel)
        panel.update(f"[muted]{icon('cloud')} Проверяю GitHub...[/]")
        from flamquency import __version__
        from flamquency.updater import check_for_update

        info = check_for_update(__version__)
        if info.error and info.error != "релизов ещё не опубликовано":
            panel.update(
                f"[warning]{icon('warning')} {info.error}[/]\n\n"
                f"[muted]Обновиться вручную:\n{info.url}[/]"
            )
        elif info.error:
            panel.update(
                f"[success]{icon('success')} Установлена последняя версия "
                f"{info.current}[/]\n\n"
                f"[muted]релизов ещё не опубликовано — обновиться можно "
                f"через git pull[/]"
            )
        elif info.available:
            notes = ""
            if info.release_notes:
                notes = f"\n\n[bold]Что нового:[/]\n{info.release_notes[:300]}"
            panel.update(
                f"[warning]{icon('update')} Доступна версия "
                f"[bold]{info.latest}[/] (у вас {info.current})[/]\n"
                f"[muted]Источник: {info.source}[/]{notes}\n\n"
                f"[bold]Обновить:[/] flamquency update --yes"
            )
        else:
            panel.update(
                f"[success]{icon('success')} Установлена последняя версия "
                f"[bold]{info.current}[/]\n[muted]Источник: {info.source}[/]"
            )


# ── Приложение ──────────────────────────────────────────────────────

class FlamQuencyApp(App):
    """FlamQuency-Sync Textual application — тема «Угольки»."""
    
    TITLE = "FlamQuency-Sync"
    SUB_TITLE = "File Sync with Version Control"
    
    CSS = """
    /* ═══ Поверхности (§3) ═══ */
    Screen {
        background: $surface;
    }

    /* ═══ Статус-бар (§4.2): sunken + огненная линия-разделитель ═══ */
    .status-bar {
        dock: top;
        width: 100%;
        background: $surface-sunken;
        height: 1;
        border-bottom: solid $accent-deep;
    }

    .status-text {
        padding: 0 1;
        width: 100%;
    }

    /* ═══ Заголовки экранов (§2) ═══ */
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

    /* ═══ Главный экран (§5.1) ═══ */
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

    /* ═══ Боковая навигация (§4.1): глубина + стекло ═══
       Rail на surface-raised, огненная граница справа. */
    NavRail {
        width: 22;
        background: $surface-raised;
        border-right: solid $accent-deep;
        padding: 1;
    }

    .nav-logo {
        text-align: center;
        width: 100%;
        color: $accent;
    }

    .nav-title {
        text-align: center;
        text-style: bold;
        color: $accent;
        width: 100%;
        padding-bottom: 1;
    }

    /* «Прозрачность» — наложение surface-overlay на surface-raised (§1.5);
       свечение — акцентный текст + рамка на фокусе. */
    .nav-btn {
        width: 100%;
        margin: 0 0 1 0;
        background: $surface-raised;
        color: $text;
        border: none;
    }

    .nav-btn:hover {
        background: $surface-overlay;
        color: $accent-warm;
    }

    .nav-btn:focus {
        background: $surface-overlay;
        color: $accent;
        text-style: bold;
    }

    .nav-btn-exit {
        width: 100%;
        margin: 0;
        border: none;
    }

    /* ═══ Панель результата (§4.5): тень через двойную рамку (§1.5) ═══
       Внешняя рамка accent-deep = угли-тень; фон surface-raised = стекло. */
    ResultPanel {
        margin: 1 2;
        padding: 1;
        background: $surface-raised;
        border: solid $accent-deep;
        min-height: 5;
        height: auto;
    }

    .result-box {
        margin: 1 2;
        padding: 1;
        background: $surface-raised;
        border: solid $accent-deep;
        min-height: 5;
    }

    /* ═══ Поля ввода: sunken + glow-рамка на фокусе ═══ */
    Input {
        margin: 0 2;
        background: $surface-sunken;
        border: solid $accent-deep;
    }

    Input:focus {
        border: solid $accent;
    }

    .field-label {
        padding: 0 2;
        color: $text-muted;
    }

    /* ═══ Таблицы (§4.4): зебра, glow-курсор ═══ */
    DataTable {
        margin: 1 2;
        background: $surface;
        border: solid $accent-deep;
        max-height: 20;
    }

    DataTable > .datatable--header {
        background: $surface-raised;
        color: $text-muted;
        text-style: bold;
    }

    DataTable > .datatable--cursor {
        background: $surface-overlay;
        color: $accent;
    }

    DataTable > .datatable--hover {
        background: $surface-raised;
    }

    /* ═══ Кнопки (§4.3) ═══ */
    Button {
        margin: 0 1;
        border: none;
    }

    .spacer {
        height: 1;
    }

    /* ═══ Настройки ═══ */
    .settings-section {
        color: $accent;
        text-style: bold;
        padding: 0 2;
    }

    .settings-value {
        color: $text-muted;
        padding: 0 2;
    }

    /* ═══ Прогресс: огненный градиент (§1.5) ═══
       Угли → пламя → ядро: фон accent-deep, заполнение accent-hot,
       завершение — success. */
    ProgressBar {
        margin: 0 2;
    }

    ProgressBar Bar {
        width: 40;
    }

    ProgressBar .bar--bar {
        color: $accent-hot;
        background: $accent-deep;
    }

    ProgressBar .bar--complete {
        color: $success;
    }

    /* ═══ Анимации (§7) ═══
       Textual 8.x не поддерживает @keyframes — движение задаётся
       через transition на offset/opacity/background виджетов. */
    .screen-title, .screen-subtitle, ResultPanel {
        transition: offset 200ms linear, opacity 200ms linear;
    }

    /* Кнопки «дышат» лёгким сдвигом при наведении (§7) */
    .nav-btn {
        transition: background 150ms linear, color 150ms linear;
    }

    Input {
        transition: border 150ms linear;
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
        elif btn_id == "nav-check":
            self._switch_screen(CheckScreen(self.sync))
        elif btn_id == "nav-update":
            self._switch_screen(UpdateScreen(self.sync))
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
