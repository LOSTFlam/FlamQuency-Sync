"""Интерактивная справка по командам — `flamquency help КОМАНДА`.

Стандартный ``--help`` печатает сухой список флагов. Здесь другое:
для каждой команды — зачем она нужна, живые примеры и связи с другими
командами, оформленные в стиле «Угольков».

Материал лежит рядом с кодом (этот модуль), а не в argparse, потому что
«зачем» и «примеры» — это про человеков, а не про парсер.
"""

# Заметки к командам: (зачем, [примеры], [смотри также])
HELP_TOPICS = {
    "sync": (
        "Синхронизировать файлы: снять версии, записать блобы, сделать "
        "снапшот. Работает по активному профилю, по указанному или по "
        "одному источнику.",
        ["flamquency sync",
         "flamquency sync --profile work",
         "flamquency sync --source ~/Документы"],
        ["profile", "stats", "restore-tree"],
    ),
    "status": (
        "Одна картинка о состоянии: когда был синк, какой бэкенд, сколько "
        "файлов отслеживается, включено ли шифрование, какой профиль активен.",
        ["flamquency status"],
        ["stats", "backend", "evolve"],
    ),
    "restore-content": (
        "Достать содержимое конкретной версии файла — в оригинал или в "
        "любой другой путь. Оригинал при этом не трогается.",
        ["flamquency restore-content заметки.md --version 0",
         "flamquency restore-content заметки.md -v 2 --output /tmp/старое.md",
         "flamquency restore-content заметки.md --list"],
        ["view-content", "restore-tree", "diff"],
    ),
    "view-content": (
        "Просто посмотреть, что было в файле в прошлой версии, ничего не "
        "восстанавливая. Большие файлы режутся лимитом.",
        ["flamquency view-content заметки.md",
         "flamquency view-content заметки.md -v 1 --max-bytes 4096"],
        ["restore-content", "diff"],
    ),
    "restore-tree": (
        "Вернуть целый каталог, весь профиль или всё хранилище к одной "
        "версии. Огромный файл случайно не удалить — можно выгрузить в "
        "отдельную папку и сравнить.",
        ["flamquency restore-tree --list",
         "flamquency restore-tree docs --output /tmp/проверка",
         "flamquency restore-tree --profile work -v 0"],
        ["restore-content", "rollback", "profile"],
    ),
    "diff": (
        "Увидеть, что изменилось между двумя версиями файла: добавленные "
        "строки зелёные, удалённые красные, плюс счётчик.",
        ["flamquency diff заметки.md --v1 0 --v2 2"],
        ["view-content", "rollback-file"],
    ),
    "schedule": (
        "Заставить синк повторяться самому: cron на Linux/macOS, Task "
        "Scheduler на Windows. Понимает человеческий язык.",
        ["flamquency schedule                      # показать текущее",
         "flamquency schedule 'каждый час'",
         "flamquency schedule 'каждые 30 минут' --profile work",
         "flamquency schedule daily                 # пресет",
         "flamquency schedule '0 3 * * *'           # сырой cron",
         "flamquency schedule --remove"],
        ["evolve", "profile"],
    ),
    "backend": (
        "Выбрать, куда складывать данные: локальная папка, GitHub, "
        "S3-совместимое облако, сетевая шара или Google Drive/Dropbox "
        "через rclone. Секреты живут в переменных окружения, не в конфиге.",
        ["flamquency backend                       # список и живой статус",
         "flamquency backend check s3              # чего не хватает",
         "flamquency backend use smb               # переключиться"],
        ["docs/BACKENDS.md", "status"],
    ),
    "evolve": (
        "Программа смотрит, как вы работаете, и предлагает стать лучше: "
        "горячие файлы, отдельный профиль для активного каталога, ярлык "
        "для частой команды. Применить — явно, одной командой.",
        ["flamquency evolve                        # показать предложения",
         "flamquency evolve --apply                # применить всё",
         "flamquency evolve --decay                # остудить жар",
         "flamquency evolve --forget заметки.md"],
        ["echo", "spark", "profile"],
    ),
    "spark": (
        "«Огниво»: ваши быстрые действия одной строкой. Три встроены "
        "сразу, остальные создавайте под себя.",
        ["flamquency spark                         # список искр",
         "flamquency spark now                     # встроенная — синк",
         "flamquency spark set деплой 'flamquency sync && ./deploy.sh'",
         "flamquency spark деплой --dry-run",
         "flamquency spark remove деплой"],
        ["evolve", "schedule"],
    ),
    "echo": (
        "«Эхо памяти»: разбирает историю вашей оболочки и подсказывает, "
        "какие каталоги пора взять под синк. Всё считается локально.",
        ["flamquency echo                          # что нашлось",
         "flamquency echo --add 2                  # добавить два лучших"],
        ["profile", "evolve"],
    ),
    "kaleido": (
        "«Калейдоскоп»: цветовые вариации темы «Угольки» — та же "
        "читаемость, другой характер. Поверхности остаются тёмными.",
        ["flamquency kaleido                       # список вариаций",
         "flamquency kaleido use magma",
         "flamquency kaleido --random"],
        ["docs/DESIGN.md"],
    ),
    "stats": (
        "Статистика хранилища: дедупликация, экономия места, разбивка по "
        "типам файлов, топ изменяемых, рост хранилища.",
        ["flamquency stats",
         "flamquency stats --graphs                # график роста",
         "flamquency stats --by-type",
         "flamquency stats --top 5"],
        ["check", "prune"],
    ),
    "ignore": (
        "Решить, что никогда не синкается: glob-правила как в .gitignore, "
        "плюс правила по размеру и типу файла.",
        ["flamquency ignore --init                 # стартовый файл",
         "flamquency ignore --add '*.psd'",
         "flamquency ignore --size-gt 1GB          # пропускать гиганты",
         "flamquency ignore --types mp4,avi",
         "flamquency ignore --check design.psd     # какое правило решило",
         "flamquency ignore --clear-global"],
        ["stats", "sync"],
    ),
    "profile": (
        "Профиль — именованный набор путей. Одна установка, разные "
        "сценарии: работа, документы, конфиги.",
        ["flamquency profile                       # список",
         "flamquency profile create work --path ~/projects --path ~/Документы",
         "flamquency profile use work",
         "flamquency profile add-path work ~/заметки",
         "flamquency profile describe work 'рабочие файлы'"],
        ["sync", "restore-tree", "echo"],
    ),
    "check": (
        "Проверить целостность хранилища: все ли блобы на месте, не "
        "повреждены ли они.",
        ["flamquency check"],
        ["stats", "prune"],
    ),
    "prune": (
        "Уборка старых снапшотов по правилам restic: хранить последние N, "
        "последний снапшот каждого часа/дня/недели, всё свежее срока.",
        ["flamquency prune --keep-last 10",
         "flamquency prune --keep-daily 7 --keep-weekly 4",
         "flamquency prune --keep-within 1y6m --dry-run"],
        ["check", "stats"],
    ),
    "encryption": (
        "Зашифровать блобы паролем (Fernet/AES). Без пароля данные "
        "недоступны — бэкдора нет.",
        ["flamquency encryption status",
         "flamquency encryption enable",
         "flamquency encryption change-password",
         "flamquency encryption disable"],
        ["status"],
    ),
    "update": (
        "Проверить и установить обновление с GitHub (pip или git).",
        ["flamquency update --check                # только проверить",
         "flamquency update --yes"],
        [],
    ),
    "watch": (
        "Следить за изменениями и синкаться автоматически. Умный режим "
        "ждёт тишины, а не дёргается на каждое сохранение.",
        ["flamquency watch ~/проекты",
         "flamquency watch                         # по умолчанию ~/.flamquency"],
        ["schedule", "sync"],
    ),
    "config": (
        "Посмотреть или открыть в редакторе файл настроек.",
        ["flamquency config                        # показать",
         "flamquency config --edit"],
        [],
    ),
}


def topics():
    """Доступные темы справки в стабильном порядке."""
    return list(HELP_TOPICS)


def get(topic):
    """(зачем, примеры, связи) или None если темы нет."""
    return HELP_TOPICS.get(topic)
