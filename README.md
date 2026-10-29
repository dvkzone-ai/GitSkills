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

The installer asks a few questions:

1. **Which agents do you want to install to?** Type `claude` in the search box, press Space on
   **Claude Code**, then Enter. The "Universal" agents are always included and only add a copy
   in `.agents/skills/`.
2. **Installation scope.** **Global** installs for your user and works in every project.
   **Project** installs in the current folder only. If you already have this skill globally,
   Global replaces that copy.
3. **Installation method.** **Copy to all agents** writes a real copy for each agent; the
   symlink option keeps one copy and links the others to it. Either works.
4. **Proceed with installation?** Yes.

At the end it may offer to install the **find-skills** skill. That one is unrelated and installs
globally; answer No if you do not want it.

Then start a new Claude Code session and type `/<skill-name>`.

Or copy the skill's folder from `skills/` into `~/.claude/skills/` (personal, every project) or
`.claude/skills/` (one project).

## License

[MIT](LICENSE)
