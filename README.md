# 🔥 PlattArgus - Backend Laravel

Sistema de automação inteligente do SEI para o CBMAC.

**URL de Produção:** https://plattargus.gt2m58.cloud

## 📋 Requisitos

- PHP 8.2+
- PostgreSQL 15+
- Redis 7+
- Composer 2+
- Docker (opcional, recomendado)

## 🚀 Instalação Rápida (Docker)

```bash
# Clone o repositório
git clone https://github.com/seu-usuario/plattargus.git
cd plattargus

# Copie o .env
cp .env.example .env

# Gere a APP_KEY do Laravel
docker compose run --rm app php artisan key:generate

# Gere a ARGUS_MASTER_KEY (criptografia SEI)
docker compose run --rm app php artisan plattargus:generate-master-key

# Suba os containers
docker compose up -d

# Execute as migrations
docker compose exec app php artisan migrate

# Execute os seeders (cria usuário admin)
docker compose exec app php artisan db:seed

# Pronto! Acesse http://localhost:8080
```

## 🌐 Deploy em Produção (plattargus.gt2m58.cloud)

### Passo 1: Preparar o servidor

```bash
# Instalar dependências
sudo apt update
sudo apt install -y nginx php8.3-fpm php8.3-pgsql php8.3-redis php8.3-mbstring php8.3-xml php8.3-curl php8.3-zip postgresql redis-server

# Criar banco de dados
sudo -u postgres psql -c "CREATE USER plattargus WITH PASSWORD 'sua_senha_segura';"
sudo -u postgres psql -c "CREATE DATABASE plattargus OWNER plattargus;"
```

### Passo 2: Clonar e configurar

```bash
cd /var/www
sudo git clone https://github.com/seu-usuario/plattargus.git
cd plattargus

# Configurar permissões
sudo chown -R www-data:www-data storage bootstrap/cache
sudo chmod -R 775 storage bootstrap/cache

# Instalar dependências
composer install --no-dev --optimize-autoloader

# Configurar .env
cp .env.example .env
nano .env  # Configure DB_PASSWORD, ARGUS_MASTER_KEY, etc.

# Gerar chaves
php artisan key:generate
php artisan plattargus:generate-master-key

# Executar migrations
php artisan migrate --force
php artisan db:seed --force
```

### Passo 3: Configurar Nginx + SSL

```bash
# Copiar configuração
sudo cp docker/nginx/plattargus-nginx.conf /etc/nginx/sites-available/plattargus.gt2m58.cloud
sudo ln -s /etc/nginx/sites-available/plattargus.gt2m58.cloud /etc/nginx/sites-enabled/

# Obter certificado SSL
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d plattargus.gt2m58.cloud

# Reiniciar nginx
sudo nginx -t && sudo systemctl reload nginx
```

### Passo 4: Configurar serviços

```bash
# Queue worker (supervisor)
sudo nano /etc/supervisor/conf.d/plattargus-worker.conf
```

```ini
[program:plattargus-worker]
process_name=%(program_name)s_%(process_num)02d
command=php /var/www/plattargus/artisan queue:work redis --sleep=3 --tries=3 --max-time=3600
autostart=true
autorestart=true
user=www-data
numprocs=2
redirect_stderr=true
stdout_logfile=/var/log/plattargus-worker.log
```

```bash
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl start plattargus-worker:*
```

### Passo 5: Cron para tarefas agendadas

```bash
# Adicionar ao crontab
(crontab -l 2>/dev/null; echo "* * * * * cd /var/www/plattargus && php artisan schedule:run >> /dev/null 2>&1") | crontab -
```

## 🔧 Instalação Manual

```bash
# Instale dependências
composer install

# Copie e configure o .env
cp .env.example .env
php artisan key:generate
php artisan plattargus:generate-master-key

# Configure o banco de dados no .env
# DB_CONNECTION=pgsql
# DB_HOST=127.0.0.1
# DB_PORT=5432
# DB_DATABASE=plattargus
# DB_USERNAME=seu_usuario
# DB_PASSWORD=sua_senha

# Execute migrations
php artisan migrate

# Execute seeders
php artisan db:seed

# Inicie o servidor
php artisan serve
```

## 🔐 Configuração de Segurança

### ARGUS_MASTER_KEY

Esta chave é usada para criptografar as senhas do SEI. **NUNCA** a exponha!

```bash
# Gerar nova chave
php artisan plattargus:generate-master-key

# Adicione ao .env
ARGUS_MASTER_KEY=sua_chave_de_64_caracteres_hex
```

### PLATT_ENGINE_SECRET

Chave para comunicação segura entre Laravel e FastAPI (Engine).

```bash
# Gere uma chave aleatória
openssl rand -hex 32

# Adicione ao .env
PLATT_ENGINE_SECRET=sua_chave_hmac
```

## 📡 API Endpoints

### Autenticação

| Método | Rota | Descrição |
|--------|------|-----------|
| POST | `/api/auth/login` | Login do usuário |
| POST | `/api/auth/primeiro-acesso` | Define senha no primeiro acesso |
| POST | `/api/auth/logout` | Logout |
| GET | `/api/auth/me` | Dados do usuário logado |

### Credenciais SEI

| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/api/credencial/status` | Verifica se tem credencial |
| POST | `/api/credencial/vincular` | Cadastra credencial SEI |
| PUT | `/api/credencial/senha` | Atualiza senha SEI |
| DELETE | `/api/credencial` | Remove credencial |

### Step-Up (Ações Críticas)

| Método | Rota | Descrição |
|--------|------|-----------|
| POST | `/api/step-up/grant` | Solicita autorização |
| POST | `/api/step-up/verify` | Verifica autorização |

### Processos

| Método | Rota | Descrição |
|--------|------|-----------|
| POST | `/api/processos/analisar` | Analisa processo |
| POST | `/api/processos/gerar-documento` | Gera documento |
| POST | `/api/processos/assinar` | Assina documento (requer step-up) |
| POST | `/api/processos/chat` | Chat analítico |

## 🏗️ Arquitetura

```
┌─────────────────────────────────────────────────────────────┐
│                      NGINX (Proxy)                          │
└─────────────────────────┬───────────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────────┐
│                    LARAVEL (API)                            │
│  • Autenticação (Sanctum)                                   │
│  • Credenciais SEI (AES-256-GCM)                           │
│  • Step-up (Redis)                                          │
│  • Auditoria                                                │
└─────────────────────────┬───────────────────────────────────┘
                          │ HMAC
┌─────────────────────────▼───────────────────────────────────┐
│                  FASTAPI (Engine)                           │
│  • Playwright (SEI)                                         │
│  • OCR/PDF                                                  │
│  • RAG/ChromaDB                                             │
│  • IA (OpenAI)                                              │
└─────────────────────────────────────────────────────────────┘
```

## 👤 Usuário Admin Padrão

Após executar os seeders:

- **Usuário:** `admin`
- **Senha:** `admin123`

⚠️ **TROQUE A SENHA EM PRODUÇÃO!**

## 📄 Licença

Proprietário - CBMAC / PlattArgus

## 🤝 Suporte

Entre em contato com a equipe de desenvolvimento.
