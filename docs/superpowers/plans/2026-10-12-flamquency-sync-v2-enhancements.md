# FlamQuency-Sync v2.0 — Амбициозные Улучшения (План Реализации)

> **Для agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Сделать FlamQuency-Sync непревзойдённым, улучшив визуальную составляющую, интуитивность и функциональность CLI и TUI, добавив полноценную систему хранения версий с восстановлением.

**Architecture:** Улучшение будет производиться по нескольким направлениям: расширение цветовой палитры и эффектов в `style.py` и `theme.py` для CLI/TUI, добавление новых иконок в `icons.py`, реализация новых функций версионирования и планирования в `sync_engine.py` и `cli.py`, а также создание новых экранов и виджетов в `textual_tui.py`. Конфигурация будет расширена в `config.py`.

**Tech Stack:** Python, Textual, Rich, pathlib, dataclasses, asyncio, fontTools (по необходимости), typer/click (по необходимости), watchdog, GitHub API (httpx/requests), GitPython (по необходимости), cron / systemd, Pydantic.

**Spec:** .hermes/composer-pastes/pasted_content_2026-10-12_14-20-17-430_f23547.txt

## Global Constraints

- Сохранение полной обратной совместимости с существующими профилями и данными.
- Все новые функции должны быть доступны как через CLI, так и через TUI, где это применимо.
- Приоритет кроссплатформенности (Linux, Windows, macOS для CLI, если Textual/Rich поддерживают TUI).
- Соблюдение принципов UX: интуитивность, минимализм, информативность.
- Использование Nerd Font v2 для иконок.

## Review Focus

- Правильная обработка больших файлов при версионировании и восстановлении (производительность, потребление памяти).
- Надёжность планировщика задач (корректная интеграция с cron/systemd-timer, обработка ошибок).
- Визуальная согласованность и читаемость всех новых элементов дизайна в различных терминалах.
- Безопасность при работе с облачными бэкендами (авторизация, шифрование).
- Сохранение производительности TUI при сложных анимациях и графиках.

---

### Task 1: Расширение иконок и обновление документации DESIGN.md

**Files:**
- Modify: `src/flamquency/icons.py`
- Create: `docs/superpowers/plans/2026-10-12-flamquency-sync-v2-enhancements.md` (этот файл)
- Modify: `docs/DESIGN.md`

**Interfaces:**
- Produces: Обновлённый `icons.py` с новыми глифами. Детализированный `DESIGN.md` с описанием новых элементов дизайна.

- [ ] **Step 1: Детализировать градиенты, тени, свечение и прозрачность в `DESIGN.md`**

    Добавить конкретные примеры Hex-кодов для градиентов "пламени" (от accent-deep к accent-hot), техники имитации свечения (blur стили или Unicode символы), тени (псевдографика, Panel слои) и прозрачности (матовое стекло).
    Описать, какие `transition` использовать для анимаций и какие расширенные компоненты (Scrollbars, Inputs, Buttons) будут стилизованы.
    Описать UX-элементы (Toast, Context Menu).

- [ ] **Step 2: Расширить `icons.py` новыми глифами**

    Добавить иконки для: графиков, расписания, облачных бэкендов, поиска, различных состояний (warning для облака без коннекта).

- [ ] **Step 3: Обновить `DESIGN.md` с описанием новых иконок и их контекстного использования**

    Описать, какие иконки будут использоваться для новых фич и как они будут менять цвет в зависимости от состояния.

- [ ] **Step 4: Commit**

```bash
git add src/flamquency/icons.py docs/DESIGN.md
git commit -m "feat: enhance icons and update DESIGN.md with new design philosophy"
```

### Task 2: Переработка стилей и тем для CLI/TUI

**Files:**
- Modify: `src/flamquency/style.py`
- Modify: `src/flamquency/theme.py`

**Interfaces:**
- Consumes: Детализированные описания градиентов, теней, свечения и анимаций из `DESIGN.md`.
- Produces: Расширенная палитра цветов, градиенты, эффекты свечения/теней, анимации, применённые к Rich и Textual компонентам.

- [ ] **Step 1: Интегрировать расширенную палитру в `src/flamquency/theme.py`**

    Добавить `accent-warm`, `accent-deep`, `accent-hot` и другие необходимые оттенки.

- [ ] **Step 2: Реализовать Rich-аналоги новых эффектов и компонентов в `src/flamquency/style.py` для CLI**

    Создать/модифицировать стили для ProgressBar (огненный градиент), заголовков, активных элементов.

- [ ] **Step 3: Применить новые CSS-эффекты (transition, border, opacity) ко всем виджетам в `src/flamquency/textual_tui.py`**

    (Этот шаг будет выполнен позже, когда `textual_tui.py` будет модифицирован. Здесь только фиксация необходимости.)

