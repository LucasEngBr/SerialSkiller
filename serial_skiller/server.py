"""Servidor local do painel (só 127.0.0.1). Sem dependências."""
from __future__ import annotations

import json
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .config import CATALOG_FILE, ROOT, load_config, save_config, DEFAULTS, HISTORY_FILE, CLAUDE_HOME
from .bula import load_bula, heuristic_bula, pending_ai

UI_DIR = ROOT / "ui"
BRAND_DIR = ROOT / "brand"
EDITABLE = {"top_k": int, "pool_ratio": float, "pool_max": int, "gate_score": float,
            "min_score": float, "hook_rerank": bool, "use_embeddings": bool}
MIME = {".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon",
        ".webmanifest": "application/manifest+json", ".html": "text/html; charset=utf-8"}


def hooks_installed() -> bool:
    try:
        return "skiller.py" in (CLAUDE_HOME / "settings.json").read_text(encoding="utf-8")
    except Exception:
        return False


def public_config() -> dict:
    cfg = load_config()
    return {k: cfg[k] for k in EDITABLE} | {"mode": cfg["mode"]}
_lock = threading.Lock()
_state = {"syncing": False}


def _items() -> list[dict]:
    return json.loads(CATALOG_FILE.read_text(encoding="utf-8"))


def _all_history() -> list[dict]:
    out = []
    if HISTORY_FILE.exists():
        for line in HISTORY_FILE.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out


def dashboard() -> dict:
    from .usage import usage_by_item, recommendation_stats
    items = _items()
    usage = usage_by_item(items)
    recs = recommendation_stats()
    rows, ia = [], 0
    days_total: dict[str, int] = {}
    for it in items:
        rec = load_bula(it)
        if rec and rec["origem"].startswith("ia"):
            ia += 1
        b = rec["bula"] if rec else heuristic_bula(it)
        u = usage.get(it["id"])
        if u:
            for d, n in u.get("days", {}).items():
                days_total[d] = days_total.get(d, 0) + n
        rows.append({
            "id": it["id"], "name": it["name"], "kind": it["kind"], "source": it["source"],
            "active": it.get("active", True), "invoke": it["invoke"],
            "resumo": b.get("resumo", ""), "categoria": b.get("categoria") or it["kind"],
            "bula_ia": bool(rec and rec["origem"].startswith("ia")),
            "uses": u["count"] if u else 0, "last": u["last"] if u else "",
            "first": u["first"] if u else "",
            "projects": sorted((u or {}).get("projects", {}).items(), key=lambda x: -x[1])[:5],
            "suggested": recs.get(it["name"], {}).get("count", 0),
            "suggested_last": recs.get(it["name"], {}).get("last", ""),
        })
    history = []
    if HISTORY_FILE.exists():
        for line in HISTORY_FILE.read_text(encoding="utf-8").splitlines()[-40:]:
            try:
                history.append(json.loads(line))
            except Exception:
                pass
    cfg = load_config()
    return {
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "mode": cfg["mode"], "models": {"bula": cfg["chat_model"], "rerank": cfg["rerank_model"],
                                        "embed": cfg["embed_model"]},
        "total": len(items), "bulas_ia": ia, "used": sum(1 for r in rows if r["uses"]),
        "items": rows, "history": list(reversed(history)),
        "days": sorted(days_total.items()), "syncing": _state["syncing"],
        "hooks": hooks_installed(), "config": public_config(),
        "tokens": tokens_summary(items, _all_history()),
    }


def tokens_summary(items: list[dict], history: list[dict]) -> dict:
    from .usage import claude_tokens
    from .config import DATA
    ct = claude_tokens()
    nv = {"chat_in": 0, "chat_out": 0, "embed_in": 0, "calls": 0}
    f = DATA / "nvidia_usage.jsonl"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except Exception:
                continue
            nv["calls"] += 1
            if r["kind"] == "chat":
                nv["chat_in"] += r["in"]; nv["chat_out"] += r["out"]
            else:
                nv["embed_in"] += r["in"]
    hooks = [h for h in history if h.get("hook")]
    ctx = [h.get("ctx_tokens", 0) for h in hooks if h.get("ctx_tokens")]
    # quanto custaria colocar a bula resumida de TODAS as habilidades no contexto
    all_chars = 0
    for it in items:
        rec = load_bula(it)
        b = rec["bula"] if rec else heuristic_bula(it)
        all_chars += len(it["name"]) + len(b.get("resumo", "")) + len("; ".join(b.get("usar_quando", [])[:3])) + 40
    return {"claude": ct, "nvidia": nv, "hook_prompts": len(hooks),
            "ctx_total": sum(ctx), "ctx_avg": round(sum(ctx) / len(ctx)) if ctx else 0,
            "all_bulas_tokens": round(all_chars / 3.6)}


