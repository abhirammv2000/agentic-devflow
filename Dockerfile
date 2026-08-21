FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app

RUN apt-get update \
 && apt-get install -y --no-install-recommends git \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY mcp_servers ./mcp_servers
COPY orchestrator ./orchestrator
COPY scripts ./scripts
COPY sandbox ./sandbox

EXPOSE 8088
CMD ["uvicorn", "orchestrator.app:app", "--host", "0.0.0.0", "--port", "8088"]
