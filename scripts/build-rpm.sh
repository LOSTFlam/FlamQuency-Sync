#!/usr/bin/env bash
# Build RPM package for flamquency-sync
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
VERSION="0.1.0"
RPMBUILD_DIR="$HOME/rpmbuild"

cd "$PROJECT_DIR"

echo "🔥 Building RPM for FlamQuency-Sync v$VERSION"

# Setup rpmbuild dirs
mkdir -p "$RPMBUILD_DIR"/{BUILD,RPMS,SOURCES,SPECS,SRPMS}

# Create source tarball
echo "  Creating source tarball..."
git archive --format=tar.gz --prefix="FlamQuency-Sync/" -o \
    "$RPMBUILD_DIR/SOURCES/flamquency-sync-${VERSION}.tar.gz" HEAD

# Copy spec
cp packaging/flamquency-sync.spec "$RPMBUILD_DIR/SPECS/"

# Build RPM
echo "  Building package..."
rpmbuild -bb "$RPMBUILD_DIR/SPECS/flamquency-sync.spec"

echo "✅ Done:"
find "$RPMBUILD_DIR/RPMS" -name "flamquency-sync-*.rpm"
