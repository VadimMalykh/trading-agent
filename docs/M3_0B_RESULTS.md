# M3-0b — the price/funding side-table: results

**Status:** 🟢 **DONE 2026-08-29.** The acceptance test passes on all four eval dumps, and
with it **M3's last build item closes.** The table also carries
[BOOK_ERA_PLAN.md](./BOOK_ERA_PLAN.md) **B0**, built on the same alignment in the same pass,
as both plans required.

**Run it:** `./scripts/m3.sh -m m3 sidetable` (M3-0b) and `./scripts/m3.sh -m m3 bookera` (B0).
**Owner code:** `ml/train/m3/sidetable.py`. **Data:** `ml/train/output/m3_0b/side_5m.parquet`,
`ml/train/output/m3_4/book_era_{5m,1m}.parquet`.

**Related:** [M3_PLAN.md](./M3_PLAN.md) §2 M3-0b (the spec) ·
[BACKLOG.md](./BACKLOG.md) (the index) · [BOOK_ERA_PLAN.md](./BOOK_ERA_PLAN.md) §B0 ·
[M3_5_INTEGRATION.md](./M3_5_INTEGRATION.md) (the live executor this prices)

---

## §0 — In plain language

**What was missing.** Every M3 number so far was computed from a table that holds only the
*endpoints* of a trade: where price was when we entered, and where it was exactly four hours
later. It held nothing about the path in between, and nothing about funding. That made three
questions literally unanswerable rather than merely unanswered, and one live behaviour
unmeasurable. This step builds the missing table — a price path on a five-minute grid across
the whole evaluation period, plus the funding rate — and then uses it to answer them.

**Term definitions, once.** A *basis point* (bps) is 0.01%. *Gross* is before trading costs,
*net* after. *Funding* is the periodic payment perpetual-futures traders make to each other —
if you are long and the rate is positive, you pay; if you are short, you are paid. A *stop* is
an order that closes a losing position at a set loss; a *target* (take-profit) closes a winning
one at a set gain. A *fixed hold* means we simply exit after four hours regardless.

**The three answers, in order of how much they matter:**

1. 🔴 **The stop and target that would apply to real orders cost about a third of the edge.**
   The executor attaches a 2% stop and a 4% target to every `auto`-path order as a catastrophe
   brake. Nobody had ever measured what that does, because measuring it needs exactly the price
   path this step built. It turns **+33.8 gross bps per trade into +23.2** — a loss of **10.5
   bps per trade**, where the whole edge is about 20 bps net. The brake is not free insurance;
   it is roughly a third of the profit. ⚠️ **This does not affect the paper test now running**:
   the paper arms ignore both barriers and close on the four-hour timer. It is a prerequisite
   for real money, alongside the unverified fee tier and the unsigned order path.

2. 🟢 **Funding is a rounding error, and now we know instead of assuming.** Charged properly
   on the policy's own 1,773 trades it costs **0.14 bps per trade** — against a per-trade
   spread of roughly 250 bps. It changes the headline from +20.59 to +20.45 net bps. This is
   a *negative* result in the useful sense: an open term that could have mattered, closed.

3. 🟢 **Barrier exits do not beat the fixed four-hour hold — C4b is answered.** The long-open
   worry (filed as C4b) was that the model is trained on take-profit/stop-loss labels while
   the P&L is booked at a fixed four-hour exit, so the backtest might be measuring the wrong
   thing. It is not measuring the wrong thing in a way that favours us: **every** barrier
   setting tried lands below the fixed hold (best +9.2 against **+19.8** net bps). The
   mismatch is real but it points the other way — the fixed hold is the better policy, not a
   flattering artifact.

**Bottom line:** this changes nothing about whether the strategy works — it still cannot be
certified on 253 days, and only forward time fixes that. **Nothing here needs acting on today**
and the running paper test is unaffected. What it changes is that three questions which were
*unanswerable* are now answered, and one real-money prerequisite that the executor itself said
"must be priced before real money goes near this" has been priced.

---

## §1 — The acceptance test, which is the gate

