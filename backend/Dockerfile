FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/workspace
WORKDIR /workspace
COPY backend/requirements.txt /workspace/requirements.txt
RUN pip install --no-cache-dir -r /workspace/requirements.txt
COPY backend/__init__.py /workspace/backend/__init__.py
COPY backend/app /workspace/backend/app
COPY backend/scripts /workspace/backend/scripts
COPY backend/migrations /workspace/backend/migrations
COPY backend/owner_console /workspace/backend/owner_console
COPY backend/alembic.ini /workspace/backend/alembic.ini
COPY frontend /workspace/frontend
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /workspace
USER appuser
EXPOSE 8000
CMD ["sh", "-c", "cd /workspace/backend && alembic upgrade head && cd /workspace && uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --workers 1 --proxy-headers --forwarded-allow-ips '*'"]
