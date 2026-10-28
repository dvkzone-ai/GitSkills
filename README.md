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

Or copy the skill's folder from `skills/` into `~/.claude/skills/` (personal, every project) or
`.claude/skills/` (one project).

## License

[MIT](LICENSE)
