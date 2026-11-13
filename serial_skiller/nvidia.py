"""Cliente mínimo de API compatível com OpenAI (NVIDIA por padrão), só stdlib."""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request

from .config import api_key, api_base, is_nvidia, DATA


def _track(kind: str, model: str, d: dict) -> None:
    """Guarda os tokens gastos na API NVIDIA (para o painel)."""
    try:
        u = d.get("usage") or {}
        rec = {"t": time.strftime("%Y-%m-%d %H:%M:%S"), "kind": kind, "model": model,
               "in": int(u.get("prompt_tokens") or 0), "out": int(u.get("completion_tokens") or 0)}
        with (DATA / "nvidia_usage.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")
    except Exception:
        pass


class NvidiaError(RuntimeError):
    pass


def _post(path: str, body: dict, timeout: float) -> dict:
    key = api_key()
    if not key:
        raise NvidiaError("chave de API ausente: defina NVIDIA_API_KEY ou SKILLER_API_KEY no .env")
    req = urllib.request.Request(
        api_base() + path,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        msg = e.read().decode("utf-8", "replace")[:300]
        raise NvidiaError(f"HTTP {e.code}: {msg}") from e
    except Exception as e:  # timeout, rede
        raise NvidiaError(str(e)) from e


def chat(messages: list[dict], model: str, timeout: float = 60, max_tokens: int = 1200,
         retries: int = 2) -> str:
    body = {
        "model": model,
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": max_tokens,
    }
    if is_nvidia():
        # desliga o modo "pensar" dos Nemotron/Qwen: resposta direta e rápida
        body["chat_template_kwargs"] = {"enable_thinking": False}
    last = None
    for attempt in range(retries + 1):
        try:
            d = _post("/chat/completions", body, timeout)
            _track("chat", model, d)
            msg = d["choices"][0]["message"]
            return (msg.get("content") or msg.get("reasoning_content") or "").strip()
        except NvidiaError as e:
            last = e
            if "HTTP 4" in str(e) and "429" not in str(e):
                break
            time.sleep(2 * (attempt + 1))
    raise last  # type: ignore[misc]


def embed(texts: list[str], model: str, input_type: str = "passage", timeout: float = 30) -> list[list[float]]:
    body = {"model": model, "input": texts, "encoding_format": "float"}
    if is_nvidia():  # parâmetros extras que só a NVIDIA aceita
        body.update(input_type=input_type, truncate="END")
    d = _post("/embeddings", body, timeout)
    _track("embed", model, d)
    return [x["embedding"] for x in sorted(d["data"], key=lambda x: x["index"])]


def extract_json(text: str):
    """Pega o primeiro objeto/array JSON de uma resposta de LLM."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    text = re.sub(r"```(?:json)?", "", text)
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        end = text.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError("resposta sem JSON válido")
