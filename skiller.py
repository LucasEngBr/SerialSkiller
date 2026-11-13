#!/usr/bin/env python
"""Serial Skiller — CLI.

Uso rápido:
  python skiller.py sync              varre tudo, atualiza índice (rápido, sem IA)
  python skiller.py enrich            gera bulas com IA NVIDIA (cache; só o que mudou)
  python skiller.py rec "pedido"      recomenda habilidades para um pedido
  python skiller.py show <nome>       mostra a bula de uma habilidade
  python skiller.py mode ask|auto|suggest|off
  python skiller.py report            gera CATALOGO.md
  python skiller.py stats             resumo do catálogo e do histórico
  python skiller.py ui                abre o painel (http://127.0.0.1:8765)
  python skiller.py discover "pedido" busca repositórios no Trendshift (NVIDIA julga)
  python skiller.py trendshift-sync   atualiza o índice local do Trendshift
  python skiller.py install|uninstall liga/desliga os hooks no Claude Code
  python skiller.py hook              (usado pelo Claude Code; lê JSON no stdin)
"""
from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from serial_skiller import config as C  # noqa: E402

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


def cmd_sync(args, log=print) -> list[dict]:
    from serial_skiller.scanner import scan_all
    from serial_skiller.bula import ensure_heuristic
    from serial_skiller.index import build
    C.ensure_dirs()
    items = scan_all(getattr(args, "project", None))
    n = ensure_heuristic(items)
    log(f"Encontrados {len(items)} itens ({n} bulas novas/alteradas).")
    build(items, log)
    return items


def cmd_enrich(args):
    from serial_skiller.bula import enrich
    from serial_skiller.index import build
    from serial_skiller.report import write_report
    items = cmd_sync(args)
    ok, fail = enrich(items, args.limit)
    if ok:
        build(items)
    write_report(items)
    print(f"Concluído: {ok} bulas IA novas, {fail} falhas. Relatório: {C.REPORT_FILE}")


def cmd_rec(args):
    from serial_skiller.recommend import recommend, format_for_human
    r = recommend(" ".join(args.prompt), cwd=args.cwd or os.getcwd(), deep=not args.fast)
    print(format_for_human(r))


def cmd_show(args):
    from serial_skiller.bula import load_bula, heuristic_bula
    items = json.loads(C.CATALOG_FILE.read_text(encoding="utf-8"))
    q = args.name.lower()
    hits = [it for it in items if it["name"].lower() == q] or [it for it in items if q in it["name"].lower()]
    if not hits:
        print("Nada encontrado.")
        return
    for it in hits[:5]:
        rec = load_bula(it)
        b = rec["bula"] if rec else heuristic_bula(it)
        print(f"== {it['name']}  [{it['kind']} · {it['source']}]  bula: {rec['origem'] if rec else 'heuristica'}")
        print(f"invocar: {it['invoke']}\narquivo: {it['path']}")
        for k, v in b.items():
            if v:
                print(f"  {k}: {v if isinstance(v, str) else '; '.join(v)}")
        print()


def cmd_mode(args):
    cfg = C.load_config()
    if args.value:
        if args.value not in ("ask", "auto", "suggest", "off"):
            sys.exit("modo inválido: use ask | auto | suggest | off")
        cfg["mode"] = args.value
        C.save_config({k: v for k, v in cfg.items() if C.DEFAULTS.get(k) != v or k == "mode"})
    print(f"Modo atual: {cfg['mode']}")


def cmd_report(args):
    from serial_skiller.report import write_report
    items = json.loads(C.CATALOG_FILE.read_text(encoding="utf-8"))
    print(write_report(items))


def cmd_stats(args):
    from collections import Counter
    from serial_skiller.bula import load_bula
    items = json.loads(C.CATALOG_FILE.read_text(encoding="utf-8"))
    kinds = Counter(it["kind"] for it in items)
    ia = sum(1 for it in items if (load_bula(it) or {}).get("origem", "").startswith("ia"))
    print(f"Itens: {len(items)}  | bulas IA: {ia}  | modo: {C.load_config()['mode']}")
    for k, n in kinds.most_common():
        print(f"  {k}: {n}")
    if C.HISTORY_FILE.exists():
        picks = Counter()
        lines = C.HISTORY_FILE.read_text(encoding="utf-8").splitlines()
        for line in lines:
            try:
                picks.update(json.loads(line)["picks"])
            except Exception:
                pass
        print(f"\nRecomendações feitas: {len(lines)}. Mais sugeridas:")
        for name, n in picks.most_common(10):
            print(f"  {n:3d}  {name}")


# ---------------- hooks ----------------

TRIVIAL = {"ok", "sim", "nao", "não", "obrigado", "valeu", "continue", "continua", "pode", "beleza", "blz",
           "yes", "no", "thanks", "go", "ola", "olá", "oi"}


