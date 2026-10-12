# 📦 Packaging Guide — FlamQuency-Sync

Полное руководство по упаковке и установке FlamQuency-Sync на разных дистрибутивах.

---

## 🐧 Arch Linux / Omarchy (AUR)

### Вариант 1: Через AUR (после публикации)
```bash
yay -S flamquency-sync
# или
paru -S flamquency-sync
```

### Вариант 2: Локальная сборка из PKGBUILD
```bash
cd packaging
# Скопировать PKGBUILD в пустую директорию (makepkg требует чистой)
mkdir /tmp/flamquency-build && cp PKGBUILD /tmp/flamquency-build/
cd /tmp/flamquency-build

# Скачать исходники и собрать
makepkg -si
```

### Вариант 3: AUR git-версия (всегда последняя)
```bash
yay -S flamquency-sync-git
```

---

## 🟠 Fedora / RHEL / CentOS (RPM)

### Через Copr (после настройки)
```bash
sudo dnf copr enable lostflam/flamquency-sync
sudo dnf install flamquency-sync
```

### Локальная сборка .rpm
```bash
# Установить зависимости сборки
sudo dnf install rpm-build python3-pip python3-build python3-installer git

# Собрать
bash scripts/build-rpm.sh

# Установить
sudo rpm -ivh ~/rpmbuild/RPMS/noarch/flamquency-sync-*.rpm
```

---

## 🟡 Debian / Ubuntu / Mint (.deb)

### Локальная сборка .deb
```bash
# Установить зависимости сборки
sudo apt-get install python3-pip python3-build python3-installer dpkg-dev

# Собрать
bash scripts/build-deb.sh

# Установить
sudo dpkg -i build-deb/flamquency-sync_*.deb
sudo apt-get install -f  # фикс зависимостей если нужно
```

---

## 🟣 Snap (любой дистрибутив со Snap)

### Через Snap Store (после публикации)
```bash
sudo snap install flamquency-sync
```

### Локальная сборка
```bash
sudo snap install snapcraft --classic
cd packaging
snapcraft
sudo snap install flamquency-sync_*.snap --dangerous
```

---

## 🔵 Flatpak (любой дистрибутив с Flatpak)

### Через Flathub (посде публикации)
```bash
flatpak install flathub com.lostflam.FlamQuencySync
flatpak run com.lostflam.FlamQuencySync
```

### Локальная сборка
```bash
# Установить flatpak-builder
sudo apt install flatpak-builder  # Debian/Ubuntu
sudo pacman -S flatpak-builder    # Arch

# Установить runtime
flatpak install flathub org.freedesktop.Platform//24.08 org.freedesktop.Sdk//24.08

# Собрать
cd packaging
flatpak-builder --force-clean build-dir com.lostflam.FlamQuencySync.yml

# Установить
flatpak-builder --user --install build-dir com.lostflam.FlamQuencySync.yml
```

---

## 🐍 PyPI (универсальный способ)

```bash
pip install flamquency-sync
```

---

## 📁 Структура файлов упаковки

```
packaging/
├── PKGBUILD                        # Arch Linux / AUR
├── .SRCINFO                        # AUR метаданные
├── snapcraft.yaml                  # Snap
├── com.lostflam.FlamQuencySync.yml # Flatpak
├── com.lostflam.FlamQuencySync.desktop
├── com.lostflam.FlamQuencySync.metainfo.xml
├── debian/control                  # .deb
├── flamquency-sync.spec            # .rpm
└── README.md                       # Этот файл

scripts/
├── build-deb.sh                    # Скрипт сборки .deb
└── build-rpm.sh                    # Скрипт сборки .rpm

docs/
├── flamquency.1                    # Man-страница
└── design.md

completions/
├── flamquency.bash                 # Bash
├── flamquency.zsh                  # Zsh
└── flamquency.fish                 # Fish
```

---

## 🔄 Обновление версии

При изменении `pkgver` в `PKGBUILD` нужно обновить:
1. `pkgver` в `packaging/PKGBUILD`
2. `Version:` в `packaging/debian/control`
3. `Version:` в `packaging/flamquency-sync.spec`
4. `version:` в `packaging/snapcraft.yaml`
5. `.SRCINFO` (перегенерировать: `makepkg --printsrcinfo > .SRCINFO`)

---

## 📝 Публикация в AUR

1. Создать аккаунт на https://aur.archlinux.org
2. Настроить SSH-ключ
3. Клонировать AUR репозиторий:
   ```bash
   git clone ssh://aur@aur.archlinux.org/flamquency-sync.git
   ```
4. Скопировать `PKGBUILD` и `.SRCINFO`:
   ```bash
   cp packaging/PKGBUILD packaging/.SRCINFO .
   makepkg --printsrcinfo > .SRCINFO
   ```
5. Закоммитить и запушить:
   ```bash
   git add PKGBUILD .SRCINFO
   git commit -m "Initial release: v0.1.0"
   git push
   ```
