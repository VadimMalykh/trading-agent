# The candle integrity guard — what it is, and how to install it on an instance

*Installed on `fluxtrader-1` on 2026-09-03. This document is the runbook for putting it on
any other instance later.*

---

## §0 — What it is, in one paragraph

Once a day the guard asks Binance for yesterday's **closed** klines and compares them, bar for
bar, against what this instance actually stored. If they disagree it sends a Telegram message.
That is the whole idea, and the reason it exists is worth keeping in view: for six weeks the
collector stored every candle as a snapshot of the bar's first minute, and **nothing noticed**
([CANDLE_POLL_DEFECT.md](./CANDLE_POLL_DEFECT.md)). The checks that existed all compared one
derived number against another — most damningly, live confidence against the offline split's
confidence, which matched perfectly because both were computed from the same corrupt candles. A
bad *input* is invisible to any check whose two sides share that input. Only a comparison
against something outside the system can catch it. That is what this is, and it is the only
check in the project of that kind.

A useful consequence: the comparison is for **exact equality**, not closeness. A closed kline is
immutable, so a correctly stored bar reproduces the exchange's numbers bit for bit. "Nearly
right" volume is the signature of a partial bar — precisely the thing being watched for — so
tolerance would defeat the purpose.

---

## §1 — What gets installed

| Where | What | Notes |
|---|---|---|
| repo | `ml/train/verify_candles.py` | the actual comparison; also runnable by hand for any date |
| repo | `scripts/candle_guard.sh` | the daily wrapper: runs the check, writes status, alerts |
| repo | `scripts/install_candle_guard.sh` | installs/updates/removes the timer on a VM |
| VM | `/etc/systemd/system/candle-guard.service` | `Type=oneshot`, runs the wrapper as your user |
| VM | `/etc/systemd/system/candle-guard.timer` | `OnCalendar=*-*-* 01:40:00`, `Persistent=true` |
| VM | `~/candle_guard.log` | appended every run, self-trimmed at 20k lines |
| VM | `/var/tmp/candle_guard_status.json` | last run's verdict, written on success **and** failure |

Because the service runs the script **from the VM's git checkout**, updating the guard is a
`git pull` on the VM. Re-running the installer is only needed to change the schedule.

### Why systemd and not cron

There is no cron daemon on the VM — `crontab` is not even installed on Ubuntu 26.04 GCE images.
A timer is the better fit regardless: `Persistent=true` runs a job that was missed while the
instance was down, and downtime is exactly when data is most likely to have gone wrong.

---

## §2 — Prerequisites on the target instance

1. Docker and Docker Compose, with the login user in the `docker` group (the service runs as
   that user, not root).
2. This repo checked out at `~/trading_agent`, and the `ml_trainer` compose service usable:
   `docker compose --profile ml run --rm ml_trainer python -c "print(1)"`.
3. Postgres reachable from that container (the normal compose setup).
4. Outbound HTTPS to `fapi.binance.com`.
5. `systemd` and `sudo`.
6. **Optional but strongly recommended:** `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in
   `~/trading_agent/.env` — the same two variables the app already reads. Without them the guard
   still runs and still records failures, but nobody is told. It logs
   `TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID unset — no alert sent` in that case, so the degraded mode
   is visible rather than silent.

The guard makes roughly `pairs × intervals` kline requests per night (24 on the current
instance). That is nowhere near any rate limit.

---

## §3 — Install

On the VM, first, so the scripts exist there:

```sh
cd ~/trading_agent && git pull
```

Then from your Mac:

```sh
./scripts/install_candle_guard.sh
```

### On a different instance

The installer resolves its target from `GCP_ALWAYS_ON` / `GCP_ZONE` (via `scripts/gcp_common.sh`),
and inline overrides win over `scripts/gcp_env`, so:

```sh
GCP_ALWAYS_ON=fluxtrader-2 GCP_ZONE=europe-west1-b ./scripts/install_candle_guard.sh
```

Verify the target before trusting it — one line, no side effects:

```sh
GCP_ALWAYS_ON=fluxtrader-2 GCP_ZONE=europe-west1-b \
  bash -c 'source scripts/gcp_common.sh >/dev/null 2>&1; echo "target=$GCP_ALWAYS_ON zone=$GCP_ZONE"'
```

### Changing the schedule

```sh
CANDLE_GUARD_ON_CALENDAR='*-*-* 03:15:00' ./scripts/install_candle_guard.sh
```

01:40 UTC is the default: late enough that yesterday is unambiguously closed, early enough that
a failure is waiting at the start of the day. `RandomizedDelaySec=300` keeps the requests off the
exact minute.

---

## §4 — Verify the install (do not skip this)

Installing the timer proves nothing. **Fire it once and read the result:**

```sh
./scripts/install_candle_guard.sh --run-now
```

or directly on the VM:

```sh
sudo systemctl start candle-guard.service
systemctl status candle-guard.service --no-pager
sudo journalctl -u candle-guard.service --no-pager -n 20
cat /var/tmp/candle_guard_status.json
```

This step is here because the failure it catches is invisible otherwise. The wrapper runs under
`set -u` and derives its paths from `$HOME`; if `$HOME` were not set in the service environment
the script would abort **before** reaching the Telegram call — failing silently, every night,
looking exactly like a healthy quiet guard. The only way to know is to run it and look. On
`fluxtrader-1` this was run and it executed correctly (`~/candle_guard.log` written, status file
written, alert delivered).

A good first run looks like this in the status file:

```json
{ "exit_code": 0, "ok": true, "failed_checks": 0, "summary": "24/24 checks passed" }
```

⚠️ **A brand-new instance will legitimately FAIL its first run** if its candle history has not
been repaired yet, or if the app has been running less than a day. That is a true positive, not
a misconfiguration. Read `~/candle_guard.log` and confirm the failures are the ones you expect
before installing anything else.

---

## §5 — What a failure looks like

Telegram message, followed by the failing lines, at most 20 of them:

```
🔴 CANDLE GUARD FAILED on fluxtrader-1
13/24 checks passed
     BTCUSDT  1m 2026-09-02: FAIL 1440/1440 bars, exact vol=0.217 close=0.267 …, median vol ratio=0.685
