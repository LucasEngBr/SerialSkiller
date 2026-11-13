<p align="center">
  <img src="docs/assets/target-s-animated.svg" width="132" alt="Serial Skiller logo">
</p>

<h1 align="center">Serial Skiller</h1>

<p align="center">
  <b>A local skill catalog and recommender for Claude Code.</b><br>
  Every installed skill, plugin, agent, command and MCP server gets a "label" (bula).
  On every prompt, Claude sees only the few that fit.
</p>

<p align="center">
  <a href="https://lucasengbr.github.io/SerialSkiller/">Step-by-step guide (pt-BR)</a> ·
  <a href="#quick-start">Quick start</a> ·
  <a href="#using-another-api">Other APIs</a> ·
  <a href="LICENSE">MIT</a>
</p>

---

## Why

Once you install dozens of skills and plugins, you lose track of what you have and when to use each one.
Claude also has to skim hundreds of descriptions to decide. Serial Skiller does that work outside Claude:

- **Catalog with labels.** It scans user skills, plugin skills, agents, commands, MCP servers and Claude Code's native tools.
  Each one gets a label: what it does, when to use it, when to avoid it, strengths, weaknesses and triggers.
- **Per-prompt recommendation.** A `UserPromptSubmit` hook finds the matching items and injects only the top 5, with their labels.
  In `ask` mode, Claude asks you which ones to apply.
- **Local dashboard.** It shows when each item was last used, which were never used and how many tokens you spent.
  It also keeps the recommendation history.
- **Trendshift discovery.** When nothing installed fits, it offers trending GitHub repos from [trendshift.io](https://trendshift.io).
- **Your Claude credits stay untouched.** The heavy lifting (labels, embeddings, judging) runs on an external API you pick.
  The default is NVIDIA's free developer API.

> The interface, labels and hook messages are in Brazilian Portuguese.

## How it works

```
prompt ──► UserPromptSubmit hook (skiller.py hook)
             │ 1. local BM25 search + pt→en glossary      (free, ~50 ms)
             │ 2. semantic similarity (embeddings API)    (~0.5 s)
             │ 3. gate: small talk stops here
             │ 4. optional AI rerank with scores + reason
             ▼
   Claude receives: top 5 + label + mode instruction
```

A `SessionStart` hook re-scans in the background, so anything you install shows up on the next session.

## Quick start

Requirements: Claude Code, Python 3.10+, git. Tested on Windows. macOS and Linux should work too,
since it uses only the Python standard library plus numpy.

```bash
git clone https://github.com/LucasEngBr/SerialSkiller.git
cd SerialSkiller
python -m pip install -r requirements.txt
cp .env.example .env          # Windows: copy .env.example .env
```

1. Get a free key at **[build.nvidia.com/settings/api-keys](https://build.nvidia.com/settings/api-keys)**:
   sign in, click **Generate API Key**, then copy the `nvapi-…` value.
   Put it in `.env` as `NVIDIA_API_KEY=nvapi-...`.
   Free-tier limits and duration are set by NVIDIA.
2. Build the catalog and the AI labels:

   ```bash
   python skiller.py enrich
   ```

3. Install the hooks into `~/.claude/settings.json`. A backup is saved automatically.

   ```bash
   python skiller.py install
   ```

   Restart Claude Code after this.
4. Open the dashboard (`http://127.0.0.1:8765`, localhost only):

   ```bash
   python skiller.py ui
   ```

Keep the folder out of cloud-synced directories: the `data/` folder stores your local catalog and prompt history.

## Modes

| Mode | Behavior |
|---|---|
| `ask` (default) | Claude asks which items to apply, with the best one marked as recommended |
| `auto` | Claude picks on its own and says which one it used |
| `suggest` | The list is shown to Claude, with no instruction |
| `off` | Disabled |

Change it from the dashboard, with `python skiller.py mode <mode>`, or by typing `#skiller <mode>` in a prompt.
Add `#noskill` to a prompt to skip the recommendation that one time.

## Using another API

Any OpenAI-compatible API works. Set these in `.env`:

```ini
SKILLER_API_BASE=https://api.openai.com/v1   # or https://openrouter.ai/api/v1, http://localhost:11434/v1 (Ollama)...
SKILLER_API_KEY=sk-...
SKILLER_CHAT_MODEL=gpt-4.1-mini
SKILLER_RERANK_MODEL=gpt-4.1-mini
SKILLER_EMBED_MODEL=text-embedding-3-small
```

Run `python skiller.py enrich` again after you switch the embedding model.

Without any key, it still works with plain labels built from each skill file, plus keyword-only search.

## Commands

| Command | What it does |
|---|---|
| `sync` | Re-scan installed items (fast, no AI) |
| `enrich` | Re-scan and generate AI labels for whatever changed |
| `rec "prompt"` | Test the recommendation for a prompt |
| `show <name>` | Show one item's label |
| `mode [mode]` | Show or change the mode |
| `stats` | Usage per item and items never used |
| `report` | Write `CATALOGO.md` with every label |
| `discover "prompt"` | Search trending repos on Trendshift |
| `trendshift-sync` | Refresh the local Trendshift index |
| `ui [--port N]` | Open the local dashboard |
| `install` / `uninstall` | Add or remove the Claude Code hooks |

All commands run as `python skiller.py <command>`.

## Privacy

- **Sent to the API you choose:**
  - the skill files' text, to write the labels;
  - your prompt, to search and judge.
- **Kept on your machine:** the catalog, labels, history, usage stats and the key.
  They live in `data/` and `.env`, which git ignores.
- **Dashboard:** it binds to `127.0.0.1` only.
- **Trendshift:** only its public pages are read.
  Requests follow `robots.txt` (no `/api/`), go out at 1 request per second and are cached for 24 h.

## Brand

Noir Glass identity with "The Target" mark: a crosshair whose outer ring forms an S, with a crimson dot for the match.
The brand guide is in `brand/index.html`, and the logo animation spec is in `brand/motion/`.

## License

MIT. This project is not affiliated with Anthropic or NVIDIA.
