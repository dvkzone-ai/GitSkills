#!/usr/bin/env python3
"""Read-only snapshot of a Claude Code setup.

Discovers settings, skills, plugins, hooks, MCP servers, CLAUDE.md files,
auto-memory, permissions and session history, then derives findings and
recommended actions. Writes one JSON file; never modifies anything.

Usage:
  python collect.py --out snapshot.json [--project DIR] [--days 90]
                    [--no-cli] [--no-network]
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import unquote

try:
    import yaml  # PyYAML, optional
except ImportError:
    yaml = None

SKIP_DIRS = {".git", "node_modules", "venv", ".venv", "__pycache__", "dist",
             "build", ".next", ".cache", "site-packages", ".superpowers", "worktrees"}
SELF = "claude-code-checkup"
CHARS_PER_TOKEN = 4  # rough estimate, labelled as such in the report
STOPWORDS = set("""the and for with this that when use user skill from into your you are any not
use una per con che del della dei delle quando questa questo come uso usa usare skill""".split())


def tok(text):
    return round(len(text or "") / CHARS_PER_TOKEN)


def read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def read_text(path):
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def run(cmd, timeout):
    exe = shutil.which(cmd[0])
    if not exe:
        return None
    try:
        r = subprocess.run([exe] + cmd[1:], capture_output=True, text=True,
                           timeout=timeout, encoding="utf-8", errors="replace")
        return (r.stdout or "") + (r.stderr or "")
    except (OSError, subprocess.TimeoutExpired):
        return None


# ---------------------------------------------------------------- discovery

def claude_home():
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def managed_settings_path():
    if sys.platform.startswith("win"):
        return Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "ClaudeCode" / "managed-settings.json"
    if sys.platform == "darwin":
        return Path("/Library/Application Support/ClaudeCode/managed-settings.json")
    return Path("/etc/claude-code/managed-settings.json")


def walk_limited(root, max_depth):
    root = Path(root)
    for dirpath, dirnames, filenames in os.walk(root):
        depth = len(Path(dirpath).relative_to(root).parts)
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".") or d == ".claude"]
        if depth >= max_depth:
            dirnames[:] = []
        yield Path(dirpath), dirnames, filenames


def load_settings(home, root):
    scopes = [
        ("user", home / "settings.json"),
        ("project", root / ".claude" / "settings.json"),
        ("local", root / ".claude" / "settings.local.json"),
        ("managed", managed_settings_path()),
    ]
    out = []
    for name, path in scopes:
        data = read_json(path) if path.exists() else None
        out.append({"scope": name, "path": str(path), "exists": path.exists(),
                    "valid": data is not None or not path.exists(), "data": data or {}})
    return out


def merged(settings, key):
    """Merge a dict-valued key; later (more specific) scopes win, managed wins last."""
    order = ["user", "project", "local", "managed"]
    res = {}
    for s in sorted(settings, key=lambda s: order.index(s["scope"])):
        val = s["data"].get(key)
        if isinstance(val, dict):
            res.update(val)
    return res


# ---------------------------------------------------------------- frontmatter

def parse_frontmatter(text):
    if not text.startswith("---"):
        return None, "missing frontmatter"
    end = re.search(r"^---\s*$", text[3:], re.M)
    if not end:
        return None, "frontmatter not closed"
    raw = text[3:3 + end.start()]
    if yaml:
        try:
            data = yaml.safe_load(raw) or {}
            if not isinstance(data, dict):
                return None, "frontmatter is not a mapping"
            return data, None
        except yaml.YAMLError as e:
            return None, "invalid YAML: " + str(e).splitlines()[0]
    data, err = {}, None
    for line in raw.splitlines():
        m = re.match(r"^([A-Za-z_-]+):\s*(.*)$", line)
        if m:
            key, val = m.groups()
            data[key] = val.strip("'\"")
            if val and val[0] not in "'\">|" and re.search(r":\s", val):
                err = "invalid YAML: unquoted ': ' in " + key
    return (None, err) if err else (data, None)


# ---------------------------------------------------------------- skills & plugins

def age_days(path):
    try:
        st = path.stat()
        born = getattr(st, "st_birthtime", None) or (st.st_ctime if sys.platform.startswith("win") else st.st_mtime)
        return (datetime.now().timestamp() - born) / 86400
    except OSError:
        return None


def find_suites(skills):
    """Group local skills that link into each other's folders (../name/...) into suites."""
    local = [s for s in skills if s["source"] in ("personal", "project")]
    names = {s["folder"]: s for s in local if len(s["folder"]) >= 4}
    parent = {n: n for n in names}

    def root(n):
        while parent[n] != n:
            parent[n] = parent[parent[n]]
            n = parent[n]
        return n
    for s in local:
        text = s.get("_text", "")
        for other in names:
            if other != s["folder"] and s["folder"] in names and re.search(
                    r"\.\./%s/" % re.escape(other), text):
                parent[root(s["folder"])] = root(other)
    groups = defaultdict(list)
    for n in names:
        groups[root(n)].append(n)
    suites = {}
    for members in groups.values():
        if len(members) >= 3:
            counts = Counter()
            for m in members:
                for o in members:
                    if o != m and o in names[m].get("_text", ""):
                        counts[o] += 1
            label = counts.most_common(1)[0][0] if counts else sorted(members)[0]
            for m in members:
                suites[m] = label
    return suites


