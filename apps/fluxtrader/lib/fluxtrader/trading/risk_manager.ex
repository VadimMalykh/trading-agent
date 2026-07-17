defmodule FluxTrader.Trading.RiskManager do
  @moduledoc """
  Enforces risk management rules before trade execution.
  """
  use GenServer
  require Logger

  def start_link(opts) do
    GenServer.start_link(__MODULE__, opts, name: __MODULE__)
  end

  def check(signal) do
    GenServer.call(__MODULE__, {:check, signal})
  end

  def get_stats do
    GenServer.call(__MODULE__, :get_stats)
  end

  @impl true
  def init(_opts) do
    config = Application.get_env(:fluxtrader, :trading, [])

    state = %{
      max_positions: Keyword.get(config, :max_positions, 3),
      max_position_pct: Keyword.get(config, :max_position_pct, 0.10),
      stop_loss_pct: Keyword.get(config, :stop_loss_pct, 0.02),
      take_profit_ratio: Keyword.get(config, :take_profit_ratio, 2.0),
      leverage: Keyword.get(config, :leverage, 5),
      max_daily_loss_pct: 0.05,
      daily_pnl: 0.0,
      open_positions: 0,
      total_capital: 1000.0
    }

    {:ok, state}
  end

  @impl true
  def handle_call({:check, signal}, _from, state) do
    cond do
      signal.confidence < 0.65 ->
        Logger.info("Rejected: confidence #{signal.confidence} < 0.65")
        {:reply, {:reject, :low_confidence}, state}

      state.open_positions >= state.max_positions ->
        Logger.info("Rejected: max positions reached (#{state.open_positions})")
        {:reply, {:reject, :max_positions}, state}

      abs(state.daily_pnl) >= state.total_capital * state.max_daily_loss_pct ->
        Logger.warning("Rejected: daily loss limit reached")
        {:reply, {:reject, :daily_loss_limit}, state}

      true ->
        position_size = calculate_position_size(signal, state)

        approved_signal =
          Map.merge(signal, %{
            quantity: position_size,
            leverage: state.leverage,
            stop_loss: calculate_stop_loss(signal, state),
            take_profit: calculate_take_profit(signal, state)
          })

        {:reply, {:ok, approved_signal}, %{state | open_positions: state.open_positions + 1}}
    end
  end

  def handle_call(:get_stats, _from, state) do
    stats = %{
      open_positions: state.open_positions,
      max_positions: state.max_positions,
      daily_pnl: state.daily_pnl,
      leverage: state.leverage
    }

    {:reply, stats, state}
  end

  defp calculate_position_size(signal, state) do
    capital_per_position = state.total_capital * state.max_position_pct
    capital_per_position / signal.price * state.leverage
  end

  defp calculate_stop_loss(signal, state) do
    case signal.side do
      "BUY" -> signal.price * (1 - state.stop_loss_pct)
      "SELL" -> signal.price * (1 + state.stop_loss_pct)
    end
  end

  defp calculate_take_profit(signal, state) do
    case signal.side do
      "BUY" -> signal.price * (1 + state.stop_loss_pct * state.take_profit_ratio)
      "SELL" -> signal.price * (1 - state.stop_loss_pct * state.take_profit_ratio)
    end
  end
end
