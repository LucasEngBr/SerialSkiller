"""Gera CATALOGO.md: o "relatório de bulas" legível por humanos."""
from __future__ import annotations

from collections import defaultdict

from .bula import load_bula, heuristic_bula
from .config import REPORT_FILE

KIND_LABEL = {"skill": "Skills do usuário", "plugin-skill": "Skills de plugins", "agent": "Agentes",
              "command": "Comandos", "mcp": "Servidores MCP", "library": "Biblioteca (inativas)",
              "native": "Ferramentas nativas"}


def write_report(items: list[dict]) -> str:
    groups: dict[str, list] = defaultdict(list)
    ia = 0
    for it in items:
        rec = load_bula(it)
        if rec and rec["origem"].startswith("ia"):
            ia += 1
        b = rec["bula"] if rec else heuristic_bula(it)
        groups[b.get("categoria") or it["kind"]].append((it, b))

    out = ["# Serial Skiller — Catálogo de habilidades", "",
           f"Total: **{len(items)}** itens · bulas por IA: **{ia}** · demais: heurística.", "",
           "| Tipo | Qtde |", "|---|---|"]
    counts: dict[str, int] = defaultdict(int)
    for it in items:
        counts[it["kind"]] += 1
    for k, n in sorted(counts.items(), key=lambda x: -x[1]):
        out.append(f"| {KIND_LABEL.get(k, k)} | {n} |")
    out.append("")
    out.append("## Categorias")
    out.append(", ".join(f"[{c}](#{c.lower().replace(' ', '-')}) ({len(v)})"
                         for c, v in sorted(groups.items(), key=lambda x: -len(x[1]))))
    for cat, rows in sorted(groups.items(), key=lambda x: -len(x[1])):
        out += ["", f"## {cat}", ""]
        for it, b in sorted(rows, key=lambda x: x[0]["name"]):
            flag = "" if it.get("active", True) else " _(inativa)_"
            out.append(f"### `{it['name']}`{flag}")
            out.append(f"- **Tipo:** {it['kind']} · **Origem:** {it['source']}")
            out.append(f"- **Invocar:** `{it['invoke']}`")
            out.append(f"- **Resumo:** {b.get('resumo', '')}")
            for key, label in (("serve_para", "Serve para"), ("usar_quando", "Usar quando"),
                               ("evitar_quando", "Evitar quando"), ("melhor_em", "Melhor em"),
                               ("pior_em", "Pior em"), ("gatilhos", "Gatilhos"),
                               ("alternativas", "Alternativas")):
                if b.get(key):
                    out.append(f"- **{label}:** " + "; ".join(b[key]))
            out.append("")
    REPORT_FILE.write_text("\n".join(out), encoding="utf-8")
    return str(REPORT_FILE)
