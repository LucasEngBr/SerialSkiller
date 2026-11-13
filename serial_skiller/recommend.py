"""Recomenda habilidades para um pedido: busca híbrida local + rerank opcional por IA."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from .config import HISTORY_FILE, load_config
from .bula import load_bula, heuristic_bula
from .index import Index
from . import nvidia


# ---------------- contexto ----------------

def project_hints(cwd: str | None) -> str:
    if not cwd:
        return ""
    p = Path(cwd)
    hints: list[str] = []
    pkg = p / "package.json"
    if pkg.exists():
        try:
            d = json.loads(pkg.read_text(encoding="utf-8"))
            deps = list((d.get("dependencies") or {}).keys()) + list((d.get("devDependencies") or {}).keys())
            hints.append("node: " + ", ".join(deps[:25]))
        except Exception:
            hints.append("node")
    for f, label in (("pyproject.toml", "python"), ("requirements.txt", "python"), ("Cargo.toml", "rust"),
                     ("go.mod", "go"), ("project.godot", "godot"), ("pubspec.yaml", "flutter"),
                     ("build.gradle", "android/gradle"), ("Podfile", "ios"), ("index.html", "html estático"),
                     ("vercel.json", "vercel"), ("Dockerfile", "docker")):
        if (p / f).exists():
            hints.append(label)
    try:
        exts: dict[str, int] = {}
        for c in list(p.iterdir())[:300]:
            if c.is_file() and c.suffix:
                exts[c.suffix.lower()] = exts.get(c.suffix.lower(), 0) + 1
        top = sorted(exts.items(), key=lambda x: -x[1])[:6]
        if top:
            hints.append("arquivos: " + " ".join(e for e, _ in top))
    except Exception:
        pass
    return f"pasta '{p.name}'; " + "; ".join(dict.fromkeys(hints))


def recent_conversation(transcript_path: str | None, max_chars: int = 1500) -> str:
    """Últimas falas da conversa (para entender pedidos como 'sim, faz isso')."""
    if not transcript_path:
        return ""
    p = Path(transcript_path)
    if not p.exists():
        return ""
    try:
        with p.open("rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - 200_000))
            lines = fh.read().decode("utf-8", "replace").splitlines()[1:]
    except Exception:
        return ""
    turns: list[str] = []
    for line in reversed(lines):
        try:
            ev = json.loads(line)
        except Exception:
            continue
        role = ev.get("type")
        if role not in ("user", "assistant"):
            continue
        content = (ev.get("message") or {}).get("content")
        if isinstance(content, list):
            text = " ".join(c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text")
        else:
            text = str(content or "")
        text = text.strip()
        if not text or "<system-reminder>" in text[:40]:
            continue
        turns.append(f"{role}: {text[:500]}")
        if len(turns) >= 4 or sum(map(len, turns)) > max_chars:
            break
    return "\n".join(reversed(turns))[-max_chars:]


# ---------------- busca ----------------

def _bula(item: dict) -> dict:
    rec = load_bula(item)
    return rec["bula"] if rec else heuristic_bula(item)


def hybrid(ix: Index, query: str, cfg: dict, embed_timeout: float) -> tuple[list[tuple[float, dict]], bool]:
    bm = ix.bm25(query)
    mx = max(bm) or 1.0
    bmn = [s / mx for s in bm]
    cos = None
    if cfg["use_embeddings"]:
        try:
            cos = ix.cosine(query, embed_timeout)
        except Exception:
            cos = None
    ix.last_max_cos = max(cos) if cos else None
    scored = []
    for i, it in enumerate(ix.items):
        if cos is not None:
            # cos típico: ~0.1 (nada a ver) a ~0.6 (muito relacionado)
            c = max(0.0, (cos[i] - 0.12) / 0.45)
            s = 0.35 * bmn[i] + 0.65 * min(c, 1.0)
        else:
            s = bmn[i] * (0.6 if bm[i] < 4 else 1.0)
        if not it.get("active", True):
            s *= 0.85
        scored.append((s, it))
    scored.sort(key=lambda x: -x[0])
    return scored, cos is not None


RERANK_SYS = (
    "Você é o Serial Skiller: escolhe quais habilidades instaladas no Claude Code ajudam no pedido atual. "
    "Seja exigente: só aponte as que realmente servem. Responda APENAS JSON."
)


def rerank(prompt: str, cands: list[tuple[float, dict]], context: str, project: str,
           cfg: dict, timeout: float) -> list[dict]:
    lines = []
    for n, (_, it) in enumerate(cands, 1):
        b = _bula(it)
        lines.append(f"{n}. {it['name']} [{it['kind']}] — {b.get('resumo', '')} "
                     f"| usar: {'; '.join(b.get('usar_quando', [])[:3])} "
                     f"| evitar: {'; '.join(b.get('evitar_quando', [])[:2])}")
    user = (f"PEDIDO DO USUÁRIO:\n{prompt[:1500]}\n\n"
            + (f"CONVERSA RECENTE:\n{context}\n\n" if context else "")
            + (f"PROJETO: {project}\n\n" if project else "")
            + "CANDIDATAS:\n" + "\n".join(lines)
            + "\n\nCRITÉRIO DE NOTA: 9-10 = a habilidade executa diretamente a tarefa pedida; "
              "7-8 = ajuda bastante numa parte central da tarefa; 6 = ajuda secundária útil; "
              "<6 = tangencial. Julgue pelo PEDIDO; o projeto e a conversa só desempatam. "
              "Ex.: pedido 'traduzir texto' NÃO combina com skills de animar texto.\n"
              'Devolva {"recomendadas":[{"n":<número>,"nota":<0-10>,"motivo":"<até 15 palavras, pt-BR, '
              'ligando a habilidade ao pedido>"}]} em ordem da mais útil para a menos, TODAS com nota >= 6 (pode ser muitas). '
              "Devolva lista VAZIA se o pedido for saudação, papo, pergunta sobre você, agradecimento, "
              "edição trivial de código (renomear, ajustar uma linha) ou se nenhuma servir de fato.")
    txt = nvidia.chat([{"role": "system", "content": RERANK_SYS}, {"role": "user", "content": user}],
                      model=cfg["rerank_model"], timeout=timeout, max_tokens=600, retries=0)
    data = nvidia.extract_json(txt)
    out = []
    for r in data.get("recomendadas", []) if isinstance(data, dict) else []:
        try:
            n = int(r["n"])
            if 1 <= n <= len(cands):
                out.append({"item": cands[n - 1][1], "nota": float(r.get("nota", 0)),
                            "motivo": str(r.get("motivo", ""))[:160]})
        except Exception:
            continue
    return out


TASK_RE = re.compile(
    r"\b(quero|queria|preciso|precisava|gostaria|fa[cç]a|faz|fazer|crie|criar|cria|monte|montar|gere|gerar|"
    r"construa|construir|desenvolva|desenvolver|implemente|implementar|automatize|automatizar|integre|integrar|"
    r"adicione|adicionar|transforme|transformar|converta|converter|edite|editar|escreva|escrever|"
    r"como (eu )?(fa[cç]o|posso|consigo)|tem (alguma )?(ferramenta|skill|jeito)|me ajuda|"
    r"build|create|make|generate|implement|need|want|how (do|can) i)\b", re.I)


def looks_like_task(prompt: str) -> bool:
    """Heurística: o pedido descreve algo a fazer/construir (e não só uma pergunta ou conversa)."""
    from .index import norm
    return bool(TASK_RE.search(norm(prompt)))


def recommend(prompt: str, cwd: str | None = None, transcript: str | None = None,
              deep: bool = True, hook: bool = False) -> dict:
    cfg = load_config()
    t0 = time.time()
    ix = Index()
    context = recent_conversation(transcript) if transcript else ""
    project = project_hints(cwd)
    query = prompt if len(prompt) > 40 or not context else f"{prompt}\n{context[-600:]}"
    emb_to = cfg["hook_embed_timeout"] if hook else 20
    scored, used_emb = hybrid(ix, query, cfg, emb_to)

    result = {"engine": "hibrido" if used_emb else "bm25", "items": []}
    # corte: nada parecido o bastante (papo, saudação, pedido trivial) -> não gasta API
    if not scored or scored[0][0] < cfg["gate_score"]:
        result["ms"] = int((time.time() - t0) * 1000)
        return result
    # pool dinâmico: só entram as que se encaixam no pedido (relativas à melhor),
    # nunca o catálogo inteiro; mínimo pool_min, máximo pool_max
    best = scored[0][0]
    cut = max(cfg["gate_score"], best * cfg["pool_ratio"])
    pool = [x for x in scored if x[0] >= cut][: cfg["pool_max"]]
    if len(pool) < cfg["pool_min"]:
        pool = scored[: cfg["pool_min"]]
    if hook:  # no hook o tempo manda: grupo menor = juiz mais rápido
        pool = pool[: cfg["hook_pool_max"]]
    result["pool"] = len(pool)
    use_ai = deep and (cfg["hook_rerank"] or not hook)
    ranked_all: list[dict] = []
    if use_ai:
        try:
            ranked = rerank(prompt, pool, context, project, cfg,
                            cfg["hook_rerank_timeout"] if hook else 60)
            result["engine"] += "+ia"
            ranked_all = [{**r, "score": next(s for s, it in pool if it is r["item"])} for r in ranked]
        except Exception as e:
            result["ai_error"] = str(e)[:160]
            use_ai = False
    if not use_ai:
        ranked_all = [{"item": it, "score": s, "nota": None, "motivo": ""}
                      for s, it in pool if s >= cfg["min_score"]]
    result["all"] = ranked_all            # todas que se encaixam, em ordem
    result["items"] = ranked_all[: cfg["top_k"]]  # as que vão para o Claude
    best_nota = max((r["nota"] or 0) for r in ranked_all) if ranked_all and use_ai else None
    mc = getattr(ix, "last_max_cos", None)
    local_weak = (mc < cfg["weak_cos"]) if mc is not None else (best < cfg["weak_score"])
    # só faz sentido sugerir ferramenta nova para pedidos de tarefa, não para perguntas/conversa
    result["weak"] = looks_like_task(prompt) and (local_weak or (use_ai and (not ranked_all or (best_nota or 0) < 7)))
    result["max_cos"] = round(mc, 3) if mc is not None else None
    result["ms"] = int((time.time() - t0) * 1000)
    # tokens que o hook injeta no contexto do Claude (~3,6 caracteres por token em pt-BR)
    result["ctx_tokens"] = round(len(format_for_claude(result, cfg["mode"])) / 3.6) if result["items"] else 0
    result["hook"] = hook
    _log(prompt, result)
    return result


def _log(prompt: str, result: dict) -> None:
    try:
        rec = {"t": time.strftime("%Y-%m-%d %H:%M:%S"), "prompt": prompt[:300], "engine": result["engine"],
               "ms": result["ms"], "picks": [r["item"]["name"] for r in result["items"]],
               "ctx_tokens": result.get("ctx_tokens", 0), "hook": result.get("hook", False)}
        with HISTORY_FILE.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


# ---------------- formatação ----------------

def _discover_cmd() -> str:
    import sys
    from .config import ROOT
    return f'"{Path(sys.executable).as_posix()}" "{(ROOT / "skiller.py").as_posix()}" discover'


def discover_offer(mode: str) -> str:
    cmd = _discover_cmd()
    base = ("[Serial Skiller] As habilidades instaladas não cobrem bem este pedido. Existe a opção de "
            f"buscar repositórios em alta no Trendshift: rode `{cmd} \"<pedido resumido>\"` (busca, "
            "leitura e julgamento são feitos localmente pela API NVIDIA; volta só um resumo curto).")
    if mode == "auto":
        return base + " INSTRUÇÃO: se o pedido realmente precisar de uma ferramenta nova, rode a busca e use o resumo."
    if mode == "ask":
        return base + (" INSTRUÇÃO: inclua na pergunta ao usuário (AskUserQuestion) a opção "
                       "'Buscar no Trendshift'; só rode a busca se ele escolher.")
    return base


def format_for_claude(result: dict, mode: str) -> str:
    items = result["items"]
    if not items:
        return discover_offer(mode) if result.get("weak") else ""
    lines = [f"[Serial Skiller] Habilidades instaladas que combinam com este pedido (modo: {mode}). "
             "Bula resumida de cada uma:"]
    for n, r in enumerate(items, 1):
        it = r["item"]
        b = _bula(it)
        nota = f" nota {r['nota']:.0f}/10" if r.get("nota") is not None else ""
        lines.append(f"{n}. {it['name']} ({it['kind']}{nota}) → invocar: {it['invoke']}")
        lines.append(f"   o que faz: {b.get('resumo', '')}")
        if r.get("motivo"):
            lines.append(f"   por que aqui: {r['motivo']}")
        if b.get("usar_quando"):
            lines.append(f"   usar quando: {'; '.join(b['usar_quando'][:3])}")
        if b.get("evitar_quando"):
            lines.append(f"   evitar: {'; '.join(b['evitar_quando'][:2])}")
    if result.get("weak"):
        lines.append("Cobertura fraca: " + discover_offer(mode).replace("[Serial Skiller] ", ""))
    if mode == "ask":
        lines.append("INSTRUÇÃO: antes de executar, use AskUserQuestion (multiSelect) para o usuário escolher "
                     "quais destas habilidades aplicar, com a mais indicada primeiro marcada '(Recomendado)' "
                     "e uma opção 'Nenhuma, siga normal'. Se o pedido for trivial ou nenhuma servir de fato, "
                     "ignore esta lista e não pergunte.")
    elif mode == "auto":
        lines.append("INSTRUÇÃO: escolha você mesmo as que realmente servem (pode ser nenhuma), carregue-as "
                     "(Skill/Agent/etc.) antes de agir e diga em uma linha quais usou.")
    else:
        lines.append("INSTRUÇÃO: apenas considere estas opções; não é obrigatório usar.")
    return "\n".join(lines)


def format_for_human(result: dict) -> str:
    if not result["items"]:
        return f"Nenhuma habilidade relevante. (motor: {result['engine']}, {result['ms']} ms)"
    out = [f"Motor: {result['engine']}  |  {result['ms']} ms" +
           (f"  |  IA falhou: {result['ai_error']}" if result.get("ai_error") else ""), ""]
    for n, r in enumerate(result["items"], 1):
        it = r["item"]
        b = _bula(it)
        nota = f"{r['nota']:.0f}/10" if r.get("nota") is not None else f"{r['score']:.2f}"
        out.append(f"{n}. {it['name']}  [{it['kind']} · {it['source']}]  {nota}"
                   + ("" if it.get("active", True) else "  (INATIVA)"))
        out.append(f"   {b.get('resumo', '')}")
        if r.get("motivo"):
            out.append(f"   ↳ {r['motivo']}")
        out.append(f"   invocar: {it['invoke']}")
    return "\n".join(out)
