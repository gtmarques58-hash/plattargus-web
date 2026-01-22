FROM python:3.11-slim

WORKDIR /app

COPY requirements_api.txt /app/requirements_api.txt
RUN pip install --no-cache-dir -r /app/requirements_api.txt

COPY app /app/app

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8000"]
