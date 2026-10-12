# Бэкенды FlamQuency-Sync

Хранилище, куда FlamQuency складывает блобы и снапшоты, подключается как
**бэкенд**. Активный бэкенд задаётся ключом `cloud_backend` в
`~/.flamquency/config.yaml`.

```bash
flamquency backend                # список + живой статус активного
flamquency backend check s3       # почему бэкенд не готов
flamquency backend use smb        # переключиться (только если готов)
```

Фабрика **никогда не подменяет** неготовое облако локальной папкой: если
S3 не настроен, вы получите понятную ошибку, а не тихую запись на диск.

## Секреты — только в окружении

В `config.yaml` хранится лишь **имя** переменной окружения, из которой
бэкенд читает секрет в момент работы. Сам конфиг можно смело коммитить и
синкарить — в нём нет ключей.

```yaml
backends:
  s3:
    bucket: my-backet
    endpoint: https://s3.eu-central-1.amazonaws.com
    region: eu-central-1
    prefix: flamquency/
    access_key_env: FLAMQUENCY_S3_ACCESS_KEY
    secret_key_env: FLAMQUENCY_S3_SECRET_KEY
```

```bash
export FLAMQUENCY_S3_ACCESS_KEY=...
export FLAMQUENCY_S3_SECRET_KEY=...
```

Чтобы объявить секрет ненужным (гостевая сетевая шара, одноранговый NFS),
поставьте пустую строку: `password_env: ""`. Диагностика перестанет его
требовать.

---

## local

Хранилище на этом же диске — `~/.flamquency/sync`. Ничего настраивать не
нужно, работает всегда. Значение по умолчанию.

## github

Приватный репозиторий как хранилище, через Git CLI. Настройки:
`cloud_repo_name`, токен в `FLAMQUENCY_GITHUB_TOKEN`.

## s3 — любое S3-совместимое хранилище

AWS S3, MinIO, Backblaze B2, Wasabi, Cloudflare R2 и всё, что говорит по
S3 API. Нужна библиотека:

```bash
pip install boto3
```

| Настройка | Смысл |
|:--|:--|
| `bucket` | имя бакета (обязательно) |
| `endpoint` | пусто → AWS; иначе URL своего S3 (`https://minio.example`) |
| `region` | регион, для AWS обязателен |
| `prefix` | префикс ключей внутри бакета (`flamquency/`) |

Секреты: `FLAMQUENCY_S3_ACCESS_KEY`, `FLAMQUENCY_S3_SECRET_KEY`.

Помимо облака бэкенд держит **локальное зеркало** в `~/.flamquency/sync`,
поэтому восстановление версий и `stats` работают даже без сети.

## smb — сетевая Windows-папка

FlamQuency **не монтирует сам**: точку монтирования готовит система
(systemd, `/etc/fstab`, `mount -t cifs`), а программа работает с готовой
папкой — так же, как с локальной. Настройки: `server`, `mount_point`.

```bash
# пример монтирования (делается один раз, вне FlamQuency)
sudo mount -t cifs //nas/backup /mnt/nas -o username=...,password=...
```

Секреты: `FLAMQUENCY_SMB_USER`, `FLAMQUENCY_SMB_PASSWORD` (или пустые
строки для гостевого доступа).

## nfs — сетевая NFS-папка

Тот же принцип: монтируете сами, FlamQuency использует. Настройки:
`server`, `mount_point`. Секретов нет. Linux/macOS.

## gdrive и dropbox — облако через rclone

Эти два бэкенда работают через **rclone**, чтобы не тащить отдельные
Python-библиотеки под каждое облако:

```bash
# один раз: авторизовать remote в rclone
rclone config          # создайте remote с именем gdrive / dropbox
```

| Бэкенд | Настройка | Remote |
|:--|:--|:--|
| `gdrive` | `folder_id` | `gdrive:<folder_id>` |
| `dropbox` | `path` | `dropbox:<path>` |

FlamQuency держит локальное зеркало и синкает его командой `rclone sync`
(`push()` — в облако, `pull()` — из облака), поэтому список файлов и
удаление работают и офлайн.

---

## Диагностика

`flamquency backend check ИМЯ` перечисляет всё, чего не хватает:

- библиотека не установлена → `pip install boto3`
- настройка не заполнена → `Не задана настройка: backends.s3.bucket`
- секрет не найден → `Нет переменной окружения: FLAMQUENCY_S3_SECRET_KEY`
- шара не смонтирована → `Точка монтирования недоступна: /mnt/nas`
- платформа не поддерживается → `Не поддерживается на windows`
