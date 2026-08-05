FROM hexpm/elixir:1.16.3-erlang-26.2.5-debian-bookworm-20240612

RUN apt-get update -y && \
    apt-get install -y build-essential git inotify-tools && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

RUN mix local.hex --force && mix local.rebar --force

WORKDIR /app

ENV MIX_ENV=dev

# Fetch + compile dependencies at build time so the runtime host never has to.
# The compile of native/rebar deps (gun, cowlib) is memory-heavy and OOM-kills
# small always-on instances when done at boot; doing it here moves that cost to
# image-build time. Copying mix.lock first also lets deps.get run fully offline
# at runtime (pinned versions already resolved).
COPY mix.exs mix.lock ./
COPY config ./config
COPY apps/fluxtrader/mix.exs ./apps/fluxtrader/mix.exs
COPY apps/fluxtrader_web/mix.exs ./apps/fluxtrader_web/mix.exs

RUN mix deps.get && mix deps.compile

# Bring in the rest of the source and precompile the umbrella apps too, so the
# named `app_build` / `app_deps` volumes seed from fully-compiled artifacts.
COPY apps ./apps
RUN mix compile

EXPOSE 4000
CMD ["mix", "phx.server"]
