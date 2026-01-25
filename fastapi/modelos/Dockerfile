# =============================================================================
# Dockerfile - API de Documentos Inteligente
# =============================================================================

FROM python:3.11-slim

WORKDIR /app

# Dependências do sistema
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Dependências Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia o código
COPY api_documento_inteligente.py .
COPY classificador_documentos.py .

# Cria diretórios
RUN mkdir -p /app/logs /data/sessions

# Porta
EXPOSE 8105

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8105/health || exit 1

# Comando
CMD ["python", "api_documento_inteligente.py"]
