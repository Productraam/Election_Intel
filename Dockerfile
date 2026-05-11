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
    EI_PORT=5001 \
    EI_DEBUG=0 \
    PYTHONUNBUFFERED=1

EXPOSE 5001

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:5001/api/status || exit 1

# 2 workers, 4 threads per worker = 8 concurrent requests.
# Bump --workers on CPU-heavy hosts; OCR is CPU-bound.
CMD ["gunicorn", "wsgi:app", \
     "--bind", "0.0.0.0:5001", \
     "--workers", "2", \
     "--threads", "4", \
     "--timeout", "300", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