BOOK_ERA_PLAN §B0 states it as "not optional": the rebuilt `fwd_ret_240` must match the eval
dumps' own `fwd_ret` on a `(pair, ts)` join, or **nothing downstream is evidence.**

The dumps store `fwd_ret` as **float32**, so the test was made sharper than a tolerance:
exact equality after a float32 round-trip. A rebuild that merely rounded close would pass a
`1e-6` check while quietly describing a different series.

| dump | bars | unmatched | exact | max abs diff |
|---|---:|---:|---:|---:|
| s1 `20260818T185438Z` | 579,157 | 0 | 579,157 / 579,157 | 1.465e-08 |
| s2 `20260819T142759Z` | 579,539 | 0 | 579,539 / 579,539 | 1.465e-08 |
| s3 `20260820T025723Z` | 579,778 | 0 | 579,778 / 579,778 | 1.465e-08 |
| o8 `20260822T012619Z` | 917,514 | 0 | 917,514 / 917,514 | 1.465e-08 |

✅ **2,655,988 bar-comparisons, every one exact, nothing unmatched.** The residual 1.5e-08 is
the float32 storage itself and vanishes on the round-trip. B0's table passes the same test
independently over the book-era overlap (29,440 / 31,352 / 32,544 / 55,524 rows, all exact) —
run separately because the two tables are built from **different exports** and a pass on one
is not a pass on the other.

**What made it pass** is that the forward return is rebuilt as a **positional shift**, not a
wall-clock offset. `data/features.forward_return` is `close.shift(-48) / close - 1` over the
candle rows *as loaded*, so where the series has a gap the training label reaches across it
rather than to a `+240m` that does not exist. A time-based `asof` join is defensible on its
own terms and would **not** have matched.

---

## §2 — Two defects found on the way

**1. The first export was the wrong window, and the acceptance test is what caught it.**
M3_PLAN §0.0 said M3-0b's data was "already on disk" from the M3-4 export. It was not: that
export covers **2026-08-05..28**, the book era, because the ladder does not exist before it.
M3-0b's price path has to span the eval validation window, and **96% of the policy's trades
fall outside the book era.** Re-exported over `2025-11-15 .. 2026-08-30`. The first run then
still failed on the o8 dump alone with 8,358 unmatched bars — the 12-pair dump's window opens
**2025-11-28**, three days before the `FROM=2025-12-01` first chosen. Both are recorded
because the second one is the acceptance test doing precisely the job it was written for:
every bar *inside* the window was already exact, and a laxer test would have shrugged at 0.9%
missing rows.

**2. `HYPEUSDT` settles funding every 4 hours, not every 8.** Eleven of the twelve pairs
settle at 00:00/08:00/16:00 UTC; HYPE settles six times a day. A side-table that generated
settlements from an assumed 8h calendar would understate HYPE's funding by half, on a pair the
policy trades. The settlement schedule is therefore **read out of the data per pair**, never
hardcoded — `sidetable.funding_settlements` derives each pair's settlement hours as those
carrying a boundary row on ~every day of the window.

That rule replaced a first version of my own that was wrong in a way worth recording: it
treated *any* row within a minute of the hour as a settlement. That is true in the sparse era,
where every row **is** a settlement, but from 2026-07 the collector polls the mark price
continuously and rows land in all 24 hours — which scored BTCUSDT at **5.28 settlements/day
against a true 3**. The pooled funding number did not move when it was fixed, and the reason
is worth stating rather than treating as luck: only **27 of 1,773 trades (1.5%)** fall after
2026-07-01, because the market has been calm since July and the policy has barely fired.

---

## §3 — The funding term

Charged on the M3-2 winner's own pooled trade ledger. **Positive is a cost.**

| quantity | value |
|---|---:|
| trades | 1,773 |
| crossing at least one settlement | 54.8% |
| mean | **+0.142 bps/trade** |
| median | +0.000 |
| p5 / p95 | −1.369 / +1.233 |
| worst single trade | +12.66 |
| earned (when it pays us) | 0.271 bps/trade |
| paid (when we pay) | 0.413 bps/trade |

