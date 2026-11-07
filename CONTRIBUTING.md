# Contributing to Craft Connect

Thanks for looking. This is a small tool with one job: write the right config line into the right file,
in the right shape, without touching anything else. Changes that respect that are easy to merge.

## What this project is, and is not

Craft Connect is a connector. The craft apps it points at belong to the
[ArtCraft suite by storytold](https://github.com/storytold), and their engines, command registries and
MCP servers are that project's work. Bugs in how PhotoCraft draws a curve are not bugs here. Bugs in how
Craft Connect writes PhotoCraft's config line are.

## Setting up

```bash
git clone https://github.com/AdibSadman192/craft-connect
cd craft-connect
python -m pip install pillow pystray      # optional: icons, tray
python craftconnect.py --check            # what did it detect on your machine?
python craftconnect.py                    # the panel
```

You need Python 3.11 or newer with Tk, and the craft apps installed through scoop for anything beyond
the interface itself. `--selftest` works without them.

## Before you open a pull request

Run these three and paste the output in the PR if something changed:

```bash
python craftconnect.py --selftest    # must pass, every assertion
python craftconnect.py --doctor      # makes sure detection still resolves
python craftconnect.py --smoke       # window builds
```

If your change touches a config writer, also try it against a real harness on your machine and say which
one. If it touches GUI mode, run `python craftconnect.py --guitest <app>` for the apps you can install;
it opens each window, probes the channel with the app up and closed, and prints a verdict. Paste the
line for the app you changed.

## Adding a harness

One entry in `build_clients()` plus a fixture in `selftest()`.

```python
Client(
    "example",                       # stable id, used in the matrix keys
    "Example IDE",                   # label shown in the panel
    "json",                          # "json", "jsonc" or "toml"
    [HOME / ".example" / "mcp.json"],  # where the file lives
    style="plain",                   # entry shape: plain, opencode, vscode, zed, copilot
    root_key="mcpServers",           # the object holding the servers
    short="Example",                 # column header, keep it short
    detect=[HOME / ".example"],      # folder that proves the app is installed
    scoop=["example"],               # scoop app name, if it has one
)
```

Rules that matter:

1. Take the file path and the entry shape from a config the app wrote itself, not from a blog post. If
   you cannot find one, say so in the PR and add the path to the Limits section of the README.
2. Honour the app's own environment variable if it has one, with the documented default as fallback.
3. Never write outside the app's own objects. Existing servers and unrelated settings must survive.
4. Add a fixture to `--selftest` that registers, checks the neighbours are intact, and cleans up.
5. Add a row to the harness table in the README.

## Adding a craft app

One `App(...)` entry in `APPS`:

```python
App("examplecraft", "ExampleCraft",
    roots="automation",   # None, "automation", "rw" or "root"
    bridge="bridge",      # None, "connect", "bridge" or "attach"
    port=7979,            # only used in attach mode
    compact=True,         # only if the CLI accepts --compact
    token=True)           # only if its control channel wants a token file
```

Check `examplecraft-cli mcp --help` and copy the flags it actually lists. If the app has no bridge flag,
leave `bridge=None` and it will stay headless in GUI mode.

## House style

- Standard library only. No new dependencies, unless the feature cannot exist without one and the
  alternative is worse.
- No absolute paths, no drive letters, no usernames. Resolve everything at runtime.
- Keep writes scoped and reversible: a `.craftconnect.bak` before the first edit, and only craft named
  entries touched.
- Keep the interface dark grey, no blue, orange only for state.
- Python 3.11 syntax. `py_compile` clean, `--selftest` green.
- Copy in comments and docstrings is plain English. Avoid the long dash habit and the "it is not X, it is
  Y" reveal.

## Commit messages

One line that says what changed and why, in the imperative. Body if the reason is not obvious. Example:

```
Skip a taken control port instead of failing to bind

GUI mode assumed 8200 was free. It now walks upward, records the choice in
ports.json, and the registrations follow.
```

## Licence of contributions

By opening a pull request you agree your contribution ships under the project licence, MIT with the
attribution term in [LICENSE](LICENSE). You keep your own copyright, and you will be credited in the PR
and the changelog.

## Reporting instead of coding

That is welcome too. A clear issue with the `--doctor` output is worth more than a vague patch. See
[SECURITY.md](SECURITY.md) for anything sensitive.
