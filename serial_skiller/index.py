"""Índice local: BM25 (texto) + embeddings NVIDIA (semântico, multilíngue)."""
from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections import Counter

from .config import (CATALOG_FILE, EMB_FILE, EMB_IDS_FILE, INDEX_FILE, ensure_dirs,
                     load_config)
from .bula import load_bula, heuristic_bula
from . import nvidia

STOP = set("""a o os as um uma uns umas de do da dos das em no na nos nas por para pra com sem
que se e ou mas como mais muito muita meu minha seu sua isso isto esse essa este esta eu voce
você ele ela nos nós eles elas ao aos à às ser estar ter fazer faz faça quero queria preciso
pode poderia vai vamos ja já tambem também so só aqui ali the a an of to in on for with and or
is are be this that it its use using when you your can will from by as at into via""".split())

# glossário pt -> en para o BM25 casar pedidos em português com skills em inglês
GLOSS = {
    "animacao": "animation motion animate", "animar": "animate animation", "rolagem": "scroll",
    "botao": "button", "tela": "screen ui", "pagina": "page", "site": "website web landing",
    "interface": "ui interface", "visual": "ui design visual", "bonito": "polish design aesthetic",
    "design": "design ui", "cor": "color", "cores": "colors palette", "fonte": "font typography",
    "tipografia": "typography", "layout": "layout grid", "grade": "grid", "fundo": "background",
    "efeito": "effect", "sombra": "shadow", "vidro": "glass glassmorphism", "escuro": "dark",
    "claro": "light", "painel": "dashboard panel", "grafico": "chart graph dataviz",
    "graficos": "charts dataviz", "tabela": "table", "formulario": "form", "acessibilidade": "accessibility a11y",
    "video": "video", "videos": "video", "audio": "audio sound", "musica": "music", "som": "sound audio",
    "legenda": "captions subtitles", "imagem": "image", "imagens": "images", "foto": "photo image",
    "logo": "logo brand", "marca": "brand", "icone": "icon", "apresentacao": "slides presentation deck",
    "slides": "slides deck", "planilha": "spreadsheet xlsx excel", "documento": "document docx",
    "pdf": "pdf", "teste": "test testing", "testes": "tests testing", "erro": "bug error debug",
    "bug": "bug debug", "trava": "freeze crash bug debug", "travando": "freeze crash bug debug",
    "quebrou": "broken bug debug", "quebrado": "broken bug debug", "falha": "failure bug debug",
    "funciona": "bug debug", "crash": "crash bug debug", "traduzir": "translate", "traduz": "translate", "depurar": "debug", "corrigir": "fix bug", "revisar": "review",
    "revisao": "review", "seguranca": "security", "desempenho": "performance", "lento": "performance slow",
    "otimizar": "optimize performance", "refatorar": "refactor", "arquitetura": "architecture",
    "planejar": "plan planning", "plano": "plan", "tarefa": "task", "tarefas": "tasks",
    "pesquisa": "research search", "pesquisar": "research search", "banco": "database",
    "dados": "data", "jogo": "game", "jogos": "games", "personagem": "character", "cenario": "environment scene",
    "modelo": "model", "modelar": "modeling", "textura": "texture", "material": "material",
    "iluminacao": "lighting", "renderizar": "render", "render": "render", "3d": "3d threejs blender",
    "celular": "mobile", "aplicativo": "app mobile", "app": "app", "android": "android", "ios": "ios",
    "commit": "git commit", "branch": "git branch", "escrever": "writing write", "texto": "text writing copy",
    "humanizar": "humanize", "resumo": "summary", "memoria": "memory", "lembrar": "remember memory",
    "navegador": "browser", "automatizar": "automate automation", "raspar": "scrape", "api": "api",
    "servidor": "server backend", "infografico": "infographic", "diagrama": "diagram",
    "fluxograma": "flowchart diagram", "prototipo": "prototype", "wireframe": "wireframe",
    "componente": "component", "componentes": "components", "particulas": "particles",
    "shader": "shader webgl", "engenharia": "engineering", "reversa": "reverse engineering decompile",
    "descompilar": "decompile", "token": "tokens", "tokens": "tokens", "barato": "cost cheap tokens",
    "explicar": "explain", "aprender": "learn teach", "editar": "edit", "cortar": "cut trim",
    "converter": "convert", "publicar": "publish deploy", "deploy": "deploy", "hospedar": "deploy hosting",
}


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def tokens(s: str, expand: bool = False) -> list[str]:
    toks = [t for t in re.split(r"[^a-z0-9]+", norm(s)) if len(t) > 1 and t not in STOP]
    if expand:
        extra = []
        for t in toks:
            if t in GLOSS:
                extra += GLOSS[t].split()
        toks += extra
    return toks


