# Ariadne — sericulture supply-chain resilience (Team 14)

Agentic triage and dynamic rerouting across mulberry → silkworm → reeler → spinner, with warehouses.
Stack per the design doc: React + Tailwind, FastAPI, LangGraph, ChromaDB, PostgreSQL, Google OR-Tools, Groq (structuring only).

> **Full run guide, example-data reference and a step-by-step demo script: [`docs/RUNNING_AND_DEMO.md`](docs/RUNNING_AND_DEMO.md)**

## Run it

```bash
docker compose up -d --build        # postgres + backend (seeds, ingests KB) + frontend
open http://localhost:5173          # API docs: http://localhost:8000/docs
```
Demo logins (password `ariadne123`): `mf1` mulberry farmer · `sf1` silkworm farmer · `reeler1` · `spinner1`.
(`mf1..mf10`, `sf1..sf10`, `reeler1..5`, `spinner1..4` all exist. Each reeler and spinner owns its warehouse; there is no separate warehouse login.)

Local dev (hot reload): `docker compose up -d postgres`, then
`cd backend && python3.10 -m venv .venv && .venv/bin/pip install -r requirements.txt && .venv/bin/python -m app.db.seed && .venv/bin/python -m app.rag.ingest && .venv/bin/uvicorn app.main:app --reload`
and `cd frontend && npm i && npm run dev` (proxies `/api` to :8000).

Reset demo data: `python -m app.db.seed --reset` (drops the schema). Tests: `cd backend && .venv/bin/python -m pytest -q`.

## Plug in your own material (nothing else needs to change)
| What | Where | Notes |
|---|---|---|
| Mulberry / silkworm disease models | `data/models/<crop>.onnx` + `<crop>.json` | See `data/models/README.md`. Until then a **flagged stub** is used (label from file name, e.g. `grasserie_x.jpg`). Other formats: implement `DiseaseClassifier` in `backend/app/vision/classifier.py`. |
| Knowledge base | `data/kb/<topic>/*.md|txt|pdf` | 13 real public documents are included (see `data/kb/SOURCES.md`) alongside 8 placeholder notes. Add more, then `python -m app.rag.ingest --reset`. |
| Gemini key | `.env` → `GEMINI_API_KEY` | Drives the agents: LLM triage with follow-up questions, a function-calling advisor with read-only tools, LLM-graded RAG, recovery planning. See *How the agents work* below and `docs/RUNNING_AND_DEMO.md` §3.3. Without it everything runs on the rule-based path. |
| Groq key (optional) | `.env` → `GROQ_API_KEY` | If set, Groq formats structured output instead of Gemini. |
| LangSmith key | `.env` → `LANGSMITH_API_KEY` | Tracing turns on automatically. A local per-incident trace is always recorded and shown in the UI. |
| Real farmers / reelers / spinners / warehouses | tables `entities`, `links`, `inventory` | `backend/app/db/seed.py` generates a synthetic network around Ramanagara. |

## How the agents work
The graph is LangGraph; each node is either deterministic (calculations, OR-Tools routing, the severity × urgency matrix, ledger) or an **LLM agent step with a deterministic fallback**:
* **Triage** reads free text and asks a follow-up when it is unclear. **Advisor** runs a Gemini function-calling loop over read-only, entity-scoped tools and must cite retrieved passages. **RAG** is LLM-graded. **Recovery planner** picks a sourcing strategy.
* The model never writes: stock and money only move through deals a human approves. Decision fields (severity, priority, escalation) are locked to the calculations, citations are verified against what was actually retrieved, and unsupported advice is labelled.
* Calls are rate-limited, retried and budgeted per request; any failure drops that step to its rule-based path.

## Phase-by-phase demo script
1. **Foundation & roles** — log in as each role. `mf1` sees only own farm; `sf1` also sees supplying mulberry farmers and reelers; `reeler1` sees spinners/farmers; `spinner1` his reelers. 
2. **Inventory, calculations & stock trigger** (Dashboard) — on-hand, safety stock, ROP, sellable, days of cover, degradation, utilisation, balance. Push a product to its reorder point with *Update stock* (or press *Ask Ariadne to restock this*) and Ariadne opens an incident by itself and proposes deals for approval.
3. **Knowledge & Agentic RAG** (Knowledge tab) — ask "silkworms have milky fluid and climb the tray edge" (cited answer) vs "capital of France" (abstains). Weak queries are rewritten and retried.
4. **Farmer path** (Assistant, as `sf1`/`mf1`) — upload `data/images/grasserie_sample.jpg`: diagnosis, severity × urgency → priority, advisory, escalate-to-reeler flag, supply impact on reelers, agent trace. Repeat the same report: *recurring issue* banner (incident memory). `blurry_photo.jpg` → "diagnosis uncertain, ask an expert".
5. **Reeler & spinner paths** — `reeler1`: report low yarn output (e.g. 90 % for 14 days): affected spinners, urgency-ordered re-allocation, shortfall. `spinner1`: set a large target: demand gap vs own stock + linked reelers.
6. **Recovery pipeline + HITL (per buyer)** — after step 5 the incident pauses ("awaiting approval"). Log in as the approving buyer (spinner for reeler incidents; reeler for farmer incidents) → *Approvals*: see qty, price, OR-Tools route, transport cost → Approve (stock, balances, ledger, audit, notifications update) or Reject (nothing changes, reserved stock is released). Searches are capped at 5.
7. **Automatic propagation & observability** — any supplier event (disease, stock drop, low stock) opens an incident for every buyer pushed below its reorder point: alert, alternatives + routing, proposed deals, buyer approval. Buyers' dashboards show a live *Supply outlook*. Linked incidents are shown visibility-filtered; the *System* tab shows what is live vs stub.
8. **Evaluation** — `cd backend && python -m app.eval.run --reset` (**wipes demo data**) → Table 5 metrics; view under *Evaluation*.

## Architecture map (design doc → code)
Triage Supervisor + 4 specialists + shared recovery: `backend/app/graph/` (`nodes.py`, `ops_agents.py`, `stock_agent.py`, `propagate.py`, `recovery.py`, `build.py`).
Agentic RAG `app/rag/` · Risk matrix `graph/profiles.py` · Calculations `app/calc/` · OR-Tools `app/routing/` ·
Visibility `app/visibility/scope.py` · Structured outputs `app/llm/` · Incident memory `app/memory/` · Eval `app/eval/`.

## Design decisions & assumptions to review
* **Approver = the paying buyer** (spinner for reeler incidents, reeler for farmer incidents); for "sell stranded cocoons downstream" it is the seller. The doc does not say who approves.
* **Severity/urgency inputs** (`DISEASE_PROFILES`, loss fractions, `ESCALATE_LOSS`, leaf-per-cocoon and cocoon-per-yarn ratios) are my working assumptions — please have domain experts tune them. The severity × urgency → priority matrix is in `profiles.py`.
* **Alternative-source search**: ring radius expands 15→150 km, skipping rings that add no new candidate; max 5 searches. Stock is reserved while a proposal awaits approval.
* **Distances** are haversine × 1.35 (no external routing key); `routing/provider.py` is the swap point for OSRM / Google Routes.
* Schema is created with `create_all` (no migrations yet): schema changes need `python -m app.db.seed --reset`.

## Reading the eval numbers honestly
The baseline in `data/eval/results/` is high because the test set is small (18 scenarios, 14 + 6 questions), the knowledge base is a short placeholder corpus I wrote, answers are extractive (grounded by construction) and the judge is heuristic without a Groq key. Retrieval thresholds were tuned on this same question set. Treat it as a regression harness; re-baseline once your real corpus, models and a Groq key are in.
