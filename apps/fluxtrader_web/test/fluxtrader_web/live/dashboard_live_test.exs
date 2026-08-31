defmodule FluxTraderWeb.DashboardLiveTest do
  @moduledoc """
  The M3 panel, in the states that matter and that a manual click-through on a populated dev
  box would never see.

  They are nearly all *empty* states. That is the point: the forward paper test is expected to
  be quiet for weeks at a time, so the states the panel exists to explain are the ones with no
  trades in them. A panel that renders those as a grey box with `0.00` in it is worse than no
  panel — it reads as a fault, and someone "fixes" a working system.

  Since the 2026-08-31 freeze the panel has a second job, and it is the opposite one: the cut
  is a constant, so a running engine whose cut is NOT that constant is serving a rule nobody
  scored, and that must read as loudly as the calm market reads quietly.
  """
  use FluxTraderWeb.ConnCase, async: false

  import Phoenix.LiveViewTest

  alias FluxTrader.Repo
  alias FluxTrader.Trading.{Ledger, Policy, PolicyBar, PolicyEngine}

  @horizon 240

  setup do
    # `autotick: false` and the injected sources keep the engine from reaching for a live
    # inference service; the panel only ever reads `status/0`, which needs neither.
    :ok
  end

  defp start_engine(signals \\ []) do
    start_supervised!(
      {PolicyEngine, [autotick: false, signals_fun: fn -> signals end, regime_fun: fn -> nil end]}
    )
  end

  # `spread` sets what the trailing top-2% rank lands on, which is the drift diagnostic the
  # panel now renders. It decides nothing — since the 2026-08-31 freeze the cut is a constant
  # — but it is the difference between "bars are clearing the cut" and "the market is calm".
  defp record_bars(n, now, {lo, hi} \\ {0.40, 0.89}) do
    span = hi - lo

    rows =
      for i <- 1..n do
        %{
          pair: "BTCUSDT",
          bar_ts: DateTime.add(now, -i * 60, :second) |> DateTime.truncate(:second),
          horizon_m: @horizon,
          confidence: lo + rem(i, 50) / 50.0 * span,
          side: 1,
          price: 1.0,
          gated: false,
          inserted_at: NaiveDateTime.utc_now() |> NaiveDateTime.truncate(:second)
        }
      end

    Repo.insert_all(PolicyBar, rows)
  end

  describe "the M3 panel" do
    test "a thin bar log is not a warmup, and the panel must not call it one", %{conn: conn} do
      # 🔴 This test replaces one that asserted the opposite. Before the 2026-08-31 freeze a
      # short rank window meant the policy could not trade, and the panel's job was to explain
      # the wait. The cut is now a constant, so there is no wait to explain — and a panel that
      # still said "warming up" would be telling an operator to sit and watch a number that
      # gates nothing.
      record_bars(1044, DateTime.utc_now())
      start_engine()
      :ok = PolicyEngine.refresh()

      {:ok, _view, html} = live(conn, "/")

      assert html =~ "M3 Policy — forward paper test"
      # The cut in force is on the page, and it is the constant.
      assert html =~ "0.632"
      assert html =~ "There is no warmup"

      # None of the retired warmup vocabulary may come back.
      refute html =~ "Warming up"
      refute html =~ "until the rank window fills"
      refute html =~ "bars/day"
      refute html =~ "seven days"

      # The bar log is thin, so the DRIFT diagnostic — not the policy — is what is not ready.
      assert html =~ "drift diagnostic needs a fuller bar log"
    end

    test "the panel goes red when the running cut is not this build's constant", %{conn: conn} do
      # The one failure mode the freeze cannot prevent on its own: a VM still running a
      # pre-freeze binary, or a re-wired trailing rank. Both serve a rule nobody scored, and
      # both are invisible unless the page compares the two numbers.
      start_engine()
      :ok = PolicyEngine.refresh()

      # Drive the panel's own predicate rather than faking a status map: this is the
      # comparison that has to be right.
      running = PolicyEngine.status().confidence_threshold
      assert running == Policy.frozen_threshold()

      {:ok, _view, html} = live(conn, "/")
      refute html =~ "not serving the rule this page describes"
    end

    test "an empty ledger renders — for every unmeasured number, never 0.00", %{conn: conn} do
      start_engine()

      {:ok, _view, html} = live(conn, "/")

      # Both arms are present with a real trade count of zero...
      assert html =~ "policy"
      assert html =~ "flat_size"
      # ...and every metric that has not been measured reads as a dash.
      assert html =~ "—"
      # 🔴 The assertion this test exists for: `nil` is not `0.0`. Rendering 0.00 would claim
      # a measurement that has not been taken.
      refute html =~ "0.00"
      assert html =~ "a dash means not measured yet, not zero"
      # The fee tier is still unverified against the account and the panel must not hide it.
      assert html =~ "fee tier UNVERIFIED"
    end

    test "a not_served skip renders the universe-drift warning in full", %{conn: conn} do
      # BNBUSDT is not in the served universe, so its bar is dropped before it can join the
      # ranking population — and counted as the named skip `not_served`.
      signal = %{
        symbol: "BNBUSDT",
        price: 100.0,
        timestamp: DateTime.utc_now(),
        horizons: %{
          "240" => %{"direction" => "up", "confidence" => 0.9, "gated" => false}
        }
      }

      start_engine([signal])
      :ok = PolicyEngine.refresh()
      assert %{skips: %{not_served: 1}} = PolicyEngine.status()

      {:ok, _view, html} = live(conn, "/")

      assert html =~ "not_served"
      assert html =~ "not_served is non-zero (1)"
      assert html =~ "the collector whitelist have drifted apart"
    end

    test "the whole dashboard still renders when the policy engine is down", %{conn: conn} do
      # No engine started: `status/0` exits and the guard returns a fallback with no `warm`.
      {:ok, _view, html} = live(conn, "/")

      assert html =~ "M3 Policy — forward paper test"
      assert html =~ "The policy engine is not answering"
      assert html =~ "this is a fault"
      # The M2-era panels are untouched and still render beside it.
      assert html =~ "System Status"
      assert html =~ "Live Candles (1m)"
    end

    test "a calm market is described as correct, not as a fault", %{conn: conn} do
      # The state the panel exists for, and the state the VM is actually in: the model's
      # confidence never gets near the cut, so nothing trades. August 2026's live bars topped
      # out at 0.569 against a cut of 0.632, so the seeded range here is the real one.
      now = DateTime.utc_now()
      record_bars(Ledger.min_rank_bars() + 50, now, {0.40, 0.56})
      start_engine()
      :ok = PolicyEngine.refresh()

      status = PolicyEngine.status()
      assert status.warm
      assert status.rolling_threshold < Policy.frozen_threshold()

      {:ok, _view, html} = live(conn, "/")

      assert html =~ "the policy is correctly taking nothing"
      assert html =~ "below the cut"
      assert html =~ "No gated signal has fired yet"
      assert html =~ "the strategy working rather than a fault"
      # Never an alarm colour for a calm market — the panel's standing rule.
      refute html =~ "not serving the rule this page describes"
    end

    test "a market that clears the cut says so", %{conn: conn} do
      now = DateTime.utc_now()
      record_bars(Ledger.min_rank_bars() + 50, now, {0.40, 0.89})
      start_engine()
      :ok = PolicyEngine.refresh()

      assert PolicyEngine.status().rolling_threshold > Policy.frozen_threshold()

      {:ok, _view, html} = live(conn, "/")

      assert html =~ "top 2% clears the cut"
      assert html =~ "so bars are clearing it"
    end
  end
end
