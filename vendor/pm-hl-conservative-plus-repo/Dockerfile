FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash ca-certificates curl && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chmod +x scripts/*.sh scripts/*.py

ENV PYTHONUNBUFFERED=1

CMD ["bash", "-lc", "./scripts/pm_stack.sh up && uvicorn src.health_api:app --host 0.0.0.0 --port 8080"]
