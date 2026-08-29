defmodule FluxTraderWeb.DashboardLiveTest do
  @moduledoc """
  The M3 panel, in the three states that matter and that a manual click-through on a
  populated dev box would never see.

  All three are *empty* states. That is the point: the forward paper test is expected to be
  quiet for weeks at a time, so the states the panel exists to explain are the ones with no
  trades in them. A panel that renders those as a grey box with `0.00` in it is worse than no
  panel — it reads as a fault, and someone "fixes" a working system.
  """
  use FluxTraderWeb.ConnCase, async: false

  import Phoenix.LiveViewTest

  alias FluxTrader.Repo
  alias FluxTrader.Trading.{Ledger, PolicyBar, PolicyEngine}

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

  defp record_bars(n, now) do
    rows =
      for i <- 1..n do
        %{
          pair: "BTCUSDT",
          bar_ts: DateTime.add(now, -i * 60, :second) |> DateTime.truncate(:second),
          horizon_m: @horizon,
          confidence: 0.40 + rem(i, 50) / 100.0,
          side: 1,
          price: 1.0,
          gated: false,
          inserted_at: NaiveDateTime.utc_now() |> NaiveDateTime.truncate(:second)
        }
      end

    Repo.insert_all(PolicyBar, rows)
  end

  describe "the M3 panel" do
    test "a short rank window renders the warmup explainer, not an empty box", %{conn: conn} do
      record_bars(1044, DateTime.utc_now())
      start_engine()

      {:ok, _view, html} = live(conn, "/")

      assert html =~ "M3 Policy — forward paper test"
      # The badge: bars seen against the bar count the window needs, never a calendar week.
      assert html =~ "1,044 / #{Ledger.min_rank_bars() |> Integer.to_string()}" or
               html =~ "1,044 / 2,016 bars"

      # The explainer, which is the whole reason the panel exists.
      assert html =~ "Warming up: 1,044 / 2,016 bars"
      assert html =~ "The policy may not trade until the rank window fills"
      assert html =~ "more hours at 12 pairs"
      # ⚠️ The window is a bar COUNT pooled across served pairs. Every document called this
      # "seven days" until 2026-08-29; the panel must not reintroduce that reading.
      assert html =~ "12 pairs x 288 = 3,456 bars/day"
      assert html =~ "not a calendar week"
      refute html =~ "seven days"
    end

    test "an empty ledger renders — for every unmeasured number, never 0.00", %{conn: conn} do
      start_engine()

      {:ok, _view, html} = live(conn, "/")

      # Both arms are present with a real trade count of zero...
      assert html =~ "policy"
      assert html =~ "signal_only"
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

    test "a silent but warm policy is described as correct, not as a fault", %{conn: conn} do
      now = DateTime.utc_now()
      record_bars(Ledger.min_rank_bars() + 50, now)
      start_engine()
      # One tick with no signals is enough to compute the coverage cut from the bar log.
      :ok = PolicyEngine.refresh()
      assert PolicyEngine.status().warm

      {:ok, _view, html} = live(conn, "/")

      assert html =~ "Warm — the rank window is full"
      assert html =~ "No gated signal has fired yet"
      assert html =~ "the strategy working rather than a fault"
    end
  end
end