- [ ] **Step 4: Реализовать анимированные цвета в `src/flamquency/theme.py` (пульсация accent, изменение на accent-hot)**

    Исследовать возможности Textual для медленного пульсирования цвета на элементах в состоянии ожидания и изменения цвета при критических действиях.

- [ ] **Step 5: Commit**

```bash
git add src/flamquency/style.py src/flamquency/theme.py
git commit -m "feat: implement enhanced 'Coals' theme with gradients, animations, and extended palette"
```

### Task 3: Полноценная система версионирования контента

**Files:**
- Modify: `src/flamquency/sync_engine.py`
- Modify: `src/flamquency/version_store.py`
- Modify: `src/flamquency/cli.py`

**Interfaces:**
- Consumes: существующая система хранения версий.
- Produces: Методы для детализированного восстановления файла/каталога/профиля, просмотра содержимого файла конкретной версии и визуального `diff`.

- [ ] **Step 1: Добавить метод `restore_file_content(rel_path, version_index, dest_path=None)` в `src/flamquency/version_store.py`**

    Этот метод должен читать блобы, дешифровать их и восстанавливать содержимое конкретной версии файла. Если `dest_path` не указан, восстанавливать в оригинальное место.

- [ ] **Step 2: Добавить команду `flamquency restore-content <file_path> --version N [--output <path>]` в `src/flamquency/cli.py`**

    Эта команда будет использовать новый метод из `version_store.py` для восстановления файла через CLI.

- [ ] **Step 3: Добавить команду `flamquency view-content <file_path> --version N` в `src/flamquency/cli.py`**

    Эта команда должна читать содержимое конкретной версии файла (также используя `version_store.py`) и выводить его в терминал.

- [ ] **Step 4: Реализовать восстановление целых каталогов/профилей в `src/flamquency/sync_engine.py`**

    Добавить логику для восстановления группы файлов или всего профиля на определённый снапшот.

- [ ] **Step 5: Улучшить `flamquency diff` для использования визуального diff-инструмента в CLI**

    Исследовать возможности Rich для отображения визуального `diff` двух версий файла, с подсветкой изменений.

- [ ] **Step 6: Написать юнит-тесты для новых функций версионирования**

    Проверить корректность восстановления файлов, каталогов и просмотра содержимого.

- [ ] **Step 7: Commit**

```bash
git add src/flamquency/sync_engine.py src/flamquency/version_store.py src/flamquency/cli.py
git commit -m "feat: implement comprehensive content versioning and restoration"
```

### Task 4: Расширенное планирование и автоматизация

**Files:**
- Modify: `src/flamquency/cli.py`
- Modify: `src/flamquency/config.py`
- Create: `src/flamquency/scheduler.py` (новый файл)

**Interfaces:**
- Produces: Интеграция с планировщиком задач (cron/systemd-timer), интеллектуальный автосинк, настраиваемые хуки после синхронизации.

- [ ] **Step 1: Расширить конфиг в `src/flamquency/config.py` для настроек расписания и хуков**

    Добавить поля для `schedule` (cron-подобные строки), `smart_autosync_timeout`, `post_sync_script`.

- [ ] **Step 2: Создать новый файл `src/flamquency/scheduler.py` для интеграции с cron/systemd-timer**

    Реализовать логику для создания и управления системными заданиями (cron/systemd-timer) на основе настроек в конфиге.

- [ ] **Step 3: Расширить команду `flamquency schedule <interval> --profile <profile_name>` в `src/flamquency/cli.py`**

    Эта команда будет взаимодействовать с `scheduler.py` для настройки синхронизации по расписанию, с привязкой к профилям.

- [ ] **Step 4: Реализовать интеллектуальный автосинк в `src/flamquency/sync_engine.py` (или в новом `scheduler.py`)**

    Использовать `watchdog` (или аналоги) с умным таймаутом, чтобы не дёргать синхронизацию на каждое мимолётное изменение.

- [ ] **Step 5: Добавить поддержку настраиваемых хуков (`post-sync-script`) после синхронизации в `src/flamquency/sync_engine.py`**

    После успешной синхронизации должен запускаться скрипт, указанный в конфиге.

- [ ] **Step 6: Написать юнит-тесты для новых функций планирования и автоматизации**

    Проверить корректность создания расписаний, работу автосинка и выполнение хуков.

- [ ] **Step 7: Commit**

```bash
git add src/flamquency/cli.py src/flamquency/config.py src/flamquency/scheduler.py src/flamquency/sync_engine.py
git commit -m "feat: implement advanced scheduling and automation features"
```

### Task 5: Расширенное управление бэкендами

**Files:**
- Modify: `src/flamquency/cli.py`
- Modify: `src/flamquency/config.py`
- Modify: `src/flamquency/cloud.py` (или создать новые файлы для каждого бэкенда)

