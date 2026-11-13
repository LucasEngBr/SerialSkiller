"""Uso REAL de cada habilidade, lido dos históricos do Claude Code (~/.claude/projects/**/*.jsonl).

Conta: chamadas da ferramenta Skill, Agent(subagent_type), ferramentas mcp__<servidor>__*,
ferramentas nativas e comandos digitados (/nome). Cache por arquivo (tamanho + data),
então só relê históricos novos ou alterados.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .config import CLAUDE_HOME, DATA, HISTORY_FILE

CACHE = DATA / "usage_cache.json"
CMD_RE = re.compile(r"<command-name>/?([^<\s]+)</command-name>")

# ferramenta nativa -> nome do item nativo no catálogo
NATIVE_TOOLS = {
    "WebSearch": "WebSearch", "WebFetch": "WebFetch", "Artifact": "Artifact",
    "mcp__Claude_Browser": "Navegador embutido", "mcp__visualize": "show_widget (visualize)",
    "mcp__ccd_session__start_session": "Sessões paralelas (start_session)",
    "EnterPlanMode": "Agent:Plan",
}


def _project_label(folder: str) -> str:
    """'C--Users-x-OneDrive-Documentos-meu-app' -> 'meu-app'; pastas temporárias -> 'sessão temporária'."""
    if "scratch" in folder or "AppData" in folder:
        return "sessão temporária"
    s = re.sub(r"^[A-Za-z]--Users-[^-]+-?", "", folder)
    s = re.sub(r"^(OneDrive-)?(Documentos|Documents|Desktop|Área-de-Trabalho)-", "", s)
    return s or "pasta do usuário"


def _bump(acc: dict, key: str, ts: str, project: str) -> None:
    rec = acc.setdefault(key, {"count": 0, "last": "", "first": "", "projects": {}})
    rec["count"] += 1
    if ts and ts > rec["last"]:
        rec["last"] = ts
    if ts and (not rec["first"] or ts < rec["first"]):
        rec["first"] = ts
    rec["projects"][project] = rec["projects"].get(project, 0) + 1
    if ts:
        days = rec.setdefault("days", {})
        days[ts[:10]] = days.get(ts[:10], 0) + 1


def _scan_file(path: Path, project: str) -> tuple[dict, dict]:
    acc: dict = {}
    per_msg: dict[str, tuple] = {}  # id da resposta -> (dia, modelo, in, cache_w, cache_r, out)
    try:
        fh = path.open("r", encoding="utf-8", errors="replace")
    except Exception:
        return acc, {}
    with fh:
        for line in fh:
            has_tool = '"tool_use"' in line
            has_cmd = "<command-name>" in line and '"type":"user"' in line
            has_usage = '"usage"' in line and '"type":"assistant"' in line
            if not (has_tool or has_cmd or has_usage):
                continue
            try:
                ev = json.loads(line)
            except Exception:
                continue
            ts = ev.get("timestamp", "")
            msg = ev.get("message") or {}
            content = msg.get("content")
            u = msg.get("usage") if ev.get("type") == "assistant" else None
            if isinstance(u, dict) and msg.get("id") and ts:
                # a mesma resposta aparece em várias linhas: conta uma vez por id
                per_msg[msg["id"]] = (ts[:10], msg.get("model") or "?", int(u.get("input_tokens") or 0),
                                      int(u.get("cache_creation_input_tokens") or 0),
                                      int(u.get("cache_read_input_tokens") or 0), int(u.get("output_tokens") or 0))
            if ev.get("type") == "user":
                text = content if isinstance(content, str) else " ".join(
                    c.get("text", "") for c in (content or []) if isinstance(c, dict))
                for m in CMD_RE.findall(text or ""):
                    _bump(acc, "cmd:" + m, ts, project)
                continue
            if ev.get("type") != "assistant" or not isinstance(content, list):
                continue
            for c in content:
                if not isinstance(c, dict) or c.get("type") != "tool_use":
                    continue
                name, inp = c.get("name", ""), c.get("input") or {}
                if name == "Skill" and inp.get("skill"):
                    _bump(acc, "skill:" + inp["skill"], ts, project)
                elif name in ("Agent", "Task") and inp.get("subagent_type"):
                    _bump(acc, "agent:" + inp["subagent_type"], ts, project)
                elif name.startswith("mcp__"):
                    parts = name.split("__")
                    full = "__".join(parts[:3])
                    server = "__".join(parts[:2])
                    if full in NATIVE_TOOLS:
                        _bump(acc, "native:" + NATIVE_TOOLS[full], ts, project)
                    elif server in NATIVE_TOOLS:
                        _bump(acc, "native:" + NATIVE_TOOLS[server], ts, project)
                    else:
                        _bump(acc, "mcp:" + parts[1], ts, project)
                elif name in NATIVE_TOOLS:
                    _bump(acc, "native:" + NATIVE_TOOLS[name], ts, project)
    tok: dict = {"days": {}, "models": {}, "msgs": len(per_msg)}
    for day, model, *v in per_msg.values():
        if model.startswith("<"):  # respostas sintéticas
            continue
        for bucket, key in ((tok["days"], day), (tok["models"], model)):
            cur = bucket.setdefault(key, [0, 0, 0, 0])
            for i in range(4):
                cur[i] += v[i]
    return acc, tok


def _merge(dst: dict, src: dict) -> None:
    for k, r in src.items():
        d = dst.setdefault(k, {"count": 0, "last": "", "first": "", "projects": {}})
        d["count"] += r["count"]
        d["last"] = max(d["last"], r["last"])
        d["first"] = min(x for x in (d["first"], r["first"]) if x) if (d["first"] or r["first"]) else ""
        for p, n in r["projects"].items():
            d["projects"][p] = d["projects"].get(p, 0) + n
        for day, n in r.get("days", {}).items():
            dd = d.setdefault("days", {})
            dd[day] = dd.get(day, 0) + n


def raw_usage() -> dict:
    root = CLAUDE_HOME / "projects"
    try:
        cache = json.loads(CACHE.read_text(encoding="utf-8"))
    except Exception:
        cache = {}
    files = {}
    changed = False
    for f in root.rglob("*.jsonl") if root.exists() else []:
        st = f.stat()
        key = str(f)
        sig = f"{st.st_size}:{int(st.st_mtime)}"
        ent = cache.get(key)
        if not ent or ent["sig"] != sig or "tok" not in ent:
            proj = _project_label(f.relative_to(root).parts[0])
            acc, tok = _scan_file(f, proj)
            ent = {"sig": sig, "acc": acc, "tok": tok, "proj": proj}
            changed = True
        files[key] = ent
    if changed or len(files) != len(cache):
        CACHE.write_text(json.dumps(files), encoding="utf-8")
    total: dict = {}
    for ent in files.values():
        _merge(total, ent["acc"])
    global _FILES
    _FILES = files
    return total


_FILES: dict = {}


def claude_tokens() -> dict:
    """Tokens reais do Claude Code (dos históricos): por dia, modelo e projeto.
    Cada valor = [entrada, cache_escrita, cache_leitura, saída]."""
    if not _FILES:
        raw_usage()
    days: dict = {}
    models: dict = {}
    projects: dict = {}
    msgs = 0
    for ent in _FILES.values():
        tok = ent.get("tok") or {}
        msgs += tok.get("msgs", 0)
        for src, dst in ((tok.get("days", {}), days), (tok.get("models", {}), models)):
            for k, v in src.items():
                cur = dst.setdefault(k, [0, 0, 0, 0])
                for i in range(4):
                    cur[i] += v[i]
        pj = projects.setdefault(ent.get("proj", "?"), [0, 0, 0, 0])
        for v in tok.get("days", {}).values():
            for i in range(4):
                pj[i] += v[i]
    return {"days": days, "models": models, "projects": projects, "responses": msgs}


def usage_by_item(items: list[dict]) -> dict[str, dict]:
    """Casa os nomes vistos nos históricos com os ids do catálogo."""
    raw = raw_usage()
    by_name: dict[str, list[dict]] = {}
    for it in items:
        by_name.setdefault(it["name"].lower(), []).append(it)
        short = it["name"].split(":")[-1].lower()
        if short != it["name"].lower():
            by_name.setdefault("~" + short, []).append(it)
    out: dict[str, dict] = {}
    for key, rec in raw.items():
        kind, name = key.split(":", 1)
        n = name.lower()
        cands = by_name.get(n) or by_name.get("~" + n) or []
        if kind == "mcp":
            cands = [it for it in items if it["kind"] == "mcp" and n in it["name"].lower()] or cands
        if not cands:
            continue
        it = cands[0]
        cur = out.setdefault(it["id"], {"count": 0, "last": "", "first": "", "projects": {}})
        _merge({it["id"]: cur}, {it["id"]: rec})
    return out


def recommendation_stats() -> dict[str, dict]:
    """Quantas vezes o Serial Skiller sugeriu cada item."""
    out: dict[str, dict] = {}
    if not HISTORY_FILE.exists():
        return out
    for line in HISTORY_FILE.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except Exception:
            continue
        for name in r.get("picks", []):
            d = out.setdefault(name, {"count": 0, "last": ""})
            d["count"] += 1
            d["last"] = max(d["last"], r.get("t", ""))
    return out