def cmd_hook(args):
    """UserPromptSubmit: lê o pedido e injeta as bulas das habilidades que combinam."""
    try:
        data = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace") or "{}")
    except Exception:
        return
    cfg = C.load_config()
    prompt = (data.get("prompt") or "").strip()
    if cfg["mode"] == "off" or not prompt or not C.CATALOG_FILE.exists():
        return
    low = prompt.lower()
    if (low.startswith("/") or "#noskill" in low or low.strip(" .!?") in TRIVIAL
            or len(prompt) < cfg["min_prompt_chars"]):
        return
    # avisos automáticos (tarefas em segundo plano, lembretes do sistema) não são pedidos do usuário
    head = low.lstrip()[:200]
    if (head.startswith(("<task-notification", "[system notification", "<system-reminder", "<local-command",
                         "<command-name>", "<bash-")) or "<task-notification>" in low[:2000]):
        return
    # comando para trocar modo direto do chat: "#skiller auto"
    if low.startswith("#skiller"):
        parts = low.split()
        if len(parts) > 1 and parts[1] in ("ask", "auto", "suggest", "off"):
            cfg["mode"] = parts[1]
            C.save_config(cfg)
            print(f"[Serial Skiller] modo alterado para {parts[1]}. Avise o usuário em uma linha.")
        return
    from serial_skiller.recommend import recommend, format_for_claude
    try:
        r = recommend(prompt, cwd=data.get("cwd"), transcript=data.get("transcript_path"), hook=True)
    except Exception as e:
        print(json.dumps({"systemMessage": f"Serial Skiller: erro {str(e)[:100]}"}))
        return
    text = format_for_claude(r, cfg["mode"])
    if not text:
        return
    out = {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": text}}
    # linha de status na interface do Claude Code: o app mostra como aviso, então só se pedido
    if cfg.get("show_status"):
        names = ", ".join(x["item"]["name"] for x in r["items"]) or "nenhuma habilidade local"
        extra = " · Trendshift disponível" if r.get("weak") else ""
        out["systemMessage"] = f"Serial Skiller ({r['ms']} ms): {names}{extra}"
    print(json.dumps(out, ensure_ascii=False))


def cmd_session_start(args):
    """SessionStart: ressincroniza em segundo plano, sem atrasar a sessão."""
    C.ensure_dirs()
    extra = {}
    if os.name == "nt":
        extra["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
    else:
        extra["start_new_session"] = True  # macOS/Linux: solta do processo do Claude Code
    log = open(C.DATA / "background.log", "a", encoding="utf-8")
    subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "background"],
                     stdout=log, stderr=log, stdin=subprocess.DEVNULL, close_fds=True, **extra)


def cmd_background(args):
    import time
    from serial_skiller.bula import enrich, pending_ai
    from serial_skiller.index import build
    from serial_skiller.report import write_report
    lock = C.DATA / ".bg.lock"
    if lock.exists() and time.time() - lock.stat().st_mtime < 3600:
        return
    lock.write_text(str(os.getpid()))
    try:
        print(f"--- {time.strftime('%Y-%m-%d %H:%M:%S')} sync")
        items = cmd_sync(args)
        if C.api_key() and pending_ai(items):
            ok, _ = enrich(items)
            if ok:
                build(items)
        write_report(items)
        # índice do Trendshift: renova se passou de 24 h (1 req/s, cresce ~250 repos por rodada)
        if C.api_key():
            from serial_skiller.discover import index_info, build_index
            if index_info()["stale"]:
                print("trendshift: atualizando índice")
                build_index(detail_limit=250)
    finally:
        lock.unlink(missing_ok=True)


def _settings_path() -> Path:
    return C.CLAUDE_HOME / "settings.json"


def _hook_cmd(sub: str) -> str:
    py = Path(sys.executable).as_posix()
    return f'"{py}" "{Path(__file__).resolve().as_posix()}" {sub}'


def cmd_install(args):
    import shutil
    sp = _settings_path()
    s = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else {}
    shutil.copy(sp, sp.with_suffix(".json.serial-skiller.bak")) if sp.exists() else None
    hooks = s.setdefault("hooks", {})
    for event, sub, timeout in (("UserPromptSubmit", "hook", 20), ("SessionStart", "session-start", 10)):
        lst = [h for h in hooks.get(event, []) if "skiller.py" not in json.dumps(h)]
        lst.append({"hooks": [{"type": "command", "command": _hook_cmd(sub), "timeout": timeout,
                               "statusMessage": "Serial Skiller..." if sub == "hook" else None}]})
        for h in lst[-1]["hooks"]:
            if h.get("statusMessage") is None:
                h.pop("statusMessage", None)
        hooks[event] = lst
    sp.write_text(json.dumps(s, indent=2, ensure_ascii=False), encoding="utf-8")
    # skill de apoio para uso manual
    sk = C.CLAUDE_HOME / "skills" / "serial-skiller"
    sk.mkdir(parents=True, exist_ok=True)
    (sk / "SKILL.md").write_text(SKILL_MD.replace("{CLI}", _hook_cmd("").strip()), encoding="utf-8")
    print(f"Hooks instalados em {sp} (backup: settings.json.serial-skiller.bak).")
    print(f"Skill criada em {sk}. Reinicie a sessão do Claude Code.")