**Net effect on the headline: +20.59 → +20.45 net bps/trade** at M3-4's measured 9.842 bps
pooled round trip.

🟢 **Verdict: a rounding error at a 4h hold, and now a measured one.** It is *lumpy* rather
than proportional to holding time — a 4h position pays only if a settlement instant happens to
fall inside it, which is why 45% of trades pay nothing at all. It does not change any M3
conclusion, and that is the finding: it was an unquantified open term, and the honest reason
to charge it was that nobody had shown it was small.

---

## §4 — 🔴 The live brake, priced for the first time

**This is the section with a consequence.** `RiskManager` attaches `stop_loss_pct: 0.02` and
`take_profit_ratio: 2.0` — a **2% stop and a 4% target** — to every `auto`-path entry
(`apps/fluxtrader/lib/fluxtrader/trading/risk_manager.ex:88`). The policy that was validated
exits at a **fixed four hours**. That brake is therefore a deviation from the rule M3-2
scored, and until this step it could not be measured at all.

Measured on the winner's own entries, walking the 5m path forward to the first touch:

| touch rule | tp hit | sl hit | timeout | mean hold | gross bps/trade |
|---|---:|---:|---:|---:|---:|
| *(fixed 4h hold — the validated rule)* | — | — | 100% | 240m | **+33.76** |
| `intrabar` (what a resting stop really experiences) | 11.2% | 34.1% | 54.7% | 176m | **+23.24** (−10.52) |
| `close` (what the training label was built on) | 9.5% | 28.9% | 61.5% | 189m | +32.01 (−1.75) |

🔴 **The brake costs 10.5 gross bps per trade — about a third of the edge**, on a policy whose
net figure is ~20 bps. The stop fires three times as often as the target (34.1% vs 11.2%),
which is what an asymmetric band does to a symmetric-ish return distribution: a 2% stop is
simply much closer than a 4% target.

⚠️ **The `intrabar`-vs-`close` gap is 8.8 bps and is itself a result.**
`data/features.triple_barrier_labels` tests **closes only** — a documented approximation. So a
barrier backtest run the way the *label* is built understates what a *real* resting stop does
by nearly nine basis points. Anyone who measures barrier exits on closes and concludes they
are nearly free has measured the label, not the market.

**Same-bar ambiguity is charged as the stop.** When one 5m bar's range spans both barriers,
OHLC cannot say which came first, and assuming the target is how a backtest manufactures free
money. The conservative reading is applied uniformly, so the bias is known and
one-directional — it makes the brake look *no better* than it is.

### What this does and does not license

🔴 **It does not license quietly turning the brake off.** It is a *catastrophe* brake: it
bounds the loss on a single position in a way a fixed-hold backtest, which has never seen a
60% overnight move, cannot price. What this section establishes is the **premium** — 10.5 bps
per trade — not that the insurance is unwanted. That trade-off is a decision, and it is filed
in [BACKLOG.md](./BACKLOG.md) rather than taken here.

🟢 **And it is NOT urgent — the forward paper test is unaffected.** `Executor`'s own
docstring says so and the code agrees: **the paper arms ignore the stop and the target and
close on the timer.** The brake is attached only on the `auto` path, which is the real-order
path, and that path is unsigned and cannot trade. So the running A/B is measuring the pure
fixed-hold rule, exactly as intended; there is no comparability risk and no window closing at
the first fill.

**This measurement therefore discharges a precondition rather than opening a decision.** The
executor's docstring stated the requirement — the brake "is an **unmeasured** deviation from
the backtest: it must be priced before real money goes near this." It is now priced. The
choice of what to do about it belongs with the other real-money prerequisites (the unverified
fee tier, the unsigned order path), not with anything running today.

---

## §5 — The barrier ladder, and what C4b turns out to be

🔴 **Descriptive only. This is not a policy search and nothing here is promoted.**
M3_PROTOCOL §0 forbids re-picking a searched dimension after seeing results; choosing a row of
this table *because it is the best row* is exactly what that prohibits. It is printed so that
a future pre-registration can be written knowing what it would be choosing between.

Net bps/trade at the 14 bps taker line, on the winner's entries, `intrabar` touches:

