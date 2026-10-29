# claude-code-checkup

A health check and cleanup skill for [Claude Code](https://code.claude.com). It scans your setup,
builds a one-page HTML dashboard and applies only the fixes you approve, after making a backup
first.

It covers what you would otherwise piece together from `/insights`, `/context` and
`/skill-doctor`: one command and one page, with an action list ranked by impact.

## What it checks

| Area | What you get |
|---|---|
| **Skills** | Every skill and where it comes from (personal, project, plugin, claude.ai). Invalid frontmatter, a name that differs from its folder, skills installed twice, descriptions so alike that the skills compete to trigger, skills you have not used in the last 90 days |
| **Usage** | Most used skills, built-in commands and tools, and sessions per day, read from your local session history |
| **Startup context** | An estimate of what loads in every session: skill listing, CLAUDE.md files, memory index, startup hooks |
| **Plugins and hooks** | Enabled plugins and what each one brings, hooks pointing to files that no longer exist, startup hooks that inject text into every session |
| **MCP servers** | Servers that fail to connect or are waiting for authentication |
| **CLAUDE.md and memory** | Links to missing files, oversized files, memory entries without a file, files missing from the index, broken memory frontmatter |
| **Permissions** | Duplicate rules, rules already covered by a broader one, one-off rules left over from old sessions |
| **Version** | Your Claude Code version compared with the latest release |

Every action comes with an estimated token saving and a risk level. Nothing changes until you
confirm.

## Install

```bash
npx skills add dvkzone-ai/GitSkills --skill claude-code-checkup
```

The installer asks four questions. Here is what to answer and why:

1. **Which agents do you want to install to?** Claude Code is not in the visible list: type
   `claude` in the **Search** box, move to **Claude Code** (`.claude/skills`), press **Space**
   (the dot turns green) and then **Enter**.
   *Why:* Claude Code reads skills only from `.claude/skills/` and is not one of the "Universal"
   agents. If you skip it, the install succeeds but Claude Code never sees the skill. The
   Universal agents (Codex, Cursor, Gemini CLI…) are always included and only add a copy in
   `.agents/skills/`.
2. **Installation scope.** Choose **Global** (the default is Project).
   *Why:* Global makes the command available in every folder where you open Claude Code.
   Choose **Project** only to try the skill in one folder, or to share it with a team through
   that project's repository.
3. **Installation method.** With Global, keep **Symlink (Recommended)**: one copy, and
   `npx skills update` reaches every agent at once. With Project in a shared git repository,
   pick **Copy to all agents**: symlinks often arrive as plain text files on Windows checkouts.
   If the symlink fails (Windows without Developer Mode), run the installer again and pick Copy.
4. **Proceed with installation?** Check the summary first: **Claude Code** must be listed
   (otherwise go back to step 1). "overwrites" only appears if the skill is already installed
   there. The security check (Gen, Socket, Snyk) is shown before you confirm. Then answer
   **Yes**.

The first time you use the installer, it may offer to install the **find-skills** skill. That
one is unrelated and installs globally: answer **No** if you do not want it.

Then start a new Claude Code session and type `/claude-code-checkup`.

Or copy this folder into `~/.claude/skills/`.

Requires Python 3.9 or later. [PyYAML](https://pypi.org/project/PyYAML/) is optional and makes
the frontmatter check stricter.

## Use

```
/claude-code-checkup
/claude-code-checkup 30      ← look at the last 30 days of history instead of 90
```

1. **Scan.** Read-only: the skill finds your settings, skills, plugins, hooks, MCP servers,
   CLAUDE.md files, memory and history on its own. No paths are hard-coded.
2. **Dashboard.** It opens a self-contained HTML page with charts, findings and actions. The page
   works offline and has light and dark themes.
3. **Fixes.** You choose: apply the recommended fixes, pick them group by group, or keep the
   report only.
4. **Backup and undo.** Every file is backed up before it is changed, manual edits included. One
   command restores everything:
   `python scripts/apply.py --restore <report-folder>/backup`

Reports and backups are saved in `~/.claude/checkup-reports/<date>/`.

## Uninstall

Remove a skill installed globally:

```bash
npx skills remove claude-code-checkup -g
```

For a skill installed in one project, run the same command from that project's folder, without
`-g`. Use `npx skills ls -g` (or `npx skills ls` in the project) to see what is installed.

On Windows the command may end with `Assertion failed: !(handle->flags & UV_HANDLE_CLOSING)`
after "Done!". It is a known Node.js glitch on exit: the removal has already completed.

With a project install, the installer leaves behind empty `.agents/skills/` and
`.claude/skills/` folders and a `skills-lock.json` file. Delete them if you no longer need them.

If you installed the skill by copying its folder, delete that folder from `~/.claude/skills/`
(or `.claude/skills/` in the project).

**What the checkup itself leaves behind.** Removing the skill does not touch:

- **Your reports and backups** in `~/.claude/checkup-reports/`. Delete that folder to remove
  them.
- **The fixes you applied**, such as `skillOverrides`, disabled plugins or removed permission
  rules. They are ordinary Claude Code settings and stay in place. To undo them, run the restore
  **before** uninstalling, once for each report folder whose fixes you applied:

  ```bash
  python ~/.claude/skills/claude-code-checkup/scripts/apply.py --restore ~/.claude/checkup-reports/<date>/backup
  ```

  Or change them by hand: `/skills` for skill states, `/plugin` for plugins, `/permissions` for
  permission rules.

## How it changes things

- Skills are turned off or reduced only through the official
  [`skillOverrides`](https://code.claude.com/docs/en/skills) setting, and plugins through
  `enabledPlugins`. No folder is ever deleted or moved.
- It prefers `name-only` to `off` for skills you rarely use: the skill stays available from the
  `/` menu and costs only its name in the context.
- Fixes that need judgment, such as broken frontmatter or links, are shown to you first and
  backed up before the edit.

## Limits

- Token figures are estimates (about 4 characters per token). The scan cannot see the system
  prompt, built-in tools or MCP tool definitions. Run `/context` for exact numbers and paste the
  output if you want the skill to use them.
- A skill cannot run built-in slash commands. `/doctor` still covers installation health and
  updates.

## Privacy

Everything stays on your machine. The scan reads local files and runs `claude mcp list`,
`claude --version` and `npm view @anthropic-ai/claude-code version`; skip those with `--no-cli`
and `--no-network`. The report contains local paths and usage data: do not publish it.

## License

[MIT](../../LICENSE)
