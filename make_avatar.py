#!/usr/bin/env python3
"""
Draw an avatar with PhotoCraft, over MCP, as an agent would.

This is a small MCP client: it spawns `photocraft-cli mcp` (the same server Craft
Connect registers), speaks JSON-RPC over stdio, and builds the picture out of the
engine's own commands (shape.create, batch, save). No GUI, no Photoshop.

    python make_avatar.py            # writes craft-work/avatar.png
    python make_avatar.py out.png
"""

from __future__ import annotations

import json
import math
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

HOME = Path.home()
ROOT = HOME / "craft-work"
NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def find_cli():
    """Find photocraft-cli wherever it lives. No drive or username baked in."""
    for name in ("photocraft-cli.exe", "photocraft-cli"):
        hit = shutil.which(name)
        if hit:
            return Path(hit)
    roots = [os.environ.get("SCOOP"), HOME / "scoop",
             Path(os.environ.get("USERPROFILE") or HOME) / "scoop",
             Path("C:/scoop"), Path("C:/ProgramData/scoop")]
    for root in roots:
        if not root:
            continue
        for cand in (Path(root) / "shims" / "photocraft-cli.exe",
                     Path(root) / "apps" / "photocraft" / "current" / "photocraft-cli.exe"):
            try:
                if cand.exists():
                    return cand
            except OSError:
                continue
    return Path("photocraft-cli")  # last resort: let PATH decide at spawn time


EXE = find_cli()


# --------------------------------------------------------------------------- #
# A minimal MCP client
# --------------------------------------------------------------------------- #


class MCPSession:
    def __init__(self, exe, args, timeout=60.0):
        self.timeout = timeout
        self.proc = subprocess.Popen(
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
        self.lines = queue.Queue()
        self.errors = []
        threading.Thread(target=self._read, daemon=True).start()
        threading.Thread(target=self._read_err, daemon=True).start()
        self.next_id = 0

    def _read(self):
        try:
            for line in self.proc.stdout:
                self.lines.put(line)
        except Exception:
            pass
        self.lines.put(None)

    def _read_err(self):
        try:
            for line in self.proc.stderr:
                self.errors.append(line.rstrip())
        except Exception:
            pass

    def _send(self, message):
        self.proc.stdin.write(json.dumps(message) + "\n")
        self.proc.stdin.flush()

    def request(self, method, params=None):
        self.next_id += 1
        want = self.next_id
        message = {"jsonrpc": "2.0", "id": want, "method": method}
        if params is not None:
            message["params"] = params
        self._send(message)
        end = time.time() + self.timeout
        while time.time() < end:
            try:
                line = self.lines.get(timeout=max(0.05, end - time.time()))
            except queue.Empty:
                break
            if line is None:
                break
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if not isinstance(obj, dict) or obj.get("id") != want:
                continue
            if "error" in obj:
                raise RuntimeError(f"{method}: {obj['error'].get('message', obj['error'])}")
            return obj.get("result")
        tail = " | ".join(self.errors[-3:])
        raise RuntimeError(f"{method}: no response ({tail})")

    def notify(self, method, params=None):
        message = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        self._send(message)

    def start(self):
        info = self.request(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "make-avatar", "version": "1.0"},
            },
        )
        self.notify("notifications/initialized")
        return info

    def call(self, tool, arguments=None):
        result = self.request("tools/call", {"name": tool, "arguments": arguments or {}})
        if not isinstance(result, dict):
            return result
        if result.get("isError"):
            text = " ".join(
                c.get("text", "") for c in result.get("content", []) if c.get("type") == "text"
            )
            raise RuntimeError(f"{tool} failed: {text[:400]}")
        texts = [c.get("text") for c in result.get("content", []) if c.get("type") == "text"]
        if len(texts) == 1:
            try:
                return json.loads(texts[0])
            except Exception:
                return texts[0]
        return texts or result.get("structuredContent")

    def close(self):
        try:
            self.proc.stdin.close()
        except Exception:
            pass
        try:
            self.proc.terminate()
            self.proc.wait(timeout=5)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass


# --------------------------------------------------------------------------- #
# Shapes
# --------------------------------------------------------------------------- #


def arc(cx, cy, rx, ry, a0, a1, n):
    """Points along an ellipse arc. Screen coords: 270 deg is straight up."""
    out = []
    for i in range(n):
        a = math.radians(a0 + (a1 - a0) * i / (n - 1))
        out.append([round(cx + rx * math.cos(a), 1), round(cy + ry * math.sin(a), 1)])
    return out


def curve(points):
    """A closed=False path through points, for the smile."""
    return {"subpaths": [{"closed": False, "knots": points}], "fillRule": "nonzero", "inverted": False}


def grad(stops, angle=90, style="linear"):
    return {"gradient": {"stops": stops, "angle": angle, "style": style}}


def shape(**kw):
    return {"id": "shape.create", "params": kw}


