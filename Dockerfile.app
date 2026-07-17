FROM hexpm/elixir:1.16.3-erlang-26.2.5-debian-bookworm-20240612

RUN apt-get update -y && \
    apt-get install -y build-essential git inotify-tools && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

RUN mix local.hex --force && mix local.rebar --force

WORKDIR /app

COPY mix.exs ./
COPY config ./config
COPY apps ./apps

RUN mix deps.get

EXPOSE 4000
CMD ["mix", "phx.server"]
