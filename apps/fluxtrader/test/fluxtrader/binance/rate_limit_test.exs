defmodule FluxTrader.Binance.RateLimitTest do
  @moduledoc """
  The guard that keeps this node from extending a Binance IP ban (2026-10-13: two bans of
  2–4 hours each, extended by the collector's own retries) and from crossing the 2,400/min
  weight ceiling in the first place.
  """
  use ExUnit.Case, async: false

  alias FluxTrader.Binance.{Client, RateLimit}

  # 2026-10-13 07:26:00.000 UTC — a minute boundary, so the arithmetic below is exact.
  @t0 1_791_876_360_000

  setup do
    RateLimit.reset()
    :ok
  end

  test "the used weight is the exchange's header for the current minute and 0 once it rolls over" do
    assert RateLimit.used_weight(@t0) == 0
    RateLimit.observe(200, [{"x-mbx-used-weight-1m", "973"}], %{}, @t0 + 48_000)
    assert RateLimit.used_weight(@t0 + 59_000) == 973
    assert RateLimit.used_weight(@t0 + 60_000) == 0
  end

  test "reserve answers :ok under the cap and the time to the next minute over it" do
    RateLimit.observe(200, [{"x-mbx-used-weight-1m", "1985"}], %{}, @t0 + 30_000)
    assert RateLimit.reserve(10, 2_000, @t0 + 30_000) == :ok
    assert RateLimit.reserve(20, 2_000, @t0 + 30_000) == {:wait, 30_500}
    # The book's higher cap still has room when the tape's does not.
    assert RateLimit.reserve(20, 2_200, @t0 + 30_000) == :ok
    assert RateLimit.reserve(20, 2_000, @t0 + 60_000) == :ok
  end

  test "a 418 blocks every call until the ban's own epoch, and a shorter ban never shortens it" do
    body = %{"code" => -1003, "msg" => "Way too many requests; IP(1.2.3.4) banned until 1791877197998."}
    RateLimit.observe(418, [], body, @t0)
    assert RateLimit.blocked_until(@t0) == 1_791_877_197_998 + 1_000
    assert RateLimit.reserve(1, 2_400, @t0) == {:wait, 1_791_877_197_998 + 1_000 - @t0}
    assert RateLimit.blocked?(@t0 + 837_998)
    refute RateLimit.blocked?(@t0 + 839_000)

    RateLimit.observe(418, [], %{"msg" => "banned until 1791877000000"}, @t0 + 1_000)
    assert RateLimit.blocked_until(@t0 + 1_000) == 1_791_877_197_998 + 1_000
  end

  test "a 429 blocks until the minute rolls over, or for retry-after when the header is present" do
    RateLimit.observe(429, [], %{"code" => -1003, "msg" => "Too many requests"}, @t0 + 40_000)
    assert RateLimit.blocked_until(@t0 + 40_000) == @t0 + 60_500
    RateLimit.reset()
    RateLimit.observe(429, [{"retry-after", "120"}], "", @t0 + 40_000)
    assert RateLimit.blocked_until(@t0 + 40_000) == @t0 + 40_000 + 120_500
  end

  test "the client refuses a market call while blocked, without a request" do
    RateLimit.observe(418, [], %{"msg" => "banned until #{System.system_time(:millisecond) + 60_000}"})
    {us, result} = :timer.tc(fn -> Client.klines("BTCUSDT", "1m", limit: 1) end)
    assert result == {:error, :rate_limited}
    assert us < 100_000
  end
end
