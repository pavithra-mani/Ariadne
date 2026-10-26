# Is Ariadne agentic? A strict, external-style assessment

Written to be checked, not to flatter. Test used throughout: **who chooses the next action: the code or the model?** A fixed program
with LLM-filled steps is a *workflow*; a system where the model selects actions and tools from observations, against a stated
objective, is an *agent* (Anthropic, "Building effective agents"; Yao et al., ReAct; Wooldridge & Jennings 1995). Source IDs R1-R5 are in
`sources/SOURCES.md` (cited from memory: verify before publication).

## Verdict
| Part of Ariadne | Verdict | Why |
|---|---|---|
| **Guardian agent** (`agents/guardian_agent.py`, LLM available) | **Agentic** (one LLM agent, bounded autonomy) | Event-woken; the model chooses tools, order and arguments from observations, against an explicit cost objective it can measure (`score_plan`) and optimise against (`optimize_sourcing`); verifies results; reads learned memory; replans after declines. |
| **Optimiser baseline** (`guardian_mode=optimizer`) | Not agentic (exact optimisation) | Same tools and guardrails, no model deciding. It is the benchmark AND a tool the agent may call. |
| **Rules path** (`guardian_mode=rules`, also the labelled fallback) | Not agentic (event-driven automation) | `if gap then open pipeline incident`. |
| **User-reported incident graph** (`graph/`) | Not agentic (LLM-assisted workflow) | Fixed node order; the LLM fills triage, RAG grading, advice. Do not call it multi-agent. |
| Flow solver, router, CP-SAT, stock maths, ledger | Tools (deterministic) | The model never invents quantities. |

## The objective (`calc/objective.py`)
cost(plan) = E[purchase] + E[transport] + penalty x E[unmet kg]; utility = -cost. Every offer is weighted by the seller's **learned acceptance probability**
(a human must approve). E[transport] is the REAL consolidated vehicle-routing cost (OR-Tools); stops the router cannot serve count as undelivered.
Penalty = unit price x 3 (assumption: an unmet kg of input halts production). Hedging up to 1.25x need is allowed. The same function scores the agent's tool,
the optimiser, the simulator and the paper tables. **Constants that are assumptions** (truck cost INR 18/km, penalty multiplier 3, acceptance prior Beta(2,1))
are labelled as such in `app/constants.py` and the System page: results are conditional on them.

## Criteria checklist (guardian agent)
| # | Property | Evidence | Status |
|---|---|---|---|
| 1 | Autonomy / pro-activeness (R1) | events wake it; no sweep, no button (`test_guardian.py`, `test_agent.py`) | met |
| 2 | LLM is the controller (R3) | 11 tools; trace of every step in `agent_events.result.steps`, visible in the Chain page; live episode below | met when an LLM is reachable |
| 3 | Explicit objective | `evaluate_plan`; tools `score_plan`, `optimize_sourcing`; **ablation** `agent_tools=no_optimizer` withholds them | met (measurement pending LLM quota) |
| 4 | Planning / look-ahead | the agent can score alternative plans before committing; parallel tool calls | met |
| 5 | Reflection / verification | `verify_coverage` tool; deterministic `_observe` pass after every episode; optional regret log vs CP-SAT (`agent_log_regret`) | met (verification), partial (no learning from reflections beyond memory) |
| 6 | Learning memory | **Beta posterior over each vendor's acceptance**, from the deal history (`agents/memory.acceptance`); used by optimiser, scoring tool, agent; agent-written notes; ablation `memory_enabled=false` | met; effect measured below |
| 7 | Replanning | decline event with reason wakes the agent; decliner excluded; the *rules* path also replans (so replanning alone does not separate agent from automation) | met |
| 8 | Bounded autonomy / HITL | only `propose_offer` acts, creating a PENDING deal; quantities clamped to DB truth; **both seller and buyer must approve**; step/offer caps; adversarial test (poisoned decline reason) | met |
| 9 | Honest degradation | no LLM / mid-episode failure -> `mode = rules` / `agent+rules` + reason, shown in UI | met |
| 10 | Social ability | offers and notices to humans; no agent-to-agent protocol | partial |

## Evaluation (all reproducible; raw JSON in `data/eval/results/`)
### A. Optimiser vs rules-style greedy, single demand surge (`calc/objective` evaluator, same acceptance probabilities)
17 open needs, 20,771 kg: greedy cost INR 7.95 M vs CP-SAT INR 7.75 M (**-2.5%**); CP-SAT proved a bound within 0.4% of its solution. Most of the cost is
shortfall nobody can fill (the network is supply-constrained in this scenario), so the optimiser's headroom is small here. This is a *model-internal* comparison: section D shows it did not translate into lower realised cost against simulated humans.