**Interfaces:**
- Produces: Поддержка большего количества облачных и локальных сетевых бэкендов, TUI-управление бэкендами.

- [ ] **Step 1: Расширить конфиг в `src/flamquency/config.py` для новых типов бэкендов**

    Добавить поля для S3-совместимых хранилищ (endpoint, access_key, secret_key), Google Drive, Dropbox (через токены/ключи), SMB/NFS (пути, учетные данные).

- [ ] **Step 2: Реализовать поддержку S3-совместимых хранилищ в `src/flamquency/cloud.py`**

    Использовать `boto3` или аналогичную библиотеку для взаимодействия с S3-бэкендами.

- [ ] **Step 3: Добавить поддержку Google Drive и Dropbox**

    Исследовать соответствующие CLI-утилиты или Python API для интеграции. Возможно, потребуется создание новых файлов (например, `src/flamquency/google_drive_backend.py`, `src/flamquency/dropbox_backend.py`).

- [ ] **Step 4: Добавить поддержку локальных сетевых хранилищ (SMB/NFS)**

    Реализовать возможность использования сетевых папок как бэкендов, с учётом прав доступа и монтирования.

- [ ] **Step 5: Расширить `src/flamquency/cli.py` для управления новыми бэкендами**

    Добавить команды для добавления, удаления, переключения и просмотра статуса бэкендов.

- [ ] **Step 6: Написать юнит-тесты для новых бэкендов**

    Проверить корректность подключения, синхронизации и обработки ошибок для каждого нового бэкенда.

- [ ] **Step 7: Commit**

```bash
git add src/flamquency/cli.py src/flamquency/config.py src/flamquency/cloud.py # и/или новые файлы для бэкендов
git commit -m "feat: extend backend management with cloud and network storage"
```

### Task 6: Улучшенное управление ignore-правилами

**Files:**
- Modify: `src/flamquency/ignore.py`
- Modify: `src/flamquency/cli.py`

**Interfaces:**
- Produces: TUI-редактор `.flamquencyignore`, правила исключения по размеру/типу файла.

- [ ] **Step 1: Реализовать TUI-редактор `.flamquencyignore`**

    Создать Textual виджет для интерактивного редактирования `ignore`-файла с подсветкой синтаксиса и проверкой правил на лету. (Это будет связано с `textual_tui.py` позже).

- [ ] **Step 2: Добавить поддержку глобальных правил игнорирования по размеру файла и типу в `src/flamquency/ignore.py`**

    Расширить логику игнорирования, чтобы можно было задавать правила типа `ignore_size_gt=1GB` или `ignore_types=mp4,avi`.

- [ ] **Step 3: Обновить `src/flamquency/cli.py` для управления новыми ignore-правилами**

    Добавить команды для добавления, удаления и просмотра глобальных ignore-правил.

- [ ] **Step 4: Написать юнит-тесты для новых ignore-правил**

    Проверить корректность игнорирования файлов по размеру и типу.

- [ ] **Step 5: Commit**

```bash
git add src/flamquency/ignore.py src/flamquency/cli.py
git commit -m "feat: enhance ignore rules with TUI editor and size/type exclusions"
```

### Task 7: Продвинутая статистика и аналитика

**Files:**
- Modify: `src/flamquency/sync_engine.py`
- Modify: `src/flamquency/cli.py`

**Interfaces:**
- Produces: Графики использования хранилища, топ-изменённых файлов, детализированная статистика.

- [ ] **Step 1: Собирать данные для графиков использования хранилища, дедупликации и размеров снапшотов в `src/flamquency/sync_engine.py`**

    Расширить логику синхронизации для сбора этих метрик.

- [ ] **Step 2: Добавить команду `flamquency stats --graphs` в `src/flamquency/cli.py` для отображения графиков в CLI**

    Использовать Rich для отрисовки простых текстовых графиков или ссылок на внешние утилиты для более сложных.

- [ ] **Step 3: Реализовать список топ-изменённых файлов в `src/flamquency/sync_engine.py`**

    Отслеживать и хранить информацию о файлах, которые меняются чаще всего.

- [ ] **Step 4: Расширить команду `flamquency stats` для детализации по типам файлов, по профилям, по размеру**

    Добавить опции для фильтрации и группировки статистики.

- [ ] **Step 5: Написать юнит-тесты для новых функций статистики и аналитики**

    Проверить корректность сбора данных и вывода статистики.

- [ ] **Step 6: Commit**

```bash
git add src/flamquency/sync_engine.py src/flamquency/cli.py
git commit -m "feat: implement advanced statistics and analytics"
```

### Task 8: Улучшенный UX для CLI

**Files:**
- Modify: `src/flamquency/cli.py`

