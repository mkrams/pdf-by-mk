FROM python:3.11-slim

WORKDIR /app

# Install system deps for PyMuPDF + Docling (libxcb, OCR libs)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libxcb1 \
    libx11-6 \
    libxext6 \
    libxrender1 \
    libglib2.0-0 \
    libgl1 \
    libsm6 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

# Create upload directory
RUN mkdir -p /tmp/pdf_uploads

CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
