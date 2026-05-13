FROM python:3.12-slim

# System deps: tesseract for OCR fallback, fonts for PDF report generation
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-eng \
        libgl1 \
        libglib2.0-0 \
        fonts-dejavu-core \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first for better layer caching
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy app
COPY . .

# Persisted state lives under /app/data (mount this as a volume)
RUN mkdir -p /app/saved_wards /app/uploads /app/data \
    && chmod -R 755 /app

ENV EI_HOST=0.0.0.0 \
    EI_PORT=8080 \
    PORT=8080 \
    EI_DEBUG=0 \
    PYTHONUNBUFFERED=1

EXPOSE 8080

# Cloud Run handles health checks itself — no HEALTHCHECK needed.

# 1 worker + 4 threads is safe with NullPool (Supabase shared pooler).
CMD ["/bin/sh", "-c", "gunicorn wsgi:app --bind 0.0.0.0:${PORT:-8080} --workers 1 --threads 4 --timeout 300 --access-logfile - --error-logfile -"]
