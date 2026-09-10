defmodule FluxTrader.Binance.AuthTest do
  use ExUnit.Case, async: true

  alias FluxTrader.Binance.Auth

  # The payload shape from Binance's API documentation, signed by an INDEPENDENT
  # implementation — `openssl dgst -sha256 -hmac <secret>` — so that a bug in how the
  # payload reaches `:crypto` cannot agree with itself. Verified 2026-09-10 in the app
  # container. A wrong signature is rejected by the exchange with -1022 on every order.
  @secret "NhqPtmdSJYdKjVHjA7PZj4Nge3eKSiZbA1aHsQkD1cYSyBlfG0vBAAcbP1Z3HnmR"
  @payload "symbol=LTCBTC&side=BUY&type=LIMIT&timeInForce=GTC&quantity=1&price=0.1&recvWindow=5000&timestamp=1499827319559"
  @signature "49015ab10eec39b7208c2712f263a5c23a494c6ce9535dd1aea7189c107215aa"

  test "signs the documented payload exactly as openssl does" do
    assert Auth.sign(@secret, @payload) == @signature
  end

  test "a signed payload appends recvWindow, timestamp and the signature, in that order" do
    payload = Auth.signed_payload([symbol: "BTCUSDT", orderId: 42], "s3cret", 1_700_000_000_000)

    # openssl: echo -n "symbol=BTCUSDT&orderId=42&recvWindow=5000&timestamp=1700000000000" \
    #   | openssl dgst -sha256 -hmac s3cret
    assert payload ==
             "symbol=BTCUSDT&orderId=42&recvWindow=5000&timestamp=1700000000000&signature=" <>
               "c51cd4f1a7e80c09d5825c57d0b85071d2bb1199ba8fb8e3ed08dcc7aa014634"
  end

  test "nil parameters are dropped, booleans and floats render as Binance expects" do
    payload = Auth.signed_payload([symbol: "BTCUSDT", reduceOnly: true, stopPrice: nil, quantity: 0.008], "s", 1)
    assert String.starts_with?(payload, "symbol=BTCUSDT&reduceOnly=true&quantity=0.008&")
    refute payload =~ "stopPrice"
  end
end