def scan_skill_dir(base, source, plugin=None, prefix=""):
    found = []
    if not base.is_dir():
        return found
    for d in sorted(base.iterdir()):
        md = d / "SKILL.md"
        if not md.is_file():
            continue
        text = read_text(md)
        fm, err = parse_frontmatter(text)
        fm = fm or {}
        name = str(fm.get("name") or d.name)
        desc = str(fm.get("description") or "")
        extra = str(fm.get("when_to_use") or "")
        found.append({
            "name": prefix + name, "base_name": name, "folder": d.name, "source": source,
            "plugin": plugin, "path": str(md), "frontmatter_error": err,
            "name_mismatch": bool(fm.get("name")) and str(fm.get("name")) != d.name,
            "desc_chars": len(desc + extra), "desc_tokens": tok(desc + extra),
            "name_tokens": max(1, tok(prefix + name)),
            "disable_model_invocation": str(fm.get("disable-model-invocation")).lower() == "true",
            "user_invocable": str(fm.get("user-invocable", "true")).lower() != "false",
            "description": desc[:400],
            "age_days": age_days(md),
            "_text": text,
        })
    return found


def scan_plugins(home, enabled_map):
    reg = read_json(home / "plugins" / "installed_plugins.json") or {}
    plugins = []
    for key, entries in (reg.get("plugins") or {}).items():
        entry = entries[0] if isinstance(entries, list) and entries else (entries or {})
        path = Path(entry.get("installPath") or "")
        short = key.split("@")[0]
        hooks = read_json(path / "hooks" / "hooks.json") or {}
        hooks = hooks.get("hooks", hooks) if isinstance(hooks, dict) else {}
        mcp = read_json(path / ".mcp.json") or {}
        plugins.append({
            "key": key, "name": short, "version": entry.get("version"),
            "path": str(path), "exists": path.is_dir(),
            "enabled": bool(enabled_map.get(key, False)),
            "skills": scan_skill_dir(path / "skills", "plugin", key, short + ":"),
            "commands": sorted(p.stem for p in (path / "commands").glob("*.md")) if path.is_dir() else [],
            "agents": sorted(p.stem for p in (path / "agents").glob("*.md")) if path.is_dir() else [],
            "hooks": hooks if isinstance(hooks, dict) else {},
            "mcp_servers": sorted((mcp.get("mcpServers", mcp) or {}).keys()) if isinstance(mcp, dict) else [],
        })
    return plugins


def collect_skills(home, root, plugins, overrides):
    skills = []
    skills += scan_skill_dir(home / "skills", "personal")
    synced = home / "skills" / "synced"
    if synced.is_dir():
        for acct in synced.iterdir():
            if acct.is_dir():
                # claude.ai skills are listed under this namespace in Claude Code
                skills += scan_skill_dir(acct, "claude.ai", prefix="anthropic-skills:")
                skills += scan_skill_dir(acct / "skills", "claude.ai", prefix="anthropic-skills:")
    skills += scan_skill_dir(root / ".claude" / "skills", "project")
    for d, dirs, _ in walk_limited(root, 4):
        if d != root and (d / ".claude" / "skills").is_dir():
            skills += scan_skill_dir(d / ".claude" / "skills", "nested")
    for p in plugins:
        for s in p["skills"]:
            s["plugin_enabled"] = p["enabled"]
            skills.append(s)
    for s in skills:
        state = "on"
        if s["source"] != "plugin":
            state = overrides.get(s["name"], "on")
        elif not s.get("plugin_enabled"):
            state = "plugin-disabled"
        s["state"] = state
        if s["source"] == "nested":
            s["listing_tokens"] = 0  # loaded only in sessions started inside that subfolder
        elif state in ("off", "user-invocable-only", "plugin-disabled") or s["disable_model_invocation"]:
            s["listing_tokens"] = 0
        elif state == "name-only":
            s["listing_tokens"] = s["name_tokens"]
        else:
            s["listing_tokens"] = s["name_tokens"] + s["desc_tokens"]
    return skills


