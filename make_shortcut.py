#!/usr/bin/env python3
r"""Create or refresh the Craft Connect shortcut on the Desktop.

Uses pythonw.exe so no console flashes up, points the icon at the generated
craftconnect-logo.ico, and sets the working directory to this folder.

    python make_shortcut.py                    # Desktop\Craft Connect.lnk
    python make_shortcut.py --name "Craft"     # a different label
    python make_shortcut.py --where "%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs"
    python make_shortcut.py --remove
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
SCRIPT = APP_DIR / "craftconnect.py"
ICON = APP_DIR / "craftconnect-logo.ico"
IS_WIN = os.name == "nt"


def find_pythonw():
    """pythonw next to the interpreter running this, else on PATH, else python."""
    exe = Path(sys.executable)
    for name in ("pythonw.exe", "python.exe"):
        cand = exe.with_name(name)
        if cand.exists():
            return cand
    for name in ("pythonw", "pythonw.exe", "python"):
        hit = shutil.which(name)
        if hit:
            return Path(hit)
    return exe


def desktop_dir():
    profile = os.environ.get("USERPROFILE") or str(Path.home())
    one_drive = os.environ.get("OneDrive")
    for base in (Path(profile) / "Desktop", Path(profile) / "OneDrive" / "Desktop"):
        if base.is_dir():
            return base
    if one_drive and (Path(one_drive) / "Desktop").is_dir():
        return Path(one_drive) / "Desktop"
    return Path(profile) / "Desktop"


def ps(value):
    return "'" + str(value).replace("'", "''") + "'"


def run_ps(command):
    if not IS_WIN:
        raise SystemExit("Shortcuts are a Windows feature. On other systems, make a launcher by hand.")
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", command],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise SystemExit(f"PowerShell failed:\n{result.stderr.strip() or result.stdout.strip()}")
    return result.stdout.strip()


def main():
    ap = argparse.ArgumentParser(description="Create the Craft Connect desktop shortcut")
    ap.add_argument("--name", default="Craft Connect", help="shortcut label, without .lnk")
    ap.add_argument("--where", default=None, help="folder to put the .lnk in (default: Desktop)")
    ap.add_argument("--remove", action="store_true", help="delete the shortcut instead")
    args = ap.parse_args()

    folder = Path(os.path.expandvars(args.where)) if args.where else desktop_dir()
    link = folder / f"{args.name}.lnk"

    if args.remove:
        if link.exists():
            link.unlink()
            print(f"removed {link}")
        else:
            print(f"nothing to remove at {link}")
        return 0

    if not SCRIPT.exists():
        raise SystemExit(f"craftconnect.py not found next to this script ({APP_DIR})")
    if not folder.is_dir():
        folder.mkdir(parents=True, exist_ok=True)

    pythonw = find_pythonw()
    icon = ICON if ICON.exists() else SCRIPT
    if not ICON.exists():
        print("craftconnect-logo.ico is missing, falling back to the script icon."
              " Run `python craftconnect.py --make-icons` to build it.")

    run_ps(
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut({link});"
        "$s.TargetPath = {exe};"
        "$s.Arguments = '\"' + {script} + '\"';"
        "$s.WorkingDirectory = {wd};"
        "$s.IconLocation = {icon} + ',0';"
        "$s.Description = 'Craft Connect: attach craft apps to your AI tools';"
        "$s.WindowStyle = 1;"
        "$s.Save()".format(
            link=ps(link), exe=ps(pythonw), script=ps(SCRIPT),
            wd=ps(APP_DIR), icon=ps(icon),
        )
    )

    print(f"shortcut  {link}")
    print(f"target    {pythonw}")
    print(f"arguments {SCRIPT}")
    print(f"icon      {icon}")
    print(f"workdir   {APP_DIR}")

    readback = run_ps(
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut({});"
        "'target=' + $s.TargetPath + \"`nicon=\" + $s.IconLocation + \"`nwd=\" + $s.WorkingDirectory".format(
            ps(link))
    )
    print("\nread back from the file:")
    print("  " + readback.replace("\n", "\n  "))

    exists = link.exists()
    ok = exists and str(pythonw) in readback and "craftconnect-logo.ico" in readback
    print("\n" + ("verified: the shortcut points at pythonw, this script and the logo"
                  if ok else "warning: the shortcut was written but does not read back as expected"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
