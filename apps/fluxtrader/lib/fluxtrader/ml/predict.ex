defmodule FluxTrader.ML.Predict do
  @moduledoc """
  ML prediction interface. Sends features to the inference service
  and receives trade signals.
  """
  require Logger

  @confidence_threshold 0.65

  def predict(features) do
    case call_inference_service(features) do
      {:ok, prediction} ->
        signal = build_signal(prediction, features)

        if signal.confidence >= @confidence_threshold do
          Logger.info("Prediction: #{signal.side} confidence=#{Float.round(signal.confidence, 3)}")
          {:ok, signal}
        else
          Logger.info("Prediction below threshold: #{signal.confidence} < #{@confidence_threshold}")
          {:ok, :below_threshold}
        end

      {:error, reason} ->
        Logger.error("Inference failed: #{inspect(reason)}")
        {:error, reason}
    end
  end

  defp call_inference_service(features) do
    # TODO: Connect to ml_inference Docker service
    # For now, return a mock prediction
    direction = if features[:rsi_14] < 30, do: "BUY", else: "SELL"

    confidence =
      cond do
        features[:rsi_14] < 25 -> 0.85
        features[:rsi_14] < 35 -> 0.72
        features[:rsi_14] > 75 -> 0.80
        features[:rsi_14] > 65 -> 0.70
        true -> 0.55
      end

    {:ok, %{direction: direction, confidence: confidence, magnitude: 0.02}}
  end

  defp build_signal(prediction, features) do
    %{
      symbol: features[:symbol],
      side: if(prediction.direction == "BUY", do: "BUY", else: "SELL"),
      confidence: prediction.confidence,
      price: features[:current_price],
      magnitude: prediction.magnitude,
      timestamp: DateTime.utc_now()
    }
  end
end
