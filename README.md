<div align="center">

<img src="Orange%20C%20Connection%20Logo.png" alt="Craft Connect logo" width="160">

<h1>Craft Connect</h1>

<p><strong>Sixteen craft apps, sixteen AI tools, one grid of toggles.</strong></p>

[![Platform](https://img.shields.io/badge/platform-Windows%2010%20%7C%2011-0078d4?style=flat-square)](#requirements)
[![Python](https://img.shields.io/badge/python-3.11%2B-3776ab?style=flat-square)](#requirements)
[![Licence](https://img.shields.io/badge/licence-MIT%20%2B%20attribution-f96b0d?style=flat-square)](LICENSE)
[![Built on ArtCraft](https://img.shields.io/badge/built%20on-ArtCraft%20by%20storytold-f96b0d?style=flat-square)](https://github.com/storytold)

</div>

A GUI that connects the ArtCraft apps (PhotoCraft, VectorCraft, PdfCraft and the rest) to
the AI tools on your machine, so you never have to remember a terminal command again.

> **Windows only, for now.** This has been built and tested on Windows 10 and Windows 11. The code has
> fallbacks for other systems in places, but nobody has run them, so treat macOS and Linux as untested
> rather than supported. The GUI mode control channel, the shortcut script, the icon handling and the
> tray all lean on Windows APIs.


I wrote this because my own setup had sixteen craft apps and sixteen AI tools, and every single pairing
meant copying a command line out of one help page into another config file. Now it is a grid of
checkboxes. Tick what you want, press Apply, restart the tool you ticked, done.

## Requirements

| Need | Why | If it's missing |
|---|---|---|
| Windows 10 or 11 | Tk window, DPI APIs, loopback control channel | nothing runs, and nothing else has been tested |
| Python 3.11+ with Tk | the whole tool | it won't start |
| Pillow | icon generator, window logo, tray picture | icons and tray are skipped, the panel still works |
| pystray | tray icon | the window stays on the taskbar instead of hiding |
| scoop plus the ArtCraft apps | `<app>-cli.exe` for each app | that row shows `missing` and its toggles are disabled |
| the app's own `.exe` | GUI mode only | the **Open** button is disabled for that app |

Python 3.10 works everywhere except the Codex target, which needs `tomllib` from 3.11. Everything else
is standard library.

```bash
python -m pip install pillow pystray     # the only optional pieces
python craftconnect.py --check           # what did it find?
python craftconnect.py                   # the panel
```

For the desktop shortcut, run the included script. It finds pythonw, points the icon at the generated
`.ico`, sets the working directory to this folder, then reads the `.lnk` back and tells you whether it
matches.

```bash
python make_shortcut.py                      # Desktop\Craft Connect.lnk
python make_shortcut.py --name "Craft Connect"
python make_shortcut.py --where "%APPDATA%\Microsoft\Windows\Start Menu\Programs"
python make_shortcut.py --remove
```

If you would rather do it by hand, right click `craftconnect.py`, choose *Send to* then *Desktop*, and
set the icon to `craftconnect-logo.ico` yourself.

## Icons, all from the logo

Every icon surface comes from `Orange C Connection Logo.png` in this folder. Nothing is drawn by hand
unless the PNG is missing.

| Surface | How it is made |
|---|---|
| Desktop shortcut | `craftconnect-logo.ico` with ten embedded frames (16, 20, 24, 32, 40, 48, 64, 96, 128, 256) |
| Window and taskbar | the same `.ico` through `iconbitmap`, plus an AppUserModelID so the taskbar cannot fall back to pythonw's icon |
| Tray icon | the PNG at 64 px, handed to `pystray` |
| In-window logo | the PNG at 32 px, scaled by DPI |
| Anything else | `icons/craftconnect-{16...512}.png` |

```bash
python craftconnect.py --make-icons     # rebuild everything
```

The PNG is trimmed to its artwork and padded square first. Frames below 32 px are cropped in another
4 to 10 percent so the little node stems survive at 16 px. `--make-icons` deletes the old
`craftconnect.ico` on purpose: Explorer caches icons per path, and a renamed file is the only reliable
way to force a redraw without restarting Explorer.

## Fits any screen and DPI

- Per-monitor DPI awareness is requested before Tk starts (`SetProcessDpiAwarenessContext(-4)`, falling
  back to `shcore` and then `SetProcessDPIAware`). Without it Windows bitmap-scales the window and
  everything looks soft at 125 or 150 percent.
- Tk scaling comes from the display's real DPI (`winfo_fpixels("1i")`), and every pixel dimension is
  multiplied by it: header, toggles, paddings, scrollbars, dialogs.
- The window opens at `min(1180, 95% of screen width)` by `min(830, 90% of screen height)`, centred.
  Minimum size is `min(640, screen)` by `min(480, screen)`, so it can never be forced wider than the
  display.
- The app grid sits in a canvas. Scrollbars appear only when the content actually overflows, and the
  table stretches to the visible width so columns spread instead of floating.
- The wheel scrolls whichever pane the pointer is over. Shift plus wheel scrolls the grid sideways.

## What ticking a box does

Every craft app ships a headless engine with an MCP server, for example `photocraft-cli mcp`. Ticking a
box writes that command into the harness's own config file, in that file's own format.

| Harness | File | Format | Shape written |
|---|---|---|---|
| Claude Code | `~/.claude.json` (or `$CLAUDE_CONFIG_DIR`) | JSON | `mcpServers.<app>` then `{command, args}` |
| Codex | `$CODEX_HOME/config.toml` | TOML | `[mcp_servers.<app>]` inside a marked block |
| Antigravity | `~/.gemini/config/mcp_config.json` and `~/.gemini/settings.json` | JSON | `mcpServers.<app>` |
| OpenCode | `$XDG_CONFIG_HOME/opencode/opencode.jsonc` | JSONC | `mcp.<app>` with a command array |
| Cursor | `~/.cursor/mcp.json` | JSON | `mcpServers.<app>` |
| VS Code | `$APPDATA/Code/User/mcp.json` (Insiders and VSCodium too) | JSON | `servers.<app>` with `type: stdio` |
| Zed | `$XDG_CONFIG_HOME/zed/settings.json` or `$APPDATA/Zed/settings.json` | JSONC | `context_servers.<app>` with `command.path` |
| Devin | `$APPDATA/Devin/mcp_config.json` | JSON | `mcpServers.<app>` |
| Trae | `$APPDATA/Trae/User/mcp.json` (Trae CN too) | JSON | `mcpServers.<app>` |
| Cline | `~/.cline/data/settings/cline_mcp_settings.json` and the VS Code globalStorage copy | JSON | `mcpServers.<app>` |
| Copilot CLI | `~/.copilot/mcp-config.json` | JSON | `mcpServers.<app>` with `type` and `tools: ["*"]` |
| LM Studio | `~/.lmstudio/mcp.json` | JSON | `mcpServers.<app>` |
| Qoder | `~/.qoder/mcp.json` | JSON | `mcpServers.<app>` |
| Verdent | `~/.verdent/mcp.json` | JSON | `mcpServers.<app>` |
| JetBrains Air | `$APPDATA/JetBrains/Air/mcp.json` | JSON | `mcpServers.<app>` with `type: stdio` |
| Kiro | `~/.kiro/settings/mcp.json` | JSON | `mcpServers.<app>` |

Sixteen hosts, and the shapes above are each app's own. VS Code nests under `servers`, Copilot adds
`tools`, OpenCode wants a command array, Zed wants `command.path`. I took every shape from a config the
app itself had already written. Kiro is the one exception, see Limits at the bottom.

Only Craft Connect's own entries are touched. Servers that were already there (`rea`, `linear` and
friends), plus unrelated settings like your theme, font sizes, `$schema` and comments, stay exactly as
they were. A `<file>.craftconnect.bak` is written before the first edit of each file.

Restart the harness you toggled. They all read MCP config at startup, and the banner names the ones
that changed.

## Detection, and why a column is on or off

A harness column is enabled only when that harness is really present: its config file, its config
folder, or its scoop app has to exist. Nothing is guessed from a name.

| Mark | State | Meaning |
|---|---|---|
| `[x]` | present | the config file exists and can be written |
| `[~]` | creatable | the app or config folder exists, the MCP file has not been written yet |
| `[ ]` | absent | nothing found, the file would be created from scratch |

Three ways to see the details:

- Hover any column header. A tooltip names the harness, its state, and the exact path that was tested.
- Press **Detect** in the footer, or run `--doctor`. You get every harness with its reason and every
  path checked, plus each app's CLI, its GUI, and whether its control port is free right now.
- Run `--check` for the short version. It also lists the AI tools that expose no MCP config at all,
  such as Kilo, MiMo Code, t3code, zcode, jcode, OpenWork and Orca.

`--doctor NAME` answers one question at a time, for a harness id like `vscode` or an app id like
`photocraft`.

The status line reads something like `16 registrations · 16/16 CLIs · 16/16 harnesses · root <path>`.

## Controls

- **Project root**: handed to apps that support automation roots (`--automation-read-root`,
  `--read-root`, `--root`), so an agent cannot read or write outside it. Created on first apply. Clear
  the box if you want no confinement.
- **compact tools**: adds `--compact` for the apps that accept it (LightCraft and PdfCraft). You get a
  small core set plus `tool_search` and `tool_call` instead of hundreds of definitions. LightCraft alone
  drops from 406 tools to 17.
- **Mode**: Headless, Attach, or GUI. See below.
- **find**: filters the app list as you type.
- **Test / Test all**: spawns the engine and runs a real MCP handshake (`initialize`, then
  `tools/list`), reporting the tool count. Green means a registration will work.
- **Config files**: every path, whether it exists yet, and a Reveal button.

## Three modes, and why you want all of them

Headless is right for pure agent work. The harness starts the engine, edits, saves, and closes it. No
window, no port, almost no memory.

Attach drives an app you already have open, on the port shown in the row.

GUI is the one that makes the setup feel finished. The panel starts the real app with its control
channel open and points the harness at that same window:

```
photocraft --control 8200 --control-token-file ...\craft-connect\tokens\photocraft.token
photocraft-cli mcp --bridge 8200 --control-token-file ...\craft-connect\tokens\photocraft.token
```

So an agent can place a shape while you watch, and you can move it half a second later. One document,
two pairs of hands.

Details worth knowing:

- **Open** on a row launches that window, or does nothing when it is already up. *Apply all* in GUI mode
  opens every app you have ticked.
- Every app gets its own control port starting at `8200`. The shipped defaults collide four ways:
  DesignCraft, VectorCraft, CADCraft and GridCraft all claim 7979.
- **Ports are negotiated, not assumed.** Before launching, the panel tries to bind each candidate port.
  If the preferred one is taken it walks upward, records the choice in `ports.json`, and the
  registrations follow that number. I tested this by holding 8200 open on purpose: it moved to 8201,
  the registration said 8201, and the bridge answered with 26 tools.
- PhotoCraft's channel is authenticated, so the app creates `tokens/photocraft.token` on first launch
  and the CLI reads the same file. Loopback only, nothing is exposed off the machine.
- In GUI mode the root flags are dropped. You set the read and write roots in the app's own dialog, as
  the CLI help says.
- Pressing Test while the window is closed says `GUI closed - press Open` instead of failing with a
  spawn error.
- pdfcraft, soundcraft and craft-anything have no bridge flag. GUI mode still opens their window for
  manual work but leaves them registered headless.
- If you ever delete `ports.json` after writing GUI registrations, the configs still point at the old
  port until the next Apply all. The log warns you when a port is renegotiated.

### What the sixteen apps actually do

I opened every one with `--guitest`, which launches the app, checks its control port, and probes the
harness command twice: once with the window up, once with it closed. That second probe is the honest
test. A bridge that quietly starts a headless engine answers both times, and looks fine until you notice
your edits never reach the window.

| App | Window opens | Control port | Harness reaches that window |
|---|---|---|---|
| PhotoCraft | yes | 8200 | not confirmed, the CLI returns the same 26 tools with the window closed |
| LightCraft | yes | 8201 | yes, 628 tools bridged against 28 headless |
| VectorCraft | yes | 8202 | yes, answers only while the window is up |
| DesignCraft | yes | 8203 | yes |
| FigCraft | yes | 8204 | yes |
| EffectCraft | yes | 8205 | not confirmed, 36 tools either way |
| FilmCraft | yes | none | no channel opened |
| SoundCraft | yes | 8207 | none, the CLI has no bridge flag |
| WordCraft | yes | 8208 | not confirmed, 17 tools either way |
| DeckCraft | yes | 8209 | yes |
| GridCraft | yes | 8210 | yes |
| PdfCraft | yes | none | none, the CLI has no bridge flag |
| CADCraft | yes | 8212 | yes |
| MaterialCraft | yes | 8213 | yes |
| TextureCraft | yes | 8214 | yes |
| Craft Anything | yes | none | none, the CLI has no bridge flag |

So GUI mode is genuinely useful for nine of them, opens a window for all sixteen, and falls back to
headless where the app cannot be driven. Run `python craftconnect.py --guitest` yourself after an app
update; it takes a few minutes and prints this table for your machine.

## System tray

Minimising or clicking X hides the window to the tray. Right click the tray icon for Show, Apply all,
Re-check configs, Test all, and Quit. The panel is a configuration tool, and the harnesses spawn their
own servers, so closing it never breaks a registration.

## Undo

Untick the box. Or delete the `>>> craftconnect` block from the TOML or JSONC file. Or restore the
`.craftconnect.bak` copy that sits next to each config.

## Command line

```
python craftconnect.py                  # the window
python craftconnect.py --check          # detection, provenance, registrations, ports
python craftconnect.py --doctor [NAME]  # why a harness or app is on or off
python craftconnect.py --guitest [APP]  # open each app, test its control channel, close it
python craftconnect.py --gui photocraft # open the window with its control channel
python craftconnect.py --probe photocraft [--compact]
python craftconnect.py --selftest       # every writer exercised on temp files
python craftconnect.py --make-icons     # rebuild icons from the logo
```

`--selftest` only touches its own `tempfile` directory. It builds fake Claude, Codex, OpenCode, VS Code,
Zed, Copilot and Cline files, registers two apps, checks the entries and the untouched neighbours,
removes them again, and confirms nothing is left behind. Fifty assertions at the moment.

## Proof it drives the apps

`make_avatar.py` is a small MCP client. It spawns `photocraft-cli mcp`, finishes the handshake, and
draws a 512 by 512 avatar from 21 `shape.create` commands, then saves `~/craft-work/avatar.png`. Same
server that Craft Connect registers, driven the way a harness drives it.

```
python make_avatar.py
# connected: photocraft 0.21.0 / completed=21 failed=0 / layers now: 22
```

## Built on the ArtCraft suite

Craft Connect is only the connector. The apps behind these toggles are the work of
[**storytold**](https://github.com/storytold): sixteen craft engines, one command registry each, an MCP
server on every one. Without that suite this panel would have nothing to connect.

[![ArtCraft](https://img.shields.io/badge/ArtCraft-by%20storytold-f96b0d?style=flat-square)](https://github.com/storytold)
[![PhotoCraft](https://img.shields.io/badge/PhotoCraft-storytold-f96b0d?style=flat-square)](https://github.com/storytold/photocraft)

| App | Source |
|---|---|
| ArtCraft suite | [storytold/artcraft](https://github.com/storytold/artcraft) |
| PhotoCraft | [storytold/photocraft](https://github.com/storytold/photocraft) |
| LightCraft | [storytold/lightcraft](https://github.com/storytold/lightcraft) |
| VectorCraft | [storytold/vectorcraft](https://github.com/storytold/vectorcraft) |
| DesignCraft | [storytold/designcraft](https://github.com/storytold/designcraft) |
| FigCraft | [storytold/figcraft](https://github.com/storytold/figcraft) |
| EffectCraft | [storytold/effectcraft](https://github.com/storytold/effectcraft) |
| FilmCraft | [storytold/filmcraft](https://github.com/storytold/filmcraft) |
| SoundCraft | [storytold/soundcraft](https://github.com/storytold/soundcraft) |
| WordCraft | [storytold/wordcraft](https://github.com/storytold/wordcraft) |
| DeckCraft | [storytold/deckcraft](https://github.com/storytold/deckcraft) |
| GridCraft | [storytold/gridcraft](https://github.com/storytold/gridcraft) |
| PdfCraft | [storytold/pdfcraft](https://github.com/storytold/pdfcraft) |
| CADCraft | [storytold/cadcraft](https://github.com/storytold/cadcraft) |
| MaterialCraft | [storytold/materialcraft](https://github.com/storytold/materialcraft) |
| TextureCraft | [storytold/texturecraft](https://github.com/storytold/texturecraft) |
| Craft Anything | [storytold/craft-anything](https://github.com/storytold/craft-anything) |

All sixteen links were checked and resolve. Craft Connect is not affiliated with the ArtCraft project,
it simply talks to its command line interfaces. If an app of theirs misbehaves, report it there, not
here.

## Privacy: exactly what it reads and writes

Reads: the scoop root, the harness config files in the table above, and `root_path` from
`~/.config/scoop/config.json`.

Writes: craft entries in those configs, a `<file>.craftconnect.bak` before the first edit of each, and
`icons/` when you rebuild artwork. That's it.

Never: no telemetry, no outbound network calls, no reading of API keys or tokens from your configs, and
no printing of their values. The only socket is the loopback control channel between an app and its CLI.

`tokens/<app>.token` is a local credential the app creates. It is excluded from git and safe to delete,
because the app makes a new one on the next launch.

## Licence and credits

MIT, with one added term: **attribution**. If you use this in a commercial product, a paid service, or
anything you distribute, credit the original author somewhere visible, for example:

```
Craft Connect by Adib Sadman (@AdibSadman192)
https://github.com/AdibSadman192
```

Personal and non-commercial use needs no announcement, though a link is always welcome. The full text is
in [LICENSE](LICENSE). Note that GitHub shows this as "Other" rather than "MIT" because of the extra
term. If you would rather have the MIT badge, move the attribution paragraph into a NOTICE file and keep
LICENSE as plain MIT.

Written by Adib Sadman, [@AdibSadman192](https://github.com/AdibSadman192). Issues and pull requests are
welcome.

## Community

- [CONTRIBUTING.md](CONTRIBUTING.md) covers setup, how to add a harness or an app, and the house style.
- [SECURITY.md](SECURITY.md) explains private reporting for anything sensitive.
- [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) is short and boring on purpose.
- [CHANGELOG.md](CHANGELOG.md) records what changed and when.

## Limits

- Kiro's `~/.kiro/settings/mcp.json` is the only path taken from documentation rather than from a file
  Kiro had already written.
- The VS Code fork scan looks in `%APPDATA%` only, and stops at six forks.
- GUI mode is measured, not assumed. Nine apps take a bridge into their window, three answer the same
  with the window closed (PhotoCraft, EffectCraft, WordCraft) and look headless, four open a window with
  no usable channel. The table above is the result of running `--guitest`, and the command can be re-run
  after any app update. For the three that fall back, the panel now warns when you apply in GUI mode and
  marks them `bridge unconfirmed` in `--doctor`.
- PhotoCraft's fallback is not a token problem. I tried the inline `--control-token` form with a matching
  token, a wrong token, the token file, and the app closed. Every combination answered with the same 26
  tools, which means the CLI never reached the window. That is upstream behaviour in build 0.21.0, and it
  needs a fix there.
- Zed and VS Code shapes match their existing files, but I did not restart either editor to watch it
  pick up the server.
- A JSONC file that the standard parser cannot read after comments and trailing commas are stripped is
  refused, not rewritten.
- Kilo, MiMo Code, t3code, zcode, jcode, OpenWork and Orca are detected and listed, but they expose no
  MCP config file, so there is nothing to write.
- Attach mode uses each app's shipped default port, and four apps share 7979. Bridge one GUI at a time.
  GUI mode avoids this with its own ports.
- Rebuilding icons renames the `.ico`, which breaks a shortcut made against the old name. Point the
  shortcut at `craftconnect-logo.ico` once and it stays valid.
