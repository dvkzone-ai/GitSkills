# GitSkills

Agent skills for [Claude Code](https://code.claude.com) and other agents that read `SKILL.md`
files. Each skill lives in its own folder under [`skills/`](skills/), with a README that explains
what it does and how to use it.

## Skills

| Skill | What it does |
|---|---|
| [claude-code-checkup](skills/claude-code-checkup/) | A health check and cleanup for your Claude Code setup. It scans skills, plugins, hooks, MCP servers, CLAUDE.md files, memory, permissions and usage, builds a one-page HTML dashboard, and applies only the fixes you approve, after making a backup. |

## Install

Install one skill:

```bash
npx skills add dvkzone-ai/GitSkills --skill <skill-name>
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

Then start a new Claude Code session and type `/<skill-name>`.

Or copy the skill's folder from `skills/` into `~/.claude/skills/` (personal, every project) or
`.claude/skills/` (one project).

## License

[MIT](LICENSE)
