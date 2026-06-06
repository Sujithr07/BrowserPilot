# Shared image for the API and the worker. Based on Playwright's image so
# Chromium + all its system libs are preinstalled (the worker drives a real
# headless browser).
FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && python -m playwright install chromium

COPY . .

# Default command runs the API; docker-compose overrides it for the worker.
EXPOSE 8000
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
