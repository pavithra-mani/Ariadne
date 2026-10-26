# How Ariadne acts on its own

## Perceive → reason → act → observe
| Step | What happens | Code |
|---|---|---|
| **Perceive** | Every change records an `agent_events` row and wakes the agent: a stock edit, a new demand target (spinner or reeler), a deal that executed or was declined. No polling sweep; after a restart it handles changes that arrived while it was down. | `agents/guardian.py` `submit`, `resume_pending` |
| **Reason** | The flow solver carries the change **up the chain** (a tier's requested output becomes input demand on its suppliers) and **back down** (what suppliers can really deliver limits what buyers get), re-asking other suppliers for any shortfall, until the numbers stop changing. Stock policy flags reorder points and surplus that will spoil. | `calc/flow.py`, `calc/supply.py` |
| **Act** | For every entity that can no longer be served, an incident runs the sourcing graph: look for alternative vendors **in both directions** (buyers short of input → sellers; sellers with surplus → buyers who need it), route with OR-Tools, and **send offers automatically** to the counterparties. | `graph/recovery.py`, `graph/stock_agent.py` |
| **Observe** | A decline is remembered (24 h) and the agent re-plans with another source. | `api/deals.py`, `recovery.find_candidates` |

**Human in the loop:** nothing moves until the **seller and the buyer both approve**. Either can decline.

## Flow solver
`POST /api/flow/what-if {entity_id, qty}` simulates extra demand at any entity (saves nothing). `GET /api/flow` shows the chain as it stands. Ratios: `leaf_per_kg_cocoon`, `cocoon_per_yarn`, `yarn_per_thread` (see below).

## Constants and live prices (`app/constants.py`, `app/refresh/live_data.py`)
At start-up (and daily while running) Ariadne reads the **Central Silk Board silk-price bulletin**: reeling cocoon prices by Karnataka market → cocoon price; raw-silk prices (filature 20/22, multi-end) → yarn and thread prices. Each value is sanity-checked; on any failure the **last good value** stays, and with none the **built-in default**. The System page shows each value's source and whether it is live. Conversion ratios and the leaf price have no public feed: they are labelled defaults (assumptions to be reviewed by a sericulture expert). Note: csb.gov.in's robots.txt returns 403; the refresh makes one identified GET per page at most every 6 hours.

## Speed of issue handling (measured 2026-10-26, free-tier Gemini key)
* The old default `gemini-3.5-flash-lite` took **18–24 s per call and then 504'd**; with no client timeout one stalled call froze an incident for minutes.
* Benchmark of one structured triage call: `gemini-2.5-flash-lite` **1.0 s**, `gemini-2.5-flash` 1.5 s, `gemini-3-flash-preview` 3.5 s, `gemini-3.1-flash-lite-preview` 3.2 s, `gemini-3.5-flash(-lite)` timeouts.
* Now: default `gemini-2.5-flash-lite`, fallback `gemini-2.5-flash` (separate quota), 15 s hard timeout, circuit breaker (after both fail, calls skip straight to the rule-based path for a while), chat runs in the background and the UI polls, buyer incidents run in parallel.
* End-to-end with live Gemini: free-text silkworm report ≈ 7 s (4 LLM calls), reeler shortage → proposed deals ≈ 3 s, knowledge question ≈ 0.5 s.

## Disease models (see `data/models/README.md`, `data/eval/results/vision_*.json`)
Both Keras models are converted to ONNX and load. On the supplied silkworm images the model is close to chance (healthy-vs-sick accuracy 0.57); mulberry accuracy cannot be measured (no disease labels). Low-margin predictions are routed to "uncertain, ask an expert".