**Interfaces:**
- Produces: Автодополнение команд, интерактивный `--help`, прогресс-бары для долгих операций.

- [ ] **Step 1: Интегрировать автодополнение команд и аргументов**

    Исследовать `typer`/`click` или аналоги для создания скриптов автодополнения для bash/zsh/fish.

- [ ] **Step 2: Реализовать интерактивный `--help`**

    Добавить возможность `flamquency help sync` для получения детальной справки по конкретной команде, возможно, с использованием Rich `HelpPanel`.

- [ ] **Step 3: Добавить Rich-прогресс-бары для всех долгих CLI-операций**

    Применить прогресс-бары к `sync`, `prune`, `check` и другим длительным командам.

- [ ] **Step 4: Написать юнит-тесты для автодополнения и интерактивного `--help` (если применимо)**

- [ ] **Step 5: Commit**

```bash
git add src/flamquency/cli.py
git commit -m "feat: enhance CLI UX with autocompletion, interactive help, and progress bars"
```

### Task 9: Инновации Таи (интеграция в TUI)

**Files:**
- Modify: `src/flamquency/textual_tui.py`
- Modify: `src/flamquency/cli.py` (для "Огниво")
- Modify: `src/flamquency/config.py` (для "Огниво" и "Калейдоскопа")
- Create: `src/flamquency/spark.py` (новый файл для "Огниво")

**Interfaces:**
- Consumes: Все предыдущие улучшения стилей, иконок, версионирования, планирования.
- Produces: "Огниво", "Эхо памяти", "Калейдоскоп", персонализированные подсказки в TUI.

- [ ] **Step 1: Реализовать "Огниво" (FlamQuency Spark)**

    Создать новый файл `src/flamquency/spark.py` для определения настраиваемых быстрых действий.
    Добавить команду `flamquency spark <action_name>` в `src/flamquency/cli.py`.
    Интегрировать "Огниво" в TUI через кнопку или горячую клавишу.
    Расширить конфиг для определения "Огнива".

- [ ] **Step 2: Интегрировать "Эхо памяти"**

    Исследовать, как получить историю команд терминала.
    Разработать логику, чтобы FlamQuency мог предлагать синхронизировать часто изменяемые файлы на основе этой истории.

- [ ] **Step 3: Создать экран "Калейдоскоп" в `src/flamquency/textual_tui.py`**

    Этот экран будет рандомно переключать цветовые вариации темы "Угольки" (с сохранением базовой структуры). Расширить конфиг для настроек "Калейдоскопа".

- [ ] **Step 4: Реализовать персонализированные подсказки в TUI**

    Создать механизм для отображения маленьких, ненавязчивых подсказок, которые появляются по мере использования, обучая новым функциям.

- [ ] **Step 5: Создать `RestoreContentScreen` для интерактивного восстановления в `src/flamquency/textual_tui.py`**

    Этот экран будет использовать функции версионирования из Task 3.

- [ ] **Step 6: Добавить `ScheduleScreen` для настройки расписания в `src/flamquency/textual_tui.py`**

    Этот экран будет взаимодействовать с `scheduler.py` из Task 4.

- [ ] **Step 7: Интегрировать TUI-версию `flamquency stats` с графиками в `src/flamquency/textual_tui.py`**

    Если Textual позволяет, использовать его возможности для отрисовки визуальных графиков.

- [ ] **Step 8: Реализовать навигацию по DataTables с контекстным меню в `src/flamquency/textual_tui.py`**

    Добавить возможность вызывать контекстное меню при выделении элемента в таблице (снапшот, файл).

- [ ] **Step 9: Commit**

```bash
git add src/flamquency/textual_tui.py src/flamquency/cli.py src/flamquency/config.py src/flamquency/spark.py
git commit -m "feat: implement Tai's innovations and TUI enhancements"
```

### Task 10: Общие тесты, прогон, верификация и документация

**Files:**
- Modify: `README.md`
- Create/Modify: `tests/*.py` (общие тесты)

**Interfaces:**
- Consumes: Все реализованные функции и улучшения.
- Produces: Полностью протестированный и задокументированный FlamQuency-Sync.

- [ ] **Step 1: Провести полный прогон всех юнит-тестов**

    Убедиться, что все новые функции и изменения работают корректно.

- [ ] **Step 2: Ручная проверка CLI и TUI**

    Визуально оценить новые элементы дизайна, анимации, работу новых команд и экранов.

- [ ] **Step 3: Обновить `README.md`**

    Отразить все новые возможности, изменения в UX, информацию о планировщике, бэкендах, версионировании и инновациях Таи.

- [ ] **Step 4: Финализировать коммит и запушить изменения**

```bash
git add .
git commit -m "release: FlamQuency-Sync v2.0 with all ambitious enhancements"
git push
```
