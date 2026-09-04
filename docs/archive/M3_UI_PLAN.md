# M3 dashboard panel — what to build (archived)

> **ARCHIVED 2026-09-04 — the dashboard panel it specifies was built 2026-08-29 and deployed 2026-08-31**, and its warmup requirements describe a mechanism that no longer exists (the coverage-cut freeze removed the rank window).
> Its one durable idea, the empty-state doctrine, moved into [M3_5_INTEGRATION.md](../M3_5_INTEGRATION.md) §2 before archiving. Kept as the build record.


**Status:** ✅ **BUILT 2026-08-29, deployed 2026-08-31, and REVISED the same day by the
coverage-cut freeze** ([M3_FIDELITY_RESULTS.md](../M3_FIDELITY_RESULTS.md) §6).

🔴 **Read §0.1 before using this document as a spec.** Its warmup requirements described a
mechanism that no longer exists. Everything else in it — the empty-state doctrine, the `nil`
vs `0.00` rule, the degraded-Postgres requirement — stands unchanged and is the reason the
panel earned its keep.
**GPU required:** No. **Keys required:** No. **Touches trading logic:** **No — read-only.**

**Owner files:** `apps/fluxtrader_web/lib/fluxtrader_web/live/dashboard_live.ex` (the only
file that changed in `lib/`), plus the web app's first tests. Nothing in `apps/fluxtrader/`
changed, as §5 required: every number the panel shows already existed.

**Related:** [M3_5_INTEGRATION.md](../M3_5_INTEGRATION.md) (what runs live, and how to read
`/api/health`) · [BACKLOG.md](../BACKLOG.md) (the index) · [M3_PLAN.md](../M3_PLAN.md) §0.0
(current status) · [M3_0B_RESULTS.md](../M3_0B_RESULTS.md) (the most recent results)

---

## §0.1 — 🔴 What the freeze changed in this spec, 2026-08-31

The panel was specified around a **warmup**: the served cut was re-ranked over a trailing 14
days of `policy_bars`, so the policy could not trade until 2,016 bars had accumulated, and the
single most useful thing the panel could say was how far along that was.

That rule was measured and retired the day after this panel was deployed. The cut is now the
constant `backtest.py` derives over the whole evaluation split, so **there is no warmup and
never will be** — `warm` is true from the first bar. Every warmup requirement below is
therefore superseded:

| specified below | what was built instead |
|---|---|
| "Rank window" badge, `n / 2,016 bars` | **Cut (frozen)** — the cut the running engine is deciding with (0.632), red if it differs from this build's constant — and **Confidence vs cut**, the drift diagnostic |
| the warmup explainer and its ETA sentence | a plain-language drift sentence: whether the top 2% of recent bars clears the cut, and by how much it falls short if not |
| `warm: false` as the panel's headline fact | `confidence_threshold == frozen_threshold` as the headline fact. `warm` is still rendered, but it no longer distinguishes anything |
| the LiveView assertion on `n / 2016` | an assertion that the retired warmup vocabulary **cannot come back**, plus one that a mismatched running cut renders as a fault |

🟢 **The doctrine survives intact, and it is what made this panel worth building.** §0's rule —
*every empty state must say why it is empty and what would change it* — is exactly why the
drift diagnostic was kept rather than deleted with the trailing cut. A policy silent because
the market is calm and a policy silent because it is broken still look identical, and the panel
still has to tell them apart. Only the specific emptiness changed.

⚠️ This panel is also what surfaced the defect it is now revised for: it made the served-vs-
scored threshold gap visible, which is [M3_FIDELITY_RESULTS.md](../M3_FIDELITY_RESULTS.md).

---

## §0 — Why this exists, in plain language

The project's current phase has exactly one deliverable: **a forward paper test that
accumulates independent trading days.** It is the only mechanism that can ever make the edge
certifiable, because no rearrangement of the existing 253 days can. Everything else in M3 is
now built.

