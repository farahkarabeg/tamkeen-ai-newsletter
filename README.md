# AI Pulse — Weekly AI News Digest

An automated, scheduled agent that scans public AI-news sources, curates and
summarises the most relevant developments **for Tamkeen's context**, compiles
them into an on-brand Microsoft Teams digest, routes the draft to **Policy &
Strategy (P&S)** for sign-off, and — only on approval — broadcasts it to an
all-staff Teams channel.

It replaces the status quo where staff have no reliable way to stay current and
relevant model releases, policy moves, and sector applications surface late or
not at all.

---

## How it works (at a glance)

```
            ┌──────── Phase A (weekly, automatic) ────────┐      ┌── Phase B (manual) ──┐
 RSS/Atom ─▶│ ingest ─▶ dedup ─▶ curate (Claude) ─▶ compose │     │  broadcast approved   │
 + HN API   │            │                           │       │     │  draft to all-staff   │
            │            ▼                           ▼       │     │                       │
            │      SQLite "seen" store        Adaptive Card  │     │  loads the EXACT saved │
            │                                  (saved draft) │     │  card — never regen'd  │
            └──────────────┬──────────────────────────────┘      └───────────┬───────────┘
                           ▼                                                  ▼
              Posts DRAFT to the P&S review channel               Posts to the all-staff channel
```

- **Phase A** runs on a weekly cron, generates the digest, and posts a clearly
  banner-marked **DRAFT** to the P&S review channel. Nothing reaches staff yet.
- **Phase B** is triggered by a reviewer *after* approval. It loads the saved
  draft and broadcasts the **exact** reviewed card to all staff — the content is
  never regenerated between review and broadcast.

### Sources
Config-driven RSS/Atom feeds (the major AI labs, reputable tech press AI
sections, arXiv `cs.AI`/`cs.LG`) plus Hacker News via the Algolia API, all
filtered to the last 7 days. Feeds are validated at startup; a dead feed is
logged and skipped, never fatal. Add or remove feeds in `config.yaml` — no code
changes.

---

## Quick start (local dry-run — do this first)

You do **not** need any Teams webhooks to try it. `--dry-run` does everything
except posting: it prints the rendered Adaptive Card JSON and a readable preview.

```bash
# 1. Python 3.11+ then:
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS/Linux

pip install -r requirements.txt
pip install -e .

# 2. Provide your Anthropic key (for the curation/summary step)
copy .env.example .env           # then edit .env and paste your key
#   ANTHROPIC_API_KEY=sk-ant-...

# 3. Dry run — curate + render, post nothing:
python -m ai_pulse --dry-run
```

You should see a branded digest of 5–8 stories. Once that looks right, wire up
Teams and the schedule below.

> **No Anthropic key handy?** `python scripts/offline_dryrun.py` runs the whole
> pipeline against live feeds with the Claude step stubbed (keyword scoring +
> placeholder summaries) — useful as a smoke test. It is not part of the product.

---

## Manual setup (one-time)

### (a) Get an Anthropic API key
1. Sign in at <https://console.anthropic.com/>.
2. **Settings → API Keys → Create Key**. Copy it (starts with `sk-ant-`).
3. Keep it secret. You'll paste it into `.env` (local) or a GitHub secret (CI).

### (b) Create the two Teams webhooks (Power Automate "Workflows")
We use the modern **Power Automate "Workflows"** incoming webhook — the
replacement for the **retired** Office 365 / Incoming Webhook connector. Do this
**twice**: once for the **P&S review** channel, once for the **all-staff** channel.

