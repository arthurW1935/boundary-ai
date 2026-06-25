FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY api/pyproject.toml api/README.md /app/api/
COPY mcp_server/pyproject.toml mcp_server/README.md /app/mcp_server/
COPY api/src /app/api/src
COPY mcp_server/src /app/mcp_server/src
COPY mcp_server/sandbox/.gitkeep /app/mcp_server/sandbox/.gitkeep

RUN pip install --no-cache-dir -e /app/mcp_server -e /app/api

EXPOSE 8000

CMD ["uvicorn", "armoriq_api.main:app", "--host", "0.0.0.0", "--port", "8000", "--app-dir", "/app/api/src"]