# ---------------------------------------------------------------- hooks

PATH_RE = re.compile(r"""(?:"([^"]+\.(?:sh|py|js|mjs|cjs|ps1|cmd|bat|ts))"|'([^']+\.(?:sh|py|js|mjs|cjs|ps1|cmd|bat|ts))'|(\S+\.(?:sh|py|js|mjs|cjs|ps1|cmd|bat|ts)))""")


def iter_hooks(hooks_obj, origin, plugin_root=None):
    for event, groups in (hooks_obj or {}).items():
        if not isinstance(groups, list):
            continue
        for g in groups:
            for h in (g or {}).get("hooks", []) or []:
                cmd = h.get("command") or ""
                missing = []
                for m in PATH_RE.finditer(cmd):
                    p = next(x for x in m.groups() if x)
                    if "$" in p.replace("${CLAUDE_PLUGIN_ROOT}", "").replace("$CLAUDE_PLUGIN_ROOT", ""):
                        continue
                    if plugin_root:
                        p = p.replace("${CLAUDE_PLUGIN_ROOT}", plugin_root).replace("$CLAUDE_PLUGIN_ROOT", plugin_root)
                    p = os.path.expanduser(p)
                    if (os.path.isabs(p) or p.startswith(".")) and not os.path.exists(p):
                        missing.append(p)
                yield {"origin": origin, "event": event, "matcher": g.get("matcher", ""),
                       "type": h.get("type", "command"), "command": cmd[:300],
                       "missing_paths": missing}


# ---------------------------------------------------------------- CLAUDE.md & memory

LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
IMPORT_RE = re.compile(r"(?:^|\s)@((?:~|\.{1,2})?[\w./\\-]+\.\w{1,5})\b", re.M)


def broken_links(path, text):
    base = Path(path).parent
    bad = []
    stripped = re.sub(r"```.*?```", "", text, flags=re.S)
    stripped = re.sub(r"`[^`]*`", "", stripped)
    targets = [m.group(1) for m in LINK_RE.finditer(stripped)]
    targets += [m.group(1) for m in IMPORT_RE.finditer(stripped)]
    for t in targets:
        if re.match(r"^[a-z][a-z0-9+.-]*:", t, re.I) or t.startswith("#"):
            continue
        t = unquote(t.split("#")[0])
        if not t:
            continue
        p = Path(os.path.expanduser(t))
        p = p if p.is_absolute() else base / p
        if not p.exists():
            bad.append(t)
    return sorted(set(bad))


def collect_claude_md(home, root):
    files = []

    def add(path, kind, startup):
        path = Path(path)
        if path.is_file() and str(path) not in {f["path"] for f in files}:
            text = read_text(path)
            files.append({"path": str(path), "kind": kind, "loaded_at_startup": startup,
                          "lines": text.count("\n") + 1, "tokens": tok(text),
                          "broken_links": broken_links(path, text)})

    add(home / "CLAUDE.md", "user", True)
    d = root
    while True:
        for n in ("CLAUDE.md", "CLAUDE.local.md", ".claude/CLAUDE.md"):
            add(d / n, "project" if d == root else "ancestor", True)
        if d.parent == d:
            break
        d = d.parent
    for d, _, fnames in walk_limited(root, 5):
        if d != root and "CLAUDE.md" in fnames:
            add(d / "CLAUDE.md", "nested", False)
    return files


def project_slug(root):
    return re.sub(r"[^A-Za-z0-9]", "-", str(root))


