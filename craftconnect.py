#!/usr/bin/env python3
"""
Craft Connect - click to attach ArtCraft craft apps to the AI harnesses you use.

Every craft app ships a headless engine with an MCP server:

    photocraft-cli mcp          vectorcraft-cli mcp        pdfcraft-cli mcp
    ... and the same for the other 13.

This window registers those servers in each harness's own config file, using
that file's own format, and can run the MCP handshake to prove it works. Only
Craft Connect's own entries are ever touched:

    Claude Code   ~/.claude.json (or $CLAUDE_CONFIG_DIR)   JSON   mcpServers.<app>
    Codex         ~/.codex/config.toml (or $CODEX_HOME)    TOML   [mcp_servers.<app>]
    Antigravity   ~/.gemini/...                            JSON   mcpServers.<app>
    OpenCode      $XDG_CONFIG_HOME/opencode/opencode.jsonc JSONC  mcp.<app>
    Cursor        ~/.cursor/mcp.json                       JSON   mcpServers.<app>
    VS Code       $APPDATA/Code/User/settings.json         JSONC  mcp.servers.<app>
    Zed           $XDG_CONFIG_HOME/zed/settings.json       JSONC  context_servers.<app>

Nothing is hardcoded to a drive: the scoop root comes from $SCOOP, the scoop shim
on PATH, ~/.config/scoop/config.json or a drive scan, and every harness path is
derived from the standard environment variables for that harness. A
"<file>.craftconnect.bak" is made before the first edit of each file.

Commands:
    python craftconnect.py                  open the window
    python craftconnect.py --check          what is installed, what is registered, and how each path was found
    python craftconnect.py --probe APP      MCP handshake test for one app (writes nothing)
    python craftconnect.py --selftest       exercise the writers against temp files
    python craftconnect.py --make-icons     rebuild icons from the logo PNG
    python craftconnect.py --smoke          build the window, then exit
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

IS_WIN = os.name == "nt"
NO_WINDOW = 0x08000000 if IS_WIN else 0
APP_DIR = Path(__file__).resolve().parent
ICON_DIR = APP_DIR / "icons"
LOGO_SRC = APP_DIR / "Orange C Connection Logo.png"
ICO_FILE = APP_DIR / "craftconnect-logo.ico"

BEGIN = ">>> craftconnect"
END = "<<< craftconnect"

# Deep greys plus the logo's orange. No blue anywhere.
P = {
    "bg": "#111111",
    "surface": "#181818",
    "surface2": "#1e1e1e",
    "surface3": "#242424",
    "border": "#2c2c2c",
    "line": "#383838",
    "text": "#e8e8e8",
    "muted": "#8d8d8d",
    "dim": "#5f5f5f",
    "accent": "#f96b0d",
    "accent_hover": "#ff7f2a",
    "accent_dark": "#b34a06",
    "ok": "#5ec27a",
    "warn": "#d9a441",
    "err": "#e05252",
}


# --------------------------------------------------------------------------- #
# Where things live - detected, never assumed
# --------------------------------------------------------------------------- #


def home() -> Path:
    return Path(os.environ.get("CRAFT_CONNECT_HOME") or Path.home())


HOME = home()


def _existing(paths):
    for p in paths:
        try:
            if p and p.exists():
                return p
        except OSError:
            continue
    return paths[0] if paths else None


def mount_roots():
    """Every fixed local drive. Never removable, never network shares."""
    roots = []
    if IS_WIN:
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            mask = kernel32.GetLogicalDrives()
            for i, letter in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
                if not mask & (1 << i):
                    continue
                root = f"{letter}:/"
                if kernel32.GetDriveTypeW(ctypes.c_wchar_p(root)) == 3:  # DRIVE_FIXED
                    roots.append(Path(root))
        except Exception:
            pass
    return roots or [Path("/")]


def detect_scoop():
    """Find scoop's root, with the reason, so a fresh machine still works."""
    candidates = []

    env = os.environ.get("SCOOP")
    if env:
        candidates.append((Path(env), "from $SCOOP"))

    which = shutil.which("scoop")
    if which:
        for parent in Path(which).parents:
            if parent.name.lower() == "shims":
                candidates.append((parent.parent, f"from scoop on PATH ({which})"))
                break

    cfg_home = Path(os.environ.get("XDG_CONFIG_HOME") or (HOME / ".config"))
    for cfg in (cfg_home / "scoop" / "config.json", HOME / ".config" / "scoop" / "config.json"):
        try:
            data = json.loads(cfg.read_text(encoding="utf-8-sig"))
            root = data.get("root_path") or data.get("rootPath")
            if root:
                candidates.append((Path(root), f"from {cfg}"))
        except Exception:
            pass

    for p in (
        HOME / "scoop",
        Path(os.environ.get("USERPROFILE") or HOME) / "scoop",
        Path(os.environ.get("ProgramData") or "C:/ProgramData") / "scoop",
        Path("C:/scoop"),
    ):
        candidates.append((p, "common location"))

    for root in mount_roots():
        for sub in ("scoop", "Applications/scoop", "Apps/scoop", "Tools/scoop"):
            candidates.append((root / sub, "drive scan"))

    for path, why in candidates:
        try:
            if (path / "shims").is_dir() or (path / "apps").is_dir():
                return path, why
        except OSError:
            continue
    return HOME / "scoop", "not found (would be created)"


SCOOP, SCOOP_SOURCE = detect_scoop()


def config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or (HOME / ".config"))


def appdata() -> Path:
    return Path(os.environ.get("APPDATA") or (HOME / "AppData" / "Roaming"))


# --------------------------------------------------------------------------- #
# Icons, all derived from the logo PNG
# --------------------------------------------------------------------------- #