```

How to read a line: `exact vol` is the fraction of bars whose stored volume equals the
exchange's exactly, and `median vol ratio` is stored ÷ true. **A median ratio well under 1.0 is
the partial-bar signature** — around 0.10 for 5m and 0.65 for 1m when the collector is freezing
the first sighting of each bar. A `MISSING=n` suffix instead means rows are absent, which is a
collection gap (app downtime), a different problem with a different fix.

Exit codes: `0` all checks passed · `1` at least one failed, or the run died · `2` the repo was
not found. `ok` in the status file requires exit 0 **and** a parseable summary line, so a run
that crashes partway is never recorded as a pass.

---

## §6 — Configuration

All optional; set them in the systemd unit's `Environment=` if you want them permanent.

| Variable | Default | Meaning |
|---|---|---|
| `CANDLE_GUARD_REPO` | `$HOME/trading_agent` | repo checkout to run from |
| `CANDLE_GUARD_INTERVALS` | `5m,1m` | intervals checked; `1m,5m,15m,1h` are supported |
| `CANDLE_GUARD_SYMBOLS` | *(empty)* | empty means **every symbol in `candles`**, which is what a guard should watch. Set it only to narrow the check while testing |
| `CANDLE_GUARD_LOG` | `$HOME/candle_guard.log` | appended each run |
| `CANDLE_GUARD_STATUS` | `/var/tmp/candle_guard_status.json` | last verdict |
| `CANDLE_GUARD_ON_CALENDAR` | `*-*-* 01:40:00` | installer only; systemd `OnCalendar` |

Ad-hoc use of the underlying check, which is often what you actually want:

```sh
docker compose --profile ml run --rm ml_trainer \
  python verify_candles.py --intervals 5m --days 2026-08-20,2026-09-01
docker compose --profile ml run --rm ml_trainer \
  python verify_candles.py --symbols BTCUSDT --intervals 5m --since-yesterday
```

---

## §7 — Troubleshooting

**`crontab: command not found`** — expected; there is no cron. Use the timer (§1).

**Timer listed but never seems to run.** `systemctl list-timers candle-guard.timer` shows
`NEXT`/`LAST`. If `LAST` is empty long after `NEXT` passed, check
`sudo journalctl -u candle-guard.service`. Then run §4's one-shot: a unit that fails instantly
usually means the user is not in the `docker` group, or `WorkingDirectory` does not exist.

**Service runs, but no Telegram on a failure.** Check the journal for
`TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID unset` (credentials missing from `.env`) or
`Telegram send failed` (network or a bad token). The guard deliberately does not fail the run
over an undeliverable message — the status file is still authoritative.

**First run takes several minutes.** It builds/starts the `ml_trainer` container.
`TimeoutStartSec=1800` allows for it, but a hung run cannot block the next day's.

**All `5m` checks pass but `1m` fails, right after a deploy.** Not a bug, and worth
understanding because it is easy to misread as one. On startup the app's `backfill_candles/3`
re-fetches the last 500 closed bars per pair and — since the fix — *replaces* them. 500 bars is
41.7 hours at 5m but only 8.3 hours at 1m, so a restart silently repairs yesterday at 5m and
only part of it at 1m. This was observed exactly on 2026-09-03 and the boundary matched the
arithmetic to within half a percent.

**Failures on days the app was down.** Those show `MISSING=n`. Genuine, but a collection gap,
not corruption — repair with `backfill_history.py` in its normal (gap-filling) mode.

**Porting the wrapper to another shell/host.** Keep it on `bash`. Note that
`"${arr[@]}"` on an empty array aborts under `set -u` on bash 3.2 (macOS's system bash); the
script uses positional parameters instead for exactly this reason, since the empty-symbols case
is the production default and must be the one that cannot break.

---

## §8 — Uninstall

```sh
./scripts/install_candle_guard.sh --uninstall
# or, on another instance:
GCP_ALWAYS_ON=fluxtrader-2 GCP_ZONE=europe-west1-b ./scripts/install_candle_guard.sh --uninstall
```

Removes the timer and unit. `~/candle_guard.log` and the status file are left in place.

---

## §9 — A host without systemd, or outside GCP

Everything above is packaging. The guard is one command:

```sh
cd /path/to/trading_agent && ./scripts/candle_guard.sh
```

It is idempotent, exits non-zero on failure, and needs no arguments. Any scheduler that can run
a command daily and notice a non-zero exit will do — a real `cron` entry, a Kubernetes CronJob, a
CI schedule. Only `install_candle_guard.sh` is GCP- and systemd-specific.

---

## §10 — The gap this does not cover

**If the instance is off, or the timer is disabled, nothing runs and nothing alerts** — and
silence is indistinguishable from a clean bill of health. The guard cannot report its own
absence. `/var/tmp/candle_guard_status.json` carries `finished_utc` precisely so something else
can notice staleness; surfacing it on `/api/health` and treating "older than 48 hours" as a
failure would close the loop. That is still parked in [BACKLOG.md](./BACKLOG.md), along with a
second, cheaper monitor with no external call at all: the served model's live feature z-scores
against the checkpoint's own `norm_stats`, where a column sitting at −2σ for a month is this
same defect's signature.
