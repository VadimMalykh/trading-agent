defmodule FluxTrader.Notifications.Telegram do
  require Logger

  @base_url "https://api.telegram.org"

  def bot_token do
    System.get_env("TELEGRAM_BOT_TOKEN") ||
      Application.get_env(:fluxtrader, :telegram, [])
      |> Keyword.get(:bot_token)
  end

  def chat_id do
    System.get_env("TELEGRAM_CHAT_ID") ||
      Application.get_env(:fluxtrader, :telegram, [])
      |> Keyword.get(:chat_id)
  end

  def configured? do
    bot_token() != nil && chat_id() != nil
  end

  def send_trade_signal(%{trade: true, side: side, symbol: _symbol} = signal)
      when side in ["BUY", "SELL"] do
    if configured?() do
      message = format_signal(signal)
      send_message(message)
    else
      Logger.debug("Telegram not configured — skipping notification")
      :ok
    end
  end

  def send_trade_signal(_), do: :ok

  defp format_signal(signal) do
    side = signal[:side]
    symbol = signal[:symbol]
    price =
      if is_float(signal[:price]), do: Float.round(signal[:price], 2), else: signal[:price]
    conf =
      if is_float(signal[:confidence]),
        do: Float.round(signal[:confidence] * 100, 1),
        else: signal[:confidence]
    primary = signal[:primary_horizon_m]
    gate = signal[:gate_threshold]
    horizons = signal[:horizons] || %{}

    icon = if side == "BUY", do: "🟢", else: "🔴"

    horizon_lines =
      horizons
      |> Enum.sort()
      |> Enum.map(fn {h, hv} ->
        dir = horizon_dir(hv)
        hc = horizon_conf(hv)
        hg = horizon_gated(hv)
        hcp = if is_float(hc), do: Float.round(hc * 100, 1), else: hc
        check = if hg, do: " ✓", else: ""
        "  #{h}m: #{dir} (#{hcp}%)#{check}"
      end)
      |> Enum.join("\n")

    "#{icon} *TRADE SIGNAL* #{icon}\n" <>
      "`#{symbol}` #{side} at $#{price}\n" <>
      "Conf: #{conf}% · Prim: #{primary}m · Gate: #{gate}\n" <>
      "#{horizon_lines}"
  end

  defp horizon_dir(%{"direction" => d}), do: d
  defp horizon_dir(%{direction: d}), do: d
  defp horizon_dir(_), do: "?"

  defp horizon_conf(%{"confidence" => c}) when is_number(c), do: c
  defp horizon_conf(%{confidence: c}) when is_number(c), do: c
  defp horizon_conf(_), do: 0.0

  defp horizon_gated(%{"gated" => g}), do: g
  defp horizon_gated(%{gated: g}), do: g
  defp horizon_gated(_), do: false

  defp send_message(text) do
    token = bot_token()
    chat = chat_id()

    url = "#{@base_url}/bot#{token}/sendMessage"

    body =
      Jason.encode!(%{
        chat_id: chat,
        text: text,
        parse_mode: "Markdown"
      })

    request = Finch.build(:post, url, [{"content-type", "application/json"}], body)

    case Finch.request(request, FluxTrader.Finch, receive_timeout: 10_000) do
      {:ok, %{status: status}} when status in 200..299 ->
        :ok

      {:ok, %{status: status, body: body}} ->
        Logger.warning("Telegram API error: #{status} #{body}")
        :ok

      {:error, reason} ->
        Logger.warning("Telegram request failed: #{inspect(reason)}")
        :ok
    end
  end
end
