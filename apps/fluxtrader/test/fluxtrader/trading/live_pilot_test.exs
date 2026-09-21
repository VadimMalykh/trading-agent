defmodule FluxTrader.Trading.LivePilotTest do
  @moduledoc """
  The two side arms added 2026-09-21 — the exploratory top-5% paper arm and the real-money
  micro-pilot — and the boot grace. The invariant under all of it: the registered A/B
  (`policy`, `flat_size`) books exactly what it booked before, in paper.
  """
  use FluxTrader.DataCase, async: false

  alias FluxTrader.Binance.Trade.Fake
  alias FluxTrader.Repo
  alias FluxTrader.Trading.{Executor, Ledger, LivePilot, PaperTrade, Policy, PolicyEngine, RiskManager}

  setup do
    prev = for k <- [:trading, :binance, :trade_client, :live_pilot], do: {k, Application.get_env(:fluxtrader, k)}

    on_exit(fn ->
      for {k, v} <- prev do
        if v == nil, do: Application.delete_env(:fluxtrader, k), else: Application.put_env(:fluxtrader, k, v)
      end

      Fake.stop()
    end)

    Application.put_env(:fluxtrader, :trading,
      mode: "simulation",
      max_positions: 12,
      max_position_pct: 0.10,
      max_notional_pct: 0.20,
      max_daily_loss_pct: 0.05,
      leverage: 5,
      max_leverage: 10,
      min_confidence: 0.0,
      total_capital: 1000.0
    )

    Application.put_env(:fluxtrader, :trade_client, Fake)
    Application.put_env(:fluxtrader, :binance, api_key: "k", api_secret: "s", testnet: true)
    :ok
  end

  defp pilot(opts), do: Application.put_env(:fluxtrader, :live_pilot, [enabled: true, notional_usd: 200.0] ++ opts)

  defp boot(signals, engine_opts \\ []) do
    {:ok, _} = Fake.start()
    start_supervised!({Executor, []})
    start_supervised!({RiskManager, []})

    start_supervised!(
      {PolicyEngine,
       [
         autotick: false,
         signals_fun: fn -> signals end,
         regime_fun: fn -> %{value: 0.025, edges: Policy.frozen_regime_edges(), samples: 8640} end,
         checkpoint_fun: fn -> Policy.frozen_checkpoint_sha256() end,
         interval_fun: fn -> Policy.candle_interval() end,
         closed_bars_fun: fn -> true end
       ] ++ engine_opts}
    )

    :ok = PolicyEngine.refresh()
  end

  defp signal(symbol, confidence) do
    %{
      symbol: symbol,
      price: 100_000.0,
      timestamp: DateTime.utc_now(),
      horizons: %{"240" => %{"direction" => "up", "confidence" => confidence, "gated" => false}}
    }
  end

  test "the exploratory arm takes top-5% bars the policy rejects, in paper, and the A/B does not see them" do
    assert Policy.explore_threshold() < Policy.frozen_threshold()

    boot([signal("BTCUSDT", 0.97), signal("ETHUSDT", 0.64), signal("SOLUSDT", 0.55)])

    assert Ledger.open_pairs("policy") == MapSet.new(["BTCUSDT"])
    assert Ledger.open_pairs("flat_size") == MapSet.new(["BTCUSDT"])
    assert Ledger.open_pairs("explore_cov05") == MapSet.new(["BTCUSDT", "ETHUSDT"])

    for t <- Ledger.open_trades("explore_cov05") do
      assert t.fill_source == "paper"
      assert_in_delta t.size, 4 / 3, 1.0e-9
    end

    assert Enum.map(Ledger.ab_summary(), & &1.arm) == PaperTrade.arms()
    assert PaperTrade.arms() == ~w(policy flat_size)
    assert Fake.calls() == []
  end

  test "with the pilot off, which is the default, nothing reaches the exchange" do
    Application.delete_env(:fluxtrader, :live_pilot)
    refute LivePilot.enabled?()
    assert LivePilot.refusal() == :not_requested

    boot([signal("BTCUSDT", 0.97)])

    assert Ledger.open_pairs("policy") == MapSet.new(["BTCUSDT"])
    assert Ledger.open_pairs("live") == MapSet.new()
    assert Fake.calls() == []
    assert PolicyEngine.status().decisions == %{policy_opened: 1, control_opened: 1, explore_opened: 1}
  end

  test "with the pilot on, the policy row stays paper and the live row is the exchange's fill at flat size" do
    pilot([])
    boot([signal("BTCUSDT", 0.97)])

    assert Executor.mode() == "simulation"
    assert Executor.status().live_orders

    [p] = Ledger.open_trades("policy")
    assert p.fill_source == "paper"
    assert p.entry_price == 100_000.0

    [l] = Ledger.open_trades("live")
    assert l.fill_source == "exchange"
    assert l.size == 1.0
    assert l.quantity == 0.002
    assert l.entry_price == Fake.fill_price()
    assert is_integer(l.stop_order_id) and is_integer(l.target_order_id)

    # 1x, and the same 2% / 4% brake the auto path places.
    assert [{:set_leverage, ["BTCUSDT", 1]}] = Fake.calls(:set_leverage)
    [{:place_algo_order, [stop]}, {:place_algo_order, [target]}] = Fake.calls(:place_algo_order)
    assert stop[:triggerPrice] == 98_000.0
    assert target[:triggerPrice] == 104_000.0

    # ... and it closes on the exchange although the mode is simulation.
    assert {:ok, closed} = Executor.close(l, 99_000.0)
    assert closed.exit_reason == "timer"
    assert closed.exit_price == Fake.fill_price()
  end

  test "the pilot's limits come from its own ledger rows: open count, daily loss, total loss" do
    pilot(max_positions: 1, daily_loss_usd: 10.0, max_total_loss_usd: 100.0)
    d = %{pair: "ETHUSDT", side: 1, entry_price: 2_000.0}

    assert {:ok, order} = LivePilot.check(d)
    assert order.notional == 200.0
    assert order.quantity == 0.1
    assert order.leverage == 1

    closed_row = fn pair, net_bps, exit_ts ->
      Repo.insert!(%PaperTrade{
        arm: "live", pair: pair, side: 1, size: 1.0, status: "closed", fill_source: "exchange",
        entry_ts: DateTime.add(exit_ts, -14_400, :second), exit_after_ts: exit_ts, exit_ts: exit_ts,
        entry_price: 1.0, exit_price: 1.0, notional: 200.0, net_bps: net_bps
      })
    end

    now = DateTime.utc_now() |> DateTime.truncate(:second)

    # -$12 yesterday: inside the total, outside today.
    closed_row.("XRPUSDT", -600.0, DateTime.add(now, -2 * 86_400, :second))
    assert {:ok, _} = LivePilot.check(d)

    # -$12 today: the daily limit.
    closed_row.("ADAUSDT", -600.0, now)
    assert LivePilot.check(d) == {:reject, :daily_loss_limit}
    assert_in_delta LivePilot.status().realised_usd_total, -24.0, 1.0e-9

    # -$100 in total: the kill level outranks everything.
    closed_row.("SOLUSDT", -4_000.0, DateTime.add(now, -3 * 86_400, :second))
    assert LivePilot.check(d) == {:reject, :total_loss_limit}
  end

  test "an open live row fills the pilot's cap, and the refusal is named" do
    pilot(max_positions: 1)

    Repo.insert!(%PaperTrade{
      arm: "live", pair: "ETHUSDT", side: 1, size: 1.0, status: "open", fill_source: "exchange",
      entry_ts: DateTime.utc_now() |> DateTime.truncate(:second),
      exit_after_ts: DateTime.utc_now() |> DateTime.add(14_400, :second) |> DateTime.truncate(:second),
      entry_price: 2_000.0, notional: 200.0
    })

    boot([signal("BTCUSDT", 0.97)])

    assert Ledger.open_pairs("policy") == MapSet.new(["BTCUSDT"])
    assert Ledger.open_pairs("live") == MapSet.new(["ETHUSDT"])
    assert PolicyEngine.status().decisions[:live_refused_max_positions] == 1
    assert Fake.calls(:place_order) == []
  end

  test "a symbol the account already holds a position on is never touched — nor one that cannot be read" do
    pilot([])

    for {answer, n} <- [
          {{:ok, [%{"symbol" => "BTCUSDT", "positionAmt" => "-0.250"}]}, 1},
          {{:error, :timeout}, 2}
        ] do
      {:ok, _} = Fake.start(responses: %{position_risk: [answer]})
      start_supervised!({Executor, []}, id: {:executor, n})

      now = DateTime.utc_now()

      d = %{
        pair: "BTCUSDT", side: 1, size: 1.0, entry_price: 100_000.0, confidence: 0.9,
        entry_ts: now, exit_after_ts: DateTime.add(now, 14_400, :second)
      }

      {:ok, order} = LivePilot.check(d)
      assert Executor.open("live", d, order) == {:error, :foreign_position}

      # Nothing but the read: no leverage change, no order, no brake, no cancel.
      assert Enum.map(Fake.calls(), &elem(&1, 0)) == [:position_risk]
      assert Ledger.open_trades("live") == []
      stop_supervised!({:executor, n})
    end
  end

  test "the engine names a foreign-position refusal and still books the paper arms" do
    pilot([])
    {:ok, _} = Fake.start(responses: %{position_risk: [{:ok, [%{"positionAmt" => "676"}]}]})
    start_supervised!({Executor, []})
    start_supervised!({RiskManager, []})

    start_supervised!(
      {PolicyEngine,
       [
         autotick: false,
         signals_fun: fn -> [signal("BTCUSDT", 0.97)] end,
         regime_fun: fn -> %{value: 0.025, edges: Policy.frozen_regime_edges(), samples: 8640} end,
         checkpoint_fun: fn -> Policy.frozen_checkpoint_sha256() end,
         interval_fun: fn -> Policy.candle_interval() end,
         closed_bars_fun: fn -> true end
       ]}
    )

    :ok = PolicyEngine.refresh()

    assert Ledger.open_pairs("policy") == MapSet.new(["BTCUSDT"])
    assert Ledger.open_pairs("live") == MapSet.new()
    assert PolicyEngine.status().decisions[:live_refused_foreign_position] == 1
    assert Fake.calls(:place_order) == []
  end

  test "the pilot refuses to double an auto executor, and refuses without credentials" do
    pilot([])
    Application.put_env(:fluxtrader, :trading, mode: "auto")
    assert LivePilot.refusal() == :executor_is_auto

    Application.put_env(:fluxtrader, :trading, mode: "simulation")
    Application.put_env(:fluxtrader, :binance, api_key: nil, api_secret: nil, testnet: false)
    assert LivePilot.refusal() == :missing_credentials
  end

  test "boot grace: the first minutes of an app start record bars and decide none" do
    boot([signal("BTCUSDT", 0.97)], boot_grace_s: 300)

    assert Ledger.open_pairs("policy") == MapSet.new()
    assert Ledger.open_pairs("explore_cov05") == MapSet.new()
    assert PolicyEngine.status().skips == %{boot_grace: 1}
    assert Ledger.liveness().bars_last_24h == 1
  end
end
