---
name: claude-code-checkup
description: >-
  Health check and cleanup for a Claude Code setup. It finds skills, plugins, hooks, MCP servers,
  CLAUDE.md files, auto-memory, permissions and session history on its own. It then builds a single
  HTML dashboard with charts, findings and a ranked action list (estimated token saving and risk for
  each action), and applies only the fixes the user approves, after making a backup. Use it when the
  user asks to check, audit, clean up, slim down or optimise their Claude Code setup, asks which
  skills or plugins they actually use, why startup context is heavy, or wants one report in place of
  /insights, /context and /skill-doctor.
disable-model-invocation: true
argument-hint: "[days of history, default 90]"
---

# Claude Code checkup

A read-only scan, a one-page dashboard, then optional fixes chosen by the user. Everything is
discovered at runtime: never assume a folder layout, a language or a project structure.

## Ground rules

- **Read-only until the user confirms.** Steps 1–3 never change anything.
- **Never delete or move** skill folders, plugin caches or memory files. Skills are turned off only
  through the official `skillOverrides` setting, and plugins only through `enabledPlugins`.
- **Prefer `name-only` over `off`** for skills the user wrote: the skill stays callable from `/` and
  by Claude, and costs only its name in the context.
- Built-in slash commands (`/doctor`, `/context`, `/insights`…) cannot be run by a skill. Mention
  them when they help. Never pretend to have run them.
- The report contains local paths and usage data. Keep it on the user's machine and never upload it
  anywhere.

## 1. Collect (read-only)

Pick a report folder: `<claude-home>/checkup-reports/<YYYY-MM-DD-HHMM>/`. `<claude-home>` is
`$CLAUDE_CONFIG_DIR` if set, otherwise `~/.claude`. Run from the user's current project folder:

```bash
python "${CLAUDE_SKILL_DIR}/scripts/collect.py" --out "<report-dir>/snapshot.json" --project "<cwd>"
```

If `$ARGUMENTS` is a number, pass it as `--days $ARGUMENTS`. Options: `--days 90` (usage window), `--no-cli` (skip `claude mcp list` / `claude --version`),
`--no-network` (skip the latest-version lookup). On Windows, set `PYTHONIOENCODING=utf-8`.
PyYAML is optional: without it the frontmatter check falls back to a simpler parser.

The script prints a one-line JSON summary (health score, counts, estimated startup tokens).

## 2. Render the dashboard

Write the report in the language the user is using:

```bash
python "${CLAUDE_SKILL_DIR}/scripts/render.py" --data "<report-dir>/snapshot.json" --out "<report-dir>/report.html" --lang <en|it>
```

For any other language, read the `STRINGS["en"]` dictionary in `render.py`, write a JSON file with
the same keys translated (keep the `{placeholders}`), and pass it with `--strings <file>`.

Open the file in the browser (`start ""` on Windows, `open` on macOS, `xdg-open` on Linux) and give
the user its full path.

## 3. Summarise in chat

Give a short summary: the health score, the estimated startup context, the recommended saving, and
the 3 most important findings in plain words. Then mention two optional extras:
- For **exact** token figures, the user can run `/context` and paste the output. Use those numbers
  in place of the estimates when discussing savings. The scan cannot see the system prompt, the
  built-in tools or the MCP tool definitions.
- `/doctor` still covers installation health and updates. Suggest it at the end.

Check the snapshot for skills set to `off` that look like the user's own work, for example personal
or project skills with their own scripts or references. Point these out: `name-only` is usually the
better choice for them.

## 4. Offer the fixes

Read `actions` in `snapshot.json`. They are already ranked by impact, and each one has an `id`, a
`group`, a `saving_tokens` estimate, a `risk` and a `recommended` flag. Ask with the
question tool, the same way `/doctor` does:

1. First question: **Apply the recommended actions** (list the total saving and the risk) /
   **Let me choose** / **Report only**.
2. If the user picks "Let me choose", ask one multi-select question per group, at most 4 options
   each. Use the action title, saving and risk as the option text. Groups: `repair`, `duplicates`,
   `unused`, `permissions`, `plugins`, `safety`.

Explain any action with `risk` "medium" before the user picks it. Disabling a plugin also removes
its hooks, commands, agents and MCP servers.

## 5. Apply with a backup

Settings-level actions (`apply` is not null):

```bash
python "${CLAUDE_SKILL_DIR}/scripts/apply.py" --data "<report-dir>/snapshot.json" --ids <id1,id2,...> --backup-dir "<report-dir>/backup" --dry-run
```

Show the dry-run changes to the user. Then run the same command without `--dry-run`. The script
copies every file it touches into the backup folder before writing, and records the copies in a
`manifest.json`.

Manual actions (`apply` is null: frontmatter, broken links, broken hooks, MCP, update) are not
automated. For each one, show the exact edit or command and make it only after the user says yes.
**Before editing any file by hand, back it up into the same folder** so that `--restore` undoes
manual edits too:

```bash
python "${CLAUDE_SKILL_DIR}/scripts/apply.py" --backup-files "<file1>" "<file2>" --backup-dir "<report-dir>/backup"
```

- **Invalid frontmatter**: usually an unquoted `: ` inside `description`. Rewrite the value as a
  YAML block scalar (`description: >-` followed by the text indented on the next lines). If the
  same skill exists in more than one place (a working copy and an archive copy, for instance),
  edit every copy.
- **Broken links**: fix the path, or ask whether to remove the link.
- **MCP servers** that fail or need auth: the user runs `/mcp` or `claude mcp`. A local server
  that is simply not running is not an error.
- **Update**: `claude update`, or the update path of the user's install method.

## 6. Close

Run steps 1–2 again into a new report folder and show the before/after difference: health score,
startup tokens, skills listed. Then tell the user:
- the changes take effect in a **new session**;
- how to undo everything, automated and manual edits alike: `python "${CLAUDE_SKILL_DIR}/scripts/apply.py" --restore "<report-dir>/backup"`;
- to run `/doctor` for installation checks, if they want.

## Files

- `scripts/collect.py`: discovery, usage stats, findings and actions → JSON.
- `scripts/render.py`: JSON → self-contained HTML dashboard (inline SVG charts, light/dark, no network).
- `scripts/apply.py`: applies selected action ids with a backup, and `--restore` undoes them.
