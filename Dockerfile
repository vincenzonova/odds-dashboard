FROM python:3.11-slim

WORKDIR /app

# Install Python deps first (needed to run playwright install-deps)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Let Playwright install ALL its own system dependencies automatically
RUN playwright install-deps chromium

# Download the Chromium browser binary
RUN playwright install chromium

# Copy app source
COPY . .

EXPOSE 8000
ENV REFRESH_MINUTES=10
ENV MAX_MATCHES=40
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
