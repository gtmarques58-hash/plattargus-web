#!/bin/bash
# =============================================================================
# PLATTARGUS-DETALHAR - Script de Setup
# =============================================================================
# Executa na primeira instalação para criar diretórios e configurar ambiente
# =============================================================================

set -e

echo "=============================================="
echo "  PLATTARGUS-DETALHAR - Setup"
echo "=============================================="

# Diretório base (onde está o plattargus-web)
BASE_DIR="/opt/plattargus-web"
DATA_DIR="$BASE_DIR/data"

# Verificar se está no lugar certo
if [ ! -d "$BASE_DIR/fastapi" ]; then
    echo "❌ ERRO: Diretório $BASE_DIR/fastapi não encontrado!"
    echo "   Execute este script de dentro de /opt/plattargus-web/plattargus-detalhar/"
    exit 1
fi

echo "📁 Criando estrutura de diretórios em $DATA_DIR..."

# Criar diretórios de dados
mkdir -p "$DATA_DIR/sessions"
mkdir -p "$DATA_DIR/detalhar"
mkdir -p "$DATA_DIR/sei_storage"
mkdir -p "$DATA_DIR/evidencias"
mkdir -p "$DATA_DIR/logs/worker"
mkdir -p "$DATA_DIR/logs/api"

# Permissões (importante para containers)
chmod -R 755 "$DATA_DIR"

echo "✅ Diretórios criados:"
echo "   $DATA_DIR/sessions      - Sessões Playwright"
echo "   $DATA_DIR/detalhar      - Cache de processos"
echo "   $DATA_DIR/sei_storage   - Storage SEI"
echo "   $DATA_DIR/evidencias    - Screenshots de assinatura"
echo "   $DATA_DIR/logs/         - Logs do serviço"

# Verificar scripts
SCRIPTS_DIR="$BASE_DIR/fastapi/scripts"
if [ -d "$SCRIPTS_DIR" ]; then
    SCRIPT_COUNT=$(ls -1 "$SCRIPTS_DIR"/*.py 2>/dev/null | wc -l)
    echo "✅ Scripts Playwright encontrados: $SCRIPT_COUNT arquivos"
else
    echo "⚠️  AVISO: Diretório de scripts não encontrado em $SCRIPTS_DIR"
fi

# Verificar .env
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        echo ""
        echo "⚠️  Arquivo .env não encontrado!"
        echo "   Copiando .env.example para .env..."
        cp .env.example .env
        echo "   IMPORTANTE: Edite .env e configure as chaves de API!"
    else
        echo "❌ ERRO: Nem .env nem .env.example encontrados!"
        exit 1
    fi
else
    echo "✅ Arquivo .env encontrado"
fi

# Verificar rede Docker
echo ""
echo "🔍 Verificando rede Docker..."
if docker network ls | grep -q "plattargus-web_plattargus"; then
    echo "✅ Rede plattargus-web_plattargus existe"
else
    echo "⚠️  Rede plattargus-web_plattargus não existe"
    echo "   Será criada automaticamente ao subir o compose principal"
fi

echo ""
echo "=============================================="
echo "  Setup concluído!"
echo "=============================================="
echo ""
echo "Próximos passos:"
echo ""
echo "1. Edite o .env com suas chaves de API:"
echo "   nano .env"
echo ""
echo "2. Suba o compose principal primeiro (se ainda não estiver rodando):"
echo "   cd $BASE_DIR && docker-compose up -d"
echo ""
echo "3. Depois suba o detalhar:"
echo "   cd $BASE_DIR/plattargus-detalhar"
echo "   docker-compose up -d --build"
echo ""
echo "4. Verifique os logs:"
echo "   docker-compose logs -f"
echo ""