**That test is currently invisible in the UI.** The dashboard at `/` was built for the M2 era
and shows candles, M2 signals, and simulated positions. It shows **nothing** about the M3
policy, the rank-window warmup, or the A/B arms. The only way to see the thing that matters is
to SSH to the VM and read raw JSON:

```sh
gcloud compute ssh --zone me-central1-b --project fluxtrader fluxtrader-1 \
  -- "curl -s localhost:4000/api/health"
```

**The job is to put that on the dashboard.** No new measurement, no new endpoint, no change to
any trading decision — the data already exists and is already computed.

### The one design principle that matters

🔴 **The panel's job is to make CORRECT SILENCE legible.** This is the same reason
`/api/health` was built, and `HealthController`'s moduledoc states it: the served checkpoint
produced **no gated signal between 2026-06-29 and the forward test's restart**, because the
edge lives in volatile bars and the market has been the calmest of the whole period since July.
That is the strategy working. But *a system that has been silent for two months is
indistinguishable from a broken one*, and a panel that renders that state as an empty grey box
with "0 trades" is **worse than no panel** — it will be read as a fault, and someone will
"fix" a working system.

So every empty state must say **why** it is empty and **what would change it**. Concretely:

* ⚫ *superseded by §0.1:* warming up → *"Warming up: 1,044 / 2,016 bars…"* — there is no
  warmup any more; the equivalent state is a thin bar log, which delays only the diagnostic.
* no signal → *"The policy trades any bar at or above a FIXED confidence of 0.632… Right now
  even the top 2% of recent bars only reaches 0.548 — 0.084 below the cut — so the policy is
  correctly taking nothing."*
* never *"No data"* on its own.

---

## §1 — What the dashboard shows today, and what is missing

`dashboard_live.ex` currently renders four panels: **System Status**, **Open Positions (sim)**,
**M2 Signals (gated simulation)**, **Live Candles (1m)**. Everything below is absent:

| what is missing | why it matters now |
|---|---|
| ⚫ *superseded by §0.1:* **warm / not warm, and progress** | Was "the single fact that says whether the policy is allowed to trade yet". Replaced by **the cut in force vs this build's constant**, which is the fact that now decides whether the panel is describing the rule the engine is running |
| **the A/B arms side by side** | `policy` vs the control is PLAN.md's M3 A/B and the whole point of the forward test. ⚠️ The control was `signal_only` when this was written and is `flat_size` since 2026-08-31 — the panel reads whatever `Ledger.ab_summary/0` returns, so no UI change was needed |
| **named skip reasons** | The difference between "correctly quiet" and "broken" |
| **time since last bar / last gated signal** | Liveness. A stalled `PolicyEngine` and a calm market look identical without this |
| **the live coverage cut and served universe** | A non-empty `not_served` skip means the served and collector lists have drifted apart — the exact production defect of 2026-08-28 |
| **exec cost + `fee_tier_verified: false`** | Every paper P&L is charged these; the tier is still unverified and the UI should not hide that |

---

## §2 — What to build

**One new panel, full width, placed FIRST** — above System Status, because it is now the most
important thing on the page. Title: **M3 Policy — forward paper test**.

### 2.1 Row one: state badges

Reuse the existing `.status_badge` component and the existing colour vocabulary
(`#2ecc71` green, `#f39c12` amber, `#e74c3c` red, `#533483` / `#0f3460` neutral).

| badge | value | colour |
|---|---|---|
| `Policy` | `warm` / `warming` / `down` | green / amber / red |
| `Rank window` | `1044 / 2016 bars` | amber while short, green when full |
| `Rule` | `cov0.02_hold240_SIZED` | neutral |
| `Universe` | `12 served` | neutral; **red if `served_pairs` ≠ `collector_pairs`** |
| `Last bar` | `3m ago` | green < 15m, amber < 60m, red beyond |
| `Last gated` | `14d ago` or `never` | neutral — **never red**, see §0 |

### 2.2 Row two: the warmup / silence explainer

One sentence of prose, computed from the same data, following §0's rules. This is the most
valuable element on the panel and the easiest to skip — **do not skip it.**