def collect_memory(home, root):
    projects = home / "projects"
    slug = project_slug(root).lower()
    mem_dir = None
    if projects.is_dir():
        for d in projects.iterdir():
            if d.name.lower() == slug and (d / "memory").is_dir():
                mem_dir = d / "memory"
                break
    if not mem_dir:
        return {"dir": None}
    index = mem_dir / "MEMORY.md"
    text = read_text(index)
    linked = {unquote(m.group(1).split("#")[0]) for m in LINK_RE.finditer(text)}
    files = sorted(p.name for p in mem_dir.glob("*.md") if p.name != "MEMORY.md")
    bad_fm = []
    for f in files:
        fm, err = parse_frontmatter(read_text(mem_dir / f))
        if err or not (fm or {}).get("description"):
            bad_fm.append(f)
    return {
        "dir": str(mem_dir), "index_exists": index.exists(),
        "index_lines": text.count("\n") + 1 if text else 0,
        "index_tokens": tok("\n".join(text.splitlines()[:200])),
        "files": len(files),
        "missing": sorted(l for l in linked if not (mem_dir / l).exists()),
        "orphans": sorted(f for f in files if f not in linked),
        "bad_frontmatter": bad_fm,
    }


# ---------------------------------------------------------------- permissions

ONE_OFF_RE = re.compile(r"(\\Temp\\|/tmp/|\\tmp\\|scratchpad|AppData[\\/]+Local[\\/]+Temp|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", re.I)


def rule_prefix(rule):
    m = re.match(r"^(\w+)\((.*)\)$", rule)
    if not m:
        return None
    tool, inner = m.groups()
    for suf in (":*", " *", "*", "/**"):
        if inner.endswith(suf) and len(inner) > len(suf):
            return tool, inner[: -len(suf)]
    return None


def collect_permissions(settings):
    rules = []
    for s in settings:
        perms = s["data"].get("permissions") or {}
        for lst in ("allow", "deny", "ask"):
            for r in perms.get(lst) or []:
                rules.append({"scope": s["scope"], "file": s["path"], "list": lst, "rule": r})
    seen = Counter((r["list"], r["rule"]) for r in rules)
    broad = [(r, rule_prefix(r["rule"])) for r in rules]
    broad = [(r, p) for r, p in broad if p]
    for r in rules:
        flags = []
        if seen[(r["list"], r["rule"])] > 1:
            flags.append("duplicate")
        m = re.match(r"^(\w+)\((.*)\)$", r["rule"])
        if m:
            tool, inner = m.groups()
            for b, (btool, bprefix) in broad:
                if b is not r and b["list"] == r["list"] and btool == tool \
                        and inner != b["rule"][len(tool) + 1:-1] and inner.startswith(bprefix):
                    flags.append("covered")
                    r["covered_by"] = b["rule"]
                    break
            if r["list"] == "allow" and (ONE_OFF_RE.search(inner) or len(inner) > 160):
                flags.append("one-off")
        r["flags"] = flags
    return rules


# ---------------------------------------------------------------- usage

CMD_RE = re.compile(r"<command-name>/?([^<]+)</command-name>")


def collect_usage(home, days):
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    since30 = now - timedelta(days=30)
    skills90, skills30, slash, slash30, tools, models = (Counter() for _ in range(6))
    last_used = {}
    per_day = Counter()
    hook_inject = []
    sessions = 0
    projects = home / "projects"
    files = []
    if projects.is_dir():
        for p in projects.rglob("*.jsonl"):
            try:
                if datetime.fromtimestamp(p.stat().st_mtime, timezone.utc) >= since:
                    files.append(p)
            except OSError:
                pass
    for path in files:
        is_sub = "subagents" in path.parts
        first_ts, injected = None, None
        try:
            fh = open(path, encoding="utf-8", errors="replace")
        except OSError:
            continue
        with fh:
            for line in fh:
                if not any(k in line for k in ('"tool_use"', "command-name", "hook_success", '"timestamp"')):
                    continue
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                ts = ev.get("timestamp")
                try:
                    t = datetime.fromisoformat(ts.replace("Z", "+00:00")) if ts else None
                except (ValueError, AttributeError):
                    t = None
                if t and first_ts is None:
                    first_ts = t
                if t and t < since:
                    continue
                att = ev.get("attachment") or {}
                if att.get("type") == "hook_success" and str(att.get("hookEvent")) == "SessionStart":
                    injected = (injected or 0) + tok(att.get("stdout", "")) + tok(att.get("content", ""))
                msg = ev.get("message") or {}
                if ev.get("type") == "assistant":
                    if msg.get("model") and not is_sub:
                        models[msg["model"]] += 1
                    for c in msg.get("content") or []:
                        if isinstance(c, dict) and c.get("type") == "tool_use":
                            tools[c.get("name")] += 1
                            if c.get("name") == "Skill":
                                name = str((c.get("input") or {}).get("skill", "")).lstrip("/")
                                if name:
                                    skills90[name] += 1
                                    if t and t >= since30:
                                        skills30[name] += 1
                                    if t:
                                        last_used[name] = max(last_used.get(name, ""), t.date().isoformat())
                elif ev.get("type") == "user":
                    content = msg.get("content")
                    texts = [content] if isinstance(content, str) else [
                        c.get("text", "") for c in content or [] if isinstance(c, dict)]
                    for tx in texts:
                        for m in CMD_RE.finditer(tx or ""):
                            name = m.group(1).strip()
                            slash[name] += 1
                            if t:
                                last_used[name] = max(last_used.get(name, ""), t.date().isoformat())
                            if t and t >= since30:
                                slash30[name] += 1
        if not is_sub and first_ts and first_ts >= since:
            sessions += 1
            per_day[first_ts.date().isoformat()] += 1
            if injected is not None:
                hook_inject.append(injected)
    days30 = [(now - timedelta(days=i)).date().isoformat() for i in range(29, -1, -1)]
    return {
        "window_days": days, "sessions": sessions,
        "sessions_per_day_30": [[d, per_day.get(d, 0)] for d in days30],
        "skill_calls_90": dict(skills90), "skill_calls_30": dict(skills30),
        "slash_commands": dict(slash), "slash_commands_30": dict(slash30), "tools": dict(tools.most_common(25)),
        "models": dict(models), "last_used": last_used,
        "startup_hook_tokens_avg": round(sum(hook_inject) / len(hook_inject)) if hook_inject else 0,
        "transcripts_scanned": len(files),
    }