def doc_fields(item: dict) -> tuple[str, str]:
    """(texto para BM25, texto para embedding)."""
    rec = load_bula(item)
    b = rec["bula"] if rec else heuristic_bula(item)
    name = re.sub(r"[-_:]", " ", item["name"])
    gat = " ; ".join(b.get("gatilhos", []))
    usar = " ; ".join(b.get("usar_quando", []) + b.get("serve_para", []))
    resumo = b.get("resumo", "")
    bm = " ".join([name] * 3 + [gat] * 2 + [resumo, usar, b.get("categoria", ""),
                                             item.get("description", "")])
    emb = f"{item['name']}. {resumo} Usar quando: {usar}. Gatilhos: {gat}. {item.get('description', '')[:700]}"
    return bm, emb


def build(items: list[dict], log=print) -> None:
    ensure_dirs()
    cfg = load_config()
    docs, emb_texts = [], []
    for it in items:
        bm, em = doc_fields(it)
        docs.append(Counter(tokens(bm, expand=True)))
        emb_texts.append(em)
    df: Counter = Counter()
    for d in docs:
        df.update(d.keys())
    lengths = [sum(d.values()) for d in docs]
    index = {
        "ids": [it["id"] for it in items],
        "tf": [dict(d) for d in docs],
        "df": dict(df),
        "len": lengths,
        "avgdl": (sum(lengths) / len(lengths)) if lengths else 1,
    }
    INDEX_FILE.write_text(json.dumps(index), encoding="utf-8")
    CATALOG_FILE.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    log(f"Índice BM25: {len(items)} itens.")
    if cfg["use_embeddings"]:
        try:
            build_embeddings(items, emb_texts, cfg, log)
        except Exception as e:
            log(f"Embeddings indisponíveis ({str(e)[:120]}); seguindo só com BM25.")


def build_embeddings(items, texts, cfg, log) -> None:
    import numpy as np
    old: dict[str, tuple[str, list]] = {}
    if EMB_FILE.exists() and EMB_IDS_FILE.exists():
        meta = json.loads(EMB_IDS_FILE.read_text(encoding="utf-8"))
        mat = np.load(EMB_FILE)
        if meta.get("model") == cfg["embed_model"]:
            for i, (id_, h) in enumerate(zip(meta["ids"], meta["hashes"])):
                old[id_] = (h, mat[i])
    hashes = [hashlib.sha1(t.encode("utf-8")).hexdigest()[:12] for t in texts]
    vecs: list = [None] * len(items)
    todo = []
    for i, (it, h) in enumerate(zip(items, hashes)):
        if it["id"] in old and old[it["id"]][0] == h:
            vecs[i] = old[it["id"]][1]
        else:
            todo.append(i)
    if todo:
        log(f"Gerando embeddings de {len(todo)} itens ...")
    for s in range(0, len(todo), 32):
        chunk = todo[s:s + 32]
        out = nvidia.embed([texts[i] for i in chunk], cfg["embed_model"], "passage", timeout=60)
        for i, v in zip(chunk, out):
            vecs[i] = np.asarray(v, dtype=np.float32)
    mat = np.vstack(vecs).astype(np.float32)
    mat /= np.linalg.norm(mat, axis=1, keepdims=True) + 1e-9
    np.save(EMB_FILE, mat)
    EMB_IDS_FILE.write_text(json.dumps({"model": cfg["embed_model"], "ids": [it["id"] for it in items],
                                        "hashes": hashes}), encoding="utf-8")
    log(f"Embeddings: {mat.shape[0]} x {mat.shape[1]}.")


# ---------------- consulta ----------------

class Index:
    def __init__(self):
        self.items = json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
        self.by_id = {it["id"]: it for it in self.items}
        ix = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
        self.ids, self.tf, self.df = ix["ids"], ix["tf"], ix["df"]
        self.len, self.avgdl = ix["len"], ix["avgdl"]
        self.N = len(self.ids)
        self.mat = None
        if EMB_FILE.exists() and EMB_IDS_FILE.exists():
            meta = json.loads(EMB_IDS_FILE.read_text(encoding="utf-8"))
            if meta["ids"] == self.ids:
                import numpy as np
                self.mat = np.load(EMB_FILE)
                self.embed_model = meta["model"]

    def bm25(self, query: str, k1=1.4, b=0.75) -> list[float]:
        q = tokens(query, expand=True)
        scores = [0.0] * self.N
        for t in set(q):
            n = self.df.get(t)
            if not n:
                continue
            idf = math.log(1 + (self.N - n + 0.5) / (n + 0.5))
            for i, tf in enumerate(self.tf):
                f = tf.get(t)
                if f:
                    scores[i] += idf * f * (k1 + 1) / (f + k1 * (1 - b + b * self.len[i] / self.avgdl))
        return scores

    def cosine(self, query: str, timeout: float) -> list[float] | None:
        if self.mat is None:
            return None
        import numpy as np
        v = np.asarray(nvidia.embed([query], self.embed_model, "query", timeout=timeout)[0], dtype=np.float32)
        v /= np.linalg.norm(v) + 1e-9
        return (self.mat @ v).tolist()
