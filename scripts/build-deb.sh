#!/usr/bin/env bash
# Build .deb package for flamquency-sync
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
VERSION="0.1.0"
BUILD_DIR="$PROJECT_DIR/build-deb"

cd "$PROJECT_DIR"

echo "🔥 Building .deb for FlamQuency-Sync v$VERSION"

# Clean
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"

# Build wheel
echo "  Building wheel..."
python -m build --wheel --no-isolation

# Install to staging
STAGING="$BUILD_DIR/staging"
mkdir -p "$STAGING"
python -m installer --destdir="$STAGING" dist/*.whl

# Create deb structure
DEB_ROOT="$BUILD_DIR/flamquency-sync_${VERSION}_all"
mkdir -p "$DEB_ROOT"
cp -r "$STAGING"/* "$DEB_ROOT/"

# Add license
install -Dm644 LICENSE "$DEB_ROOT/usr/share/licenses/flamquency-sync/LICENSE"

# Add man page
install -Dm644 docs/flamquency.1 "$DEB_ROOT/usr/share/man/man1/flamquency.1"

# Add completions
install -Dm644 completions/flamquency.bash \
    "$DEB_ROOT/usr/share/bash-completion/completions/flamquency"
install -Dm644 completions/flamquency.zsh \
    "$DEB_ROOT/usr/share/zsh/site-functions/_flamquency"
install -Dm644 completions/flamquency.fish \
    "$DEB_ROOT/usr/share/fish/vendor_completions.d/flamquency.fish"

# Add control files
mkdir -p "$DEB_ROOT/DEBIAN"
cp packaging/debian/control "$DEB_ROOT/DEBIAN/control"

# Build deb
echo "  Building package..."
dpkg-deb --build "$DEB_ROOT"

echo "✅ Done: $BUILD_DIR/flamquency-sync_${VERSION}_all.deb"
