defmodule FluxTrader.Trading.RiskManagerTest do
  @moduledoc """
  M3_PLAN §6's last unchecked exit criterion: **the policy never bypasses hard `RiskManager`
  limits.** Until M3-5 nothing called the risk manager at all, so the box could not be
  ticked. These tests are what tick it.
  """
  use ExUnit.Case, async: false

  alias FluxTrader.Trading.RiskManager

  setup do
    # Started per test rather than from the supervision tree, so each test gets a clean
    # position count and daily P&L.
    prev = Application.get_env(:fluxtrader, :trading, [])

    on_exit(fn -> Application.put_env(:fluxtrader, :trading, prev) end)
    :ok
  end

  defp start_risk(opts) do
    base = [
      max_positions: 8,
      max_position_pct: 0.10,
      max_notional_pct: 0.20,
      max_daily_loss_pct: 0.05,
      leverage: 5,
      max_leverage: 10,
      min_confidence: 0.0,
      total_capital: 1000.0
    ]

    Application.put_env(:fluxtrader, :trading, Keyword.merge(base, opts))
    pid = start_supervised!({RiskManager, []})
    pid
  end

  defp order(overrides \\ []) do
    Enum.into(overrides, %{
      symbol: "BTCUSDT",
      side: "BUY",
      price: 100_000.0,
      size: 1.0,
      confidence: 0.8
    })
  end

  test "an ordinary policy order is approved and sized off capital" do
    start_risk([])
    assert {:ok, approved} = RiskManager.check(order())
    # 1000 capital x 10% x size 1.0 x 5x leverage = 500 notional.
    assert_in_delta approved.notional, 500.0, 1.0e-9
    assert_in_delta approved.quantity, 500.0 / 100_000.0, 1.0e-12
    assert approved.leverage == 5
  end

  test "the position cap is hard: the policy cannot open past it" do
    start_risk(max_positions: 2)
    assert {:ok, _} = RiskManager.check(order())
    assert {:ok, _} = RiskManager.check(order(symbol: "ETHUSDT"))
    assert {:reject, :max_positions} = RiskManager.check(order(symbol: "SOLUSDT"))
  end

  test "releasing a slot lets the next order through, and the counter never goes negative" do
    start_risk(max_positions: 1)
    assert {:ok, _} = RiskManager.check(order())
    assert {:reject, :max_positions} = RiskManager.check(order(symbol: "ETHUSDT"))

    RiskManager.release()
    assert {:ok, _} = RiskManager.check(order(symbol: "ETHUSDT"))

    RiskManager.release()
    RiskManager.release()
    RiskManager.release()
    assert %{open_positions: 0} = RiskManager.get_stats()
  end

  test "the policy's own size ladder cannot push a position past the notional ceiling" do
    # The whole point of a separate ceiling: the policy sizes 1/3..5/3, and 5/3 of a base
    # the operator set too high must be refused rather than silently clamped.
    start_risk(max_position_pct: 0.15, max_notional_pct: 0.20)
    assert {:ok, _} = RiskManager.check(order(size: 1.0))
    assert {:reject, :position_too_large} = RiskManager.check(order(size: 5 / 3))
  end

  test "the daily loss limit stops trading, and a good day does not" do
    start_risk(total_capital: 1000.0, max_daily_loss_pct: 0.05)

    RiskManager.record_close(-49.0)
    assert {:ok, _} = RiskManager.check(order())

    RiskManager.record_close(-2.0)
    assert {:reject, :daily_loss_limit} = RiskManager.check(order(symbol: "ETHUSDT"))
  end

  test "a profitable day is not a reason to halt" do
    start_risk(total_capital: 1000.0, max_daily_loss_pct: 0.05)
    RiskManager.record_close(+500.0)
    assert {:ok, _} = RiskManager.check(order())
  end

  test "leverage above the ceiling refuses everything" do
    start_risk(leverage: 25, max_leverage: 10)
    assert {:reject, :leverage_exceeded} = RiskManager.check(order())
  end

  test "the confidence floor is off by default because the policy owns coverage" do
    # M3_PLAN §3.1: a floor here could only ever narrow what the policy chose, never widen
    # it, so it defaults to 0.0 and the old hard-coded 0.65 is gone.
    start_risk([])
    assert {:ok, _} = RiskManager.check(order(confidence: 0.01))
  end

  test "the confidence floor still works as an explicit operator override" do
    start_risk(min_confidence: 0.65)
    assert {:reject, :low_confidence} = RiskManager.check(order(confidence: 0.5))
    assert {:ok, _} = RiskManager.check(order(confidence: 0.7))
  end

  test "rejections are counted so a silent refusal loop is visible on /api/health" do
    start_risk(max_positions: 0)
    assert {:reject, :max_positions} = RiskManager.check(order())
    assert {:reject, :max_positions} = RiskManager.check(order())
    assert %{rejections: %{max_positions: 2}} = RiskManager.get_stats()
  end
end