def load_logo():
    """The logo, trimmed to its artwork and padded square. None without Pillow."""
    try:
        from PIL import Image
    except Exception:
        return None
    if not LOGO_SRC.exists():
        return None
    try:
        im = Image.open(LOGO_SRC).convert("RGBA")
    except Exception:
        return None
    bbox = im.getchannel("A").getbbox()
    if bbox:
        im = im.crop(bbox)
    side = max(im.size)
    pad = max(2, int(side * 0.04))
    canvas = Image.new("RGBA", (side + 2 * pad, side + 2 * pad), (0, 0, 0, 0))
    canvas.paste(im, ((canvas.width - im.width) // 2, (canvas.height - im.height) // 2), im)
    return canvas


def logo_image(size, zoom=1.0):
    """The logo at `size` px. `zoom` crops in, so tiny sizes keep the mark readable."""
    im = load_logo()
    if im is not None:
        from PIL import Image

        if zoom > 1.0:
            w, h = im.size
            dx, dy = int(w * (1 - 1 / zoom) / 2), int(h * (1 - 1 / zoom) / 2)
            im = im.crop((dx, dy, w - dx, h - dy))
        return im.resize((size, size), Image.LANCZOS)
    return drawn_logo(size)


def drawn_logo(size=64):
    """Fallback mark when the PNG or Pillow is missing: the same idea, drawn."""
    try:
        from PIL import Image, ImageDraw
    except Exception:
        return None
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([1, 1, size - 2, size - 2], radius=int(size * 0.22), fill=(5, 4, 5, 255))
    r = int(size * 0.30)
    d.ellipse(
        [int(size * 0.16), int(size * 0.30), int(size * 0.16) + 2 * r, int(size * 0.30) + 2 * r],
        outline=(249, 107, 13, 255),
        width=max(2, size // 12),
    )
    return img


ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)


def set_app_id(app_id="CraftConnect.Panel"):
    """Without this the taskbar borrows pythonw's icon instead of ours."""
    if not IS_WIN:
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except Exception:
        pass


def make_icons(verbose=True):
    """Write the .ico the shortcut uses plus a PNG set for anything else."""
    if load_logo() is None:
        if verbose:
            print("logo PNG or Pillow unavailable; nothing generated")
        return False
    ICON_DIR.mkdir(parents=True, exist_ok=True)
    for s in ICO_SIZES + (512,):
        logo_image(s, _zoom_for(s)).save(ICON_DIR / f"craftconnect-{s}.png")
    base = logo_image(256)
    ico_sizes = [(s, s) for s in ICO_SIZES]
    base.save(ICO_FILE, sizes=ico_sizes)
    for stale in (APP_DIR / "craftconnect.ico", ICON_DIR / "craftconnect.ico"):
        try:
            stale.unlink()
        except OSError:
            pass
    if verbose:
        print(f"icons written from {LOGO_SRC.name}")
        print(f"  {ICO_FILE}  (frames: {', '.join(str(s) for s in ICO_SIZES)})")
        print(f"  {ICON_DIR}\\craftconnect-*.png")
    return True


def _zoom_for(size):
    """Crop in a little at small sizes; the node stems vanish otherwise."""
    if size <= 24:
        return 1.10
    if size <= 48:
        return 1.04
    return 1.0


def ico_frames(path=ICO_FILE):
    """Which sizes an .ico really contains (Windows uses these when scaling)."""
    try:
        from PIL import Image

        with Image.open(path) as im:
            return sorted(getattr(im, "ico", None).sizes() if hasattr(im, "ico") else [im.size])
    except Exception:
        return []


# --------------------------------------------------------------------------- #
# The apps
# --------------------------------------------------------------------------- #


class App:
    """One craft app, described by the flags its CLI actually accepts."""

    __slots__ = ("id", "label", "roots", "bridge", "port", "compact", "token", "bridge_ok")

    def __init__(self, id, label, roots=None, bridge=None, port=7979, compact=False,
                 token=False, bridge_ok=True):
        self.id = id
        self.label = label
        # roots: None | "automation" | "rw" (--read/write-root) | "root" (--root)
        self.roots = roots
        # bridge: None | "connect" (--connect ADDR) | "bridge" (--bridge PORT) | "attach" (--attach PORT)
        self.bridge = bridge
        self.port = port
        self.compact = compact  # accepts --compact (fewer tool definitions in context)
        self.token = token  # the app's control channel wants a token file
        # Measured with --guitest: False means the CLI answers the same with the window
        # closed, so --bridge is being served by a headless engine instead.
        self.bridge_ok = bridge_ok

    @property
    def has_bridge(self):
        return self.bridge is not None


APPS = [
    App("photocraft", "PhotoCraft", roots="automation", bridge="bridge", port=7999, token=True,
        bridge_ok=False),
    App("lightcraft", "LightCraft", bridge="connect", port=7980, compact=True),
    App("vectorcraft", "VectorCraft", roots="automation", bridge="connect", port=7979),
    App("designcraft", "DesignCraft", roots="automation", bridge="connect", port=7979),
    App("figcraft", "FigCraft", bridge="attach", port=47800),
    App("effectcraft", "EffectCraft", roots="automation", bridge="bridge", port=9877,
        bridge_ok=False),
    App("filmcraft", "FilmCraft", bridge="bridge", port=9876),
    App("soundcraft", "SoundCraft"),
    App("wordcraft", "WordCraft", roots="automation", bridge="connect", port=7981,
        bridge_ok=False),
    App("deckcraft", "DeckCraft", roots="automation", bridge="connect", port=7990),
    App("gridcraft", "GridCraft", bridge="connect", port=7979),
    App("pdfcraft", "PdfCraft", roots="root", compact=True),
    App("cadcraft", "CADCraft", bridge="connect", port=7979),
    App("materialcraft", "MaterialCraft", roots="rw", bridge="bridge", port=7878),
    App("texturecraft", "TextureCraft", roots="rw", bridge="bridge", port=7878),
    App("craft-anything", "Craft Anything"),
]

APP_BY_ID = {a.id: a for a in APPS}


def exe_path(app):
    """Where the app's headless CLI lives, whatever the scoop root is."""
    for cand in (
        SCOOP / "shims" / f"{app.id}-cli.exe",
        SCOOP / "shims" / f"{app.id}-cli",
        SCOOP / "apps" / app.id / "current" / f"{app.id}-cli.exe",
        SCOOP / "apps" / app.id / "current" / f"{app.id}-cli",
        HOME / "scoop" / "shims" / f"{app.id}-cli.exe",
    ):
        try:
            if cand.exists():
                return cand
        except OSError:
            continue
    found = shutil.which(f"{app.id}-cli") or shutil.which(f"{app.id}-cli.exe")
    return Path(found) if found else None


# --- GUI mode ----------------------------------------------------------------
# `photocraft --control <port>` opens the real app and serves the control channel;
# `photocraft-cli mcp --bridge <port>` then drives that same window. So a harness
# and your hands work on one document instead of two engines.

GUI_BASE_PORT = 8200
PORT_FILE = APP_DIR / "ports.json"
DETACHED = 0x00000008 | 0x00000200 if IS_WIN else 0  # DETACHED_PROCESS | NEW_GROUP


def port_free(port, host="127.0.0.1"):
    """True only when nothing answers there and we could bind it ourselves.

    A bind test alone lies on Windows: an app that opened the port with SO_REUSEADDR
    still lets us bind, so we would call an occupied port free.
    """
    import socket

    try:
        with socket.create_connection((host, int(port)), timeout=0.3):
            return False  # something answered
    except OSError:
        pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind((host, int(port)))
        return True
    except OSError:
        return False


def load_ports():
    try:
        data = json.loads(PORT_FILE.read_text(encoding="utf-8"))
        return {k: int(v) for k, v in data.items() if isinstance(v, (int, str)) and str(v).isdigit()}
    except Exception:
        return {}


PORTS = load_ports()


def save_ports():
    try:
        PORT_FILE.write_text(json.dumps(PORTS, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except Exception:
        pass


def gui_exe(app):
    """The windowed binary, next to the CLI in the same scoop app."""
    for cand in (
        SCOOP / "apps" / app.id / "current" / f"{app.id}.exe",
        HOME / "scoop" / "apps" / app.id / "current" / f"{app.id}.exe",
    ):
        try:
            if cand.exists():
                return cand
        except OSError:
            continue
    found = shutil.which(f"{app.id}.exe") or shutil.which(app.id)
    return Path(found) if found else None


def gui_port(app):
    """The control port this app is registered against, negotiated and remembered.

    Stable across runs (ports.json) because the chosen port is baked into every
    harness config; renegotiated only when it is actually taken.
    """
    return int(PORTS.get(app.id) or (GUI_BASE_PORT + APPS.index(app)))


def pick_port(app, log=None):
    """First free port from this app's preference upwards; remembers the choice."""
    want = gui_port(app)
    for port in range(want, want + 60):
        if port_free(port):
            if port != want:
                PORTS[app.id] = port
                save_ports()
                if log:
                    log(f"{app.label}: control port {want} is taken, using {port} "
                        "(Apply all rewrites the registrations)")
            return port
    if log:
        log(f"! {app.label}: no free port in {want}..{want + 59}")
    return want


def token_file(app):
    return APP_DIR / "tokens" / f"{app.id}.token"


def stop_gui(app, hard=False):
    """Ask the window to close, then insist. Only used by the GUI test."""
    if not IS_WIN:
        return
    cmd = ["taskkill", "/IM", f"{app.id}.exe", "/T"]
    if hard:
        cmd.insert(1, "/F")
    try:
        subprocess.run(cmd, capture_output=True, timeout=20, creationflags=NO_WINDOW)
    except Exception:
        pass


def gui_running(app):
    if not IS_WIN:
        return False
    name = f"{app.id}.exe"
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {name}", "/NH"],
            capture_output=True, text=True, timeout=10, creationflags=NO_WINDOW,
        ).stdout
    except Exception:
        return False
    return name.lower() in out.lower()


def launch_gui(app, log=None):
    """Start the app with its control channel open. Returns (port, problem)."""
    exe = gui_exe(app)
    if not exe:
        return None, f"{app.label}: no GUI binary installed"
    if gui_running(app):
        return gui_port(app), None
    port = pick_port(app, log)
    argv = [str(exe), "--control", str(port)]
    if app.token:
        token_file(app).parent.mkdir(parents=True, exist_ok=True)
        argv += ["--control-token-file", str(token_file(app))]
    try:
        subprocess.Popen(argv, cwd=str(exe.parent), close_fds=True,
                         creationflags=DETACHED)
    except Exception as e:
        return None, f"{app.label}: cannot start the GUI ({e})"
    if log:
        log(f"opened {app.label} on control port {port}"
            + (" (token file created by the app)" if app.token else ""))
    return port, None


def mcp_args(app, mode, root, port, compact=False, log=None):
    """The argv after the executable, for one app in the chosen mode."""
    args = ["mcp"]
    if mode == "gui":
        if app.has_bridge:
            p = str(gui_port(app))
            if app.bridge == "connect":
                args += ["--connect", f"127.0.0.1:{p}"]
            elif app.bridge == "bridge":
                args += ["--bridge", p]
            else:
                args += ["--attach", p]
            if app.token:
                args += ["--control-token-file", str(token_file(app))]
            if not app.bridge_ok and log:
                log(f"! {app.label}: this build answers --bridge headless, so the window "
                    "will not follow. Use Headless mode for predictable results")
        elif log:
            log(f"... {app.label} has no bridge flag; left headless, use its window by hand")
    if mode == "attach":
        if app.has_bridge:
            p = str(port or app.port).strip() or str(app.port)
            if app.bridge == "connect":
                args += ["--connect", f"127.0.0.1:{p}"]
            elif app.bridge == "bridge":
                args += ["--bridge", p]
            else:
                args += ["--attach", p]
        elif log:
            log(f"... {app.label} has no attach bridge; registered headless instead")
    if compact and app.compact:
        args.append("--compact")
    if mode == "headless" and app.roots and root:
        if app.roots == "automation":
            args += ["--automation-read-root", root, "--automation-write-root", root]
        elif app.roots == "rw":
            args += ["--read-root", root, "--write-root", root]
        elif app.roots == "root":
            args += ["--root", root]
    return args


# --------------------------------------------------------------------------- #
# The harnesses
# --------------------------------------------------------------------------- #


class Client:
    """A harness: where its config lives, what shape it wants, how to spot it."""

    def __init__(self, key, label, kind, paths, style="plain", prefix=(), detect=(), scoop=(),
                 root_key="mcpServers", short=None):
        self.key = key
        self.label = label
        self.kind = kind  # "json" | "jsonc" | "toml"
        self.paths = [Path(p) for p in paths]
        self.style = style  # "plain" | "opencode" | "vscode" | "zed" | "copilot"
        self.prefix = tuple(prefix)  # key chain for jsonc targets
        self.root_key = root_key  # object holding the servers in plain JSON
        self.short = short or label  # column header, kept narrow
        self.detect = [Path(p) for p in detect]
        self.scoop = tuple(scoop)

    @property
    def installed(self):
        try:
            if any(p.exists() for p in self.paths) or any(p.exists() for p in self.detect):
                return True
            return any((SCOOP / "apps" / name).exists() for name in self.scoop)
        except OSError:
            return False

    def status(self):
        """Why this column is usable or not: (state, human reason)."""
        for p in self.paths:
            try:
                if p.exists():
                    return "present", f"config found: {p}"
            except OSError:
                pass
        for p in self.detect:
            try:
                if p.exists():
                    return "creatable", f"{p} exists, config not written yet"
            except OSError:
                pass
        for name in self.scoop:
            try:
                if (SCOOP / "apps" / name).exists():
                    return "creatable", f"scoop app '{name}' installed, config not written yet"
            except OSError:
                pass
        return "absent", f"nothing found; would create {self.paths[0]}"


def build_clients():
    cfg, ad = config_home(), appdata()

    claude_dir = os.environ.get("CLAUDE_CONFIG_DIR")
    claude_file = (Path(claude_dir) / ".claude.json") if claude_dir else (HOME / ".claude.json")

    codex_home = Path(os.environ.get("CODEX_HOME") or (HOME / ".codex"))

    opencode_file = _existing(
        [
            cfg / "opencode" / "opencode.jsonc",
            cfg / "opencode" / "opencode.json",
            cfg / "opencode" / "config.json",
        ]
    )

    # VS Code keeps MCP servers in their own mcp.json ({"servers": {...}}), not settings.json,
    # and a portable install keeps that profile beside the exe instead of in %APPDATA%.
    vsc_candidates = [
        ad / "Code" / "User" / "mcp.json",
        ad / "Code - Insiders" / "User" / "mcp.json",
        ad / "VSCodium" / "User" / "mcp.json",
    ]
    portable = os.environ.get("VSCODE_PORTABLE")
    if portable:
        base = Path(portable)
        vsc_candidates = [
            base / "data" / "user-data" / "User" / "mcp.json",
            base / "user-data" / "User" / "mcp.json",
        ] + vsc_candidates
    vsc = _existing(vsc_candidates)

    zed = _existing(
        [
            cfg / "zed" / "settings.json",
            ad / "Zed" / "settings.json",
        ]
    )

    kiro_home = Path(os.environ.get("KIRO_HOME") or (HOME / ".kiro"))

    extra = []
    windsurf = HOME / ".codeium" / "windsurf" / "mcp_config.json"
    if windsurf.exists():
        extra.append(Client("windsurf", "Windsurf", "json", [windsurf], short="Wind",
                            detect=[windsurf.parent]))

    return [
        Client("claude", "Claude Code", "json", [claude_file],
               detect=[claude_file.parent / ".claude"], scoop=["claude-code"]),
        Client("codex", "Codex", "toml", [codex_home / "config.toml"],
               detect=[codex_home], scoop=["codex"]),
        Client(
            "antigravity", "Antigravity", "json",
            [HOME / ".gemini" / "config" / "mcp_config.json", HOME / ".gemini" / "settings.json"],
            detect=[HOME / ".gemini"], scoop=["antigravity", "antigravity-cli", "antigravity-ide"],
        ),
        Client("opencode", "OpenCode", "jsonc", [opencode_file],
               style="opencode", prefix=("mcp",),
               detect=[cfg / "opencode"], scoop=["opencode2", "opencode2-desktop"]),
        Client("cursor", "Cursor", "json", [HOME / ".cursor" / "mcp.json"],
               detect=[HOME / ".cursor"], scoop=["cursor-latest", "cursor"]),
        Client("vscode", "VS Code", "json", [vsc],
               style="vscode", root_key="servers", short="VSCode",
               detect=[vsc.parent], scoop=["vscode-insiders", "vscodium", "vscode"]),
        Client("zed", "Zed", "jsonc", [zed],
               style="zed", prefix=("context_servers",),
               detect=[zed.parent], scoop=["zed"]),
        Client("devin", "Devin", "json", [ad / "Devin" / "mcp_config.json"],
               detect=[ad / "Devin"], scoop=["devin"]),
        Client("trae", "Trae", "json",
               [ad / "Trae" / "User" / "mcp.json", ad / "Trae CN" / "User" / "mcp.json"],
               detect=[ad / "Trae", ad / "Trae CN"], scoop=["trae", "trae-cn"]),
        Client("cline", "Cline", "json",
               [HOME / ".cline" / "data" / "settings" / "cline_mcp_settings.json",
                ad / "Code" / "User" / "globalStorage" / "saoudrizwan.claude-dev"
                / "settings" / "cline_mcp_settings.json"],
               detect=[HOME / ".cline",
                       ad / "Code" / "User" / "globalStorage" / "saoudrizwan.claude-dev"]),
        Client("copilot", "Copilot CLI", "json", [HOME / ".copilot" / "mcp-config.json"],
               style="copilot", short="Copilot",
               detect=[HOME / ".copilot"], scoop=["copilot-cli", "github-copilot"]),
        Client("lmstudio", "LM Studio", "json", [HOME / ".lmstudio" / "mcp.json"],
               short="LM Studio", detect=[HOME / ".lmstudio"], scoop=["lmstudio"]),
        Client("qoder", "Qoder", "json", [HOME / ".qoder" / "mcp.json"],
               detect=[HOME / ".qoder"], scoop=["qoder"]),
        Client("verdent", "Verdent", "json", [HOME / ".verdent" / "mcp.json"],
               detect=[HOME / ".verdent"], scoop=["verdent"]),
        Client("air", "JetBrains Air", "json", [ad / "JetBrains" / "Air" / "mcp.json"],
               style="vscode", short="Air",
               detect=[ad / "JetBrains" / "Air"], scoop=["air"]),
        Client("kiro", "Kiro", "json", [kiro_home / "settings" / "mcp.json"],
               detect=[kiro_home], scoop=["kiro", "kiro-cli"]),
    ] + extra + code_fork_clients(ad, {"Code", "Code - Insiders", "VSCodium", "Trae",
                                       "Trae CN", "Zed", "Cursor", "Qoder", "Kilo"})


def code_fork_clients(ad, skip):
    """Other VS Code forks that keep servers in their own User/mcp.json."""
    out = []
    try:
        for entry in sorted(ad.iterdir()):
            if len(out) >= 6:
                break
            if not entry.is_dir() or entry.name in skip:
                continue
            cand = entry / "User" / "mcp.json"
            if not cand.exists():
                continue
            try:
                data = json.loads(cand.read_text(encoding="utf-8-sig"))
            except Exception:
                continue
            if not isinstance(data, dict) or not isinstance(data.get("servers"), dict):
                continue
            label = entry.name.replace(" - Insiders", " Insiders")
            out.append(Client(f"fork:{entry.name}", label, "json", [cand],
                              style="vscode", root_key="servers",
                              short=label[:8], detect=[entry], scoop=[]))
    except OSError:
        pass
    return out


CLIENTS = build_clients()
CLIENT_BY_KEY = {c.key: c for c in CLIENTS}
CRAFT_IDS = {a.id for a in APPS}


# --------------------------------------------------------------------------- #
# Reading existing configs
# --------------------------------------------------------------------------- #


def jsonc_to_json(text):
    """Strip comments and trailing commas so the standard parser can read JSONC."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    kept = [ln for ln in text.splitlines() if not ln.lstrip().startswith("//")]
    return re.sub(r",(\s*[}\]])", r"\1", "\n".join(kept))


def read_json_names(path, root_key="mcpServers"):
    try:
        data = json.loads(jsonc_to_json(Path(path).read_text(encoding="utf-8-sig")))
    except Exception:
        return set()
    srv = data.get(root_key) if isinstance(data, dict) else None
    return set(srv) if isinstance(srv, dict) else set()


def read_jsonc_names(path, prefix):
    try:
        data = json.loads(jsonc_to_json(Path(path).read_text(encoding="utf-8-sig")))
    except Exception:
        return set()
    node = data
    for key in prefix:
        if not isinstance(node, dict):
            return set()
        node = node.get(key)
    return set(node) if isinstance(node, dict) else set()


def read_toml_names(path):
    try:
        import tomllib
    except ImportError:
        return set()
    try:
        data = tomllib.loads(Path(path).read_text(encoding="utf-8-sig"))
    except Exception:
        return set()
    srv = data.get("mcp_servers") if isinstance(data, dict) else None
    return set(srv) if isinstance(srv, dict) else set()


def registered_craft(client):
    names = set()
    for p in client.paths:
        if client.kind == "toml":
            names |= read_toml_names(p)
        elif client.kind == "jsonc":
            names |= read_jsonc_names(p, client.prefix)
        else:
            names |= read_json_names(p, client.root_key)
    return names & CRAFT_IDS


# --------------------------------------------------------------------------- #
# Writing configs
# --------------------------------------------------------------------------- #


def backup(path):
    bak = path.with_name(path.name + ".craftconnect.bak")
    if path.exists() and not bak.exists():
        shutil.copy2(path, bak)
        return bak
    return None


def write_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    backup(path)
    bom, nl = False, "\n"
    if path.exists():
        head = path.read_bytes()[:4096]
        bom = head.startswith(b"\xef\xbb\xbf")
        if b"\r\n" in head:
            nl = "\r\n"
    body = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\n", nl)
    data = body.encode("utf-8")
    if bom:
        data = b"\xef\xbb\xbf" + data
    with open(path, "wb") as f:
        f.write(data)


def entry_for(style, exe, args):
    if style == "opencode":
        return {"type": "local", "command": [exe, *args], "enabled": True}
    if style == "vscode":
        return {"type": "stdio", "command": exe, "args": list(args)}
    if style == "zed":
        return {"source": "custom", "command": {"path": exe, "args": list(args), "env": {}}}
    if style == "copilot":
        return {"type": "stdio", "command": exe, "args": list(args), "tools": ["*"]}
    return {"command": exe, "args": list(args)}


def write_json_entries(path, desired, style="plain", root_key="mcpServers"):
    """Add/remove only craft entries in the servers object, leaving everything else alone."""
    data = {}
    if path.exists():
        try:
            data = json.loads(jsonc_to_json(path.read_text(encoding="utf-8-sig")))
        except Exception as e:
            raise RuntimeError(f"{path.name}: not readable JSON ({e}); nothing written")
        if not isinstance(data, dict):
            raise RuntimeError(f"{path.name}: top level is not an object; nothing written")
    srv = data.get(root_key)
    if srv is None:
        srv = data[root_key] = {}
    if not isinstance(srv, dict):
        raise RuntimeError(f"{path.name}: {root_key} is not an object; nothing written")
    for app in APPS:
        if app.id in desired:
            exe, args = desired[app.id]
            srv[app.id] = entry_for(style, exe, args)
        else:
            srv.pop(app.id, None)
    write_text(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def toml_str(value):
    return json.dumps(str(value), ensure_ascii=False)


def toml_block(desired):
    if not desired:
        return []
    lines = [f"# {BEGIN} - managed by Craft Connect, rewritten on every apply"]
    for app in APPS:
        if app.id not in desired:
            continue
        exe, args = desired[app.id]
        lines += [
            "",
            f"[mcp_servers.{app.id}]",
            f"command = {toml_str(exe)}",
            "args = [" + ", ".join(toml_str(a) for a in args) + "]",
            "startup_timeout_sec = 30",
        ]
    lines += ["", f"# {END}"]
    return lines


def strip_marked_block(text):
    out, skipping = [], False
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#") and BEGIN in line:
            skipping = True
            continue
        if stripped.startswith("#") and END in line:
            skipping = False
            continue
        if not skipping:
            out.append(line)
    return "\n".join(out) + ("\n" if out else "")


def write_toml_block(path, desired):
    text = path.read_text(encoding="utf-8-sig") if path.exists() else ""
    body = strip_marked_block(text).rstrip("\n")
    block = toml_block(desired)
    if block:
        body = (body + "\n\n" if body else "") + "\n".join(block)
    write_text(path, body + "\n")
    try:
        import tomllib

        parsed = tomllib.loads(path.read_text(encoding="utf-8-sig"))
        got = set((parsed.get("mcp_servers") or {})) & CRAFT_IDS
        if got != set(desired):
            raise RuntimeError(
                f"post-write check failed: expected {sorted(desired)}, found {sorted(got)}"
            )
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"{path.name}: result does not parse as TOML ({e})")


def jsonc_block(desired, indent, trailing_comma, style):
    """The managed block. It is written first inside the target object, so a
    separating comma belongs after our last item (only when entries follow)."""
    pad = " " * indent
    inner = " " * (indent + 2)
    out = [f"{pad}// {BEGIN} - managed by Craft Connect, rewritten on every apply"]
    items = []
    for app in APPS:
        if app.id not in desired:
            continue
        exe, args = desired[app.id]
        body = json.dumps(entry_for(style, exe, args), indent=2, ensure_ascii=False)
        body = body.replace("\n", "\n" + inner)
        items.append(f'{inner}"{app.id}": {body}')
    for i, item in enumerate(items):
        needs = i < len(items) - 1 or (trailing_comma and items)
        out.append(item + ("," if needs else ""))
    out.append(f"{pad}// {END}")
    return out


def has_following_content(lines, after_index):
    for line in lines[after_index + 1 :]:
        s = line.strip()
        if not s or s.startswith("//"):
            continue
        return not s.startswith("}")
    return False


def find_chain(lines, prefix):
    idx = -1
    for depth, key in enumerate(prefix):
        pattern = re.compile(r'^\s*"' + re.escape(key) + r'"\s*:\s*\{\s*$')
        found = None
        for j in range(idx + 1, len(lines)):
            if pattern.match(lines[j]):
                found = j
                break
        if found is None:
            return None, depth
        idx = found
    return idx, len(prefix)


def create_chain(prefix, desired, style, base=2):
    pad = lambda n: " " * n  # noqa: E731
    if len(prefix) == 1:
        return (
            [f'{pad(base)}"{prefix[0]}": {{']
            + jsonc_block(desired, base + 2, False, style)
            + [f"{pad(base)}}}"]
        )
    return (
        [f'{pad(base)}"{prefix[0]}": {{', f'{pad(base + 2)}"{prefix[1]}": {{']
        + jsonc_block(desired, base + 4, False, style)
        + [f"{pad(base + 2)}}}", f"{pad(base)}}}"]
    )


def inject_block(text, desired, prefix, style):
    lines = text.splitlines()
    b = next((i for i, l in enumerate(lines) if l.lstrip().startswith("//") and BEGIN in l), None)
    e = next((i for i, l in enumerate(lines) if l.lstrip().startswith("//") and END in l), None)
    if b is not None and e is not None and e > b:
        indent = len(lines[b]) - len(lines[b].lstrip())
        block = jsonc_block(desired, indent, has_following_content(lines, e), style)
        return "\n".join(lines[:b] + block + lines[e + 1 :]) + "\n"

    idx, depth = find_chain(lines, prefix)
    if idx is not None:
        indent = len(lines[idx]) - len(lines[idx].lstrip())
        block = jsonc_block(desired, indent, has_following_content(lines, idx), style)
        return "\n".join(lines[: idx + 1] + block + lines[idx + 1 :]) + "\n"

    if depth > 0:
        raise RuntimeError(
            f'"{prefix[depth]}" exists but "{prefix[depth - 1]}" does not; '
            "edit this file by hand instead"
        )

    close = next((i for i in range(len(lines) - 1, -1, -1) if lines[i].strip() == "}"), None)
    if close is None:
        raise RuntimeError("cannot find the top-level closing brace; nothing written")
    j = close - 1
    while j >= 0 and not lines[j].strip():
        j -= 1
    if j >= 0 and lines[j].rstrip()[-1] not in ",{[":
        lines[j] = lines[j].rstrip() + ","
    return "\n".join(lines[:close] + create_chain(prefix, desired, style) + lines[close:]) + "\n"


def write_jsonc_block(path, desired, prefix, style):
    if path.exists():
        text = path.read_text(encoding="utf-8-sig")
    elif prefix == ("mcp",):
        text = '{\n  "$schema": "https://opencode.ai/config.json"\n}\n'
    else:
        text = "{\n}\n"
    new_text = inject_block(text, desired, prefix, style)
    try:
        parsed = json.loads(jsonc_to_json(new_text))
    except Exception as e:
        raise RuntimeError(f"{path.name}: generated text is not valid JSONC ({e}); nothing written")
    node = parsed
    for key in prefix:
        node = node.get(key) if isinstance(node, dict) else None
    got = set(node) & CRAFT_IDS if isinstance(node, dict) else set()
    if got != set(desired):
        raise RuntimeError(
            f"{path.name}: post-write check failed (expected {sorted(desired)}, found {sorted(got)})"
        )
    write_text(path, new_text)


def sync_client(client, desired):
    """Make the client's craft entries match `desired` ({app_id: (exe, args)})."""
    if client.kind == "toml":
        for p in client.paths:
            write_toml_block(p, desired)
    elif client.kind == "jsonc":
        for p in client.paths:
            write_jsonc_block(p, desired, client.prefix, client.style)
    else:
        for p in client.paths:
            if not p.exists() and not desired:
                continue
            write_json_entries(p, desired, client.style, client.root_key)
    return sorted(desired)


# --------------------------------------------------------------------------- #
# MCP handshake probe
# --------------------------------------------------------------------------- #


def probe(app, args, timeout=25.0):
    """Start the app's MCP server and complete initialize + tools/list."""
    exe = exe_path(app)
    if not exe:
        return "not installed", False
    deadline = time.time() + timeout
    try:
        proc = subprocess.Popen(
            [str(exe), *args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=NO_WINDOW,
        )
    except Exception as e:
        return f"cannot start: {e}", False

    lines = queue.Queue()
    errbuf = []

    def reader():
        try:
            for line in proc.stdout:
                lines.put(line)
        except Exception:
            pass
        lines.put(None)

    def err_reader():
        try:
            for line in proc.stderr:
                errbuf.append(line.strip())
        except Exception:
            pass

    threading.Thread(target=reader, daemon=True).start()
    threading.Thread(target=err_reader, daemon=True).start()

    def death_note():
        code = proc.poll()
        if code is None:
            return None
        tail = " ".join(x for x in errbuf[-2:] if x).strip()
        return f"exited with code {code}" + (f": {tail[:120]}" if tail else "")

    def rpc(message, want_id):
        try:
            proc.stdin.write(json.dumps(message) + "\n")
            proc.stdin.flush()
        except Exception:
            return None
        while time.time() < deadline:
            try:
                line = lines.get(timeout=max(0.05, deadline - time.time()))
            except queue.Empty:
                return None
            if line is None:
                return None
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if not isinstance(obj, dict):
                continue
            if obj.get("id") == want_id:
                return obj
        return None

    try:
        init = rpc(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "craft-connect", "version": "1.2"},
                },
            },
            1,
        )
        if init is None:
            return death_note() or "no answer to initialize (timed out)", False
        if "error" in init:
            msg = str(init["error"].get("message", init["error"]))[:60]
            return f"initialize error: {msg}", False
        try:
            proc.stdin.write(
                json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"
            )
            proc.stdin.flush()
        except Exception:
            pass
        listed = rpc({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}, 2)
        if listed is None:
            return death_note() or "connected, tools/list timed out", True
        tools = (listed.get("result") or {}).get("tools") or []
        return f"{len(tools)} tools", True
    finally:
        try:
            proc.stdin.close()
        except Exception:
            pass
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


# --------------------------------------------------------------------------- #
# The window
# --------------------------------------------------------------------------- #


def enable_dpi_awareness():
    """Without this Windows bitmap-scales the window: blurry text at 125%/150%."""
    if not IS_WIN:
        return
    try:
        import ctypes

        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # per-monitor v2
        return
    except Exception:
        pass
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        import ctypes

        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def dark_titlebar(root):
    if not IS_WIN:
        return
    try:
        import ctypes

        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        value = ctypes.c_int(1)
        for attr in (20, 19):
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attr, ctypes.byref(value), ctypes.sizeof(value)
            )
    except Exception:
        pass


