defmodule FluxTrader.ML.SignalEngine do
  @moduledoc """
  Periodically scores whitelist pairs via M2 inference and broadcasts signals.
  In simulation mode, logs gated signals as paper intents (no real orders).
  """
  use GenServer
  require Logger

  @poll_ms 30_000

  def start_link(opts) do
    GenServer.start_link(__MODULE__, opts, name: __MODULE__)
  end

  def latest do
    GenServer.call(__MODULE__, :latest)
  end

  def refresh do
    GenServer.cast(__MODULE__, :refresh)
  end

  @impl true
  def init(_opts) do
    state = %{
      signals: %{},
      inference_ok: false,
      last_error: nil,
      last_run_at: nil
    }

    Process.send_after(self(), :tick, 5_000)
    {:ok, state}
  end

  @impl true
  def handle_call(:latest, _from, state) do
    {:reply,
     %{
       signals: state.signals,
       inference_ok: state.inference_ok,
       last_error: state.last_error,
       last_run_at: state.last_run_at
     }, state}
  end

  @impl true
  def handle_cast(:refresh, state) do
    {:noreply, run_cycle(state)}
  end

  @impl true
  def handle_info(:tick, state) do
    state = run_cycle(state)
    Process.send_after(self(), :tick, @poll_ms)
    {:noreply, state}
  end

  def handle_info(_msg, state), do: {:noreply, state}

  defp run_cycle(state) do
    case FluxTrader.ML.Predict.health() do
      {:ok, %{"ok" => true}} ->
        score_pairs(%{state | inference_ok: true, last_error: nil})

      {:ok, body} ->
        err = "inference unhealthy: #{inspect(body)}"
        Logger.warning(err)
        %{state | inference_ok: false, last_error: err}

      {:error, reason} ->
        err = "inference unreachable: #{inspect(reason)}"
        Logger.warning(err)
        %{state | inference_ok: false, last_error: err}
    end
  end

  defp score_pairs(state) do
    pairs =
      try do
        FluxTrader.Pairs.Selector.active_pairs()
      rescue
        _ ->
          Application.get_env(:fluxtrader, :trading, [])
          |> Keyword.get(:whitelist_pairs, ["BTCUSDT", "ETHUSDT", "SOLUSDT"])
      catch
        :exit, _ ->
          Application.get_env(:fluxtrader, :trading, [])
          |> Keyword.get(:whitelist_pairs, ["BTCUSDT", "ETHUSDT", "SOLUSDT"])
      end

    {signals, errors} =
      Enum.reduce(pairs, {%{}, []}, fn pair, {acc, errs} ->
        case FluxTrader.ML.Predict.predict_symbol(pair) do
          {:ok, signal} ->
            maybe_log_simulation(signal)
            Phoenix.PubSub.broadcast(FluxTrader.PubSub, "signals:live", {:signal, signal})
            {Map.put(acc, pair, signal), errs}

          {:error, reason} ->
            {acc, [{pair, reason} | errs]}
        end
      end)

    if errors != [] do
      Logger.warning("SignalEngine errors: #{inspect(errors)}")
    end

    %{
      state
      | signals: Map.merge(state.signals, signals),
        last_run_at: DateTime.utc_now(),
        last_error: if(errors == [], do: nil, else: inspect(errors))
    }
  end

  defp maybe_log_simulation(%{trade: true, side: side, symbol: sym, confidence: conf, price: price} = signal)
       when side in ["BUY", "SELL"] do
    mode =
      Application.get_env(:fluxtrader, :trading, [])
      |> Keyword.get(:mode, "simulation")

    if mode in ["simulation", "signal"] do
      conf_s = if is_float(conf), do: Float.round(conf, 3), else: conf
      price_s = if is_float(price), do: Float.round(price, 2), else: price

      Logger.info(
        "[SIM_SIGNAL] #{side} #{sym} conf=#{conf_s} price=#{price_s} " <>
          "h=#{signal[:primary_horizon_m]}m gate=#{signal[:gate_threshold]} (paper only, no order)"
      )
    end
  end

  defp maybe_log_simulation(_), do: :ok
end
