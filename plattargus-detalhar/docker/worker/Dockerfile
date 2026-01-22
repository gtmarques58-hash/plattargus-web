FROM mcr.microsoft.com/playwright/python:v1.49.1-jammy

WORKDIR /app

# OCR
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr tesseract-ocr-por \
    && rm -rf /var/lib/apt/lists/*

COPY requirements_worker.txt /app/requirements_worker.txt
RUN pip install --no-cache-dir -r /app/requirements_worker.txt

COPY app /app/app

# Scripts vêm via volume, não precisa copiar

ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "app.worker"]