class Toggle:
    """A square on/off switch drawn on a canvas.

    ttk's checkbox indicator on clam is a light box that shows almost nothing on a
    dark background, and its tick colour cannot be set reliably. This draws both
    states explicitly so a tick is unmistakable.
    """

    def __init__(self, master, variable, command=None, enabled=True, size=15,
                 bg=P["bg"], hover=None):
        import tkinter as tk

        self.tk = tk
        self.var = variable
        self.command = command
        self.size = size
        self.enabled = enabled
        self.hover = hover
        self.canvas = tk.Canvas(master, width=size, height=size, bg=bg,
                                highlightthickness=0, bd=0,
                                cursor="hand2" if enabled else "arrow")
        self.canvas.bind("<Button-1>", self._click)
        self.canvas.bind("<Enter>", lambda e: self._draw(True))
        self.canvas.bind("<Leave>", lambda e: self._draw(False))
        variable.trace_add("write", lambda *a: self._draw(False))
        self._draw(False)

    def grid(self, **kw):
        return self.canvas.grid(**kw)

    def grid_remove(self):
        return self.canvas.grid_remove()

    def _draw(self, hover):
        c, s = self.canvas, self.size
        c.delete("all")
        on = bool(self.var.get())
        if not self.enabled:
            fill, outline = P["surface"], P["border"]
        elif on:
            fill, outline = P["accent"], P["accent"]
        else:
            fill = P["surface3"] if hover else P["surface2"]
            outline = "#454545" if hover else P["line"]
        c.create_rectangle(1, 1, s - 1, s - 1, fill=fill, outline=outline)
        if on and self.enabled:
            c.create_line(4, s * 0.52, s * 0.42, s - 4, s - 3, 4,
                          fill="#141414", width=max(2, s // 8),
                          capstyle="round", joinstyle="round")

    def _click(self, _event):
        if not self.enabled:
            return
        self.var.set(not self.var.get())
        if self.command:
            self.command()


class Tooltip:
    """Small hover label that says how a column was detected."""

    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tip = None
        widget.bind("<Enter>", self.show, add="+")
        widget.bind("<Leave>", self.hide, add="+")

    def show(self, _event=None):
        if self.tip is not None or not self.text:
            return
        import tkinter as tk

        x = self.widget.winfo_rootx() + 6
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.configure(bg=P["line"])
        tk.Label(self.tip, text=self.text, bg=P["surface2"], fg=P["text"],
                 font=("Segoe UI", 8), justify="left", padx=7, pady=4
                 ).pack(padx=1, pady=1)
        self.tip.wm_geometry(f"+{x}+{y}")

    def hide(self, _event=None):
        if self.tip is not None:
            try:
                self.tip.destroy()
            except Exception:
                pass
            self.tip = None


class CraftConnectWindow:
    def __init__(self, root, tray=True):
        import tkinter as tk
        from tkinter import ttk, scrolledtext

        self.tk, self.ttk, self.root = tk, ttk, root
        self.uiq = queue.Queue()
        self.ticked, self.port_vars = {}, {}
        self.status_labels, self.status_vars = {}, {}
        self.row_widgets = {}
        self.dirty = set()
        self.tray = None
        self._quitting = False
        self._logo_img = None

        # DPI: ask Tk for the real dots-per-inch, then size everything from it.
        try:
            dpi = root.winfo_fpixels("1i")
            root.tk.call("tk", "scaling", dpi / 72.0)
        except Exception:
            dpi = 96.0
        self.scale = max(1.0, min(3.0, dpi / 96.0))

        def px(value):
            return max(1, int(round(value * self.scale)))

        self.px = px
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        width = min(px(1180), int(sw * 0.95))
        height = min(px(830), int(sh * 0.90))
        x = max(0, (sw - width) // 2)
        y = max(0, (sh - height) // 3)
        root.geometry(f"{width}x{height}+{x}+{y}")
        root.minsize(min(px(640), sw), min(px(480), sh))
        root.title("Craft Connect")
        root.configure(bg=P["bg"])
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.bind("<Unmap>", self._on_unmap)
        try:
            if ICO_FILE.exists():
                root.iconbitmap(default=str(ICO_FILE))
        except Exception:
            pass

        style = ttk.Style(root)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        base_font = ("Segoe UI", 9)
        style.configure(
            ".",
            background=P["bg"],
            foreground=P["text"],
            fieldbackground=P["surface2"],
            bordercolor=P["border"],
            lightcolor=P["surface"],
            darkcolor=P["surface"],
            troughcolor=P["bg"],
            focuscolor=P["accent"],
            selectbackground=P["accent"],
            selectforeground="#141414",
            font=base_font,
        )
        style.configure("TFrame", background=P["bg"])
        style.configure("TLabel", background=P["bg"], foreground=P["text"])
        style.configure("Sub.TLabel", background=P["bg"], foreground=P["muted"],
                        font=("Segoe UI", 8))
        style.configure("Hdr.TLabel", background=P["bg"], foreground=P["muted"],
                        font=("Segoe UI", 8, "bold"))
        style.configure("Off.TLabel", background=P["bg"], foreground=P["dim"])
        style.configure("TButton", background=P["surface"], foreground=P["text"],
                        bordercolor=P["border"], padding=(px(9), px(3)), relief="flat")
        style.map("TButton",
                  background=[("active", P["surface3"]), ("pressed", P["accent_dark"])],
                  foreground=[("disabled", P["dim"])])
        style.configure("Accent.TButton", background=P["accent"], foreground="#141414",
                        bordercolor=P["accent_dark"], padding=(px(11), px(3)), relief="flat")
        style.map("Accent.TButton", background=[("active", P["accent_hover"])])
        style.configure("TRadiobutton", background=P["bg"], foreground=P["text"],
                        focuscolor=P["bg"], indicatorcolor=P["surface2"])
        style.map("TRadiobutton",
                  background=[("active", P["bg"])],
                  indicatorcolor=[("selected", P["accent"]), ("!selected", P["surface2"])])
        style.configure("TEntry", fieldbackground=P["surface2"], foreground=P["text"],
                        bordercolor=P["border"], insertcolor=P["text"], padding=px(3))
        style.configure("TLabelframe", background=P["bg"], bordercolor=P["border"],
                        relief="solid", borderwidth=1)
        style.configure("TLabelframe.Label", background=P["bg"], foreground=P["muted"])
        style.configure("TScrollbar", background=P["surface3"], troughcolor=P["bg"],
                        bordercolor=P["bg"], arrowcolor=P["muted"])
        style.map("TScrollbar", background=[("active", P["accent_dark"])])

        # header ------------------------------------------------------------
        head = tk.Frame(root, bg=P["surface"], height=px(62))
        head.pack(fill="x")
        head.pack_propagate(False)
        try:
            from PIL import ImageTk

            self._logo_img = ImageTk.PhotoImage(logo_image(px(32)))
            tk.Label(head, image=self._logo_img, bg=P["surface"], bd=0).pack(
                side="left", padx=(px(14), px(10)), pady=px(14))
        except Exception:
            pass
        titles = tk.Frame(head, bg=P["surface"])
        titles.pack(side="left", pady=px(11))
        tk.Label(titles, text="Craft Connect", bg=P["surface"], fg="#f4f4f4",
                 font=("Segoe UI", 13, "bold")).pack(anchor="w")
        sub = tk.Frame(titles, bg=P["surface"])
        sub.pack(anchor="w")
        tk.Label(sub, text="craft engines to your AI harnesses",
                 bg=P["surface"], fg=P["muted"], font=("Segoe UI", 8)).pack(side="left")
        tk.Label(sub, text="\u00b7  by @AdibSadman192", bg=P["surface"], fg=P["dim"],
                 font=("Segoe UI", 8)).pack(side="left", padx=(px(2), 0))

        right = tk.Frame(head, bg=P["surface"])
        right.pack(side="right", padx=px(12))
        tk.Label(right, text="find", bg=P["surface"], fg=P["muted"],
                 font=("Segoe UI", 8)).pack(side="left", padx=(0, px(5)))
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *a: self.filter_rows())
        tk.Entry(right, textvariable=self.search_var, width=13, bg=P["surface2"],
                 fg=P["text"], insertbackground=P["text"], relief="flat",
                 highlightthickness=1, highlightbackground=P["border"],
                 highlightcolor=P["accent"]).pack(side="left", ipady=px(2))
        ttk.Button(right, text="Apply all", style="Accent.TButton",
                   command=self.apply_all).pack(side="left", padx=(px(7), 0))

        tk.Frame(root, bg=P["border"], height=1).pack(fill="x")

        # controls ----------------------------------------------------------
        bar = ttk.Frame(root, padding=(px(12), px(7), px(12), px(1)))
        bar.pack(fill="x")
        ttk.Label(bar, text="Project root").pack(side="left")
        self.root_var = tk.StringVar(value=str(Path.home() / "craft-work"))
        ttk.Entry(bar, textvariable=self.root_var, width=36).pack(side="left", padx=(px(7), px(3)))
        ttk.Button(bar, text="Browse", command=self.pick_root).pack(side="left")
        self.compact_var = tk.BooleanVar(value=False)
        comp = Toggle(bar, self.compact_var, command=self.apply_all, size=px(15))
        comp.canvas.pack(side="left", padx=(px(16), px(5)))
        ttk.Label(bar, text="compact tools").pack(side="left")

        modebar = ttk.Frame(root, padding=(px(12), px(3), px(12), px(5)))
        modebar.pack(fill="x")
        ttk.Label(modebar, text="Mode").pack(side="left")
        self.mode_var = tk.StringVar(value="headless")
        ttk.Radiobutton(modebar, text="Headless", value="headless",
                        variable=self.mode_var, command=self.on_mode
                        ).pack(side="left", padx=(px(7), px(4)))
        ttk.Radiobutton(modebar, text="Attach", value="attach",
                        variable=self.mode_var, command=self.on_mode
                        ).pack(side="left", padx=(0, px(4)))
        ttk.Radiobutton(modebar, text="GUI", value="gui",
                        variable=self.mode_var, command=self.on_mode
                        ).pack(side="left", padx=(0, px(4)))
        self.mode_hint = tk.StringVar(
            value="headless: the harness drives its own engine, no window, no port")
        tk.Label(modebar, textvariable=self.mode_hint, bg=P["bg"], fg=P["dim"],
                 font=("Segoe UI", 8)).pack(side="left", padx=(px(4), 0))

        # matrix in a horizontally scrollable canvas ------------------------
        wrap = ttk.Frame(root, padding=(px(12), 0))
        wrap.pack(fill="both", expand=True)
        wrap.grid_rowconfigure(0, weight=1)
        wrap.grid_columnconfigure(0, weight=1)
        self.grid_canvas = tk.Canvas(wrap, bg=P["bg"], highlightthickness=0, bd=0)
        self.grid_canvas.grid(row=0, column=0, sticky="nsew")
        self.grid_vbar = ttk.Scrollbar(wrap, orient="vertical",
                                       command=self.grid_canvas.yview)
        self.grid_hbar = ttk.Scrollbar(wrap, orient="horizontal",
                                       command=self.grid_canvas.xview)
        self.grid_vbar.grid(row=0, column=1, sticky="ns")
        self.grid_hbar.grid(row=1, column=0, sticky="ew")
        self.grid_vbar.grid_remove()
        self.grid_hbar.grid_remove()
        self.grid_canvas.configure(yscrollcommand=self._vbar_set,
                                   xscrollcommand=self._hbar_set)
        table = ttk.Frame(self.grid_canvas)
        self._table_item = self.grid_canvas.create_window((0, 0), window=table, anchor="nw")
        table.bind("<Configure>", self._table_resized)
        self.grid_canvas.bind("<Configure>", self._canvas_resized)
        self.grid_canvas.bind("<Shift-MouseWheel>", self._wheel_h)
        self.root.bind_all("<MouseWheel>", self._wheel)
        self.table = table

        cols = [("App", 0)]
        cols += [(c.short, px(46)) for c in CLIENTS]
        cols += [("Port", px(40)), ("", px(34)), ("app", px(40)), ("handshake", px(90))]
        for i, (text, width) in enumerate(cols):
            lbl = ttk.Label(table, text=text, style="Hdr.TLabel")
            lbl.grid(row=0, column=i, sticky="w",
                     padx=px(4), pady=(px(2), px(5)))
            if 0 < i <= len(CLIENTS):
                client = CLIENTS[i - 1]
                state, why = client.status()
                lbl.configure(style="Hdr.TLabel" if state != "absent" else "Off.TLabel")
                Tooltip(lbl, f"{client.label}\n{MARKS[state]} {why}\nclick a box below to register")
        self.table.grid_columnconfigure(len(cols) - 1, weight=1)

        self.available = {}
        row = 1
        for app in APPS:
            exe = exe_path(app)
            self.available[app.id] = exe
            widgets = []
            label = ttk.Label(table, text=app.label if exe else f"{app.label}  ·  missing",
                              style="TLabel" if exe else "Off.TLabel", anchor="w")
            label.grid(row=row, column=0, sticky="ew", padx=px(4), pady=px(1))
            widgets.append(label)

            col = 1
            for client in CLIENTS:
                var = tk.BooleanVar(value=False)
                self.ticked[(app.id, client.key)] = var
                tog = Toggle(table, var, command=lambda ck=client.key: self.on_toggle(ck),
                             enabled=bool(exe and client.installed),
                             size=px(15), bg=P["bg"])
                tog.grid(row=row, column=col, padx=px(4), pady=px(2))
                widgets.append(tog)
                col += 1

            port_var = tk.StringVar(value=str(app.port) if app.has_bridge else "n/a")
            self.port_vars[app.id] = port_var
            pe = ttk.Entry(table, textvariable=port_var, width=6, justify="center")
            pe.grid(row=row, column=col, padx=px(3))
            if not app.has_bridge:
                pe.state(["disabled"])
            widgets.append(pe)

            ttk.Button(table, text="Test", width=5,
                       command=lambda a=app: self.test_many([a])
                       ).grid(row=row, column=col + 1, padx=px(3))
            opn = ttk.Button(table, text="Open", width=5,
                             command=lambda a=app: self.open_app(a))
            opn.grid(row=row, column=col + 2, padx=px(3))
            if not gui_exe(app):
                opn.state(["disabled"])
            widgets.append(opn)
            sv = tk.StringVar(value="")
            self.status_vars[app.id] = sv
            lbl = tk.Label(table, textvariable=sv, bg=P["bg"], fg=P["muted"],
                           font=("Consolas", 8), anchor="w")
            lbl.grid(row=row, column=len(cols) - 1, sticky="w", padx=px(4))
            self.status_labels[app.id] = lbl
            widgets.append(lbl)
            self.row_widgets[app.id] = widgets
            row += 1

        # footer ------------------------------------------------------------
        foot = ttk.Frame(root, padding=(px(12), px(6), px(12), px(1)))
        foot.pack(fill="x")
        ttk.Button(foot, text="Test all", command=lambda: self.test_many(APPS)).pack(side="left")
        ttk.Button(foot, text="Re-check", command=self.reload).pack(side="left", padx=px(5))
        ttk.Button(foot, text="Config files", command=self.show_configs).pack(side="left", padx=px(5))
        ttk.Button(foot, text="Detect", command=self.show_detection).pack(side="left", padx=px(5))
        ttk.Button(foot, text="Send to tray", command=self.hide_window).pack(side="left", padx=px(5))
        ttk.Button(foot, text="Quit", command=self.quit_app).pack(side="left", padx=px(5))
        self.banner = tk.StringVar(value="")
        tk.Label(foot, textvariable=self.banner, bg=P["bg"], fg=P["warn"],
                 font=("Segoe UI", 8)).pack(side="left", padx=px(10))

        self.status_var = tk.StringVar(value="")
        tk.Label(root, textvariable=self.status_var, bg=P["bg"], fg=P["muted"],
                 font=("Segoe UI", 8), anchor="w").pack(fill="x", padx=px(12))

        logframe = ttk.LabelFrame(root, text="Log", padding=(px(7), px(3)))
        logframe.pack(fill="x", padx=px(12), pady=(px(4), px(2)))
        self.logtext = scrolledtext.ScrolledText(
            logframe, height=7, wrap="word", font=("Consolas", 9),
            background=P["surface2"], foreground="#d8d8d8",
            insertbackground=P["text"], relief="flat", borderwidth=0,
            highlightthickness=0, selectbackground=P["accent_dark"])
        self.logtext.pack(fill="both", expand=True)
        try:  # ScrolledText uses a classic scrollbar; make it match the theme
            self.logtext.vbar.configure(
                bg=P["surface3"], activebackground=P["accent_dark"],
                troughcolor=P["bg"], highlightthickness=0, bd=0,
                relief="flat", width=self.px(10))
        except Exception:
            pass
        self.logtext.configure(state="disabled")

        tk.Label(root, text="Harnesses read MCP config at startup, so restart the one you toggled.  "
                            "Backups: <file>.craftconnect.bak",
                 bg=P["bg"], fg=P["dim"], font=("Segoe UI", 8), anchor="w"
                 ).pack(fill="x", padx=px(12), pady=(0, px(6)))

        self.log(f"Ready. scoop root {SCOOP} ({SCOOP_SOURCE}).")
        self.log("Tick an app for a harness to register it; Test proves the handshake.")
        self.reload()
        dark_titlebar(root)
        if tray:
            self.start_tray()
        self._drain_id = self.root.after(150, self.drain)

    # -- responsive bits ---------------------------------------------------- #

    def _hbar_set(self, first, last):
        # the scrollbars appear only when the table really overflows
        if float(first) <= 0.0 and float(last) >= 1.0:
            self.grid_hbar.grid_remove()
        else:
            self.grid_hbar.grid()
        self.grid_hbar.set(first, last)

    def _vbar_set(self, first, last):
        if float(first) <= 0.0 and float(last) >= 1.0:
            self.grid_vbar.grid_remove()
        else:
            self.grid_vbar.grid()
        self.grid_vbar.set(first, last)

    def _table_resized(self, event):
        self.grid_canvas.configure(scrollregion=self.grid_canvas.bbox("all"))
        self._canvas_resized(type("E", (), {"width": self.grid_canvas.winfo_width()})())

    def _canvas_resized(self, event):
        """Stretch the table to the visible width so columns spread out, never float."""
        try:
            wanted = max(event.width, self.table.winfo_reqwidth())
            self.grid_canvas.itemconfigure(self._table_item, width=wanted)
        except Exception:
            pass

    def _wheel_h(self, event):
        self.grid_canvas.xview_scroll(-1 * (event.delta // 120), "units")

    def _wheel(self, event):
        """Route the wheel to whichever pane the pointer is over."""
        try:
            under = self.root.winfo_containing(event.x_root, event.y_root)
        except Exception:
            under = None
        path = str(under) if under is not None else ""
        step = -1 * (event.delta // 120)
        if path.startswith(str(self.grid_canvas)):
            self.grid_canvas.yview_scroll(step, "units")
        elif path.startswith(str(self.logtext)) or path.startswith(str(self.logtext.master)):
            self.logtext.yview_scroll(step, "units")
        else:
            self.grid_canvas.yview_scroll(step, "units")

    # -- tray --------------------------------------------------------------- #

    def start_tray(self):
        try:
            import pystray
        except Exception as e:
            self.log(f"tray unavailable ({e}); the window keeps a taskbar button instead")
            return False
        image = logo_image(64)
        if image is None:
            self.log("tray needs Pillow; the window keeps a taskbar button instead")
            return False
        menu = pystray.Menu(
            pystray.MenuItem("Show Craft Connect", self._via_tray(self.show_window), default=True),
            pystray.MenuItem("Apply all", self._via_tray(self.apply_all)),
            pystray.MenuItem("Re-check configs", self._via_tray(self.reload)),
            pystray.MenuItem("Test all", self._via_tray(lambda: self.test_many(APPS))),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self._via_tray(self.quit_app)),
        )
        self.tray = pystray.Icon("craft-connect", image, "Craft Connect", menu)
        threading.Thread(target=self.tray.run, daemon=True).start()
        self.log("tray icon up: minimise or close the window and it stays here")
        return True

    def _via_tray(self, fn):
        return lambda *a, **k: self.root.after(0, fn)

    def hide_window(self):
        self.root.withdraw()
        if self.tray:
            self.log("hidden to the tray; right-click the tray icon to get back")

    def show_window(self):
        self.root.deiconify()
        self.root.lift()
        try:
            self.root.focus_force()
        except Exception:
            pass

    def _on_unmap(self, event):
        if event.widget is self.root and self.tray and self.root.state() == "iconic":
            self.root.after(1, self.hide_window)

    def on_close(self):
        if self.tray and not self._quitting:
            self.hide_window()
        else:
            self.quit_app()

    def quit_app(self):
        self._quitting = True
        try:
            self.root.after_cancel(getattr(self, "_drain_id", ""))
        except Exception:
            pass
        if self.tray is not None:
            try:
                self.tray.stop()
            except Exception:
                pass
        try:
            self.root.destroy()
        except Exception:
            pass

    # -- helpers ------------------------------------------------------------ #

    def log(self, message):
        self.logtext.configure(state="normal")
        self.logtext.insert("end", f"{time.strftime('%H:%M')}  {message}\n")
        self.logtext.see("end")
        self.logtext.configure(state="disabled")

    def pick_root(self):
        from tkinter import filedialog

        chosen = filedialog.askdirectory(initialdir=self.root_var.get() or str(Path.home()))
        if chosen:
            self.root_var.set(str(Path(chosen)))
            self.on_mode()

    def current_root(self):
        root = self.root_var.get().strip()
        if root:
            path = Path(root)
            if not path.exists():
                try:
                    path.mkdir(parents=True, exist_ok=True)
                    self.log(f"created project root {path}")
                except Exception as e:
                    self.log(f"! cannot create {path}: {e}")
                    return ""
        return root

    def desired_for(self, client, root, mode):
        out = {}
        for app in APPS:
            if not self.ticked[(app.id, client.key)].get():
                continue
            exe = self.available.get(app.id) or exe_path(app)
            if not exe:
                raise RuntimeError(f"{app.label}: CLI not found on this machine")
            args = mcp_args(app, mode, root, self.port_vars[app.id].get(),
                            self.compact_var.get(), self.log)
            out[app.id] = (str(exe), args)
        return out

    def filter_rows(self):
        needle = self.search_var.get().strip().lower()
        for app in APPS:
            show = not needle or needle in app.label.lower() or needle in app.id
            for widget in self.row_widgets[app.id]:
                if show:
                    widget.grid()
                else:
                    widget.grid_remove()

    # -- actions ------------------------------------------------------------ #

    def on_toggle(self, client_key):
        client = CLIENT_BY_KEY[client_key]
        try:
            names = sync_client(
                client, self.desired_for(client, self.current_root(), self.mode_var.get()))
        except Exception as e:
            self.log(f"x {client.label}: {e}")
            self.reload()
            return
        self.log(f"ok {client.label}: {', '.join(names) if names else 'none'}")
        self.dirty.add(client.label)
        self.update_banner()

    def on_mode(self):
        mode = self.mode_var.get()
        self.mode_hint.set({
            "headless": "headless: the harness drives its own engine, no window, no port",
            "attach": "attach: drives the app you have open, on the port at right",
            "gui": "gui: Open (or Apply all) starts the app; you and the harness share it",
        }.get(mode, ""))
        self.apply_all(quiet=True)
        self.log(f"mode: {mode} (all registrations re-applied)")

    def open_app(self, app):
        port, problem = launch_gui(app, self.log)
        if problem:
            self.log(f"! {problem}")
            return
        if self.mode_var.get() == "gui":
            self.apply_all(quiet=True)
        else:
            self.log(f"{app.label} is open on port {port}; switch Mode to GUI to let a "
                     "harness drive this same window")

    def apply_all(self, quiet=False):
        root = self.current_root()
        mode = self.mode_var.get()
        if mode == "gui":
            for app in APPS:
                if any(self.ticked[(app.id, c.key)].get() for c in CLIENTS):
                    _, problem = launch_gui(app, self.log)
                    if problem:
                        self.log(f"! {problem}")
        for client in CLIENTS:
            if not client.installed:
                continue
            try:
                names = sync_client(client, self.desired_for(client, root, mode))
            except Exception as e:
                self.log(f"x {client.label}: {e}")
                continue
            if names:
                self.log(f"ok {client.label}: {', '.join(names)}")
                self.dirty.add(client.label)
        if not quiet:
            self.log("applied" + (", compact" if self.compact_var.get() else "") + ".")
        self.refresh_status()
        self.update_banner()

    def reload(self):
        for client in CLIENTS:
            have = registered_craft(client)
            for app in APPS:
                self.ticked[(app.id, client.key)].set(app.id in have)
        self.refresh_status()

    def refresh_status(self):
        total = sum(1 for var in self.ticked.values() if var.get())
        clis = sum(1 for app in APPS if self.available.get(app.id))
        harnesses = sum(1 for c in CLIENTS if c.installed)
        self.status_var.set(
            f"{total} registration{'s' if total != 1 else ''}  ·  "
            f"{clis}/{len(APPS)} CLIs  ·  {harnesses}/{len(CLIENTS)} harnesses  ·  "
            f"root {SCOOP}"
        )

    def update_banner(self):
        self.banner.set(("restart: " + ", ".join(sorted(self.dirty))) if self.dirty else "")

    def test_many(self, apps):
        root = self.current_root()
        mode = self.mode_var.get()
        compact = self.compact_var.get()

        def work():
            for app in apps:
                if not exe_path(app):
                    self.uiq.put(("status", app.id, "missing CLI", P["dim"]))
                    continue
                if mode == "gui" and not gui_running(app):
                    self.uiq.put(("status", app.id,
                                  "GUI closed - press Open", P["warn"]))
                    continue
                args = mcp_args(app, mode, root, self.port_vars[app.id].get(), compact, None)
                self.uiq.put(("status", app.id, "handshaking…", P["warn"]))
                text, ok = probe(app, args)
                self.uiq.put(("status", app.id, text, P["ok"] if ok else P["err"]))

        threading.Thread(target=work, daemon=True).start()

    def drain(self):
        while True:
            try:
                kind, aid, text, colour = self.uiq.get_nowait()
            except queue.Empty:
                break
            if kind == "status":
                label = self.status_labels.get(aid)
                if label is not None:
                    label.configure(text=text, fg=colour or P["muted"])
        if self._quitting:
            return
        self._drain_id = self.root.after(150, self.drain)

    def show_detection(self):
        import tkinter as tk
        from tkinter import ttk

        win = self.tk.Toplevel(self.root)
        win.title("Detection")
        win.configure(bg=P["bg"])
        win.geometry(f"{self.px(760)}x{self.px(520)}")
        frame = ttk.Frame(win, padding=self.px(10))
        frame.pack(fill="both", expand=True)
        box = tk.Text(frame, wrap="none", font=("Consolas", 9),
                      bg=P["surface2"], fg=P["text"], relief="flat", borderwidth=0,
                      highlightthickness=0, padx=self.px(8), pady=self.px(6))
        bar = ttk.Scrollbar(frame, orient="vertical", command=box.yview)
        hbar = ttk.Scrollbar(frame, orient="horizontal", command=box.xview)
        box.configure(yscrollcommand=bar.set, xscrollcommand=hbar.set)
        bar.pack(side="right", fill="y")
        box.pack(side="left", fill="both", expand=True)
        hbar.pack(side="bottom", fill="x")
        box.insert("1.0", "\n".join(doctor_lines()))
        box.configure(state="disabled")

    def show_configs(self):
        from tkinter import ttk

        win = self.tk.Toplevel(self.root)
        win.title("Config files")
        win.geometry(f"{self.px(880)}x{self.px(460)}")
        win.configure(bg=P["bg"])
        frame = ttk.Frame(win, padding=self.px(12))
        frame.pack(fill="both", expand=True)
        row = 0
        for client in CLIENTS:
            state = "detected" if client.installed else "not installed"
            ttk.Label(frame, text=f"{client.label}  ·  {state}").grid(
                row=row, column=0, sticky="w", pady=(self.px(9), 0))
            row += 1
            for p in client.paths:
                exists = "exists" if p.exists() else "will be created"
                ttk.Label(frame, text=f"{p}   [{exists}]", style="Sub.TLabel").grid(
                    row=row, column=0, sticky="w", padx=(self.px(13), 0))
                ttk.Button(frame, text="Reveal", width=8,
                           command=lambda q=p: self.reveal(q)
                           ).grid(row=row, column=1, padx=self.px(5))
                row += 1
        ttk.Button(frame, text="Close", command=win.destroy).grid(
            row=row, column=0, sticky="w", pady=(self.px(12), 0))

    def reveal(self, path):
        try:
            if path.exists():
                if IS_WIN:
                    subprocess.Popen(["explorer", "/select,", str(path)])
                else:
                    subprocess.Popen(["xdg-open", str(path.parent)])
                return
            path.parent.mkdir(parents=True, exist_ok=True)
            if IS_WIN:
                subprocess.Popen(["explorer", str(path.parent)])
        except Exception as e:
            self.log(f"cannot reveal: {e}")


# --------------------------------------------------------------------------- #
# Self test / CLI
# --------------------------------------------------------------------------- #


def import_toml(path):
    import tomllib

    return tomllib.loads(Path(path).read_text(encoding="utf-8-sig"))


def selftest():
    import tempfile

    ok = True

    def check(label, condition):
        nonlocal ok
        print(("PASS  " if condition else "FAIL  ") + label)
        ok = ok and bool(condition)

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        claude = Client("claude", "Claude Code", "json", [tmp / "claude.json"])
        codex = Client("codex", "Codex", "toml", [tmp / "config.toml"])
        openc = Client("opencode", "OpenCode", "jsonc", [tmp / "opencode.jsonc"],
                       style="opencode", prefix=("mcp",))

        (tmp / "claude.json").write_text(
            json.dumps({"userID": "x", "mcpServers": {"rea": {"command": "npx", "args": ["mcp"]}}}),
            encoding="utf-8")
        (tmp / "config.toml").write_text(
            'model = "gpt-6-luna"\n\n[mcp_servers.rea]\ncommand = "cmd.exe"\nargs = ["/c", "x"]\n',
            encoding="utf-8")
        (tmp / "opencode.jsonc").write_text(
            '{\n  "$schema": "https://opencode.ai/config.json",\n  "mcp": {\n'
            '    "rea": {\n      "type": "local",\n      "command": ["cmd.exe", "/c", "x"],\n'
            '      "enabled": true\n    }\n  }\n}\n', encoding="utf-8")

        first = {
            "photocraft": (r"D:\shims\photocraft-cli.exe",
                           ["mcp", "--automation-read-root", "D:\\w"]),
            "vectorcraft": (r"D:\shims\vectorcraft-cli.exe", ["mcp"]),
        }
        for client in (claude, codex, openc):
            sync_client(client, first)
        check("claude keeps foreign servers",
              read_json_names(tmp / "claude.json") == {"rea", "photocraft", "vectorcraft"})
        check("codex registers both",
              read_toml_names(tmp / "config.toml") == {"rea", "photocraft", "vectorcraft"})
        check("opencode registers both",
              read_jsonc_names(tmp / "opencode.jsonc", ("mcp",)) == {"rea", "photocraft", "vectorcraft"})
        check("codex still parses and keeps model",
              import_toml(tmp / "config.toml").get("model") == "gpt-6-luna")
        check("backup written", (tmp / "config.toml.craftconnect.bak").exists())

        second = {"photocraft": first["photocraft"]}
        for client in (claude, codex, openc):
            sync_client(client, second)
        check("claude drops vectorcraft only",
              read_json_names(tmp / "claude.json") == {"rea", "photocraft"})
        check("codex drops vectorcraft only",
              read_toml_names(tmp / "config.toml") == {"rea", "photocraft"})
        check("opencode drops vectorcraft only",
              read_jsonc_names(tmp / "opencode.jsonc", ("mcp",)) == {"rea", "photocraft"})

        for client in (claude, codex, openc):
            sync_client(client, {})
        check("claude back to just rea", read_json_names(tmp / "claude.json") == {"rea"})
        check("codex back to just rea", read_toml_names(tmp / "config.toml") == {"rea"})
        check("opencode back to just rea",
              read_jsonc_names(tmp / "opencode.jsonc", ("mcp",)) == {"rea"})
        check("codex has no leftover marker",
              BEGIN not in (tmp / "config.toml").read_text(encoding="utf-8"))
        check("opencode still valid JSON",
              isinstance(json.loads(jsonc_to_json(
                  (tmp / "opencode.jsonc").read_text(encoding="utf-8"))), dict))
        check("opencode keeps its $schema",
              json.loads(jsonc_to_json((tmp / "opencode.jsonc").read_text(encoding="utf-8")))
              .get("$schema") == "https://opencode.ai/config.json")

        fresh = tmp / "fresh.jsonc"
        fresh.write_text('{\n  "plugins": ["a"]\n}\n', encoding="utf-8")
        write_jsonc_block(fresh, {"photocraft": (r"D:\x.exe", ["mcp"])}, ("mcp",), "opencode")
        check("creates mcp key from scratch",
              read_jsonc_names(fresh, ("mcp",)) == {"photocraft"})

        # VS Code keeps its servers in User/mcp.json under "servers", not settings.json
        vsc = tmp / "vsc-mcp.json"
        vsc.write_text(json.dumps({
            "servers": {"playwright": {"type": "stdio", "command": "npx", "args": ["-y", "p"]}},
            "inputs": []}, indent=2), encoding="utf-8")
        vsc_client = Client("vscode", "VS Code", "json", [vsc],
                            style="vscode", root_key="servers")
        sync_client(vsc_client, first)
        check("vscode mcp.json registers both",
              read_json_names(vsc, "servers") == {"playwright", "photocraft", "vectorcraft"})
        parsed = json.loads(vsc.read_text(encoding="utf-8"))
        check("vscode entry is stdio with args",
              parsed["servers"]["photocraft"]["type"] == "stdio"
              and parsed["servers"]["photocraft"]["args"][0] == "mcp")
        check("vscode keeps its inputs list", parsed.get("inputs") == [])
        sync_client(vsc_client, {})
        check("vscode cleans up and keeps playwright",
              read_json_names(vsc, "servers") == {"playwright"})

        # Copilot CLI wants type + tools; the plain hosts want command/args only
        cop = Client("copilot", "Copilot CLI", "json", [tmp / "copilot.json"], style="copilot")
        sync_client(cop, second)
        parsed = json.loads((tmp / "copilot.json").read_text(encoding="utf-8"))
        check("copilot entry carries type and tools",
              parsed["mcpServers"]["photocraft"]["type"] == "stdio"
              and parsed["mcpServers"]["photocraft"]["tools"] == ["*"])

        plain_hosts = {}
        for key in ("devin", "trae", "qoder", "verdent", "lmstudio", "cline", "kiro"):
            p = tmp / f"{key}.json"
            p.write_text(json.dumps({"mcpServers": {"rea": {"command": "x", "args": []}}}),
                         encoding="utf-8")
            sync_client(Client(key, key.title(), "json", [p]), second)
            plain_hosts[key] = read_json_names(p)
        check("every plain host registers and keeps rea",
              all(v == {"rea", "photocraft"} for v in plain_hosts.values()))

        zed = tmp / "zed-settings.json"
        zed.write_text('{\n  "theme": "One Dark"\n}\n', encoding="utf-8")
        zed_client = Client("zed", "Zed", "jsonc", [zed],
                            style="zed", prefix=("context_servers",))
        sync_client(zed_client, first)
        parsed = json.loads(jsonc_to_json(zed.read_text(encoding="utf-8")))
        check("zed registers context servers",
              read_jsonc_names(zed, ("context_servers",)) == {"photocraft", "vectorcraft"})
        check("zed entry has source and command.path",
              parsed["context_servers"]["photocraft"]["source"] == "custom"
              and parsed["context_servers"]["photocraft"]["command"]["path"].endswith(".exe"))
        sync_client(zed_client, {})
        check("zed cleans up and keeps its theme",
              json.loads(jsonc_to_json(zed.read_text(encoding="utf-8"))).get("theme") == "One Dark")

        cur = Client("cursor", "Cursor", "json", [tmp / "mcp.json"], style="plain")
        sync_client(cur, first)
        check("cursor registers plain entries",
              read_json_names(tmp / "mcp.json") == {"photocraft", "vectorcraft"})
        sync_client(cur, {})
        check("cursor cleans up", read_json_names(tmp / "mcp.json") == set())

        light, pc = APP_BY_ID["lightcraft"], APP_BY_ID["photocraft"]
        check("compact goes to LightCraft", "--compact" in mcp_args(light, "headless", "", None, True))
        check("compact skipped for PhotoCraft", "--compact" not in mcp_args(pc, "headless", "", None, True))

        gui = mcp_args(pc, "gui", "", None)
        check("gui mode bridges to the app's control port",
              gui[:3] == ["mcp", "--bridge", str(gui_port(pc))])
        check("gui mode passes the control token file",
              "--control-token-file" in gui and str(token_file(pc)) in gui)
        check("gui mode drops the roots (the window owns them)",
              "--automation-read-root" not in gui)
        check("attach mode still uses the app's own port",
              mcp_args(light, "attach", "", None)[:3] == ["mcp", "--connect", "127.0.0.1:7980"])

        notes = []
        mcp_args(pc, "gui", "", None, False, notes.append)
        check("an unconfirmed bridge warns in gui mode",
              any("will not follow" in n for n in notes))
        quiet = []
        mcp_args(light, "gui", "", None, False, quiet.append)
        check("a working bridge stays quiet", quiet == [])
        check("control ports are all distinct",
              len({gui_port(a) for a in APPS}) == len(APPS))

        # --- port negotiation -------------------------------------------------
        import socket

        wanted = gui_port(pc)
        saved_port = PORTS.get(pc.id)
        had_port_file = PORT_FILE.exists()
        blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        blocker.bind(("127.0.0.1", wanted))
        blocker.listen(1)
        try:
            picked = pick_port(pc)
            check("a taken control port is skipped",
                  picked != wanted and port_free(picked))
            check("the replacement is remembered",
                  gui_port(pc) == picked and PORTS.get(pc.id) == picked)
            check("ports.json records it",
                  PORT_FILE.exists() and str(picked) in PORT_FILE.read_text(encoding="utf-8"))
        finally:
            blocker.close()
            if saved_port is None:
                PORTS.pop(pc.id, None)
            else:
                PORTS[pc.id] = saved_port
            save_ports()
            if not had_port_file:  # leave the folder exactly as we found it
                try:
                    PORT_FILE.unlink()
                except OSError:
                    pass

        # --- detection states and fork discovery ------------------------------
        ghost = Client("ghost", "Ghost", "json", [tmp / "ghost.json"],
                       detect=[tmp / "ghost-app"])
        check("absent harness explains itself",
              ghost.status()[0] == "absent" and "would create" in ghost.status()[1])
        (tmp / "ghost-app").mkdir()
        check("creatable once the app exists", ghost.status()[0] == "creatable")
        (tmp / "ghost.json").write_text("{}", encoding="utf-8")
        check("present once the config exists", ghost.status()[0] == "present")

        forky = tmp / "appdata"
        (forky / "ForkEd" / "User").mkdir(parents=True)
        (forky / "ForkEd" / "User" / "mcp.json").write_text(
            json.dumps({"servers": {"x": {"command": "npx", "args": []}}}), encoding="utf-8")
        (forky / "NotAFork" / "User").mkdir(parents=True)
        (forky / "NotAFork" / "User" / "mcp.json").write_text('{"foo": 1}', encoding="utf-8")
        forks = code_fork_clients(forky, set())
        check("a VS Code fork is discovered", [c.label for c in forks] == ["ForkEd"])
        check("a folder without a servers object is ignored",
              all(c.label != "NotAFork" for c in forks))
        check("fork target writes under 'servers'", bool(forks) and forks[0].root_key == "servers")
        sync_client(forks[0], second)
        check("fork gets the registration, keeps its own",
              read_json_names(forky / "ForkEd" / "User" / "mcp.json", "servers")
              == {"x", "photocraft"})

        roots = mount_roots()
        check("fixed drives are enumerated", bool(roots) and all(r.exists() for r in roots))
        report = "\n".join(doctor_lines())
        check("doctor names every harness", all(c.label in report for c in CLIENTS))
        check("doctor reports app ports", "port 82" in report)

        # detection: a bogus HOME must still resolve a scoop root and all clients
        check("scoop root resolves", isinstance(SCOOP, Path) and str(SCOOP))
        check("the sixteen known harnesses are all defined", len(CLIENTS) >= 16)
        check("every client has a path", all(c.paths and c.paths[0] for c in CLIENTS))
        check("no harness path is hardcoded to a drive",
              all(not str(c.paths[0]).startswith(("C:\\", "D:\\")) or
                  str(c.paths[0]).startswith(str(HOME)) for c in CLIENTS))

    print("\nSELFTEST", "PASSED" if ok else "FAILED")
    return 0 if ok else 1


UNSUPPORTED_AI = [
    "kilo", "mimo-code", "t3code", "zcode", "jcode", "cliproxyapi",
    "agent-browser", "oh-my-pi", "openwork", "orca-ide", "unigetui",
]


MARKS = {"present": "[x]", "creatable": "[~]", "absent": "[ ]"}


def doctor_lines(only=None):
    """Every detection decision, as text: the CLI prints it, the window shows it."""
    lines = [
        f"scoop root    {SCOOP}",
        f"resolved via  {SCOOP_SOURCE}",
        f"fixed drives  {', '.join(str(d) for d in mount_roots()) or '(none)'}",
        f"port file     {PORT_FILE if PORT_FILE.exists() else '(not written yet)'}",
        "",
        "HARNESSES   [x] config present   [~] app found, config creatable   [ ] absent",
    ]
    for client in CLIENTS:
        state, why = client.status()
        lines.append(f"  {MARKS[state]} {client.label:<14} {why}")
        if state != "absent":
            for p in client.paths:
                lines.append(f"        {'exists' if p.exists() else 'absent'}  {p}")
    lines += ["", "APPS"]
    for app in APPS:
        cli, gui = exe_path(app), gui_exe(app)
        port = gui_port(app)
        bridge = ("bridge unconfirmed" if not app.bridge_ok
                  else "bridge" if app.has_bridge else "no bridge flag")
        lines.append(
            f"  {app.label:<14} CLI {'yes' if cli else 'NO'}   GUI {'yes' if gui else 'NO'}   "
            f"port {port} ({'free' if port_free(port) else 'IN USE'})   {bridge}")
        if not cli:
            lines.append(f"        looked for {SCOOP / 'shims' / (app.id + '-cli.exe')}")
    if only:
        lines.append("")
        client = CLIENT_BY_KEY.get(only)
        if client:
            state, why = client.status()
            lines.append(f"{client.label}: {state} - {why}")
        elif only in APP_BY_ID:
            app = APP_BY_ID[only]
            lines.append(f"{app.label}: CLI {exe_path(app) or 'missing'}, "
                         f"GUI {gui_exe(app) or 'missing'}, control port {gui_port(app)}")
        else:
            lines.append(f"no harness or app called {only}")
    return lines


def cmd_doctor(only=None):
    print("\n".join(doctor_lines(only)))
    return 0


def guitest(apps, log=print):
    """Open each app for real and work out whether the harness reaches that window.

    A bridge that silently falls back to a headless engine looks identical from the
    tool list alone, so we probe with the app closed first. If the closed probe still
    answers, the arguments are not reaching any window.
    """
    rows = []
    for app in apps:
        stop_gui(app, hard=True)
        time.sleep(1.0)
        args = mcp_args(app, "gui", "", None)
        if app.has_bridge:
            closed_text, closed_ok = probe(app, args, timeout=12)
        else:
            closed_text, closed_ok = "no bridge flag", False

        port, problem = launch_gui(app, None)
        if problem:
            rows.append((app.label, "failed", "", problem))
            continue
        opened = False
        for _ in range(40):
            if gui_running(app):
                opened = True
                break
            time.sleep(0.5)
        listening = False
        if opened:  # a fresh window takes a moment to bind its channel
            for _ in range(30):
                if not port_free(port):
                    listening = True
                    break
                time.sleep(0.5)
        if not opened:
            verdict = "window did not appear"
        elif not listening:
            verdict = "window open, no control port"
        elif not app.has_bridge:
            verdict = "window open, no bridge support"
        else:
            open_text, open_ok = probe(app, args, timeout=20)
            if not open_ok:
                verdict = "window open, bridge refused"
            elif not closed_ok:
                verdict = "window open, bridge OK (real: answers only with the app up)"
            elif open_text != closed_text:
                verdict = f"window open, bridge OK ({open_text} vs {closed_text} headless)"
            else:
                verdict = f"window open, bridge unconfirmed ({open_text} with or without the app)"
        rows.append((app.label, "opened" if opened else "no window",
                     f"port {port} {'up' if listening else 'down'}", verdict))
        stop_gui(app)
        time.sleep(1.0)
        if gui_running(app):
            stop_gui(app, hard=True)
            time.sleep(0.5)
    print()
    for label, state, port, verdict in rows:
        print(f"{label:<14} {state:<10} {port:<14} {verdict}")
    return rows


def cmd_check():
    print(f"scoop root       {SCOOP}   ({SCOOP_SOURCE})")
    print(f"config home      {HOME}")
    frames = ico_frames()
    print(f"icon             {ICO_FILE if ICO_FILE.exists() else 'missing'}"
          f"{'  frames: ' + ', '.join(map(str, frames)) if frames else ''}\n")
    missing = [a.label for a in APPS if not exe_path(a)]
    print(f"craft CLIs       {len(APPS) - len(missing)}/{len(APPS)} found")
    if missing:
        print(f"  missing        {', '.join(missing)}")
    guis = [a for a in APPS if gui_exe(a)]
    print(f"craft GUIs       {len(guis)}/{len(APPS)} installed  (GUI mode: --control 8200+)")
    print(f"harnesses        {sum(1 for c in CLIENTS if c.installed)}/{len(CLIENTS)} detected")
    print()
    for client in CLIENTS:
        have = registered_craft(client)
        state = ", ".join(sorted(have)) if have else "-"
        flag = "" if client.installed else "   (not detected)"
        print(f"{client.label:<14} {state}{flag}")
        for p in client.paths:
            print(f"  {'ok ' if p.exists() else 'no '}{p}")
    print("craft apps (GUI binary, control port):")
    for app in APPS:
        exe = gui_exe(app)
        print(f"  {app.label:<14} {('port ' + str(gui_port(app))) if exe else 'no GUI'}   "
              f"{exe if exe else ''}")
    print()
    found = [n for n in UNSUPPORTED_AI if (SCOOP / "apps" / n).exists()]
    print("other AI tools here (no MCP config target):")
    print("  " + (", ".join(sorted(found)) if found else "none"))
    return 0


def main():
    ap = argparse.ArgumentParser(add_help=True, description="Craft Connect")
    ap.add_argument("--check", action="store_true", help="print detection and registrations")
    ap.add_argument("--probe", metavar="APP", help="MCP handshake test for one app id")
    ap.add_argument("--gui", metavar="APP", help="open one app's window with its control channel")
    ap.add_argument("--doctor", nargs="?", const="", metavar="NAME",
                    help="explain detection: every harness, app and port")
    ap.add_argument("--guitest", nargs="*", metavar="APP",
                    help="open each app for real and test its control channel")
    ap.add_argument("--selftest", action="store_true", help="test the config writers on temp files")
    ap.add_argument("--make-icons", action="store_true", help="rebuild icons from the logo PNG")
    ap.add_argument("--smoke", action="store_true", help="build the window then exit")
    ap.add_argument("--root", default=str(Path.home() / "craft-work"))
    ap.add_argument("--mode", choices=["headless", "attach", "gui"], default="headless")
    ap.add_argument("--compact", action="store_true", help="pass --compact where supported")
    ap.add_argument("--no-tray", action="store_true", help="run without a tray icon")
    args = ap.parse_args()

    if args.make_icons:
        return 0 if make_icons() else 1
    if args.selftest:
        return selftest()
    if args.guitest is not None:
        chosen = [APP_BY_ID[a] for a in args.guitest if a in APP_BY_ID] or APPS
        guitest(chosen)
        return 0
    if args.doctor is not None:
        return cmd_doctor(args.doctor or None)
    if args.check:
        return cmd_check()
    if args.gui:
        app = APP_BY_ID.get(args.gui)
        if not app:
            print(f"unknown app {args.gui}; try one of: {', '.join(sorted(APP_BY_ID))}")
            return 2
        port, problem = launch_gui(app, print)
        if problem:
            print(problem)
            return 1
        print(f"{app.label}: control port {port}; bridge with: "
              f"{app.id}-cli {' '.join(mcp_args(app, 'gui', '', None))}")
        return 0
    if args.probe:
        app = APP_BY_ID.get(args.probe)
        if not app:
            print(f"unknown app {args.probe}; try one of: {', '.join(sorted(APP_BY_ID))}")
            return 2
        if args.root:
            Path(args.root).mkdir(parents=True, exist_ok=True)
        argv = mcp_args(app, args.mode, args.root, app.port, args.compact)
        print(f"{app.label}: {exe_path(app)} {' '.join(argv)}")
        text, ok = probe(app, argv)
        print(("OK   " if ok else "FAIL ") + text)
        return 0 if ok else 1

    import tkinter as tk

    enable_dpi_awareness()
    set_app_id()
    root = tk.Tk()
    CraftConnectWindow(root, tray=not (args.smoke or args.no_tray))
    if args.smoke:
        root.update()
        print("smoke: window", root.winfo_width(), "x", root.winfo_height(),
              "| screen", root.winfo_screenwidth(), "x", root.winfo_screenheight())
        root.destroy()
        return 0
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
