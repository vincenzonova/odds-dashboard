# Official Playwright image: Chromium + all system deps pre-installed
FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app source
COPY . .

EXPOSE 8000
ENV REFRESH_MINUTES=10
ENV MAX_MATCHES=40
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