When `warm: false`, include the estimated time to warm:
`(min_rank_bars - bars_in_rank_window) / (288 * length(served_pairs))` days.
At 12 pairs that is 3,456 bars/day. ⚠️ **Do not describe the warmup as "seven days"** — that
error was in every document until 2026-08-29. `@min_rank_bars` is `7 * 288` **bars**, pooled
across served pairs, so it clears in ~14 hours at twelve pairs.

### 2.3 Row three: the A/B table

Two rows, `policy` and `flat_size` (`signal_only` before 2026-08-31), from `Ledger.ab_summary/0`. Columns:

`arm · trades · trades/day · net bps · gross bps · win rate · cum net bps · max drawdown · open`

* Colour `net_bps` and `cum_net_bps` with the existing `pnl_color/1`.
* 🔴 **`nil` is not `0.0`.** With no trades yet, `gross_bps` / `net_bps` / `win_rate` come back
  `nil`. Render those as `—`, never as `0.00`, which would read as "measured, and it is zero".
* Under the table, one line of provenance:
  `charged M3-4 measured per-pair crossing cost (pooled 9.842 bps) · fee tier UNVERIFIED`.
  Show `fee_tier_verified: false` in amber — it is a real open item
  ([BACKLOG.md](../BACKLOG.md)), and hiding it in JSON is how it stays open.

### 2.4 Row four: skips and rejections

`skips` and `risk_rejections` are maps of `reason => count`. Render as small chips, sorted by
count descending, empty state *"no skips recorded"*.

🔴 **`not_served` must render red with an explanation.** Its presence means the policy is
seeing bars for pairs it does not serve, i.e. `served_pairs` and the collector whitelist have
drifted apart. That is the 2026-08-28 production defect, and BACKLOG names a non-zero
`not_served` as the signal to watch for its recurrence.

---

## §3 — Where the data comes from

🔴 **Call the modules directly. Do NOT have the LiveView fetch its own `/api/health` over
HTTP.** That would add a network hop, a JSON round-trip and a second failure mode to a process
that already runs inside the same VM. `HealthController` is a thin wrapper over these calls and
is the reference for what to call and how to guard it:

| data | call | notes |
|---|---|---|
| policy state, skips, rejections, coverage, served pairs | `FluxTrader.Trading.PolicyEngine.status/0` | `GenServer.call`, 10s timeout, already catches `:exit` |
| warm progress, last bar, last gated | `FluxTrader.Trading.Ledger.liveness/0` | hits Postgres |
| the A/B arms | `FluxTrader.Trading.Ledger.ab_summary/0` | hits Postgres, aggregates `PaperTrade` |
| collector whitelist | `FluxTrader.Settings.get_whitelist/0` | for the drift check in §2.1 |
| cost provenance | `FluxTrader.Trading.ExecCost.pooled_bps/0` etc. | constants |
| rule labels | `FluxTrader.Trading.Policy.coverage/0`, `.hold_minutes/0` | constants |

**Guard every one of them.** `dashboard_live.ex` already has the pattern —
`safe_candles/0`, `safe_engine/0`, `safe_positions/0` each `rescue` and `catch :exit` and
return a usable fallback. Add `safe_policy/0`, `safe_liveness/0`, `safe_ab/0` in the same
shape. 🔴 **A dashboard that crashes when Postgres blips is a worse regression than the missing
panel** — this page is what someone opens *because* they think something is wrong.

---

## §4 — Refresh cadence

The existing loop is `@refresh_ms 15_000`, driven by `Process.send_after(self(), :refresh_candles, ...)`.

🔴 **Do not put the M3 block on the 15-second timer.** `ab_summary/0` and `liveness/0` are
Postgres aggregations over the whole `policy_bars` / `paper_trades` history, and they would run
every 15 seconds **per connected browser**, against the same small VM that runs the collector
and the policy. The underlying data moves on a **five-minute** bar.

