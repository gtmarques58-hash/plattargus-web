# PlattArgus - Arquitetura de Produção
**Última atualização:** 2026-01-20

## 🌐 FLUXO DE REQUISIÇÕES (PRODUÇÃO)
```
Internet → Nginx Externo (443) → Laravel (8081) → FastAPI (8002) → SEI Runner
                                     ↓
                              PostgreSQL (credenciais)
```

## 📦 CONTAINERS E PORTAS

| Container | Porta Externa | Porta Interna | Função |
|-----------|---------------|---------------|--------|
| plattargus-nginx | 8081 | 80 | Nginx do Laravel |
| plattargus-app | - | 9000 | PHP-FPM Laravel |
| plattargus-api-1 | 8002 | 8000 | FastAPI (IA) |
| plattargus-web-1 | 3002 | 80 | Frontend HTML (não usado em prod) |
| plattargus-db | 5433 | 5432 | PostgreSQL |
| plattargus-redis | 6380 | 6379 | Redis |
| plattargus-runner-1 | - | 8001 | SEI Runner |

## 🔐 FLUXO DE AUTENTICAÇÃO E CREDENCIAIS
```
1. Frontend → POST /api/auth/login → Laravel (Sanctum token)
2. Frontend → POST /api/processos/analisar (com cookie/token)
3. Laravel ProcessoController::analisar()
   → Valida autenticação (auth:sanctum)
   → PlattEngineService::analisarProcesso($user)
   → User::getCredencialSei()
   → CredentialVaultService::decrypt() [AES-256-GCM]
   → FastAPI /api/v2/analisar-processo (senha descriptografada)
```

## 📁 ARQUIVOS IMPORTANTES

### Laravel
- `/opt/plattargus-web/app/Http/Controllers/ProcessoController.php` - Controller principal
- `/opt/plattargus-web/app/Services/PlattEngineService.php` - Chama FastAPI
- `/opt/plattargus-web/app/Services/CredentialVaultService.php` - Descriptografa AES-256-GCM
- `/opt/plattargus-web/app/Models/User.php` - getCredencialSei()
- `/opt/plattargus-web/routes/api.php` - Rotas da API

### FastAPI
- `/opt/plattargus-web/fastapi/api.py` - API principal
- `/opt/plattargus-web/fastapi/laravel_integration.py` - Endpoints de integração
- `/opt/plattargus-web/fastapi/.env` - Variáveis (OPENAI_API_KEY, ARGUS_MASTER_KEY)

### Nginx
- `/etc/nginx/sites-enabled/plattargus.gt2m58.cloud.conf` - Nginx externo (SSL)
- `/opt/plattargus-web/docker/nginx/default.conf` - Nginx Laravel interno
- `/opt/plattargus-web/docker/nginx/frontend.conf` - Nginx frontend (não usado)

## 🔑 VARIÁVEIS DE AMBIENTE

### Laravel (.env)
- `ARGUS_MASTER_KEY` - Chave AES-256 para descriptografar senhas SEI
- `DB_*` - Conexão PostgreSQL

### FastAPI (.env)
- `OPENAI_API_KEY` - API OpenAI
- `ARGUS_MASTER_KEY` - Mesma chave do Laravel
- `DB_*` - Conexão PostgreSQL (se usar endpoint direto)

## 🗄️ BANCO DE DADOS

### Tabela users (credenciais SEI)
```sql
SELECT usuario_sei, sei_orgao_id, sei_cargo, sei_credencial_ativa,
       sei_senha_cipher, sei_senha_iv, sei_senha_tag
FROM users WHERE ativo = true;
```

## 🚀 COMANDOS ÚTEIS
```bash
# Ver logs Laravel
docker exec plattargus-app tail -50 /var/www/storage/logs/laravel.log

# Ver logs FastAPI
docker logs plattargus-api-1 --tail 50

# Reiniciar containers
docker restart plattargus-app plattargus-api-1 plattargus-nginx

# Testar endpoint autenticado (via curl)
curl -s http://localhost:8081/api/auth/me -H "Accept: application/json"

# Ver rotas Laravel
docker exec plattargus-app php artisan route:list --path=processos
```

## ⚠️ DECISÕES DE ARQUITETURA

1. **Frontend vai pelo Laravel (não FastAPI direto)**
   - Motivo: Segurança, autenticação Sanctum, auditoria
   
2. **Credenciais descriptografadas no Laravel**
   - Motivo: Chave mestra fica só no backend PHP
   
3. **FastAPI recebe senha já descriptografada**
   - Motivo: Separação de responsabilidades

## 🐛 PROBLEMAS COMUNS

| Erro | Causa | Solução |
|------|-------|---------|
| 500 Internal Server | Credencial não encontrada | Verificar se usuário tem credencial SEI |
| 404 Not Found | Rota não existe | Verificar nginx externo |
| Unauthenticated | Token expirado | Fazer login novamente |
| Erro descriptografia | Chave incorreta | Verificar ARGUS_MASTER_KEY |