| stop | target | tp hit | sl hit | timeout | mean hold | net bps |
|---:|---:|---:|---:|---:|---:|---:|
| 0.5% | 0.5% | 52.6% | 47.1% | 0.3% | 18m | −9.88 |
| 0.5% | 1.0% | 35.7% | 61.3% | 3.0% | 37m | −5.08 |
| 1.0% | 1.0% | 47.9% | 44.6% | 7.4% | 60m | −7.30 |
| 1.0% | 2.0% | 27.1% | 54.9% | 17.9% | 96m | −1.49 |
| 2.0% | 2.0% | 35.1% | 31.3% | 33.6% | 140m | +6.64 |
| 2.0% | 4.0% | 11.2% | 34.1% | 54.7% | 176m | +9.24 |
| **fixed 4h hold** | — | — | — | 100% | 240m | **+19.76** |

**Every barrier setting loses to the fixed hold, and the ordering is monotone**: the wider the
band and the longer the effective hold, the better it does — the ladder is climbing back
*toward* the fixed hold, not away from it. That is a coherent story rather than noise: the
signal is a 240-minute-horizon signal, and cutting it short at any band throws away edge that
has not yet arrived.

🟢 **C4b is answered, in the direction that costs nothing to accept.** The mismatch it
identified is real — the model is trained on triple-barrier labels while the P&L books a
fixed-horizon return — but the fixed-hold booking is not flattering the result. Fixing the
mismatch by moving the *policy* to barriers would cost 10 to 30 bps per trade.

⚠️ **What this does NOT establish** is that no barrier policy could ever help. Six
(stop, target) pairs at one hold horizon on one entry rule is a slice, not a search, and it is
deliberately not one. A trailing stop, a volatility-scaled band, or a barrier applied only in
the high-volatility regime are all untested. They stay untested until someone writes a
pre-registration first.

---

## §6 — What B0 delivers

Built by the same module on the same alignment, `./scripts/m3.sh -m m3 bookera`:

* `book_era_5m.parquet` — 79,488 rows x 12 pairs, 2026-08-05..27
* `book_era_1m.parquet` — 423,130 rows x 12 pairs, 2026-08-05..29

Both carry the five book scalars (`spread_bps`, `imbalance`, `micro_mid`,
`bid_ask_vol_ratio`, `depth_near_imb`), the three tape scalars (`trade_count`,
`buy_sell_imb`, `trade_vol`), `funding`, the `fwd_ret_{5,15,60,240}` set, and the presence
masks — joined with **training's own asof and staleness caps** (`BOOK_MAX_AGE=5`,
`TRADES_MAX_AGE=5`, `FUNDING_OI_MAX_AGE=480`), because a side-table aligned differently from
training is not evidence about training.

Book freshness is **0.9994 on the eight main pairs and 0.6028 on ADA/AVAX/LINK/XRP** at 5m,
which is the expected reading and a useful sanity check: those four joined the collector on
2026-08-14, i.e. 14 of the window's 23 days — 14/23 = 0.609.

⚠️ **Nine of B0's eleven scalars are built. `oi` and `oi_chg` are absent** because
`open_interest` is not one of the tables `scripts/gcp_m3_export.sh` pulls. Adding it is a
one-line export change and **not** an alignment change — it is filed in BACKLOG rather than
left as a silent gap, and B1/B2 can proceed on nine.

**B0 is therefore closed and B1 is unblocked.**

---

## §7 — What is now possible that was not

The table exists, so these stop being impossible and become merely un-run:

* **Position-state observations** for a policy feature vector — unrealised P&L, time in trade,
  drawdown-since-entry. M3-3 had to omit these for want of a price path. ⚠️ M3-3's verdict
  (all 14 learned runs lost to the hand-written rule) was pre-registered as **not** evidence
  that a bigger model would win, and new features do not reopen it: that needs its own
  pre-registration.
* **Slippage realism beyond a per-trade constant**, now that the intra-hold path is available
  next to M3-4's measured ladder.
* **B1 and B2** (BOOK_ERA_PLAN), which were gated on B0 and are not any more.