Add a **separate 60-second timer** (`@m3_refresh_ms 60_000`) with its own
`handle_info(:refresh_m3, socket)`. Follow the existing loop's two conventions:

1. **reschedule first**, before doing any work, so a timeout cannot kill the loop forever;
2. **never wipe good data on a transient failure** — on error keep the previous assigns, as
   the `:refresh_candles` clause does for signals.

---

## §5 — Files to touch

| file | change |
|---|---|
| `apps/fluxtrader_web/lib/fluxtrader_web/live/dashboard_live.ex` | the whole feature: assigns in `mount/3`, the `:refresh_m3` loop, the three `safe_*` helpers, the panel markup, formatting helpers |
| `apps/fluxtrader_web/test/fluxtrader_web/live/dashboard_live_test.exs` | new — see §6 |

**Nothing in `apps/fluxtrader/` should change.** If the panel seems to need a new function in
`Ledger` or `PolicyEngine`, that is a signal to re-read this spec: every number listed in §2 is
already returned by an existing call. Adding to the trading modules to serve a dashboard is out
of scope and would put UI pressure on the code that trades.

---

## §6 — How to verify

**Everything runs in Docker** (`AGENTS.md`) — no host Elixir, no `mix` outside a container.

```sh
docker compose up -d
docker compose exec app mix test                 # whole suite must stay green (74 tests as of 2026-08-29)
open http://localhost:4001                       # local compose maps 4001; the VM uses 4000
```

**Acceptance, in order:**

1. **The suite is green**, including the new LiveView test.
2. **The panel renders with an empty ledger.** This is the state that actually matters and the
   one a fresh dev environment is in: no trades, `warm: false`, `nil` metrics. It must show the
   warmup explainer and `—` for every unmeasured number, and it must not crash.
3. **It renders with Postgres down.** `docker compose stop postgres`, reload. The page must
   still render, with the M3 panel degraded rather than the whole dashboard 500ing.
4. **It renders against the real VM state.** The VM is the only place with a real rank window
   and a real A/B. Either read `/api/health` from the VM and check the panel would render that
   payload correctly, or deploy and look.

**A LiveView test is required, not optional** — the empty and `nil` states are the whole point
and they are exactly what a manual click-through on a populated dev box would miss. Use
`Phoenix.LiveViewTest.live/2` and assert on rendered text for at least:

* `warm: false` with partial bars → the warmup sentence and the `n / 2016` badge appear;
* `ab_summary` with `nil` metrics → `—` appears and the string `0.00` does **not**;
* a `%{"not_served" => 3}` skip map → the drift warning appears.

---

## §7 — Explicitly out of scope

Named so the next session does not quietly widen the job:

* ❌ **Any change to trading behaviour, the policy, the rule, or `RiskManager`.** Read-only.
* ❌ **The `auto` path's stop/target decision.** Measured in [M3_0B_RESULTS.md](../M3_0B_RESULTS.md)
  §4 and filed with the real-money blockers in BACKLOG. Unrelated to this panel.
* ❌ **Charts or equity curves.** The A/B has zero trades and may have very few for weeks; a
  time-series chart of nothing is worse than a table. Revisit once an arm has ~50 trades.
* ❌ **Auth, a redesign, or a CSS framework.** The page uses inline styles on a dark palette;
  match it. A redesign is a separate decision and not one this spec makes.
* ❌ **A new API endpoint.** `/api/health` already exists and stays the machine-readable source.

---

## §8 — The exact next action

```sh
cd /Users/vadim/Documents/src/open/trading_agent
git pull
docker compose up -d
docker compose exec app mix test          # confirm green BEFORE changing anything
```

Then read, in this order: this document, `HealthController` (the reference for every call and
its guard), and `dashboard_live.ex` (the conventions to match). Then build §2.

**What to bring back:** the suite result, a screenshot or rendered-text sample of the panel in
the **empty/warming** state (the state that matters most), and confirmation of acceptance
items 2 and 3 in §6.

---

## §9 — What was built, and what it was verified against

