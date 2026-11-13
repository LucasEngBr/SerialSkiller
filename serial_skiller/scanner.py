"""Varre tudo que está instalado no Claude Code e monta o catálogo bruto."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from .config import CLAUDE_HOME, CLAUDE_JSON, load_config
from .natives import NATIVES

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None

FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.S)


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def parse_frontmatter(text: str) -> tuple[dict, str]:
    m = FM_RE.match(text.lstrip("﻿"))
    if not m:
        return {}, text
    raw, body = m.group(1), text[m.end():]
    meta: dict = {}
    if yaml:
        try:
            meta = yaml.safe_load(raw) or {}
            if not isinstance(meta, dict):
                meta = {}
        except Exception:
            meta = {}
    if not meta:  # fallback simples chave: valor
        for line in raw.splitlines():
            if ":" in line and not line.startswith((" ", "\t")):
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip().strip('"').strip("'")
    return meta, body


def _hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()[:16]


def _first_paragraph(body: str) -> str:
    for block in re.split(r"\n\s*\n", body):
        b = block.strip()
        if b and not b.startswith(("#", "```", "|", "<", "---")):
            return re.sub(r"\s+", " ", b)[:400]
    return ""


def _item(kind: str, name: str, source: str, invoke: str, path: Path, text: str,
          meta: dict, body: str, active: bool = True) -> dict:
    desc = str(meta.get("description") or "").strip() or _first_paragraph(body)
    return {
        "id": f"{kind}:{source}:{name}",
        "name": name,
        "kind": kind,
        "source": source,
        "invoke": invoke,
        "active": active,
        "path": str(path),
        "description": re.sub(r"\s+", " ", desc),
        "hash": _hash(text),
        "body_excerpt": body[:6000],
    }


# ---------- skills do usuário e biblioteca ----------

def scan_skill_dir(root: Path, kind: str, source: str, active: bool, prefix: str = "") -> list[dict]:
    out = []
    if not root.is_dir():
        return out
    candidates = [root / "SKILL.md"] if (root / "SKILL.md").exists() else sorted(root.glob("*/SKILL.md"))
    for f in candidates:
        text = _read(f)
        meta, body = parse_frontmatter(text)
        name = str(meta.get("name") or f.parent.name).strip()
        full = f"{prefix}{name}"
        if kind == "library":
            invoke = f"inativa: copie {f.parent} para {CLAUDE_HOME / 'skills'} e use Skill('{name}')"
        else:
            invoke = f"Skill('{full}')  ou  /{full}"
        out.append(_item(kind, full, source, invoke, f, text, meta, body, active))
    return out


# ---------- plugins ----------

def _as_list(v) -> list[str]:
    if v is None:
        return []
    return [v] if isinstance(v, str) else [x for x in v if isinstance(x, str)]


def scan_plugins(include_inactive: bool) -> list[dict]:
    out: list[dict] = []
    installed = CLAUDE_HOME / "plugins" / "installed_plugins.json"
    settings = CLAUDE_HOME / "settings.json"
    if not installed.exists():
        return out
    try:
        data = json.loads(_read(installed)).get("plugins", {})
        enabled = json.loads(_read(settings)).get("enabledPlugins", {}) if settings.exists() else {}
    except Exception:
        return out

    for key, entries in data.items():
        if not entries:
            continue
        active = bool(enabled.get(key))
        if not active and not include_inactive:
            continue
        root = Path(entries[-1]["installPath"])
        manifest = {}
        mf = root / ".claude-plugin" / "plugin.json"
        if mf.exists():
            try:
                manifest = json.loads(_read(mf))
            except Exception:
                manifest = {}
        plugin = manifest.get("name") or key.split("@")[0]
        pfx = f"{plugin}:"

        # skills
        skill_paths = _as_list(manifest.get("skills")) or ["./skills/"]
        seen = set()
        for sp in skill_paths:
            for it in scan_skill_dir((root / sp).resolve(), "plugin-skill", plugin, active, pfx):
                if it["name"] not in seen:
                    seen.add(it["name"])
                    out.append(it)
        if (root / "SKILL.md").exists() and not seen:
            out += scan_skill_dir(root, "plugin-skill", plugin, active, pfx)

        # agentes
        agent_files: list[tuple[Path, str]] = []
        for ap in _as_list(manifest.get("agents")) or ["./agents/"]:
            p = (root / ap)
            if p.suffix == ".md":
                agent_files.append((p, ""))
            elif p.is_dir():
                for f in sorted(p.rglob("*.md")):
                    sub = f.parent.relative_to(p).as_posix()
                    agent_files.append((f, "" if sub == "." else sub.replace("/", ":") + ":"))
        for f, sub in agent_files:
            text = _read(f)
            meta, body = parse_frontmatter(text)
            name = f"{sub}{meta.get('name') or f.stem}"
            out.append(_item("agent", f"{pfx}{name}", plugin,
                             f"Agent(subagent_type='{pfx}{name}')", f, text, meta, body, active))

        # comandos
        cmd_files: list[Path] = []
        for cp in _as_list(manifest.get("commands")) or ["./commands/"]:
            p = (root / cp)
            cmd_files += [p] if p.suffix == ".md" else sorted(p.glob("*.md")) if p.is_dir() else []
        for f in cmd_files:
            text = _read(f)
            meta, body = parse_frontmatter(text)
            name = f.stem
            out.append(_item("command", f"{pfx}{name}", plugin, f"/{pfx}{name}",
                             f, text, meta, body, active))

        # MCP do plugin
        mcp = dict(manifest.get("mcpServers") or {}) if isinstance(manifest.get("mcpServers"), dict) else {}
        mj = root / ".mcp.json"
        if mj.exists():
            try:
                mcp.update(json.loads(_read(mj)).get("mcpServers", {}))
            except Exception:
                pass
        for name in mcp:
            readme = _read(root / "README.md")[:3000]
            meta = {"description": f"Servidor MCP '{name}' do plugin {plugin}. {manifest.get('description', '')}"}
            out.append(_item("mcp", f"{pfx}{name}", plugin,
                             f"ferramentas mcp__plugin_{plugin}_{name}__* (ToolSearch '{name}')",
                             mj if mj.exists() else mf, json.dumps(mcp.get(name)) + readme, meta, readme, active))
    return out


# ---------- agentes / comandos do usuário ----------

def scan_user_md(kind: str, folder: Path) -> list[dict]:
    out = []
    if not folder.is_dir():
        return out
    for f in sorted(folder.glob("*.md")):
        text = _read(f)
        meta, body = parse_frontmatter(text)
        name = str(meta.get("name") or f.stem)
        inv = f"Agent(subagent_type='{name}')" if kind == "agent" else f"/{name}"
        out.append(_item(kind, name, "user", inv, f, text, meta, body))
    return out


# ---------- MCP global ----------

def scan_mcp() -> list[dict]:
    out = []
    if not CLAUDE_JSON.exists():
        return out
    try:
        d = json.loads(_read(CLAUDE_JSON))
    except Exception:
        return out
    servers = dict(d.get("mcpServers") or {})
    for name, cfg in servers.items():
        text = json.dumps(cfg)
        meta = {"description": f"Servidor MCP global '{name}' ({cfg.get('command') or cfg.get('url') or cfg.get('type', '')})."}
        out.append(_item("mcp", name, "user", f"ferramentas mcp__{name}__* (ToolSearch '{name}')",
                         CLAUDE_JSON, text, meta, ""))
    return out


def scan_natives() -> list[dict]:
    out = []
    for n in NATIVES:
        text = n["description"] + json.dumps(n.get("bula", {}), ensure_ascii=False)
        it = _item("native", n["name"], "claude-code", n["invoke"], Path("<nativo>"), text,
                   {"description": n["description"]}, "")
        it["native_bula"] = n.get("bula")
        out.append(it)
    return out


def scan_all(project_dir: str | None = None) -> list[dict]:
    cfg = load_config()
    items: list[dict] = []
    items += scan_skill_dir(CLAUDE_HOME / "skills", "skill", "user", True)
    items += scan_user_md("agent", CLAUDE_HOME / "agents")
    items += scan_user_md("command", CLAUDE_HOME / "commands")
    items += scan_plugins(cfg["include_inactive_plugins"])
    items += scan_mcp()
    if cfg["include_library"]:
        items += scan_skill_dir(CLAUDE_HOME / "skill-library", "library", "skill-library", False)
    if project_dir:
        pd = Path(project_dir) / ".claude"
        items += scan_skill_dir(pd / "skills", "skill", "projeto", True)
        items += scan_user_md("agent", pd / "agents")
        items += scan_user_md("command", pd / "commands")
    items += scan_natives()
    # dedup por id
    uniq: dict[str, dict] = {}
    for it in items:
        uniq.setdefault(it["id"], it)
    return list(uniq.values())