def uses_of(skill, usage):
    names = {skill["name"], skill["base_name"], skill["folder"]}
    n90 = sum(usage["skill_calls_90"].get(n, 0) + usage["slash_commands"].get(n, 0) for n in names)
    n30 = sum(usage["skill_calls_30"].get(n, 0) + usage["slash_commands_30"].get(n, 0) for n in names)
    last = max((usage["last_used"].get(n, "") for n in names), default="")
    return n90, n30, last


# ---------------------------------------------------------------- MCP & version

def collect_mcp(home, root, use_cli):
    servers = []
    cfg = read_json(Path.home() / ".claude.json") or {}
    for n in (cfg.get("mcpServers") or {}):
        servers.append({"name": n, "scope": "user", "status": "unknown"})
    proj = (cfg.get("projects") or {})
    for k, v in proj.items():
        if Path(k).as_posix().lower() == root.as_posix().lower():
            for n in (v.get("mcpServers") or {}):
                servers.append({"name": n, "scope": "local", "status": "unknown"})
    for n in ((read_json(root / ".mcp.json") or {}).get("mcpServers") or {}):
        servers.append({"name": n, "scope": "project", "status": "unknown"})
    if use_cli:
        out = run(["claude", "mcp", "list"], 120)
        if out:
            known = {s["name"]: s for s in servers}
            for line in out.splitlines():
                m = re.match(r"^(.+?):\s+(.+?)\s+-\s+(.+)$", line.strip())
                if not m:
                    continue
                name, target, status_txt = m.groups()
                low = status_txt.lower()
                status = ("connected" if "connected" in low else "needs-auth" if "auth" in low
                          else "disabled" if "disabled" in low else "failed" if "fail" in low else "unknown")
                s = known.get(name) or {"name": name, "scope": "plugin" if name.startswith("plugin:")
                                        else "claude.ai" if name.startswith("claude.ai") else "other"}
                s.update({"status": status, "target": target[:120]})
                if name not in known:
                    servers.append(s)
                    known[name] = s
    return servers


def collect_version(use_cli, use_network):
    cur = run(["claude", "--version"], 30) if use_cli else None
    cur = re.search(r"\d+\.\d+\.\d+", cur or "")
    latest = run(["npm", "view", "@anthropic-ai/claude-code", "version"], 30) if use_network else None
    latest = re.search(r"\d+\.\d+\.\d+", latest or "")
    return {"current": cur.group(0) if cur else None, "latest": latest.group(0) if latest else None}


# ---------------------------------------------------------------- analysis

def words(text):
    return {w for w in re.findall(r"[a-zàèéìòù]{4,}", text.lower()) if w not in STOPWORDS}


def vtuple(v):
    return tuple(int(x) for x in v.split(".")) if v else ()