def item_detail(id_: str) -> dict:
    for it in _items():
        if it["id"] == id_:
            rec = load_bula(it)
            return {"item": {k: v for k, v in it.items() if k != "body_excerpt"},
                    "bula": rec["bula"] if rec else heuristic_bula(it),
                    "origem": rec["origem"] if rec else "heuristica"}
    return {}


def _start_ts_build():
    with _lock:
        if _state.get("ts_building"):
            return
        _state["ts_building"] = True

    def run():
        from .discover import build_index
        try:
            build_index(log=lambda *_: None)
        finally:
            _state["ts_building"] = False
    threading.Thread(target=run, daemon=True).start()


def _bg_sync():
    from .scanner import scan_all
    from .bula import ensure_heuristic, enrich
    from .index import build
    from .report import write_report
    try:
        items = scan_all()
        ensure_heuristic(items)
        build(items, log=lambda *_: None)
        if pending_ai(items):
            if enrich(items, log=lambda *_: None)[0]:
                build(items, log=lambda *_: None)
        write_report(items)
    finally:
        _state["syncing"] = False


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # silencioso
        pass

    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data, code=200):
        self._send(code, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        try:
            if u.path in ("/", "/index.html"):
                return self._send(200, (UI_DIR / "index.html").read_bytes(), "text/html; charset=utf-8")
            if u.path.startswith("/brand/"):
                rel = u.path[len("/brand/"):] or "index.html"
                f = (BRAND_DIR / rel).resolve()
                if BRAND_DIR.resolve() in f.parents and f.is_file():
                    return self._send(200, f.read_bytes(), MIME.get(f.suffix, "application/octet-stream"))
                return self._send(404, b"not found", "text/plain")
            if u.path == "/favicon.ico":
                return self._send(200, (BRAND_DIR / "logo" / "favicon.ico").read_bytes(), "image/x-icon")
            if u.path == "/api/config":
                return self._json(public_config())
            if u.path == "/api/dashboard":
                return self._json(dashboard())
            if u.path == "/api/item":
                return self._json(item_detail(q.get("id", [""])[0]))
            if u.path == "/api/rec":
                from .recommend import recommend
                r = recommend(q.get("q", [""])[0], cwd=None)
                return self._json({
                    "weak": r.get("weak", False), "max_cos": r.get("max_cos"),
                    "engine": r["engine"], "ms": r["ms"], "pool": r.get("pool", 0),
                    "error": r.get("ai_error"),
                    "items": [{"id": x["item"]["id"], "name": x["item"]["name"], "kind": x["item"]["kind"],
                               "invoke": x["item"]["invoke"], "nota": x.get("nota"),
                               "score": round(x["score"], 3), "motivo": x.get("motivo", "")}
                              for x in r.get("all", [])]})
            if u.path == "/api/trendshift":
                from .discover import index_info, recent_searches
                return self._json({"index": index_info(), "searches": recent_searches(15),
                                   "building": _state.get("ts_building", False)})
            if u.path == "/api/discover":
                from .discover import search, index_info
                info = index_info()
                if not info["repos"]:
                    _start_ts_build()
                    return self._json({"building": True, "results": [], "index": info})
                if info["stale"]:
                    _start_ts_build()  # atualiza em segundo plano; busca no índice atual
                    import time as _t
                    from . import discover as _d
                    ix = _d._load(); ix["fetched"] = _t.time() - 60; _d._save(ix)
                return self._json(search(q.get("q", [""])[0], k=8, log=lambda *_: None))
            self._send(404, b"not found", "text/plain")
        except Exception as e:
            self._json({"error": str(e)}, 500)

    def do_POST(self):
        u = urlparse(self.path)
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        if u.path == "/api/mode":
            m = body.get("mode")
            if m not in ("ask", "auto", "suggest", "off"):
                return self._json({"error": "modo inválido"}, 400)
            cfg = load_config()
            cfg["mode"] = m
            save_config({k: v for k, v in cfg.items() if DEFAULTS.get(k) != v or k == "mode"})
            return self._json({"mode": m})
        if u.path == "/api/config":
            cfg = load_config()
            for k, typ in EDITABLE.items():
                if k in body:
                    try:
                        cfg[k] = typ(body[k])
                    except (TypeError, ValueError):
                        return self._json({"error": f"valor inválido para {k}"}, 400)
            cfg["top_k"] = max(1, min(cfg["top_k"], 15))
            cfg["pool_ratio"] = max(0.2, min(cfg["pool_ratio"], 0.95))
            save_config({k: v for k, v in cfg.items() if DEFAULTS.get(k) != v or k == "mode"})
            return self._json(public_config())
        if u.path == "/api/sync":
            with _lock:
                if not _state["syncing"]:
                    _state["syncing"] = True
                    threading.Thread(target=_bg_sync, daemon=True).start()
            return self._json({"syncing": True})
        self._send(404, b"not found", "text/plain")


def serve(port: int = 8765, open_browser: bool = True):
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"Painel Serial Skiller em {url}  (Ctrl+C para sair)")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
