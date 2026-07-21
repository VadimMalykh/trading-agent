defmodule FluxTrader.Settings do
  @moduledoc """
  Persistent app settings stored in Postgres (survives refresh/restart).
  """
  alias FluxTrader.Repo
  alias FluxTrader.Settings.Entry

  @whitelist_key "whitelist_pairs"
  @trading_key "trading"
  @default_pairs ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

  def get_whitelist do
    case get(@whitelist_key) do
      %{"pairs" => pairs} when is_list(pairs) and pairs != [] ->
        pairs |> Enum.map(&to_string/1) |> Enum.map(&String.upcase/1) |> Enum.uniq()

      _ ->
        Application.get_env(:fluxtrader, :trading, [])
        |> Keyword.get(:whitelist_pairs, @default_pairs)
    end
  end

  def put_whitelist(pairs) when is_list(pairs) do
    pairs =
      pairs
      |> Enum.map(&String.upcase(String.trim(to_string(&1))))
      |> Enum.reject(&(&1 == ""))
      |> Enum.uniq()

    pairs = if pairs == [], do: @default_pairs, else: pairs
    put(@whitelist_key, %{"pairs" => pairs})
    pairs
  end

  def get_trading do
    defaults = %{
      "mode" => "simulation",
      "max_positions" => 3,
      "stop_loss_pct" => 0.02,
      "take_profit_ratio" => 2.0,
      "leverage" => 5
    }

    Map.merge(defaults, get(@trading_key) || %{})
  end

  def put_trading(attrs) when is_map(attrs) do
    merged = Map.merge(get_trading(), stringify_keys(attrs))
    put(@trading_key, merged)
    merged
  end

  def get(key) when is_binary(key) do
    case Repo.get(Entry, key) do
      nil -> nil
      %Entry{value: value} -> value
    end
  end

  def put(key, value) when is_binary(key) and is_map(value) do
    case Repo.get(Entry, key) do
      nil ->
        %Entry{}
        |> Entry.changeset(%{key: key, value: value})
        |> Repo.insert()

      entry ->
        entry
        |> Entry.changeset(%{value: value})
        |> Repo.update()
    end
  end

  defp stringify_keys(map) do
    Map.new(map, fn
      {k, v} when is_atom(k) -> {Atom.to_string(k), v}
      {k, v} -> {to_string(k), v}
    end)
  end
end
