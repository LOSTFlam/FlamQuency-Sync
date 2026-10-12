%global pkgversion 0.1.0

Name:           flamquency-sync
Version:        0.1.0
Release:        1%{?dist}
Summary:        Terminal-based file synchronization with version control
License:        MIT
URL:            https://github.com/LOSTFlam/FlamQuency-Sync
Source0:        %{name}-%{version}.tar.gz
BuildArch:      noarch
Requires:       python3
Requires:       python3-pip
Requires:       git
Recommends:     gh

%description
FlamQuency-Sync is a terminal-based file synchronization tool with real
version control, snapshots, and one-click rollback. Every version of your
files is stored in content-addressable blob storage, so you can restore
any file or the whole system to any point in time.

Features:
  - Full sync with selective exclusions
  - Real version control (SHA256 content-addressable storage)
  - Full snapshots and one-button rollback
  - GitHub cloud backend
  - Textual TUI with arrow navigation
  - CLI mode for scripting
  - Watch mode for auto-sync
  - Optional Fernet/AES encryption

%prep
%setup -q -n FlamQuency-Sync

%build
pip3 install --no-deps --prefix=%{_prefix} .

%install
install -Dm644 LICENSE %{buildroot}/usr/share/licenses/%{name}/LICENSE
install -Dm644 docs/flamquency.1 %{buildroot}/usr/share/man/man1/flamquency.1

%files
%license LICENSE
%doc README.md docs/
%{_bindir}/flamquency
%{_bindir}/flamquency-tui

%changelog
* Mon Oct 12 2026 LOSTFlam <lostflam@users.noreply.github.com> - 0.1.0-1
- Initial RPM release
