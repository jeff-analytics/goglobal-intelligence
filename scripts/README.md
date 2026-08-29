# Utility Scripts

The repository keeps only the two primary launchers at the root:

- `run_win.bat`
- `run_mac.command`

Maintenance utilities are grouped by operating system.

## Windows

- `windows/migrate_from_existing.bat` — copy local configuration, database and reusable caches from an existing V5.3.x folder.
- `windows/self_check.bat` — run backend tests and frontend production build.
- `windows/repair.bat` — rebuild the local Python virtual environment and restart setup.
- `windows/prepare_ports.ps1` — safely release BorderMargin ports before startup.
- `windows/start_backend.bat` — internal backend launcher used by `run_win.bat`.
- `windows/start_frontend.bat` — internal frontend launcher used by `run_win.bat`.

## macOS

- `macos/migrate_from_existing.command` — migrate local V5.3.x settings/data.
- `macos/self_check.command` — run backend tests and frontend production build.
