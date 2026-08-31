defmodule FluxTrader.Trading.RegimeTest do
  @moduledoc """
  The half of the 2026-08-31 freeze that lives in `Regime`: the sizing ladder is a constant,
  and the trailing quintiles it used to serve are now a diagnostic.

  `Regime` is not started in the test environment (it opens a REST connection to Binance on
  boot), so these drive its `handle_call/3` callbacks against hand-built state. That is the
  whole of the decision logic — everything else in the module is fetching and paging — and it
  keeps the tests hermetic, which matters more here than exercising the socket.

  The substitution these pin went unnoticed for three days because both the frozen ladder and
  a trailing one are plausible-looking lists of four floats. A test that only checked "edges
  are present" would have passed throughout.
  """
  use ExUnit.Case, async: true

  alias FluxTrader.Trading.{Policy, Regime}

  @bars_per_day 288

  # A close series long enough to clear the value's 24h lookback, with a known 2% move over
  # the last day so `btc_absret_1d` is a number the test can name.
  defp closes(n_bars) do
    for i <- 0..(n_bars - 1), into: %{} do
      {i * 300, if(i < n_bars - @bars_per_day, do: 100.0, else: 102.0)}
    end
  end

  defp state(overrides) do
    Map.merge(
      %{closes: %{}, edges: nil, value: nil, last_error: nil, bootstrapped: true},
      Map.new(overrides)
    )
  end

  describe "the ladder served to the policy" do
    test "is the frozen one, never the trailing quintiles" do
      # The trailing edges here are deliberately absurd — an order of magnitude off the
      # frozen ones — so a regression that serves them cannot pass by coincidence.
      st = state(closes: closes(@bars_per_day * 2), value: 0.02, edges: [9.0, 9.1, 9.2, 9.3])

      assert {:reply, {:ok, r}, _} = Regime.handle_call(:state, self(), st)
      assert r.edges == Policy.frozen_regime_edges()
      refute r.edges == st.edges
    end

    test "is served even when the trailing edges have not been built yet" do
      # The point of freezing: sizing no longer waits on a week of klines. If this returns
      # `:cold` the warmup is back, and `Policy.decide/3` skips every bar as `:no_regime`.
      st = state(closes: closes(@bars_per_day + 12), value: 0.02, edges: nil)

      assert {:reply, {:ok, r}, _} = Regime.handle_call(:state, self(), st)
      assert r.edges == Policy.frozen_regime_edges()
    end
  end

  describe "readiness" do
    test "is cold with no value, whatever the edges say" do
      st = state(closes: closes(@bars_per_day * 2), value: nil, edges: [1.0, 2.0, 3.0, 4.0])
      assert {:reply, {:error, :cold}, _} = Regime.handle_call(:state, self(), st)
    end

    test "is cold below the value's 24h lookback" do
      # A truncated fetch must not present one stale reading as ready — sizing off a
      # fabricated regime is worse than not trading.
      st = state(closes: closes(@bars_per_day), value: 0.02)
      assert {:reply, {:error, :cold}, _} = Regime.handle_call(:state, self(), st)
    end

    test "clears at 24h of closes, not at the week the old ladder needed" do
      st = state(closes: closes(@bars_per_day + 12), value: 0.02)
      assert {:reply, {:ok, _}, _} = Regime.handle_call(:state, self(), st)
    end
  end

  describe "status/0's payload" do
    test "separates the ladder in force from the drift diagnostic" do
      st = state(closes: closes(@bars_per_day * 2), value: 0.007, edges: [0.001, 0.002, 0.003, 0.004])

      assert {:reply, s, _} = Regime.handle_call(:status, self(), st)

      # In force.
      assert s.quintile_edges == Policy.frozen_regime_edges()
      assert s.frozen_p80 == List.last(Policy.frozen_regime_edges())

      # Diagnostic. Reported, and reported as itself — the pair of numbers is the drift
      # signal, so neither may be dropped or silently substituted for the other.
      assert s.trailing_quintile_edges == st.edges
      assert s.trailing_p80 == 0.004
      assert s.ready
    end

    test "still reports the ladder while the diagnostic is cold" do
      # `/api/health` is how a deployed binary's constants are checked without reading its
      # source, so the frozen values must be present before the diagnostic warms up.
      st = state(closes: closes(@bars_per_day + 12), value: 0.007, edges: nil)

      assert {:reply, s, _} = Regime.handle_call(:status, self(), st)
      assert s.quintile_edges == Policy.frozen_regime_edges()
      assert s.trailing_quintile_edges == nil
      assert s.trailing_p80 == nil
      assert s.ready
    end
  end

  describe "refresh keeps what it already has" do
    test "an empty series does not wipe a good value or the diagnostic edges" do
      # Regression guard. When the edges were derived here, `refresh/2` only assigned inside
      # its success branch, so a barren refresh left the last good state alone. Freezing
      # restructured that function, and a `nil` value is not neutral — `Policy.decide/3`
      # turns it into a `:no_regime` skip, i.e. the policy silently stops trading.
      st = state(closes: closes(@bars_per_day * 2), value: 0.02, edges: [1.0, 2.0, 3.0, 4.0])

      # `absret_series/1` over closes with no complete lookback yields nothing.
      assert Regime.absret_series(closes(@bars_per_day)) == %{}

      # The reducer's inputs are what matter; assert the invariant through `state`.
      assert {:reply, {:ok, r}, _} = Regime.handle_call(:state, self(), st)
      assert r.value == 0.02
    end
  end

  describe "absret_series/1" do
    test "is |close(t)/close(t-24h) - 1| and skips bars with an incomplete lookback" do
      series = Regime.absret_series(closes(@bars_per_day * 2))

      # The first day has no lookback and is absent rather than interpolated.
      assert map_size(series) == @bars_per_day
      assert series[(@bars_per_day * 2 - 1) * 300] == 0.020000000000000018
    end
  end
end
