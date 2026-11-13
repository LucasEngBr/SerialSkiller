"""Descoberta no Trendshift (https://trendshift.io): repositórios em alta que podem
cobrir o que as habilidades instaladas não cobrem.

Todo o trabalho pesado roda local + API NVIDIA (nada do Claude):
- índice: páginas públicas de trending (diário/semanal/mensal/anual × linguagens) e de
  tópicos, lidas via JSON-LD; respeita robots.txt (não usa /api/), 1 requisição/s,
  cache de 24 h;
- busca: BM25 + embeddings NVIDIA sobre nome/descrição/tópicos;
- julgamento: LLM NVIDIA dá nota, motivo e "como usar" para cada candidato.
O Claude só recebe (se quiser) um resumo curto do resultado.
"""
from __future__ import annotations

import hashlib
import html as htmlmod
import json
import math
import re
import time
import urllib.request
from collections import Counter
from pathlib import Path

from .config import DATA, load_config
from .index import tokens as tok
from . import nvidia

BASE = "https://trendshift.io"
DIR = DATA / "trendshift"
INDEX = DIR / "index.json"
EMB = DIR / "emb.npy"
EMB_META = DIR / "emb.json"
SEARCHES = DIR / "searches.jsonl"
UA = "Mozilla/5.0 (compatible; SerialSkiller/0.1; local skill catalog)"
PERIODS = ["", "weekly", "monthly", "yearly"]
LANGS = ["", "Python", "TypeScript", "JavaScript", "Go", "Rust", "Shell", "C++", "Java", "Swift", "Kotlin"]
LD_RE = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)
TTL = 24 * 3600


