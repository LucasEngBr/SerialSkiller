"""Caminhos, configuração e leitura do .env."""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
BULAS_DIR = DATA / "bulas"
CATALOG_FILE = DATA / "catalog.json"
INDEX_FILE = DATA / "index.json"
EMB_FILE = DATA / "embeddings.npy"
EMB_IDS_FILE = DATA / "embeddings_ids.json"
HISTORY_FILE = DATA / "history.jsonl"
REPORT_FILE = ROOT / "CATALOGO.md"
CONFIG_FILE = ROOT / "config.json"
ENV_FILE = ROOT / ".env"

CLAUDE_HOME = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
CLAUDE_JSON = Path.home() / ".claude.json"

DEFAULTS = {
    # ask = Claude pergunta qual usar | auto = Claude escolhe sozinho
    # suggest = só mostra a lista | off = desligado
    "mode": "ask",
    "top_k": 5,
    "min_score": 0.45,   # sem IA: nota mínima para listar
    "gate_score": 0.30,  # abaixo disso nem consulta (papo/saudação)
    "weak_score": 0.55,  # sem embeddings: abaixo disso a cobertura local é fraca
    "weak_cos": 0.34,    # similaridade máxima abaixo disso = nada instalado cobre bem -> oferece Trendshift
    "min_prompt_chars": 12,
    "show_status": False,  # linha "Serial Skiller (...)" na interface; o app mostra como aviso
    "chat_model": "nvidia/nemotron-3.5-lightning-30b-a3b",   # gera as bulas
    "rerank_model": "minimaxai/minimax-m3.1-flash",          # julga o pedido
    "embed_model": "nvidia/nemotron-3.5-embed-1b",
    # outro provedor? defina SKILLER_API_BASE/SKILLER_API_KEY no .env e troque os 3 modelos acima
    # (ou use as variáveis SKILLER_CHAT_MODEL, SKILLER_RERANK_MODEL, SKILLER_EMBED_MODEL)
    "use_embeddings": True,
    "hook_rerank": False,  # juiz IA no hook: mais preciso, porém +2-10 s por pedido
    "hook_embed_timeout": 4,
    "hook_rerank_timeout": 6,
    "pool_ratio": 0.6,   # entra no pool quem tem >= 60% da nota da melhor
    "pool_min": 8,
    "pool_max": 40,
    "hook_pool_max": 15,  # dentro do hook, limite menor para caber no tempo
    "enrich_workers": 3,
    "include_library": True,
    "include_inactive_plugins": False,
}


def load_env() -> None:
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    if CONFIG_FILE.exists():
        try:
            cfg.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
        except Exception:
            pass
    load_env()
    for k in ("chat_model", "rerank_model", "embed_model"):
        v = os.environ.get("SKILLER_" + k.upper())
        if v:
            cfg[k] = v
    return cfg


def save_config(cfg: dict) -> None:
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


NVIDIA_BASE = "https://integrate.api.nvidia.com/v1"


def api_key() -> str | None:
    """Chave da API. SKILLER_API_KEY vale para qualquer provedor; NVIDIA_API_KEY é o padrão."""
    load_env()
    return os.environ.get("SKILLER_API_KEY") or os.environ.get("NVIDIA_API_KEY")


def api_base() -> str:
    """URL de qualquer API compatível com OpenAI (NVIDIA por padrão)."""
    load_env()
    return (os.environ.get("SKILLER_API_BASE") or NVIDIA_BASE).rstrip("/")


def is_nvidia() -> bool:
    return "nvidia.com" in api_base()


def ensure_dirs() -> None:
    DATA.mkdir(exist_ok=True)
    BULAS_DIR.mkdir(exist_ok=True)