def analyse(snap):
    F, A = [], []
    skills, usage = snap["skills"], snap["usage"]

    def finding(code, severity, area, items=None, **params):
        F.append({"code": code, "severity": severity, "area": area,
                  "items": items or [], "params": params})

    def action(id_, code, group, saving, risk, recommended, apply=None, items=None, **params):
        A.append({"id": id_, "code": code, "group": group, "saving_tokens": saving, "risk": risk,
                  "recommended": recommended, "apply": apply, "items": items or [], "params": params})

    for s in skills:
        s["uses_90"], s["uses_30"], s["last_used"] = uses_of(s, usage)

    bad = [s for s in skills if s["frontmatter_error"]]
    if bad:
        finding("frontmatter_invalid", "critical", "skills",
                [f'{s["name"]}: {s["frontmatter_error"]}' for s in bad], n=len(bad))
        action("fix-frontmatter", "fix_frontmatter", "repair", 0, "none", True,
               None, [s["path"] for s in bad], n=len(bad))
    mism = [s for s in skills if s["name_mismatch"]]
    if mism:
        finding("name_mismatch", "warning", "skills", [f'{s["name"]} ≠ {s["folder"]}/' for s in mism], n=len(mism))

    listed = [s for s in skills if s["listing_tokens"] > 0]
    by_base = defaultdict(list)
    for s in listed:
        by_base[s["base_name"].lower()].append(s)
    dups = [v for v in by_base.values() if len(v) > 1]
    if dups:
        fixable = any(s["source"] in ("personal", "project") for g in dups for s in g)
        finding("duplicates", "serious" if fixable else "info", "skills",
                [" / ".join(f'{s["name"]} ({s["source"]})' for s in g) for g in dups], n=len(dups))
        for g in dups:
            keep = sorted(g, key=lambda s: (-s["uses_90"], s["source"] == "personal"))[0]
            for s in g:
                if s is not keep and s["source"] in ("personal", "project"):
                    # skillOverrides is keyed by name: same-name copies can only be fixed by removing a folder
                    same = s["name"] == keep["name"]
                    action(f'dup-{s["source"]}-{s["name"]}', "dup_remove" if same else "dup_off", "duplicates",
                           s["listing_tokens"], "low", not same,
                           None if same else {"type": "skill_override", "name": s["name"], "state": "off"},
                           [s["path"]] if same else [], name=s["name"], keep=keep["name"])

    cands = [s for s in listed if s["desc_tokens"] > 10 and s["state"] == "on"]  # name-only shows no description
    pairs = []
    for i, a in enumerate(cands):
        wa = words(a["description"])
        for b in cands[i + 1:]:
            if a["base_name"].lower() == b["base_name"].lower():
                continue
            wb = words(b["description"])
            if wa and wb and len(wa & wb) / len(wa | wb) >= 0.42:
                pairs.append(f'{a["name"]} ~ {b["name"]}')
    if pairs:
        finding("similar_descriptions", "warning", "skills", pairs[:15], n=len(pairs))

    suites = snap.get("suites", {})
    dup_names = {x["params"]["name"] for x in A if x["code"] in ("dup_off", "dup_remove")}
    young = 30
    unused = [s for s in listed if s["uses_90"] == 0 and s["source"] != "plugin"
              and s["state"] == "on" and s["name"] not in dup_names and s["name"] != SELF
              and (s["age_days"] is None or s["age_days"] >= young)]
    auto = [s for s in unused if s["source"] in ("personal", "project")]  # claude.ai skills are managed on claude.ai
    families = defaultdict(list)
    for s in auto:
        if s["folder"] in suites:
            families[suites[s["folder"]]].append(s)
    in_family = set()
    for fam, members in sorted(families.items()):
        if len(members) >= 3:
            in_family.update(m["name"] for m in members)
            action(f"suite-{fam}", "family_off", "unused", sum(m["listing_tokens"] for m in members),
                   "low", False, {"type": "skill_override_many", "names": [m["name"] for m in members], "state": "off"},
                   [m["name"] for m in members], family=fam, n=len(members))
    rest = list({s["name"]: s for s in auto if s["name"] not in in_family}.values())
    if unused:
        finding("unused_skills", "info", "skills", [s["name"] for s in unused],
                n=len(unused), days=usage["window_days"])
    if rest:
        action("unused-name-only", "unused_name_only", "unused",
               sum(s["desc_tokens"] for s in rest), "low", True,
               {"type": "skill_override_many", "names": [s["name"] for s in rest], "state": "name-only"},
               [s["name"] for s in rest], n=len(rest))

    listed_bases = {s["base_name"].lower() for s in listed}
    off = [s for s in skills if s["state"] == "off" and s["source"] in ("personal", "project")
           and s["folder"] not in suites and s["base_name"].lower() not in listed_bases]
    if off:
        finding("skills_off", "info", "skills", [s["name"] for s in off], n=len(off))
        action("off-to-name-only", "off_name_only", "safety", -sum(s["name_tokens"] for s in off), "none", False,
               {"type": "skill_override_many", "names": [s["name"] for s in off], "state": "name-only"},
               [s["name"] for s in off], n=len(off))
    used_off = [s for s in skills if s["state"] == "off" and s["uses_30"] > 0]
    if used_off:
        finding("used_but_off", "serious", "skills", [s["name"] for s in used_off], n=len(used_off))

    for p in snap["plugins"]:
        if not p["enabled"]:
            continue
        own = [s for s in skills if s.get("plugin") == p["key"]]
        names = {p["name"]} | {s["base_name"] for s in own} | set(p["commands"])
        calls = sum(v for k, v in list(usage["skill_calls_90"].items()) + list(usage["slash_commands"].items())
                    if k.split(":")[0] == p["name"] or k.split(":")[-1] in names)
        p["uses_90"] = calls
        has_start_hook = "SessionStart" in p["hooks"]
        p["startup_hook"] = has_start_hook
        if calls == 0 and not p["mcp_servers"]:
            action(f'plugin-{p["name"]}', "plugin_off", "plugins",
                   sum(s["listing_tokens"] for s in own), "medium", False,
                   {"type": "plugin_disable", "key": p["key"]}, name=p["name"], hook=has_start_hook)
    if usage["startup_hook_tokens_avg"] > 1500:
        finding("heavy_startup_hooks", "warning", "context",
                [p["name"] for p in snap["plugins"] if p.get("startup_hook") and p["enabled"]],
                tokens=usage["startup_hook_tokens_avg"])

    broken = [h for h in snap["hooks"] if h["missing_paths"]]
    if broken:
        finding("broken_hooks", "critical", "hooks",
                [f'{h["origin"]} · {h["event"]}: {", ".join(h["missing_paths"])}' for h in broken], n=len(broken))
        action("fix-hooks", "fix_hooks", "repair", 0, "none", True, None, n=len(broken))

    mcp_bad = [m for m in snap["mcp"] if m.get("status") in ("failed", "needs-auth")]
    if mcp_bad:
        finding("mcp_problems", "warning", "mcp", [f'{m["name"]}: {m["status"]}' for m in mcp_bad], n=len(mcp_bad))
        action("fix-mcp", "fix_mcp", "repair", 0, "none", False, None, [m["name"] for m in mcp_bad], n=len(mcp_bad))

    links = [(f["path"], l) for f in snap["claude_md"] for l in f["broken_links"]]
    if links:
        finding("broken_links", "warning", "claude_md", [f"{Path(p).name}: {l}" for p, l in links], n=len(links))
        action("fix-links", "fix_links", "repair", 0, "none", True, None, n=len(links))
    big = [f for f in snap["claude_md"] if f["loaded_at_startup"] and (f["lines"] > 250 or f["tokens"] > 4000)]
    if big:
        finding("big_claude_md", "warning", "claude_md", [f'{f["path"]} ({f["lines"]} lines, ~{f["tokens"]} tok)' for f in big])

    mem = snap["memory"]
    if mem.get("dir"):
        if mem["missing"]:
            finding("memory_missing", "warning", "memory", mem["missing"], n=len(mem["missing"]))
        if mem["orphans"]:
            finding("memory_orphans", "info", "memory", mem["orphans"], n=len(mem["orphans"]))
        if mem["index_lines"] > 200:
            finding("memory_truncated", "serious", "memory", [], lines=mem["index_lines"])
        if mem["bad_frontmatter"]:
            finding("memory_bad_frontmatter", "warning", "memory", mem["bad_frontmatter"], n=len(mem["bad_frontmatter"]))

    for flag, risk, rec in (("duplicate", "none", True), ("covered", "none", True), ("one-off", "low", True)):
        rs = [r for r in snap["permissions"] if flag in r["flags"]]
        if flag == "one-off":
            rs = [r for r in rs if "duplicate" not in r["flags"] and "covered" not in r["flags"]]
        if rs:
            finding(f"perm_{flag.replace('-', '_')}", "info", "permissions", [r["rule"][:140] for r in rs], n=len(rs))
            action(f"perm-{flag}", f"perm_{flag.replace('-', '_')}", "permissions", 0, risk, rec,
                   {"type": "permission_remove", "rules": [{"file": r["file"], "list": r["list"], "rule": r["rule"]} for r in rs]},
                   n=len(rs))

    v = snap["version"]
    if v["current"] and v["latest"] and vtuple(v["current"]) < vtuple(v["latest"]):
        finding("outdated", "warning", "version", [], current=v["current"], latest=v["latest"])
        action("update", "update", "repair", 0, "low", True, None, current=v["current"], latest=v["latest"])

    for s in snap["settings"]:
        if s["exists"] and not s["valid"]:
            finding("settings_invalid", "critical", "settings", [s["path"]])

    weights = {"critical": 15, "serious": 8, "warning": 3, "info": 0}
    score = max(0, 100 - sum(weights[f["severity"]] for f in F))
    sev_rank = {"critical": 0, "serious": 1, "warning": 2, "info": 3}
    F.sort(key=lambda f: sev_rank[f["severity"]])
    risk_rank = {"none": 0, "low": 1, "medium": 2, "high": 3}
    A.sort(key=lambda a: (not a["recommended"], a["group"] != "repair", -a["saving_tokens"], risk_rank[a["risk"]]))
    return F, A, score


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    ap.add_argument("--project", default=os.getcwd(), help="folder Claude Code was started in (default: cwd)")
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--no-cli", action="store_true", help="skip `claude mcp list` / `claude --version`")
    ap.add_argument("--no-network", action="store_true", help="skip the latest-version lookup")
    args = ap.parse_args()

    home = claude_home()
    root = Path(args.project).resolve()  # the folder Claude Code was started in
    settings = load_settings(home, root)
    enabled = merged(settings, "enabledPlugins")
    overrides = merged(settings, "skillOverrides")
    plugins = scan_plugins(home, enabled)
    skills = collect_skills(home, root, plugins, overrides)
    suites = find_suites(skills)
    for s in skills:
        s["suite"] = suites.get(s["folder"]) if s["source"] in ("personal", "project") else None
        s.pop("_text", None)
    for p in plugins:
        for s in p["skills"]:
            s.pop("_text", None)

    hooks = []
    for s in settings:
        hooks += list(iter_hooks(s["data"].get("hooks"), f'settings:{s["scope"]}'))
    for p in plugins:
        if p["enabled"]:
            hooks += list(iter_hooks(p["hooks"], f'plugin:{p["name"]}', p["path"]))

    snap = {
        "meta": {"generated": datetime.now().astimezone().isoformat(timespec="minutes"),
                 "platform": sys.platform, "claude_home": str(home), "project": str(root),
                 "chars_per_token": CHARS_PER_TOKEN, "yaml_parser": bool(yaml)},
        "version": collect_version(not args.no_cli, not args.no_network),
        "settings": [{k: v for k, v in s.items() if k != "data"} | {
            "keys": sorted(s["data"].keys())} for s in settings],
        "skills": skills,
        "plugins": [{k: v for k, v in p.items() if k != "skills"} | {
            "skill_names": [s["name"] for s in p["skills"]]} for p in plugins],
        "hooks": hooks,
        "mcp": collect_mcp(home, root, not args.no_cli),
        "claude_md": collect_claude_md(home, root),
        "memory": collect_memory(home, root),
        "permissions": collect_permissions(settings),
        "usage": collect_usage(home, args.days),
        "suites": suites,
    }
    snap["findings"], snap["actions"], snap["health"] = analyse(snap)
    startup = {
        "skills": sum(s["listing_tokens"] for s in skills),
        "claude_md": sum(f["tokens"] for f in snap["claude_md"] if f["loaded_at_startup"]),
        "memory": snap["memory"].get("index_tokens", 0),
        "hooks": snap["usage"]["startup_hook_tokens_avg"],
    }
    snap["context"] = {"startup_estimate": startup, "total": sum(startup.values()),
                       "potential_saving": sum(max(0, a["saving_tokens"]) for a in snap["actions"] if a["recommended"])}
    for p in snap["plugins"]:
        p["hooks"] = sorted(p["hooks"].keys())

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, indent=1, default=str)
    print(json.dumps({"out": args.out, "health": snap["health"], "skills": len(skills),
                      "findings": len(snap["findings"]), "actions": len(snap["actions"]),
                      "startup_tokens_est": snap["context"]["total"]}))


if __name__ == "__main__":
    main()
