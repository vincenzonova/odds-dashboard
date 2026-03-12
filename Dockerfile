# ── Stage 1: Build ────────────────────────────────────────
FROM python:3.11-slim AS base

# Install system deps required by Playwright's Chromium
RUN apt-get update && apt-get install -y \
    wget curl gnupg ca-certificates \
    libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
    libxkbcommon0 libxcomposite1 libxdamage1 libxrandr2 \
    libgbm1 libasound2 libpangocairo-1.0-0 libpango-1.0-0 \
    libxss1 libxtst6 fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Chromium for Playwright
RUN playwright install chromium

# Copy app source
COPY . .

# ── Runtime ───────────────────────────────────────────────
EXPOSE 8000

# Environment defaults (override in Railway dashboard)
ENV REFRESH_MINUTES=10
ENV MAX_MATCHES=40

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
