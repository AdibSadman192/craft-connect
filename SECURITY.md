# Security Policy

## Reporting a vulnerability

Please do not open a public issue for anything sensitive.

Use GitHub's private reporting: go to the **Security** tab of the repository, then **Advisories**, then
**Report a vulnerability**. That opens a private channel with the maintainer. If you cannot use it, open
a public issue that says only "security issue, please make contact" and leave the details out.

What helps a report land quickly:

- what the tool did, and what you expected instead;
- the steps to reproduce, with the smallest config that shows it;
- your Python version, and the `--doctor` output with any personal paths replaced;
- whether the problem needs a local attacker, a malicious config file, or nothing at all.

Please do not include real tokens or API keys in a report. Replace them with `x` of the same length.

## Supported versions

Only the current `main` branch is supported. This is a single file tool, so fixes ship as commits rather
than backports.

## What is in scope

- Path handling, especially anything that could write outside the harness config file the user picked.
- Command construction, where a crafted app id, project root or port string could turn into extra
  arguments or a different executable.
- Handling of the loopback control token in `tokens/`, including whether it can leak into logs, config
  files, or a copy of the folder.
- The backup step, if it could overwrite or truncate a user's config.
- Anything that would send data off the machine. The tool is supposed to make no outbound calls.

## What is out of scope

- Bugs in the craft apps themselves. Those belong to the
  [ArtCraft project](https://github.com/storytold).
- Problems in scoop, Windows, or a harness's own MCP implementation.
- Attacks that already require write access to your config files, since at that point the attacker can
  simply edit them.
- The fact that MCP servers run with your user's permissions. That is how MCP works.

## What the tool is designed not to do

No telemetry, no network requests, no reading of API keys or tokens out of your configs, and no printing
of secret values. The only socket is a loopback control channel between a craft app and its CLI, on
`127.0.0.1`. If you find code that contradicts any of that, it is a bug worth reporting.
