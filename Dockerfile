# Official Playwright image: Chromium + all system deps pre-installed
FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy

WORKDIR /app

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Install Python dependencies
COPY pyproject.toml .
RUN uv pip install --system --no-cache .

# Install Playwright Chromium
RUN playwright install --with-deps chromium

# Copy app source
COPY . .

EXPOSE 8000
ENV REFRESH_MINUTES=10
ENV MAX_MATCHES=160
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
