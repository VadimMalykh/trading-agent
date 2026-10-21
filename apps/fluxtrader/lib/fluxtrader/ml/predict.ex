defmodule FluxTrader.ML.Predict do
  @moduledoc """
  Client for M2 inference service (ml_inference container).
  """
  require Logger

  @default_url "http://ml_inference:8001"

  def inference_url do
    System.get_env("ML_INFERENCE_URL") ||
      Application.get_env(:fluxtrader, :ml, [])
      |> Keyword.get(:inference_url, @default_url)
  end

  def gate_threshold do
    case System.get_env("ML_GATE_THRESHOLD") do
      nil ->
        Application.get_env(:fluxtrader, :ml, [])
        |> Keyword.get(:gate_threshold, 0.40)

      val ->
        String.to_float(val)
    end
  end

  def health do
    case get("/health") do
      {:ok, body} -> {:ok, body}
      error -> error
    end
  end

  def predict_symbol(symbol) when is_binary(symbol) do
    case get("/predict?symbol=#{URI.encode(symbol)}") do
      {:ok, %{"ok" => true} = body} ->
        {:ok, normalize(body)}

      {:ok, %{"ok" => false, "error" => err}} ->
        {:error, err}

      {:ok, body} ->
        {:error, body}

      error ->
        error
    end
  end

  def predict_all do
    case get("/predict_all") do
      {:ok, %{"ok" => true, "signals" => signals}} when is_list(signals) ->
        {:ok, Enum.map(signals, &normalize/1)}

      {:ok, body} ->
        {:error, body}

      error ->
        error
    end
  end

  defp normalize(%{"ok" => false} = body), do: body

  defp normalize(body) when is_map(body) do
    %{
      symbol: body["symbol"],
      price: body["price"],
      side: body["side"] || "FLAT",
      trade: body["trade"] == true,
      confidence: body["confidence"] || 0.0,
      primary_horizon_m: body["primary_horizon_m"] || 15,
      gate_threshold: body["gate_threshold"] || gate_threshold(),
      horizons: body["horizons"] || %{},
      model: body["model"],
      error: body["error"],
      ok: body["ok"] != false,
      timestamp: DateTime.utc_now(),
      # The CLOSED bar the features end on (`serve.py` `last_closed_bar_open_time`, its open
      # time). The policy keys `policy_bars` on it, not on the wall clock: the row then names
      # the bar it scored, and the trade goes out on the tick that bar is first served instead
      # of the tick the wall clock crosses a 5-minute mark (M3_5_INTEGRATION §4.5). `nil` for a
      # serve that predates the field; the engine drops such a signal as `signal_unusable`.
      bar_open_time: parse_bar_time(body["last_closed_bar_open_time"])
    }
  end

  defp parse_bar_time(s) when is_binary(s) do
    case DateTime.from_iso8601(s) do
      {:ok, dt, _offset} ->
        DateTime.truncate(dt, :second)

      {:error, :missing_offset} ->
        case NaiveDateTime.from_iso8601(s) do
          {:ok, naive} -> DateTime.from_naive!(naive, "Etc/UTC") |> DateTime.truncate(:second)
          _ -> nil
        end

      _ ->
        nil
    end
  end

  defp parse_bar_time(_), do: nil

  defp get(path) do
    url = inference_url() <> path

    case Finch.build(:get, url)
         |> Finch.request(FluxTrader.Finch, receive_timeout: 60_000) do
      {:ok, %{status: 200, body: body}} ->
        case Jason.decode(body) do
          {:ok, json} -> {:ok, json}
          {:error, e} -> {:error, e}
        end

      {:ok, %{status: status, body: body}} ->
        {:error, {status, body}}

      {:error, reason} ->
        {:error, reason}
    end
  end
end