### B. Routing checks (`tests/test_objective.py`)
OR-Tools vs brute-force optimum on 12 random instances of 4-7 stops: mean gap 0.00%, max 0.03% (small, single-truck cases only). Fixed: per-offer trips overpaid
37% vs a consolidated route (now consolidated); ranking over-weighted distance 7-22x (now uses the router's own cost per kg-km). Not verified: road distances
(haversine x 1.35 unless OSRM is enabled), the INR 18/km truck cost, transit-time limits (assumptions).

### C. Behavioural scenarios S1-S6 (`python -m app.eval.agentic_eval`)
The rules path passes all six, so these criteria test safety/behaviour, not intelligence, and cannot by themselves prove agentic-ness. See the earlier table in
`data/eval/results/agentic_*.json`.

### D. Simulator: rules vs optimiser, memory on/off (`python -m app.eval.simulator`)
Setup: the seeded network; 3 seeds x 6 episodes; each episode = one random disturbance (spinner/reeler demand surge, reeler/farm stock crash), the guardian acts,
**simulated humans** (hidden acceptance probabilities: 60% reliable ~0.95, 25% moderate ~0.6, 15% flaky ~0.2) approve or decline through the real approval API,
up to 3 rounds. Every episode restarts from the same stock; only the deal history (memory) carries over. Cost = executed purchases + transport + penalty x uncovered kg.
Files: `data/eval/results/simulator_20261026_225816.json` (rules), `..._225928.json` (optimiser, memory on and off).
**Pairing caveat:** because of an unordered database query, only 11-13 of 18 episodes per comparison had an identical disturbance (fixed afterwards: lists are
now sorted); numbers below use only those matched episodes. n is small, variance is large, no significance test was run.

| Matched episodes | Rules | CP-SAT optimiser (memory on) | CP-SAT optimiser (memory off) |
|---|---|---|---|
| n | 11 / 13 | 11 | 13 |
| mean realised cost (INR) | 1.10 M / 1.28 M | **1.54 M** | **1.83 M** |
| optimiser cheaper than rules in | - | 3 of 11 | 3 of 13 |
| uncovered kg after 3 rounds | 85 / 168 | 103 | 180 |
| offers sent | 7.9 / 10.8 | 12.1 | 12.7 |
| purchase spend (INR) | 0.81 M | 1.25 M | 1.40 M |

**Findings, stated plainly**
1. **The exact optimiser did NOT beat the rules path in realised cost** here (it was cheaper in 3 of 11 matched episodes, and 40% more expensive on average). It sends more offers and buys more. The most likely cause is **model misspecification, not a solver fault**: the optimiser hedges (up to 1.25x need) because its prior says a seller declines 1 time in 3 (Beta(2,1)); the simulated sellers are more reliable (mean ~0.78); and buyer-side declines are not in the objective at all. So it over-orders relative to what the humans actually do. Section A's -2.5% is a *model-internal* comparison (same expected-cost evaluator); it did not carry over to realised cost.
2. **Memory helped on cost, weakly, and not through fewer declines**: memory-on vs memory-off (13 matched pairs) mean cost 1.55 M vs 1.67 M (-7%), but declines per episode were identical (3.8 vs 3.8) and the decline rate did not fall from early to late episodes (0.347 -> 0.337 with memory; 0.378 -> 0.377 without). Consistent with the mechanism (a better-calibrated acceptance estimate means less hedging) but **not demonstrated**: n is small and the effect is inside the noise.
3. An earlier, unpaired run and a first version of the simulator that did not reset stock between episodes gave misleading numbers (cumulative shortfalls); both were discarded.
4. Regret vs the time-limited CP-SAT benchmark came out slightly *negative* in optimiser mode (-0.5% to -6%): two solves of the same problem differ because CP-SAT stops at 4 s. Treat the benchmark as a strong reference, not a proof of optimality.

**What this does and does not show.** It shows the machinery (events -> decide -> offers -> simulated approvals -> outcome events -> replan, with memory) runs end to end for hundreds of decisions and is measurable. It does **not** show that the optimiser or the agent is better than the rules path. To make the optimiser competitive the objective should model the buyer's acceptance too and be calibrated to observed behaviour; that is the next experiment, and it is exactly the kind of mis-specification the LLM agent might compensate for (arm E).

### E. LLM agent arms (agent, agent without optimiser tools): NOT YET MEASURED
Blocked by free-tier Gemini quota (2.5 models exhausted for the day; preview model returns intermittent 504s). One partial live episode exists
(gemini-3-flash-preview, scenario S1): `get_network_status` -> picked the top-of-chain yarn shortfall -> `find_vendors` -> five parallel `propose_offer`
calls totalling 444 kg -> the model call timed out and the guardian completed the rest with rules (`agent+rules`). **No claim about LLM-agent decision quality
should be made until arms E are run** (`python -m app.eval.simulator --modes agent,agent_noopt --episodes 8 --seeds 3` with an adequate key).

## What would not survive a hostile reviewer
* "Multi-agent": one guardian agent; the supervisor graph is a router over fixed nodes.
* "The agent learns": the *acceptance model* learns (Bayesian update); the LLM itself is not trained and "lessons" are free-text notes.
* "Goal-driven": the objective is explicit and measurable, but its weights are assumptions; the LLM is told the objective in a prompt and is not guaranteed to optimise it. Whether it does is exactly arm E.
* Hidden-behaviour simulation: vendor acceptance probabilities are synthetic; real farmers' behaviour is unknown. The simulator tests the machinery, not real-world benefit.
* The CP-SAT "benchmark" is time-limited (4 s) and linearises transport: it is a strong reference, not a proven global optimum (negative regret values appear when it stops short of optimal).

## Live-model caveats
Disease models: see `docs/MODELS.md` (in-source accuracy is high but out-of-source failures are severe; do not present field accuracy from it).

## References (see `sources/SOURCES.md`, "Conceptual references")
Wooldridge & Jennings (1995); Russell & Norvig, AIMA; Yao et al. (2022) ReAct; Shinn et al. (2023) Reflexion; Anthropic (2024) "Building effective agents".
