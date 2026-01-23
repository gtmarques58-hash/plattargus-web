# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

PlattArgus is an intelligent SEI (Sistema Eletrônico de Informações) automation platform for CBMAC. It consists of:
- **Laravel API** (PHP 8.2+): Authentication, credential management, audit logging
- **FastAPI Engine** (Python 3.11+): Playwright browser automation, LLM integration (OpenAI/Claude)
- **Detalhar Service**: Async job processor for long-running SEI operations

## Common Commands

### Laravel (PHP)

```bash
# Run tests
php artisan test
docker compose exec app php artisan test

# Lint/format code
composer pint
composer pint --test  # check only

# Run migrations
php artisan migrate

# Clear caches
php artisan cache:clear && php artisan config:clear && php artisan route:clear

# View routes
php artisan route:list --path=processos

# Generate master key for credential encryption
php artisan plattargus:generate-master-key
```

### Docker

```bash
# Start all services
docker compose up -d

# View Laravel logs
docker exec plattargus-app tail -50 /var/www/storage/logs/laravel.log

# View FastAPI logs
docker logs plattargus-api-1 --tail 50

# Restart services
docker restart plattargus-app plattargus-api-1 plattargus-nginx
```

### Detalhar Service

```bash
cd plattargus-detalhar
docker-compose up -d --build
docker-compose logs -f
curl http://localhost:8103/health
```

## Architecture

```
Internet → Nginx (SSL/443) → Laravel (8081) → FastAPI (8002) → SEI Runner
                                  ↓
                            PostgreSQL + Redis
```

### Request Flow

1. Frontend sends request to Laravel with Sanctum token
2. Laravel validates auth, retrieves encrypted SEI credentials
3. `CredentialVaultService` decrypts credentials (AES-256-GCM using `ARGUS_MASTER_KEY`)
4. `PlattEngineService` calls FastAPI with HMAC-signed request (`PLATT_ENGINE_SECRET`)
5. FastAPI executes Playwright automation or LLM processing
6. Response flows back through the chain

### Key Services

| Service | Port | Purpose |
|---------|------|---------|
| plattargus-app | 9000 (PHP-FPM) | Laravel API |
| plattargus-nginx | 8081 | Nginx reverse proxy |
| plattargus-api-1 | 8002 | FastAPI (AI/automation) |
| plattargus-db | 5433 | PostgreSQL |
| plattargus-redis | 6380 | Redis (cache, queues, step-up) |
| plattargus-runner-1 | 8001 (interno) | Runner (Playwright/SEI automation) |
| plattargus-detalhar-api | 8103 | Async job API (Detalhar) |

### Key Files

**Laravel:**
- `app/Http/Controllers/ProcessoController.php` - Main process controller
- `app/Services/PlattEngineService.php` - FastAPI communication
- `app/Services/CredentialVaultService.php` - AES-256-GCM encryption/decryption
- `routes/api.php` - API route definitions

**FastAPI:**
- `fastapi/api.py` - Main API entry point
- `fastapi/laravel_integration.py` - Laravel integration endpoints

**Detalhar:**
- `plattargus-detalhar/app/api.py` - Job submission API
- `plattargus-detalhar/app/worker.py` - Redis queue consumer
- `plattargus-detalhar/app/pipeline_v2/` - LLM analysis pipeline

## Security Model

- **Authentication**: Laravel Sanctum (token-based)
- **Step-up Auth**: Redis-based elevated privilege for critical actions (signing documents)
- **Credential Storage**: SEI passwords encrypted with AES-256-GCM (`sei_senha_cipher`, `sei_senha_iv`, `sei_senha_tag` columns)
- **Inter-service**: HMAC-SHA256 signing between Laravel and FastAPI

## Environment Variables

Critical variables in `.env`:
- `ARGUS_MASTER_KEY` - 64-char hex key for credential encryption (must match in Laravel and FastAPI)
- `PLATT_ENGINE_SECRET` - HMAC key for Laravel↔FastAPI communication
- `OPENAI_API_KEY` / `ARGUS_API_KEY` (Claude) - LLM API keys

## Multi-tenancy

Uses `stancl/tenancy` for multi-tenant support. Tenant configuration in `config/tenancy.php`.

## Permissions

Uses `spatie/laravel-permission`. Permission configuration in `config/permission.php`.

## System Isolation (IMPORTANTE)

Existem **dois sistemas completamente isolados** neste servidor. NUNCA misturar:

### Sistema Web PlattArgus (`/opt/plattargus-web/`)
- Este repositório
- Container: `plattargus-detalhar-api` na porta **8103**
- Redes Docker: `plattargus`
- Todos os containers com prefixo `plattargus-*`

### Sistema n8n/Telegram (ISOLADO - NÃO MEXER)
- Localização: `/root/secretario-sei/` e `/root/detalhar-service/`
- Container: `detalhar-api` na porta **8101**
- Redes Docker: `detalhar-net`, `secretario-net`
- Containers: `detalhar-*`, `secretario-sei-*`

**Regras:**
- NUNCA alterar arquivos em `/root/secretario-sei/` ou `/root/detalhar-service/`
- NUNCA referenciar `detalhar-api:8101` no sistema web (usar `plattargus-detalhar-api:8103`)
- NUNCA conectar containers do PlattArgus às redes `detalhar-net` ou `secretario-net`
- Os dois sistemas compartilham apenas o Runner (volume `/root/secretario-sei/data` montado read-only)