For each channel:
1. In Teams, go to the channel → **••• (More options) → Workflows**.
2. Choose the template **"Post to a channel when a webhook request is received."**
   (Search "webhook" if you don't see it.)
3. Pick the **Team** and **Channel**, then **Create**.
4. Teams shows a **URL** — copy it. This is your webhook for that channel.
5. Repeat for the second channel.

You now have two URLs:
- the **review** channel URL → `TEAMS_REVIEW_WEBHOOK_URL`
- the **all-staff** channel URL → `TEAMS_BROADCAST_WEBHOOK_URL`

Paste them into `.env` for local use, and/or into GitHub secrets for the
schedule (next step). They are referenced in `config.yaml` **by env-var name
only** — the URLs themselves never live in the repo.

### (c) Set GitHub secrets
In the GitHub repo: **Settings → Secrets and variables → Actions → New repository
secret**. Add:

| Secret name | Value |
|---|---|
| `ANTHROPIC_API_KEY` | your Anthropic key |
| `TEAMS_REVIEW_WEBHOOK_URL` | the P&S review channel webhook |
| `TEAMS_BROADCAST_WEBHOOK_URL` | the all-staff channel webhook |

### (d) Enable the schedule
The workflow `.github/workflows/weekly-digest.yml` runs **Phase A** on a cron.
The default is **daily, Mon–Fri 06:17 UTC (10:17 Gulf Standard Time)** — driven
by `schedule.cadence: daily` in `config.yaml`. (The cron is kept off the top of
the hour because GitHub's `:00` slots are heavily contended and often delayed.)
To change cadence/time:

- **Daily ↔ weekly:** set `schedule.cadence` (`daily` or `weekly`) in
  `config.yaml`. This drives the digest id scheme (date `2026-06-17` vs ISO week
  `2026-W25`) and the header ("Wednesday, 17 June 2026" vs "Week of …").
- **Time/days:** edit the `cron` line in the workflow (UTC) and keep
  `schedule.cron_utc` in `config.yaml` in sync. For weekly, also bump
  `lookback_days` to 7 and `select_min/max` to 5/8 (see the note in config).

GitHub runs scheduled workflows automatically once the file is on the default
branch; you can also trigger it any time from **Actions → "AI Pulse — Phase A" →
Run workflow**.

### (e) How P&S reviews and triggers the broadcast
1. Each week, Phase A posts a **DRAFT** card to the P&S review channel. Its
   footer/run-log shows the **digest id** (e.g. `2026-W25`).
2. A reviewer reads the draft. If changes are needed, adjust `config.yaml`
   (feeds, context profile, top-N) and re-run Phase A to regenerate.
3. To publish, go to **Actions → "AI Pulse — Phase B (broadcast)" → Run
   workflow**, enter the **digest id**, and run it. The exact reviewed card goes
   to the all-staff channel, and those stories are marked "sent" so they never
   appear in a future week.

   Equivalent locally: `python -m ai_pulse --broadcast --digest 2026-W25`

---

## Configuration (`config.yaml`)

Everything tunable lives in one well-commented file:

- **`ingest.feeds`** — add/remove/disable feeds; `weight` nudges relevance.
- **`ingest.hacker_news`** — query + minimum points.
- **`curate.context_profile`** — the steerable **Tamkeen context profile**:
  mission, audience, tone, and weighted **themes** (education & human-capital,
  public-sector/government AI, MENA/Gulf, frontier releases, AI policy). Reweight
  the themes or edit keywords to re-steer what gets selected.
- **`curate.select_min/max`, `relevance_floor`** — how many stories, how strict.
- **`compose.brand`** — Tamkeen green `#006A4E`, gold `#C0921E`, titles, footer.
- **`deliver.*`** — which env vars hold the two webhook URLs; retry settings.

Config is validated with pydantic at startup, so a typo fails fast with a clear
message rather than mid-run.

> **A note on brand colour.** Teams Adaptive Cards restrict text colour to a
> named palette (no arbitrary hex on text). We use the closest supported
> treatment (emphasis containers, accent/"good" text, separators) to evoke the
> Tamkeen palette, and carry the exact brand hex in the card metadata so the
> documented hosted-card upgrade (below) can apply true brand colour with no code
> change.

---

## Command reference

```bash
python -m ai_pulse                          # Phase A: generate + post draft to P&S
python -m ai_pulse --dry-run                # generate + preview, post nothing
python -m ai_pulse --list-digests           # list saved draft ids
python -m ai_pulse --broadcast --digest ID  # Phase B: broadcast a reviewed draft
python -m ai_pulse --config path/to.yaml    # use a non-default config
```

---

## What's intentionally out of scope

- **Per-person 1:1 delivery.** Delivery is to Teams **channels** only. Sending a
  DM to each employee would require **Microsoft Graph** + an **Azure AD app
  registration** (and per-user consent) — deliberately not built.
- **Interactive Approve/Reject buttons on the card.** The approval gate here is a
  two-phase manual trigger (Phase A draft → reviewer runs Phase B). True in-card
  Approve/Reject buttons require a **hosted bot endpoint** (Bot Framework / Graph)
  to receive the button callback. The upgrade path: host a small bot that listens
  for `Action.Execute` callbacks, validates the approver, and invokes the same
  Phase B broadcast. The current design already separates draft from broadcast,
  so only the trigger mechanism would change.

---

## Project structure

```
ai-pulse/
├─ config.yaml                # feeds, context profile, brand, schedule (commented)
├─ .env.example               # every required secret, documented
├─ requirements.txt           # runtime deps
├─ src/ai_pulse/
│  ├─ config.py               # pydantic config models + loader
│  ├─ ingest.py               # feed validation + fetch + Hacker News
│  ├─ dedup.py                # SQLite "seen" store + URL normalisation
│  ├─ curate.py               # Claude scoring + summaries (Curator)
│  ├─ compose.py              # Adaptive Card 1.5 + plain-text fallback
│  ├─ deliver.py              # Teams Workflows webhook POST (+ retries)
│  ├─ state.py                # save/load digests (exact-draft broadcast)
│  ├─ pipeline.py             # Phase A / Phase B orchestration
│  └─ cli.py                  # argparse entry point
├─ tests/                     # pytest: ingest, dedup, curate, compose, deliver
├─ scripts/offline_dryrun.py  # no-key live smoke test (Claude stubbed)
└─ .github/workflows/
   ├─ weekly-digest.yml       # Phase A cron (Thu 06:00 UTC) + manual dispatch
   └─ broadcast.yml           # Phase B manual broadcast (workflow_dispatch)
```

State (`state/`) and logs (`logs/`) are git-ignored locally; in CI the workflows
commit `state/` back to the repo so the dedup store and the reviewable draft
persist between runs.

---

## Resilience & observability

- A single dead feed, a failed summary, or a Teams 4xx is logged and captured in
  the **run report** — the run continues. Network calls and the Teams POST use
  exponential backoff; non-retryable 4xx errors fail fast with a clear message.
- Structured logging goes to stdout **and** a rotating file (`logs/ai_pulse.log`).
- Every run ends with a report: feeds ok/failed, items scanned, deduped,
  selected, summary failures, delivery target, and any errors.

---

## Testing

```bash
pip install -r requirements-dev.txt
pytest
```

All network and Anthropic calls are mocked. Coverage spans feed parsing, dedup +
URL normalisation, relevance selection, Adaptive Card rendering, and the Teams
payload shape.
