# Changelog

Notable changes. Format loosely follows Keep a Changelog, versions follow SemVer.

## [1.0.0] - 2026-11-07

First release. Built and tested on Windows 10 and 11 only. Fallbacks for other systems exist in the
code but have not been run, so no other platform is supported yet.

### Added

- A dark Tk panel with one row per craft app and one column per harness, sixteen of each.
- Writers for Claude Code, Codex, Antigravity, OpenCode, Cursor, VS Code, Zed, Devin, Trae, Cline,
  Copilot CLI, LM Studio, Qoder, Verdent, JetBrains Air and Kiro, each in its own shape.
- Three modes: headless, attach, and GUI, where the app window and the harness share one document over a
  loopback control channel.
- Detection that resolves the scoop root through five tiers, up to a scan of every fixed local drive,
  and harnesses through their own environment variables.
- Detection states in the interface: present, creatable, absent, with the reason and the path tested on
  hover, in a Detect dialog, and through `--doctor`.
- Port negotiation for GUI mode, recorded in `ports.json`, so a busy port never breaks a registration.
- Automatic discovery of other VS Code forks that keep a `User/mcp.json`.
- Icons at ten sizes generated from the logo, a tray icon, an AppUserModelID, and per monitor DPI
  awareness.
- `--check`, `--doctor`, `--probe`, `--gui`, `--guitest`, `--selftest`, `--smoke` and `--make-icons`.
- `--guitest` measures GUI mode instead of assuming it: it launches each app, probes the bridge with the
  window up and again with it closed, and reports whether the harness really reaches the window. Across
  the sixteen apps, nine bridge for real, three fall back to headless, and four open a window with no
  usable channel.
- `make_shortcut.py`, which creates, refreshes or removes the desktop shortcut, then reads the `.lnk`
  back and confirms the target, icon and working directory.
- Side by side documentation of every config shape, and a selftest with fifty two assertions.

### Known limits

- Kiro's config path comes from documentation, not from a file Kiro had written.
- PhotoCraft, EffectCraft and WordCraft answer the bridge command the same way with their window closed,
  which means the harness is served headless and the window never changes. For PhotoCraft I also tried
  the inline `--control-token` form with a correct token, a wrong token, and no window at all. All four
  combinations returned the same 26 tools, so the CLI is not reaching the app in build 0.21.0. The panel
  now warns on apply and marks these three `bridge unconfirmed` in `--doctor`.
- FilmCraft, PdfCraft and Craft Anything open a window but expose no control channel, and SoundCraft's
  CLI has no bridge flag at all.