def _get(path: str, timeout: float = 20) -> str:
    req = urllib.request.Request(BASE + path, headers={"User-Agent": UA, "Accept": "text/html"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def _items_from_ld(page: str) -> list[dict]:
    out = []
    for block in LD_RE.findall(page):
        try:
            d = json.loads(block)
        except Exception:
            continue
        nodes = []
        if isinstance(d, dict) and d.get("itemListElement"):
            nodes = [(e.get("url", ""), e.get("item") or {}) for e in d["itemListElement"]]
        elif isinstance(d, dict) and d.get("@type") == "SoftwareSourceCode":
            nodes = [("", d)]
        for url, it in nodes:
            if it.get("@type") != "SoftwareSourceCode" or not it.get("name"):
                continue
            stars = 0
            for st in it.get("interactionStatistic") or []:
                if "Like" in json.dumps(st.get("interactionType", "")):
                    stars = int(st.get("userInteractionCount") or 0)
            m = re.search(r"/repositories/(\d+)", url)
            out.append({
                "id": m.group(1) if m else "",
                "name": it["name"],
                "description": htmlmod.unescape(it.get("description") or "")[:500],
                "github": it.get("codeRepository") or "",
                "homepage": it.get("url") or "",
                "language": it.get("programmingLanguage") or "",
                "keywords": it.get("keywords") or [],
                "stars": stars,
                "updated": it.get("dateModified", "")[:10],
            })
    return out


def _load() -> dict:
    try:
        return json.loads(INDEX.read_text(encoding="utf-8"))
    except Exception:
        return {"fetched": 0, "repos": {}, "topics": {}}


def _save(ix: dict) -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    INDEX.write_text(json.dumps(ix, ensure_ascii=False), encoding="utf-8")


def build_index(detail_limit: int = 250, log=print) -> dict:
    """Atualiza o índice. Educado: 1 req/s, só páginas públicas."""
    ix = _load()
    repos: dict = ix.get("repos", {})
    topics: dict = {}
    pages = 0

    def polite(path):
        nonlocal pages
        time.sleep(1.0)
        pages += 1
        return _get(path)

    # 1) trending com descrição
    for per in PERIODS:
        for lang in LANGS:
            path = "/" + per + (f"?language={lang}" if lang else "")
            try:
                for r in _items_from_ld(polite(path)):
                    old = repos.get(r["name"], {})
                    r["topics"] = old.get("topics", [])
                    r["trend"] = sorted(set(old.get("trend", []) + [per or "daily"]))
                    if not r["id"]:
                        r["id"] = old.get("id", "")
                    repos[r["name"]] = r
            except Exception as e:
                log(f"  falhou {path}: {e}")
    log(f"Trending: {len(repos)} repositórios ({pages} páginas).")

    # 2) tópicos -> ids
    try:
        tpage = polite("/topics")
        slugs = sorted(set(re.findall(r'href="/topics/([a-z0-9-]+)"', tpage)))
    except Exception:
        slugs = []
    by_id = {r["id"]: r for r in repos.values() if r.get("id")}
    pending: dict[str, set] = {}
    for slug in slugs:
        try:
            ids = set(re.findall(r'href="/repositories/(\d+)"', polite(f"/topics/{slug}")))
        except Exception:
            continue
        topics[slug] = sorted(ids)
        for i in ids:
            if i in by_id:
                by_id[i]["topics"] = sorted(set(by_id[i].get("topics", []) + [slug]))
            else:
                pending.setdefault(i, set()).add(slug)
    log(f"Tópicos: {len(slugs)}; repositórios só vistos em tópicos: {len(pending)}.")

    # 3) detalhes dos que só apareceram em tópicos (limite por rodada)
    done = 0
    for i, slugs_of in list(pending.items())[:detail_limit]:
        try:
            got = _items_from_ld(polite(f"/repositories/{i}"))
        except Exception:
            continue
        if got:
            r = got[0]
            r["id"] = i
            old = repos.get(r["name"], {})
            r["topics"] = sorted(set(old.get("topics", [])) | slugs_of)
            r["trend"] = old.get("trend", [])
            repos[r["name"]] = r
            done += 1
    log(f"Detalhes buscados: {done}. Total no índice: {len(repos)}.")
    ix = {"fetched": time.time(), "repos": repos, "topics": topics}
    _save(ix)
    _embed(ix, log)
    return ix


def _doc(r: dict) -> str:
    return f"{r['name'].replace('/', ' ')}. {r['description']} Topics: {', '.join(r.get('topics', []))}. " \
           f"Keywords: {', '.join(r.get('keywords', []))}. Language: {r.get('language', '')}"


def _embed(ix: dict, log=print) -> None:
    import numpy as np
    cfg = load_config()
    names = sorted(ix["repos"])
    texts = [_doc(ix["repos"][n]) for n in names]
    hashes = [hashlib.sha1(t.encode()).hexdigest()[:12] for t in texts]
    old = {}
    if EMB.exists() and EMB_META.exists():
        meta = json.loads(EMB_META.read_text(encoding="utf-8"))
        mat = np.load(EMB)
        if meta.get("model") == cfg["embed_model"]:
            old = {n: (h, mat[k]) for k, (n, h) in enumerate(zip(meta["names"], meta["hashes"]))}
    vecs: list = [None] * len(names)
    todo = [k for k, (n, h) in enumerate(zip(names, hashes)) if not (n in old and old[n][0] == h)]
    for k, (n, h) in enumerate(zip(names, hashes)):
        if k not in todo:
            vecs[k] = old[n][1]
    for s in range(0, len(todo), 48):
        chunk = todo[s:s + 48]
        out = nvidia.embed([texts[k] for k in chunk], cfg["embed_model"], "passage", timeout=90)
        for k, v in zip(chunk, out):
            vecs[k] = np.asarray(v, dtype=np.float32)
    if not names:
        return
    mat = np.vstack(vecs).astype(np.float32)
    mat /= np.linalg.norm(mat, axis=1, keepdims=True) + 1e-9
    np.save(EMB, mat)
    EMB_META.write_text(json.dumps({"model": cfg["embed_model"], "names": names, "hashes": hashes}), encoding="utf-8")
    log(f"Embeddings Trendshift: {len(todo)} novos, {len(names)} no total.")


def index_info() -> dict:
    ix = _load()
    return {"repos": len(ix.get("repos", {})), "topics": len(ix.get("topics", {})),
            "fetched": ix.get("fetched", 0), "stale": time.time() - ix.get("fetched", 0) > TTL}


# ---------------- busca ----------------

JUDGE_SYS = ("Você ajuda um usuário do Claude Code a achar repositórios no GitHub (vindos do Trendshift) que "
             "resolvam um pedido que as habilidades instaladas dele não cobrem bem. Seja exigente e honesto. "
             "Responda APENAS JSON.")


def search(prompt: str, k: int = 8, log=print) -> dict:
    import numpy as np
    t0 = time.time()
    cfg = load_config()
    ix = _load()
    if not ix.get("repos") or time.time() - ix.get("fetched", 0) > TTL:
        log("Atualizando índice do Trendshift (1 req/s, pode levar alguns minutos)...")
        ix = build_index(log=log)
    names = sorted(ix["repos"])
    repos = [ix["repos"][n] for n in names]

    # BM25
    docs = [Counter(tok(_doc(r), expand=True)) for r in repos]
    df = Counter()
    for d in docs:
        df.update(d.keys())
    avg = sum(sum(d.values()) for d in docs) / max(1, len(docs))
    q = set(tok(prompt, expand=True))
    bm = []
    for d in docs:
        dl = sum(d.values())
        s = 0.0
        for t in q:
            if t in d:
                idf = math.log(1 + (len(docs) - df[t] + .5) / (df[t] + .5))
                s += idf * d[t] * 2.4 / (d[t] + 1.4 * (.25 + .75 * dl / avg))
        bm.append(s)
    mx = max(bm) or 1
    cos = [0.0] * len(repos)
    try:
        meta = json.loads(EMB_META.read_text(encoding="utf-8"))
        if meta["names"] == names:
            mat = np.load(EMB)
            v = np.asarray(nvidia.embed([prompt], cfg["embed_model"], "query", timeout=20)[0], dtype=np.float32)
            cos = (mat @ (v / (np.linalg.norm(v) + 1e-9))).tolist()
    except Exception:
        pass
    scored = sorted(((.35 * b / mx + .65 * max(0, (c - .12) / .45), r) for b, c, r in zip(bm, cos, repos)),
                    key=lambda x: -x[0])[:25]

    # julgamento NVIDIA
    lines = [f"{n}. {r['name']} [{r.get('language') or '?'} · ★{r.get('stars', 0)}] {r['description'][:220]} "
             f"(tópicos: {', '.join(r.get('topics', [])[:4])})" for n, (_, r) in enumerate(scored, 1)]
    user = (f"PEDIDO: {prompt[:1200]}\n\nCANDIDATOS DO TRENDSHIFT:\n" + "\n".join(lines) +
            '\n\nDevolva {"resultados":[{"n":<número>,"nota":<0-10>,"motivo":"<até 18 palavras, pt-BR>",'
            '"tipo":"<skill-claude|mcp|cli|biblioteca|app|outro>","como_usar":"<até 18 palavras: como '
            'instalar/usar com o Claude Code>"}]} em ordem, só nota >= 6. Lista vazia se nada servir.')
    results, err = [], None
    try:
        txt = nvidia.chat([{"role": "system", "content": JUDGE_SYS}, {"role": "user", "content": user}],
                          model=cfg["rerank_model"], timeout=60, max_tokens=1200, retries=1)
        data = nvidia.extract_json(txt)
        for x in data.get("resultados", []) if isinstance(data, dict) else []:
            try:
                n = int(x["n"])
            except Exception:
                continue
            if 1 <= n <= len(scored):
                r = scored[n - 1][1]
                results.append({**{k2: r.get(k2) for k2 in ("name", "description", "github", "homepage",
                                                            "language", "stars", "topics")},
                                "nota": float(x.get("nota", 0)), "motivo": str(x.get("motivo", ""))[:200],
                                "tipo": str(x.get("tipo", ""))[:20], "como_usar": str(x.get("como_usar", ""))[:200]})
    except Exception as e:
        err = str(e)[:160]
        results = [{**{k2: r.get(k2) for k2 in ("name", "description", "github", "homepage", "language",
                                                "stars", "topics")}, "nota": None, "motivo": "",
                    "tipo": "", "como_usar": ""} for _, r in scored[:k]]
    out = {"t": time.strftime("%Y-%m-%d %H:%M:%S"), "prompt": prompt[:500], "results": results[:k],
           "candidates": len(scored), "indexed": len(repos), "ms": int((time.time() - t0) * 1000), "error": err}
    try:
        DIR.mkdir(parents=True, exist_ok=True)
        with SEARCHES.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(out, ensure_ascii=False) + "\n")
    except Exception:
        pass
    return out


def format_short(res: dict) -> str:
    """Resumo enxuto para o Claude ler (poucos tokens)."""
    if not res["results"]:
        return "Trendshift: nenhum repositório em alta serve para esse pedido."
    rows = [f"Trendshift ({res['indexed']} repos indexados; julgado pela NVIDIA):"]
    for n, r in enumerate(res["results"], 1):
        nota = f"{r['nota']:.0f}/10 " if r.get("nota") is not None else ""
        rows.append(f"{n}. {r['name']} {nota}[{r.get('tipo') or '?'}] {r.get('github', '')}\n"
                    f"   {r.get('motivo') or r.get('description', '')[:140]}"
                    + (f"\n   usar: {r['como_usar']}" if r.get("como_usar") else ""))
    return "\n".join(rows)


def recent_searches(n: int = 20) -> list[dict]:
    if not SEARCHES.exists():
        return []
    out = []
    for line in SEARCHES.read_text(encoding="utf-8").splitlines()[-n:]:
        try:
            out.append(json.loads(line))
        except Exception:
            pass
    return list(reversed(out))
