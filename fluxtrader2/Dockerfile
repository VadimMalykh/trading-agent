# fluxtrader2 CPU analysis image. Built and run by scripts/ft2.sh; never run on the host.
FROM python:3.11-slim-bookworm
WORKDIR /workspace/ft2
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/workspace/ft2
CMD ["python", "-m", "ft2", "smoke"]