def cmd_discover(args):
    """Busca no Trendshift. Trabalho feito local + NVIDIA; imprime resumo curto."""
    from serial_skiller.discover import search, format_short
    res = search(" ".join(args.prompt), k=args.k, log=lambda m: print(m, file=sys.stderr))
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
    else:
        print(format_short(res))


def cmd_trendshift_sync(args):
    from serial_skiller.discover import build_index
    build_index(detail_limit=args.details)


def cmd_ui(args):
    from serial_skiller.server import serve
    serve(args.port, not args.no_browser)


def cmd_uninstall(args):
    sp = _settings_path()
    s = json.loads(sp.read_text(encoding="utf-8"))
    for event in list(s.get("hooks", {})):
        s["hooks"][event] = [h for h in s["hooks"][event] if "skiller.py" not in json.dumps(h)]
        if not s["hooks"][event]:
            del s["hooks"][event]
    if not s.get("hooks"):
        s.pop("hooks", None)
    sp.write_text(json.dumps(s, indent=2, ensure_ascii=False), encoding="utf-8")
    print("Hooks removidos. A pasta ~/.claude/skills/serial-skiller foi mantida (apague se quiser).")


SKILL_MD = """---
name: serial-skiller
description: Catálogo local de TODAS as habilidades instaladas (skills, plugins, agentes, comandos, MCP, nativas) com bula de cada uma, e recomendador que diz quais servem para um pedido. Use quando o usuário perguntar "qual skill uso para X", "o que eu tenho instalado para Y", "mostre a bula de Z", pedir para trocar o modo do Serial Skiller (ask/auto/suggest/off), ou quando você estiver em dúvida sobre qual habilidade aplicar.
---

# Serial Skiller

Catálogo e recomendador local. Rode os comandos com a ferramenta Bash/PowerShell:

- Recomendar para um pedido: `{CLI} rec "<pedido>"`
- Ver a bula de uma habilidade: `{CLI} show <nome>`
- Trocar modo: `{CLI} mode ask|auto|suggest|off`
  - ask: o hook sugere e você pergunta ao usuário com AskUserQuestion
  - auto: você escolhe e carrega sozinho
  - suggest: só mostra a lista
  - off: desligado
- Atualizar catálogo depois de instalar algo: `{CLI} sync` (rápido) e `{CLI} enrich` (bulas por IA)
- Quando nada instalado serve, buscar repositórios em alta no Trendshift (trabalho feito pela NVIDIA, volta resumo curto): `{CLI} discover "<pedido>"`
- Estatísticas: `{CLI} stats`
- Painel: `{CLI} ui` (abre http://127.0.0.1:8765)

O relatório completo fica em `CATALOGO.md` na pasta do projeto Serial Skiller.
O usuário também pode trocar o modo digitando `#skiller auto` (ou ask/suggest/off) no chat,
e pular a recomendação num pedido incluindo `#noskill`.
"""


def main():
    ap = argparse.ArgumentParser(prog="skiller", description="Serial Skiller")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("sync"); p.add_argument("--project")
    p = sub.add_parser("enrich"); p.add_argument("--limit", type=int); p.add_argument("--project")
    p = sub.add_parser("rec"); p.add_argument("prompt", nargs="+"); p.add_argument("--cwd"); p.add_argument("--fast", action="store_true")
    p = sub.add_parser("show"); p.add_argument("name")
    p = sub.add_parser("mode"); p.add_argument("value", nargs="?")
    sub.add_parser("report"); sub.add_parser("stats"); sub.add_parser("hook")
    sub.add_parser("session-start"); sub.add_parser("background")
    sub.add_parser("install"); sub.add_parser("uninstall")
    p = sub.add_parser("discover"); p.add_argument("prompt", nargs="+"); p.add_argument("-k", type=int, default=6); p.add_argument("--json", action="store_true")
    p = sub.add_parser("trendshift-sync"); p.add_argument("--details", type=int, default=250)
    p = sub.add_parser("ui"); p.add_argument("--port", type=int, default=8765); p.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()
    {
        "sync": cmd_sync, "enrich": cmd_enrich, "rec": cmd_rec, "show": cmd_show, "mode": cmd_mode,
        "report": cmd_report, "stats": cmd_stats, "hook": cmd_hook, "session-start": cmd_session_start,
        "background": cmd_background, "ui": cmd_ui, "discover": cmd_discover,
        "trendshift-sync": cmd_trendshift_sync, "install": cmd_install, "uninstall": cmd_uninstall,
    }[args.cmd](args)


if __name__ == "__main__":
    main()