def build(cx=256.0, cy=192.0):
    """The drawing, as a list of shape.create commands, bottom layer first."""
    hair_outer = arc(cx, cy, 112, 124, 182, 358, 24)
    hair_inner = arc(cx, cy + 14, 84, 94, 358, 182, 20)
    smile = [
        [cx - 34 + 68 * t, 236 + 20 * math.sin(math.pi * t)]
        for t in [i / 12 for i in range(13)]
    ]

    return [
        # backdrop
        shape(
            kind="rect",
            rect=[0, 0, 512, 512],
            fill=grad([[0, "#182033"], [0.55, "#232c45"], [1, "#101623"]], angle=120),
            name="Backdrop",
        ),
        # warm halo behind the head
        shape(
            kind="ellipse",
            rect=[120, 40, 272, 272],
            fill=grad(
                [[0, [1.0, 0.66, 0.32, 0.45]], [1, [1.0, 0.66, 0.32, 0.0]]],
                angle=90,
                style="radial",
            ),
            name="Halo",
        ),
        # neck first, so the shirt covers where it meets the body
        shape(
            kind="rect",
            rect=[cx - 34, cy + 80, 68, 150],
            fill=grad([[0, "#e8a87c"], [1, "#cd875e"]], angle=90),
            name="Neck",
        ),
        # shoulders
        shape(
            kind="roundedRect",
            rect=[76, 352, 360, 220],
            radii=124,
            fill=grad([[0, "#5766ff"], [1, "#8a4dff"]], angle=90),
            stroke={"width": 4, "color": "#0f1522", "opacity": 60, "align": "inside"},
            name="Shoulders",
        ),
        # ears
        shape(kind="ellipse", rect=[cx - 116, 164, 32, 46], fill="#e8a87c", name="Ear L"),
        shape(kind="ellipse", rect=[cx + 84, 164, 32, 46], fill="#e8a87c", name="Ear R"),
        # head
        shape(
            kind="ellipse",
            rect=[cx - 104, cy - 116, 208, 232],
            fill=grad([[0, "#ffdcbe"], [0.6, "#f6c39c"], [1, "#e0a077"]], angle=100),
            stroke={"width": 3, "color": "#b9784f", "opacity": 45, "align": "inside"},
            name="Face",
        ),
        # hair: a crescent between two arcs of the crown
        shape(
            kind="path",
            path={"subpaths": [{"closed": True, "knots": hair_outer + hair_inner}], "fillRule": "nonzero"},
            fill=grad([[0, "#2b2431"], [1, "#1a1620"]], angle=90),
            name="Hair",
        ),
        # brows
        shape(kind="roundedRect", rect=[cx - 62, 158, 44, 8], radii=4, fill="#2b2431", name="Brow L"),
        shape(kind="roundedRect", rect=[cx + 18, 158, 44, 8], radii=4, fill="#2b2431", name="Brow R"),
        # eyes
        shape(kind="ellipse", rect=[cx - 58, 180, 36, 26], fill="#ffffff", name="Eye L"),
        shape(kind="ellipse", rect=[cx + 22, 180, 36, 26], fill="#ffffff", name="Eye R"),
        shape(kind="ellipse", rect=[cx - 48, 184, 15, 17], fill="#20202a", name="Pupil L"),
        shape(kind="ellipse", rect=[cx + 33, 184, 15, 17], fill="#20202a", name="Pupil R"),
        shape(kind="ellipse", rect=[cx - 45, 186, 5, 5], fill=[1, 1, 1, 0.9], name="Glint L"),
        shape(kind="ellipse", rect=[cx + 36, 186, 5, 5], fill=[1, 1, 1, 0.9], name="Glint R"),
        # cheeks
        shape(kind="ellipse", rect=[cx - 74, 212, 34, 20], fill=[1.0, 0.45, 0.42, 0.28], name="Blush L"),
        shape(kind="ellipse", rect=[cx + 40, 212, 34, 20], fill=[1.0, 0.45, 0.42, 0.28], name="Blush R"),
        # nose
        shape(
            kind="path",
            path=curve([[cx + 2, 198], [cx - 6, 218], [cx + 6, 221]]),
            fill=None,
            stroke={"width": 5, "color": "#cf8a5f", "opacity": 85, "cap": "round", "join": "round"},
            name="Nose",
        ),
        # smile
        shape(
            kind="path",
            path=curve(smile),
            fill=None,
            stroke={"width": 9, "color": "#8d4a33", "opacity": 90, "cap": "round", "join": "round"},
            name="Smile",
        ),
        # badge, for a bit of sparkle
        shape(
            kind="star",
            rect=[396, 404, 70, 70],
            sides=5,
            starRatio=0.46,
            cornerRadius=6,
            fill=grad([[0, "#ffd166"], [1, "#ff9f1c"]], angle=90),
            stroke={"width": 5, "color": "#121824", "opacity": 70, "align": "outside"},
            name="Badge",
        ),
    ]


def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "avatar.png"
    if not EXE.exists() and not shutil.which(EXE.name):
        print(f"photocraft-cli not found (looked for {EXE}).\n"
              "Install PhotoCraft with scoop, or put photocraft-cli on PATH.")
        return 1
    ROOT.mkdir(parents=True, exist_ok=True)

    session = MCPSession(
        EXE,
        ["mcp", "--automation-read-root", str(ROOT), "--automation-write-root", str(ROOT)],
    )
    try:
        info = session.start()
        print("connected:", info["serverInfo"]["name"], info["serverInfo"]["version"])
        tools = session.request("tools/list", {})["tools"]
        print(f"tools exposed: {len(tools)}")

        doc = session.call("doc_new", {"width": 512, "height": 512, "background": "#101623", "name": "Avatar"})
        print("document:", doc)

        steps = build()
        print(f"drawing {len(steps)} shapes ...")
        batch = session.call("command_batch", {"steps": steps})
        print(f"  completed={batch.get('completed')} failed={batch.get('failed')}")
        for i, res in enumerate(batch.get("results", [])):
            if not res.get("ok"):
                print(f"  step {i} ({steps[i]['params'].get('name')}) -> {res.get('error')}")

        state = session.call("doc_inspect", {})
        layers = state.get("layers") or state.get("document", {}).get("layers") or []
        print(f"layers now: {len(layers)}")

        saved = session.call("doc_save", {"path": out.name, "format": "png"})
        print("saved:", saved)
        print("file:", out, "size:", out.stat().st_size if out.exists() else "MISSING")
    finally:
        session.close()


if __name__ == "__main__":
    main()