**Built 2026-08-29, entirely as specified.** No item in §7 was widened into, and no function
was added to `Ledger`, `PolicyEngine` or any other trading module.

| file | change |
|---|---|
| `apps/fluxtrader_web/lib/fluxtrader_web/live/dashboard_live.ex` | the panel: the `m3` assign, the separate `@m3_refresh_ms 60_000` loop, four guards (`safe_policy/0`, `safe_liveness/0`, `safe_ab/0`, `safe_collector_pairs/0`), the markup, and the formatting helpers |
| `apps/fluxtrader_web/test/fluxtrader_web/live/dashboard_live_test.exs` | **new** — five LiveView tests, all of them empty states |
| `apps/fluxtrader_web/test/test_helper.exs`, `test/support/conn_case.ex` | **new** — `fluxtrader_web` had no test tree at all. `ConnCase` takes the sandbox in **shared** mode, because a connected LiveView runs in its own process and would otherwise be unable to read the bar log |
| `apps/fluxtrader_web/mix.exs`, `mix.lock` | `{:floki, ">= 0.36.0", only: :test}` — `Phoenix.LiveViewTest` parses rendered HTML with it. ⚠️ A deps change means the `app_deps` / `app_build` volumes must be recreated on deploy, or the dev server 500s until restarted (it did, once, during this build) |

### Acceptance, §6

1. ✅ **Suite green: 79 tests, 0 failures** (74 existing + 5 new). No existing test changed.
2. ✅ **Renders with an empty ledger**, showing the warmup explainer and `—` for every
   unmeasured number. The test asserts the string `0.00` does **not** appear.
3. ✅ **Renders with Postgres down.** `docker compose stop postgres`, reload: HTTP 200, the
   M3 panel degraded to "the bar log cannot be read", the rest of the dashboard intact.
4. ✅ **Checked against the real VM state.** `fluxtrader-1`'s `/api/health` at build time was
   `warm: false`, 1,644 / 2,016 bars, 12 served / 12 collected, `skips: {warming_up: 16188}`,
   last bar 184s ago, no gated signal ever, both arms at zero trades. That state was
   reproduced in a throwaway test and the panel rendered it correctly, including the ETA
   ("about 3 more hours at 12 pairs").

### Three decisions taken while building, that the spec left open

1. 🔴 **`cum_net_bps` and `max_drawdown_bps` also render as `—` when an arm has no trades.**
   §2.3 names only `gross_bps` / `net_bps` / `win_rate` as `nil`, but `arm_summary/2` returns
   a *structural* `0.0` for the cumulative pair when `n == 0`. That zero means "no trades",
   not "measured, and it is zero" — which is the exact confusion §2.3 exists to prevent, so
   it gets the same dash. `trades` and `open` stay as real integers.
2. **"unknown" is distinguished from "never".** When the ledger is unreadable the two `ago`
   badges say `unknown`, not `never`: "never" is a fact about the ledger, "unknown" is a fact
   about this page's ability to read it, and reporting the second as the first would claim a
   silence that was never observed.
3. **A ledger blip does not wipe the panel, but it does say so.** `liveness` and `ab` carry
   the previous good values forward per §4, and an amber line then states that they are the
   last good values rather than current ones. `policy` is *not* carried forward — a stale
   `warm` badge over a dead engine would be a lie, and engine liveness is itself the reading.

### Not done: the deploy

The panel is built and verified locally; `fluxtrader-1` still serves the M2-era dashboard.
Deploying is a separate, deliberate act because **this deploy changes dependencies**, so it
needs the volume recreation named in the table above:

```sh
gcloud compute ssh --zone me-central1-b --project fluxtrader fluxtrader-1 -- \
  "cd ~/trading_agent && git pull && docker compose down && \
   docker volume rm trading_agent_app_deps trading_agent_app_build && docker compose up -d"
```

🟢 **It cannot disturb the forward paper test's comparability** — the panel reads and changes
nothing the policy uses. But the restart itself pauses collection for as long as the app is
down, and collection gaps never backfill (deploy-day defect #2), so do it deliberately.
