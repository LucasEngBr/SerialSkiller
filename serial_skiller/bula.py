"""Bula de cada habilidade: o que faz, quando usar, quando evitar, gatilhos.

Duas origens:
- heurística: extraída do texto da skill, grátis e instantânea;
- IA (NVIDIA): lê o SKILL.md e escreve a bula em português. Fica em cache
  por hash do arquivo, então só roda de novo se a skill mudar.
"""
from __future__ import annotations

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from .config import BULAS_DIR, ensure_dirs, load_config
from . import nvidia

BULA_KEYS = ["resumo", "categoria", "serve_para", "usar_quando", "evitar_quando",
             "melhor_em", "pior_em", "gatilhos", "alternativas"]


def _safe(id_: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", id_)[:150]


def bula_path(item: dict):
    return BULAS_DIR / f"{_safe(item['id'])}.json"


def load_bula(item: dict) -> dict | None:
    p = bula_path(item)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_bula(item: dict, bula: dict, origem: str) -> dict:
    ensure_dirs()
    rec = {"id": item["id"], "hash": item["hash"], "origem": origem, "bula": bula}
    bula_path(item).write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    return rec


# ---------------- heurística ----------------

_USE_RE = re.compile(r"(?:use (?:this|it|when|for|whenever|proactively)|trigger(?:s)? (?:on|when)|"
                     r"use sempre que|quando o usuário|invoke when)[^.]*\.", re.I)
_AVOID_RE = re.compile(r"\b(?:do not|don't|not for|never|skip|avoid|não use|nao use)\b[^.]*\.", re.I)
_QUOTE_RE = re.compile(r"[\"“']([^\"”']{3,40})[\"”']")


def heuristic_bula(item: dict) -> dict:
    if item.get("native_bula"):
        b = dict(item["native_bula"])
        b.setdefault("categoria", "nativo")
        return b
    desc = item.get("description", "")
    usar = [m.group(0).strip() for m in _USE_RE.finditer(desc)][:4]
    evitar = [m.group(0).strip() for m in _AVOID_RE.finditer(desc)][:3]
    gat = [q.strip() for q in _QUOTE_RE.findall(desc)][:15]
    gat += [w for w in re.split(r"[-_:/]", item["name"]) if len(w) > 2]
    first = re.split(r"(?<=[.!?])\s", desc, maxsplit=1)[0] if desc else item["name"]
    return {
        "resumo": first[:240],
        "categoria": item["kind"],
        "serve_para": [],
        "usar_quando": usar,
        "evitar_quando": evitar,
        "melhor_em": [],
        "pior_em": [],
        "gatilhos": list(dict.fromkeys(gat)),
        "alternativas": [],
    }


# ---------------- IA ----------------

SYSTEM = (
    "Você cataloga habilidades (skills, agentes, comandos, servidores MCP) do Claude Code. "
    "Para cada uma escreva uma BULA curta e precisa em português do Brasil, para que outra IA "
    "decida rápido se ela serve para um pedido. Não invente capacidades que o texto não mostra. "
    "Responda APENAS com JSON válido, sem comentários."
)

TEMPLATE = """Habilidade: {name}
Tipo: {kind}  | Origem: {source}
Como invocar: {invoke}
Descrição oficial: {description}

Trecho do arquivo:
<<<
{body}
>>>

Devolva este JSON (listas com 2 a 6 itens curtos, cada item até ~12 palavras):
{{
 "resumo": "uma frase: o que faz",
 "categoria": "uma palavra/área, ex: design-ui, animacao, video, 3d-blender, testes, git, planejamento, pesquisa, escrita, dados, backend, seguranca, engenharia-reversa, produtividade, jogos, meta-claude",
 "serve_para": ["entregas/resultados típicos"],
 "usar_quando": ["situações e pedidos ideais"],
 "evitar_quando": ["quando NÃO usar ou o que ela não faz"],
 "melhor_em": ["pontos fortes"],
 "pior_em": ["pontos fracos/limitações"],
 "gatilhos": ["8 a 15 palavras-chave/frases que um usuário diria, misture português e inglês"],
 "alternativas": ["nomes de outras skills parecidas citadas no texto, se houver"]
}}"""


def ai_bula(item: dict, model: str) -> dict:
    prompt = TEMPLATE.format(
        name=item["name"], kind=item["kind"], source=item["source"], invoke=item["invoke"],
        description=item.get("description", "")[:1500],
        body=(item.get("body_excerpt") or "")[:4500],
    )
    txt = nvidia.chat([{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
                      model=model, timeout=90, max_tokens=900)
    data = nvidia.extract_json(txt)
    if not isinstance(data, dict):
        raise ValueError("bula não é objeto")
    out = {}
    for k in BULA_KEYS:
        v = data.get(k)
        if k in ("resumo", "categoria"):
            out[k] = str(v or "").strip()
        else:
            out[k] = [str(x).strip() for x in (v or []) if str(x).strip()][:15]
    if not out["resumo"]:
        raise ValueError("bula vazia")
    return out


def ensure_heuristic(items: list[dict]) -> int:
    """Garante uma bula (pelo menos heurística) para todo item. Retorna quantas criou."""
    n = 0
    for it in items:
        rec = load_bula(it)
        if rec is None or (rec["hash"] != it["hash"] and not rec["origem"].startswith("ia")):
            save_bula(it, heuristic_bula(it), "heuristica")
            n += 1
    return n


def pending_ai(items: list[dict]) -> list[dict]:
    out = []
    for it in items:
        if it["kind"] == "native":
            continue
        rec = load_bula(it)
        if rec is None or rec["hash"] != it["hash"] or not rec["origem"].startswith("ia"):
            out.append(it)
    return out


def enrich(items: list[dict], limit: int | None = None, log=print) -> tuple[int, int]:
    cfg = load_config()
    todo = pending_ai(items)
    if limit:
        todo = todo[:limit]
    if not todo:
        log("Todas as bulas já estão enriquecidas pela IA.")
        return 0, 0
    log(f"Gerando {len(todo)} bulas com {cfg['chat_model']} ...")
    ok = fail = 0
    lock = threading.Lock()
    # limite de ~35 req/min do plano gratuito
    gap = 60 / 35
    last = [0.0]

    def work(it):
        with lock:
            wait = last[0] + gap - time.time()
            if wait > 0:
                time.sleep(wait)
            last[0] = time.time()
        model = cfg["chat_model"]
        try:
            b = ai_bula(it, model)
        except Exception:
            # alguns textos confundem o modelo principal: tenta o reserva
            model = cfg.get("rerank_model") or model
            b = ai_bula(it, model)
        save_bula(it, b, f"ia:{model}")
        return it

    with ThreadPoolExecutor(max_workers=cfg["enrich_workers"]) as ex:
        futs = {ex.submit(work, it): it for it in todo}
        for i, f in enumerate(as_completed(futs), 1):
            it = futs[f]
            try:
                f.result()
                ok += 1
            except Exception as e:
                fail += 1
                log(f"  falhou {it['name']}: {str(e)[:120]}")
            if i % 20 == 0 or i == len(todo):
                log(f"  {i}/{len(todo)}  ok={ok} falhas={fail}")
    return ok, fail
