FROM python:3.13-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements (context = project root)
COPY services/calendar_sync/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy calendar sync module
COPY services/calendar_sync/ /app/services/calendar_sync/

# Copy agents integration module (needed for GoogleCalendarSync)
COPY agents/src/integrations/google_calendar /app/agents/src/integrations/google_calendar/

# Set Python path
ENV PYTHONPATH=/app

# Healthcheck (vérifie Redis key calendar:last_sync)
HEALTHCHECK --interval=5m --timeout=10s --start-period=2m --retries=3 \
    CMD python -c "import redis, os; r = redis.from_url(os.getenv('REDIS_URL')); assert r.get('calendar:last_sync')"

# Run worker
CMD ["python", "-m", "services.calendar_sync.main"]
