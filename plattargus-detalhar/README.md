# 🚀 PLATTARGUS-DETALHAR

**Serviço isolado para operações SEI de longa duração**

## 📋 Visão Geral

```
┌─────────────────────────────────────────────────────────────────┐
│                    ARQUITETURA                                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  PLATTARGUS-WEB (Laravel/FastAPI)                              │
│         │                                                       │
│         │ POST /jobs                                           │
│         ▼                                                       │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │           PLATTARGUS-DETALHAR (Este serviço)            │   │
│  │                                                          │   │
│  │   ┌─────────┐     ┌─────────┐     ┌─────────────────┐   │   │
│  │   │  API    │────▶│  REDIS  │────▶│     WORKER      │   │   │
│  │   │ :8101   │     │  Fila   │     │   Playwright    │   │   │
│  │   └─────────┘     └─────────┘     │   + LLM v2      │   │   │
│  │                                    └─────────────────┘   │   │
│  │   ┌─────────────┐                                        │   │
│  │   │  POSTGRES   │  Cache de processos + Jobs            │   │
│  │   └─────────────┘                                        │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## 📁 Estrutura de Diretórios

```
/opt/plattargus-web/
├── fastapi/
│   └── scripts/              ← Scripts Playwright (compartilhado)
├── data/                     ← ★ Criado pelo setup.sh
│   ├── sessions/             ← Sessões Playwright
│   ├── detalhar/             ← Cache de processos
│   ├── sei_storage/          ← Storage SEI
│   ├── evidencias/           ← Screenshots
│   └── logs/                 ← Logs do serviço
│
└── plattargus-detalhar/      ← Este serviço
    ├── app/
    │   ├── api.py            ← FastAPI
    │   ├── worker.py         ← Consumer Redis
    │   └── pipeline_v2/      ← Análise com LLM
    ├── docker/
    ├── sql/
    ├── docker-compose.yml
    ├── .env
    └── setup.sh
```

## 🚀 Instalação

### 1. Copiar para o servidor

```bash
# No servidor
cd /opt/plattargus-web
mkdir -p plattargus-detalhar
cd plattargus-detalhar

# Extrair o zip (ou copiar os arquivos)
unzip plattargus-detalhar.zip -d .
```

### 2. Executar setup

```bash
chmod +x setup.sh
./setup.sh
```

### 3. Configurar .env

```bash
nano .env
```

Ajuste as chaves:
- `ARGUS_API_KEY` - Sua chave Anthropic
- `OPENAI_API_KEY` - Sua chave OpenAI
- `ARGUS_MASTER_KEY` - Mesma do Laravel

### 4. Subir os containers

```bash
# Primeiro, certifique-se que o compose principal está rodando
cd /opt/plattargus-web
docker-compose up -d

# Depois, suba o detalhar
cd plattargus-detalhar
docker-compose up -d --build
```

### 5. Verificar

```bash
# Ver status
docker-compose ps

# Ver logs
docker-compose logs -f

# Testar API
curl http://localhost:8101/health
```

## 🔌 Endpoints

### `POST /jobs` - Criar job
```json
{
  "nup": "0609.000000.00000/2025-00",
  "modo": "detalhar",
  "credenciais": {
    "usuario": "...",
    "senha_enc": "...",
    "orgao_id": 1
  },
  "prioridade": "hi"
}
```

### `GET /jobs/{job_id}` - Status do job
```json
{
  "job_id": "abc123",
  "status": "processing",
  "progress": 45,
  "message": "Extraindo documentos..."
}
```

### `GET /jobs/{job_id}/result` - Resultado
```json
{
  "job_id": "abc123",
  "status": "done",
  "resultado": {
    "resumo": "...",
    "analise": {...}
  }
}
```

### `GET /cache/{nup}` - Buscar cache
Retorna análise do cache se existir.

### `GET /health` - Health check
```json
{
  "status": "healthy",
  "redis": "ok",
  "postgres": "ok"
}
```

## 📊 Monitoramento

### Logs
```bash
# API
docker logs -f detalhar-api

# Worker
docker logs -f detalhar-worker
```

### Métricas Redis
```bash
docker exec -it detalhar-redis redis-cli info
```

### Jobs na fila
```bash
docker exec -it detalhar-redis redis-cli XLEN detalhar:hi
docker exec -it detalhar-redis redis-cli XLEN detalhar:lo
```

## 🔧 Comandos Úteis

```bash
# Restart worker (se travar)
docker-compose restart detalhar-worker

# Rebuild após mudanças
docker-compose up -d --build

# Ver uso de recursos
docker stats

# Limpar cache Redis
docker exec -it detalhar-redis redis-cli FLUSHDB

# Acessar banco
docker exec -it detalhar-postgres psql -U argus -d argus_detalhar
```

## ⚠️ Troubleshooting

### Worker trava
```bash
docker-compose restart detalhar-worker
```

### Memória alta
```bash
# Verificar
docker stats detalhar-worker

# Se necessário, ajustar limite no docker-compose.yml
```

### Redis cheio
```bash
# Limpar filas antigas
docker exec -it detalhar-redis redis-cli FLUSHDB
```

### Erro de conexão com rede principal
```bash
# Verificar se a rede existe
docker network ls | grep plattargus

# Se não existir, subir compose principal primeiro
cd /opt/plattargus-web
docker-compose up -d
```

## 📈 Escala para 1000 Usuários

Este serviço foi dimensionado para:
- **Worker**: 2 CPUs, 8GB RAM
- **Redis**: 512MB (LRU eviction)
- **Postgres**: Cache persistente

Para escalar mais:
```yaml
# docker-compose.yml
detalhar-worker:
  deploy:
    replicas: 2  # Adicionar mais workers
```

---

**Versão:** 2.0 (pipeline_v2 com LLM)  
**Data:** Janeiro 2026
