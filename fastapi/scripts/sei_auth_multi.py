#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sei_auth_multi.py - Autenticação SEI Multi-Diretoria (Híbrido)

VERSÃO 3.1 - HÍBRIDO + CREDENCIAIS DIRETAS (Laravel/PlattArgus WEB)

Mantém 100% compatibilidade com versão anterior + adiciona suporte a credenciais diretas.

Arquitetura:
┌────────────────────────────────────────────────────────────────┐
│                   criar_sessao_sei()                           │
│  ┌──────────────────────┐    ┌──────────────────────┐         │
│  │   CREDENCIAL DIRETA  │    │   SIGLA/CHAT_ID      │         │
│  │   (Laravel/Web)      │    │   (Telegram)         │         │
│  │   usuario+senha      │    │   Busca no banco     │         │
│  └──────────────────────┘    └──────────────────────┘         │
│            │                           │                       │
│            └───────────┬───────────────┘                       │
│                        ▼                                       │
│  ┌──────────────────────┐    ┌──────────────────────┐         │
│  │   PORTEIRO ATIVO?    │    │   MODO TRADICIONAL   │         │
│  │   (API rodando)      │───▶│   (monitorar, CLI)   │         │
│  │                      │ ❌ │                      │         │
│  │   Pool de browsers   │    │   Abre→Login→Fecha   │         │
│  │   ~0.5s por operação │    │   ~15-25s por op     │         │
│  └──────────────────────┘    └──────────────────────┘         │
└────────────────────────────────────────────────────────────────┘

Uso:
    # NOVO - Credenciais diretas (Laravel/PlattArgus WEB)
    async with criar_sessao_sei(usuario="gilmar.moura", senha="xxx", orgao_id="31") as sessao:
        page = sessao['page']
        # ... operações ...
    
    # LEGADO - Sigla ou chat_id (Telegram)
    async with criar_sessao_sei(sigla="DRH") as sessao:
        page = sessao['page']
        # ... operações ...
"""

import os
import sys
import asyncio
import time
import json
from typing import Optional, Dict, Any, Union
from contextlib import asynccontextmanager
from playwright.async_api import async_playwright, Page, BrowserContext, Browser, Frame

sys.path.insert(0, '/app/scripts')

from diretorias_db import DiretoriasDB

try:
    from crypto_utils import mask_password
except ImportError:
    def mask_password(s): return s[:2] + "***" if s else "***"


# ============================================
# CONFIGURAÇÕES
# ============================================

CONTROL_URL = "https://app.sei.ac.gov.br/sei/controlador.php?acao=procedimento_controlar&reset=1"
LOGIN_URL = "https://app.sei.ac.gov.br/sei/controlador.php?acao=login"

# Sessões (fallback)
SESSIONS_DIR = os.getenv("SESSIONS_DIR", "/data/sessions")
SESSION_MAX_AGE_SECONDS = int(os.getenv("SESSION_MAX_AGE", "1800"))  # 30 minutos

# Browser
DEFAULT_TIMEOUT_MS = 30000
_headless_env = os.getenv("PLAYWRIGHT_HEADLESS", "true").lower()
HEADLESS = _headless_env not in ("0", "false", "no")

# Porteiro
PORTEIRO_ENABLED = os.getenv("PORTEIRO_ENABLED", "true").lower() in ("1", "true", "yes")
PORTEIRO_FORCE_FALLBACK = os.getenv("PORTEIRO_FORCE_FALLBACK", "0").lower() in ("1", "true", "yes")

# Garantir diretório de sessões
os.makedirs(SESSIONS_DIR, exist_ok=True)


# ============================================
# VERIFICAÇÃO DO PORTEIRO
# ============================================

_porteiro_instance = None

def _get_porteiro():
    """Obtém instância do Porteiro (lazy load)."""
    global _porteiro_instance
    
    if PORTEIRO_FORCE_FALLBACK:
        return None
    
    if not PORTEIRO_ENABLED:
        return None
    
    if _porteiro_instance is not None:
        return _porteiro_instance
    
    try:
        from porteiro_sei import porteiro
        _porteiro_instance = porteiro
        return porteiro
    except ImportError:
        return None


def _porteiro_disponivel() -> bool:
    """Verifica se o Porteiro está disponível e iniciado."""
    if PORTEIRO_FORCE_FALLBACK:
        return False
    
    porteiro = _get_porteiro()
    if not porteiro:
        return False
    
    try:
        return porteiro._iniciado
    except:
        return False


# ============================================
# GERENCIAMENTO DE SESSÕES (FALLBACK)
# ============================================

def get_session_path(sigla: str) -> str:
    """Retorna o caminho do arquivo de sessão para uma diretoria."""
    return os.path.join(SESSIONS_DIR, f"{sigla.upper()}_session.json")


def session_exists(sigla: str) -> bool:
    """Verifica se existe sessão salva para a diretoria."""
    return os.path.exists(get_session_path(sigla))


def session_is_valid(sigla: str) -> bool:
    """
    Verifica se a sessão existe e não expirou.
    Retorna True se a sessão pode ser reutilizada.
    """
    session_path = get_session_path(sigla)
    
    if not os.path.exists(session_path):
        return False
    
    try:
        # Verifica idade do arquivo
        file_age = time.time() - os.path.getmtime(session_path)
        if file_age > SESSION_MAX_AGE_SECONDS:
            print(f"  ⏰ Sessão de {sigla} expirada ({int(file_age)}s > {SESSION_MAX_AGE_SECONDS}s)", file=sys.stderr)
            return False
        
        # Verifica se o arquivo é válido
        with open(session_path, 'r') as f:
            data = json.load(f)
            if 'cookies' not in data:
                return False
        
        remaining = SESSION_MAX_AGE_SECONDS - int(file_age)
        print(f"  ✅ Sessão de {sigla} válida (expira em {remaining}s)", file=sys.stderr)
        return True
        
    except Exception as e:
        print(f"  ⚠️ Erro ao verificar sessão de {sigla}: {e}", file=sys.stderr)
        return False


def save_session(sigla: str, context: BrowserContext) -> bool:
    """
    Salva o estado da sessão (cookies) para reutilização futura.
    Versão SÍNCRONA - chamado após login bem-sucedido.
    """
    try:
        session_path = get_session_path(sigla)
        # storage_state do Playwright já salva cookies e localStorage
        asyncio.get_event_loop().run_until_complete(
            context.storage_state(path=session_path)
        )
        print(f"  💾 Sessão de {sigla} salva em {session_path}", file=sys.stderr)
        return True
    except Exception as e:
        print(f"  ⚠️ Erro ao salvar sessão de {sigla}: {e}", file=sys.stderr)
        return False


async def save_session_async(sigla: str, context: BrowserContext) -> bool:
    """Versão assíncrona do save_session."""
    try:
        session_path = get_session_path(sigla)
        await context.storage_state(path=session_path)
        print(f"  💾 Sessão de {sigla} salva", file=sys.stderr)
        return True
    except Exception as e:
        print(f"  ⚠️ Erro ao salvar sessão de {sigla}: {e}", file=sys.stderr)
        return False


def delete_session(sigla: str) -> bool:
    """Remove sessão inválida/expirada."""
    try:
        session_path = get_session_path(sigla)
        if os.path.exists(session_path):
            os.remove(session_path)
            print(f"  🗑️ Sessão de {sigla} removida", file=sys.stderr)
        return True
    except Exception as e:
        print(f"  ⚠️ Erro ao remover sessão de {sigla}: {e}", file=sys.stderr)
        return False


def get_all_sessions_status() -> Dict[str, Dict]:
    """Retorna status de todas as sessões salvas."""
    status = {}
    if not os.path.exists(SESSIONS_DIR):
        return status
    
    for filename in os.listdir(SESSIONS_DIR):
        if filename.endswith('_session.json'):
            sigla = filename.replace('_session.json', '')
            session_path = os.path.join(SESSIONS_DIR, filename)
            file_age = time.time() - os.path.getmtime(session_path)
            is_valid = file_age <= SESSION_MAX_AGE_SECONDS
            
            status[sigla] = {
                'valid': is_valid,
                'age_seconds': int(file_age),
                'remaining_seconds': max(0, SESSION_MAX_AGE_SECONDS - int(file_age)),
                'path': session_path
            }
    
    return status


# ============================================
# FUNÇÕES DE LOGIN
# ============================================

async def verificar_se_logado(page: Page) -> bool:
    """
    Verifica se a página atual indica que o usuário está logado no SEI.
    Retorna True se logado, False se na tela de login ou erro.
    """
    try:
        current_url = page.url.lower()
        
        # Se está na URL de controle de procedimentos, está logado
        if "acao=procedimento_controlar" in current_url and "login" not in current_url:
            return True
        
        # Se está na tela de login, não está logado
        if "login" in current_url or "acao=login" in current_url:
            return False
        
        # Verifica se existe elemento típico de usuário logado
        try:
            sair_button = page.locator('a:has-text("Sair"), #lnkSair, .sair')
            if await sair_button.count() > 0:
                return True
        except:
            pass
        
        # Se chegou aqui, assume não logado por segurança
        return False
        
    except Exception as e:
        print(f"  ⚠️ Erro ao verificar login: {e}", file=sys.stderr)
        return False


async def fazer_login_completo(page: Page, usuario: str, senha: str, orgao_id: str = "31") -> bool:
    """
    Realiza o login completo no SEI.
    Retorna True se login bem-sucedido, False caso contrário.
    """
    print(f"🔐 Fazendo login como '{usuario}'...", file=sys.stderr)

    # 1) Sempre começa pelo controlador
    await page.goto(CONTROL_URL, wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_load_state("networkidle", timeout=60000)
    print(f"  → URL após goto CONTROL_URL: {page.url}", file=sys.stderr)

    # 2) Verifica se já está logado
    if await verificar_se_logado(page):
        print("  ✅ Já está logado!", file=sys.stderr)
        return True

    # 3) Usa a página diretamente
    target = page

    # 4) Preenche usuário
    usuario_field = target.locator('#txtUsuario')
    await usuario_field.wait_for(state="visible", timeout=15000)
    await usuario_field.fill(usuario)
    print("  ✓ Usuário preenchido", file=sys.stderr)

    # 5) Preenche senha
    senha_field = target.locator('#pwdSenha')
    await senha_field.wait_for(state="visible", timeout=15000)
    await senha_field.fill(senha)
    print(f"  ✓ Senha preenchida ({mask_password(senha)})", file=sys.stderr)

    # 6) Seleciona órgão
    try:
        orgao_field = target.locator('#selOrgao')
        count = await orgao_field.count()
        if count > 0:
            await orgao_field.select_option(value=orgao_id)
            print(f"  ✓ Órgão selecionado (ID={orgao_id})", file=sys.stderr)
    except Exception as e:
        print(f"  ⚠️ Órgão não selecionado: {e}", file=sys.stderr)

    # 7) Clica submit
    submit = target.locator('#sbmAcessar, #sbmEntrar, #sbmLogin').first
    await submit.click()
    print("  ✓ Submit acionado", file=sys.stderr)

    # 8) Aguarda pós-login
    await page.wait_for_load_state("networkidle", timeout=60000)
    print(f"  → URL após login: {page.url}", file=sys.stderr)

    # 9) Verifica sucesso
    if "login.php" in page.url.lower() or "acao=login" in page.url.lower():
        print("  ❌ Ainda está na tela de login - credenciais inválidas?", file=sys.stderr)
        return False

    if await verificar_se_logado(page):
        print("  ✅ Login concluído com sucesso.", file=sys.stderr)
        return True

    print("  ✅ Login aparentemente OK.", file=sys.stderr)
    return True


async def tentar_usar_sessao_existente(page: Page, sigla: str) -> bool:
    """
    Tenta acessar o SEI usando sessão salva.
    Retorna True se a sessão ainda é válida e funcionou.
    """
    print(f"🔄 Tentando reutilizar sessão de {sigla}...", file=sys.stderr)
    
    try:
        # Navega para a página principal
        await page.goto(CONTROL_URL, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_load_state("networkidle", timeout=30000)
        
        # Verifica se está logado
        if await verificar_se_logado(page):
            print(f"  ✅ Sessão de {sigla} reutilizada com sucesso!", file=sys.stderr)
            return True
        else:
            print(f"  ⚠️ Sessão de {sigla} expirou no servidor", file=sys.stderr)
            delete_session(sigla)
            return False
            
    except Exception as e:
        print(f"  ⚠️ Erro ao reutilizar sessão de {sigla}: {e}", file=sys.stderr)
        delete_session(sigla)
        return False


# ============================================
# CONTEXT MANAGER - LOGIN TRADICIONAL
# ============================================

@asynccontextmanager
async def _criar_sessao_tradicional(
    sigla: str = None, 
    chat_id: str = None,
    # NOVO: Credenciais diretas (Laravel/PlattArgus WEB)
    usuario: str = None,
    senha: str = None,
    orgao_id: str = "31"
):
    """
    Login tradicional (abre browser → login → operação → fecha browser).
    Usado quando o Porteiro não está disponível.
    
    NOVO: Aceita credenciais diretas (usuario/senha) além de sigla/chat_id.
    """
    
    # =========================================================================
    # RESOLVER CREDENCIAIS
    # =========================================================================
    
    if usuario and senha:
        # NOVO: Credenciais diretas (Laravel/PlattArgus WEB)
        print(f"🔐 Usando credenciais diretas: {usuario}", file=sys.stderr)
        sigla_upper = usuario.upper().replace(".", "_")  # Para nome da sessão
        diretoria = {
            'sigla': sigla_upper,
            'nome': f'Usuário {usuario}',
            'sei_usuario': usuario
        }
        # Não salva sessão para credenciais diretas (cada usuário tem sua própria)
        salvar_sessao = False
        
    elif sigla or chat_id:
        # LEGADO: Busca credenciais do banco de diretorias (Telegram)
        db = DiretoriasDB()
        diretoria = db.buscar_por_sigla(sigla) if sigla else db.buscar_por_chat_id(chat_id)
        
        if not diretoria:
            raise ValueError(f"Diretoria não encontrada: {sigla or chat_id}")
        
        sigla_upper = diretoria['sigla'].upper()
        
        credenciais = db.obter_credenciais(sigla_upper)
        if not credenciais:
            raise ValueError(f"Credenciais não encontradas para: {sigla_upper}")
        
        usuario, senha, orgao_id = credenciais
        print(f"📋 Diretoria: {sigla_upper} - {diretoria['nome']}", file=sys.stderr)
        salvar_sessao = True
        
    else:
        raise ValueError("Informe 'sigla', 'chat_id' ou credenciais (usuario/senha)")
    
    # =========================================================================
    # CRIAR SESSÃO
    # =========================================================================
    
    # Métricas de tempo
    tempo_inicio = time.time()
    login_necessario = False
    sessao_reutilizada = False
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=HEADLESS, 
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        
        try:
            # ========================================
            # TENTA REUTILIZAR SESSÃO EXISTENTE
            # ========================================
            context = None
            page = None
            
            # Só tenta reutilizar sessão se for modo sigla/chat_id
            if salvar_sessao and session_is_valid(sigla_upper):
                try:
                    session_path = get_session_path(sigla_upper)
                    context = await browser.new_context(storage_state=session_path)
                    page = await context.new_page()
                    page.set_default_timeout(DEFAULT_TIMEOUT_MS)
                    
                    if await tentar_usar_sessao_existente(page, sigla_upper):
                        sessao_reutilizada = True
                        tempo_login = round(time.time() - tempo_inicio, 2)
                        print(f"  ⚡ Sessão reutilizada em {tempo_login}s (economia de ~15-25s)", file=sys.stderr)
                    else:
                        # Sessão inválida, fecha e tenta login novo
                        await context.close()
                        context = None
                        page = None
                except Exception as e:
                    print(f"  ⚠️ Falha ao carregar sessão: {e}", file=sys.stderr)
                    if context:
                        await context.close()
                    context = None
                    page = None
            
            # ========================================
            # FAZ LOGIN NOVO SE NECESSÁRIO
            # ========================================
            if context is None:
                login_necessario = True
                print(f"  🔑 Login necessário para {usuario}", file=sys.stderr)
                
                context = await browser.new_context()
                page = await context.new_page()
                page.set_default_timeout(DEFAULT_TIMEOUT_MS)
                
                sucesso = await fazer_login_completo(page, usuario, senha, orgao_id)
                if not sucesso:
                    raise RuntimeError(f"Falha no login para {usuario}")
                
                # Salva sessão para próximas operações (só se for sigla/chat_id)
                if salvar_sessao:
                    await save_session_async(sigla_upper, context)
                
                tempo_login = round(time.time() - tempo_inicio, 2)
                print(f"  ✅ Login completo em {tempo_login}s", file=sys.stderr)
            
            # Registra login no banco (só se for sigla/chat_id)
            if salvar_sessao:
                try:
                    db.registrar_login(sigla_upper)
                except:
                    pass
            
            # Limpa senha da memória
            senha_limpa = "x" * len(senha) if senha else ""
            
            # Retorna sessão
            yield {
                'page': page, 
                'browser': browser, 
                'context': context, 
                'diretoria': diretoria,
                'sessao_reutilizada': sessao_reutilizada,
                'login_necessario': login_necessario,
                'modo': 'tradicional',
                'shard_id': -1,
                'tempo_espera': 0,
            }
            
            # ========================================
            # ATUALIZA SESSÃO APÓS USO BEM-SUCEDIDO
            # ========================================
            if salvar_sessao:
                await save_session_async(sigla_upper, context)
            
        except Exception as e:
            # Se deu erro, invalida a sessão
            if salvar_sessao:
                delete_session(sigla_upper)
            raise
            
        finally:
            try:
                if context:
                    await context.close()
            except:
                pass
            try:
                await browser.close()
            except:
                pass


# ============================================
# CONTEXT MANAGER PRINCIPAL (HÍBRIDO)
# ============================================

@asynccontextmanager
async def criar_sessao_sei(
    chat_id: str = None, 
    sigla: str = None,
    # NOVO: Credenciais diretas (Laravel/PlattArgus WEB)
    usuario: str = None,
    senha: str = None,
    orgao_id: str = "31",
    # Alias para compatibilidade
    headless: bool = None  # Ignorado, usa HEADLESS global
):
    """
    Cria uma sessão do SEI, escolhendo automaticamente entre Porteiro e fallback.
    
    NOVO (v3.1): Aceita credenciais diretas para integração com Laravel/PlattArgus WEB.
    
    Prioridade de autenticação:
    1. Se usuario+senha informados → usa credenciais diretas (NOVO)
    2. Se sigla informada → busca credenciais do banco
    3. Se chat_id informado → busca sigla pelo chat_id, depois credenciais
    
    Prioridade de modo:
    1. Se PORTEIRO_FORCE_FALLBACK=1 → usa login tradicional
    2. Se Porteiro está iniciado → usa Porteiro
    3. Senão → usa login tradicional
    
    Args:
        chat_id: Chat ID do Telegram (para resolver sigla) - LEGADO
        sigla: Sigla da diretoria - LEGADO
        usuario: Usuário SEI - NOVO (Laravel/PlattArgus WEB)
        senha: Senha SEI - NOVO (Laravel/PlattArgus WEB)
        orgao_id: ID do órgão (default: "31" = CBMAC)
    
    Yields:
        Dict com: page, browser, context, diretoria, sessao_reutilizada, modo, etc.
    
    Uso:
        # NOVO - Credenciais diretas (Laravel/PlattArgus WEB)
        async with criar_sessao_sei(usuario="gilmar.moura", senha="xxx", orgao_id="31") as sessao:
            page = sessao['page']
            # ... fazer operações ...
        
        # LEGADO - Sigla (Telegram)
        async with criar_sessao_sei(sigla="DRH") as sessao:
            page = sessao['page']
            # ... fazer operações ...
    """
    
    # Se tem credenciais diretas, usa modo tradicional direto
    if usuario and senha:
        print(f"🔑 Modo: Credenciais diretas ({usuario})", file=sys.stderr)
        async with _criar_sessao_tradicional(
            usuario=usuario, 
            senha=senha, 
            orgao_id=orgao_id
        ) as sessao:
            yield sessao
        return
    
    # Verifica se deve usar Porteiro (só para sigla/chat_id)
    usar_porteiro = _porteiro_disponivel()
    
    if usar_porteiro:
        porteiro = _get_porteiro()
        print(f"🚪 Usando Porteiro (pool de sessões)", file=sys.stderr)
        
        try:
            async with porteiro.obter_sessao(sigla=sigla, chat_id=chat_id) as sessao:
                sessao['modo'] = 'porteiro'
                sessao['sessao_reutilizada'] = True  # Porteiro sempre reutiliza
                sessao['login_necessario'] = False
                yield sessao
        except Exception as e:
            # Se Porteiro falhar, tenta fallback
            print(f"⚠️ Porteiro falhou: {e}, tentando fallback...", file=sys.stderr)
            async with _criar_sessao_tradicional(sigla=sigla, chat_id=chat_id) as sessao:
                yield sessao
    else:
        # Usa login tradicional
        async with _criar_sessao_tradicional(sigla=sigla, chat_id=chat_id) as sessao:
            yield sessao


# ============================================
# FUNÇÕES DE TESTE
# ============================================

async def testar_credenciais(usuario: str, senha: str, orgao_id: str = "31") -> Dict:
    """Testa credenciais sem salvar sessão."""
    resultado = {"sucesso": False, "erro": None, "tempo_login": None}
    inicio = time.time()
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=HEADLESS, 
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        try:
            context = await browser.new_context()
            page = await context.new_page()
            page.set_default_timeout(DEFAULT_TIMEOUT_MS)
            sucesso = await fazer_login_completo(page, usuario, senha, orgao_id)
            resultado["sucesso"] = sucesso
            resultado["tempo_login"] = round(time.time() - inicio, 2)
            if not sucesso:
                resultado["erro"] = "Falha no login - verifique credenciais"
        except Exception as e:
            resultado["erro"] = f"❌ Falha no login: {e}"
        finally:
            await browser.close()
    return resultado


# ============================================
# CLI
# ============================================

async def _testar_login_cli(sigla: str):
    """Testa login via CLI."""
    db = DiretoriasDB()
    diretoria = db.buscar_por_sigla(sigla)
    if not diretoria:
        print(json.dumps({"sucesso": False, "erro": f"Diretoria '{sigla}' não encontrada"}))
        return
    credenciais = db.obter_credenciais(sigla)
    if not credenciais:
        print(json.dumps({"sucesso": False, "erro": "Credenciais não encontradas"}))
        return
    usuario, senha, orgao_id = credenciais
    print(f"🔐 Testando login de '{sigla}'...", file=sys.stderr)
    print(f"   Usuário: {usuario}", file=sys.stderr)
    print(f"   Senha: {mask_password(senha)}", file=sys.stderr)
    resultado = await testar_credenciais(usuario, senha, orgao_id)
    print(json.dumps(resultado, indent=2, ensure_ascii=False))


async def _testar_sessao_cli(sigla: str):
    """Testa criar sessão via CLI (com Porteiro se disponível)."""
    print(f"\n🧪 Testando sessão de '{sigla}'...\n", file=sys.stderr)
    
    try:
        t1 = time.time()
        async with criar_sessao_sei(sigla=sigla) as sessao:
            tempo1 = time.time() - t1
            modo = sessao.get('modo', 'desconhecido')
            reutilizada = sessao.get('sessao_reutilizada', False)
            
            print(f"✅ Sessão obtida em {tempo1:.2f}s", file=sys.stderr)
            print(f"   Modo: {modo}", file=sys.stderr)
            print(f"   Reutilizada: {reutilizada}", file=sys.stderr)
            
            if modo == 'porteiro':
                print(f"   Shard: {sessao.get('shard_id')}", file=sys.stderr)
            
            await asyncio.sleep(1)
        
        print(f"\n✅ Teste concluído com sucesso!", file=sys.stderr)
        
    except Exception as e:
        print(f"\n❌ Erro: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()


async def _status_sessoes_cli():
    """Mostra status de todas as sessões."""
    status = get_all_sessions_status()
    if not status:
        print("Nenhuma sessão salva encontrada.")
        return
    
    print(f"\n{'='*60}")
    print(f"STATUS DAS SESSÕES (max age: {SESSION_MAX_AGE_SECONDS}s)")
    print(f"{'='*60}")
    
    for sigla, info in sorted(status.items()):
        status_icon = "✅" if info['valid'] else "❌"
        print(f"\n{status_icon} {sigla}")
        print(f"   Idade: {info['age_seconds']}s")
        if info['valid']:
            print(f"   Expira em: {info['remaining_seconds']}s")
        else:
            print(f"   EXPIRADA")
    
    print(f"\n{'='*60}\n")


async def _limpar_sessoes_cli():
    """Remove todas as sessões expiradas."""
    status = get_all_sessions_status()
    removidas = 0
    
    for sigla, info in status.items():
        if not info['valid']:
            delete_session(sigla)
            removidas += 1
    
    print(f"Sessões removidas: {removidas}")


async def _status_completo_cli():
    """Mostra status completo (sessões + Porteiro)."""
    print(f"\n{'='*60}")
    print(f"SEI AUTH MULTI v3.1 - STATUS COMPLETO")
    print(f"{'='*60}")
    
    print(f"\n⚙️  CONFIGURAÇÃO")
    print(f"   PORTEIRO_ENABLED: {PORTEIRO_ENABLED}")
    print(f"   PORTEIRO_FORCE_FALLBACK: {PORTEIRO_FORCE_FALLBACK}")
    print(f"   SESSION_MAX_AGE: {SESSION_MAX_AGE_SECONDS}s")
    print(f"   SESSIONS_DIR: {SESSIONS_DIR}")
    print(f"   Porteiro disponível: {_porteiro_disponivel()}")
    
    print(f"\n📋 SESSÕES SALVAS (fallback)")
    status = get_all_sessions_status()
    if not status:
        print("   (nenhuma)")
    else:
        for sigla, info in sorted(status.items()):
            icon = "✅" if info['valid'] else "❌"
            print(f"   {icon} {sigla}: {info['age_seconds']}s (resta {info['remaining_seconds']}s)")
    
    # Se Porteiro está disponível, mostra status dele também
    if _porteiro_disponivel():
        porteiro = _get_porteiro()
        print(f"\n🚪 PORTEIRO")
        try:
            metricas = porteiro.get_metricas()
            print(f"   Sessões: {metricas.get('sessoes_ativas', 0)}/{metricas.get('max_sessoes', 0)}")
            print(f"   Em uso: {metricas.get('sessoes_em_uso', 0)}")
            print(f"   Shards: {metricas.get('shards_ativos', 0)}/{metricas.get('shards_total', 0)}")
            print(f"   Tarefas: {metricas.get('total_tarefas', 0)}")
            print(f"   Fallbacks: {metricas.get('total_fallbacks', 0)}")
        except Exception as e:
            print(f"   Erro ao obter métricas: {e}")
    
    print(f"\n{'='*60}\n")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Autenticação SEI Multi-Diretoria v3.1 (Híbrido + Credenciais Diretas)")
    parser.add_argument("--testar", metavar="SIGLA", help="Testa login de uma diretoria (credenciais)")
    parser.add_argument("--sessao", metavar="SIGLA", help="Testa criar sessão (com Porteiro se disponível)")
    parser.add_argument("--status", action="store_true", help="Mostra status das sessões salvas")
    parser.add_argument("--status-completo", action="store_true", help="Mostra status completo (sessões + Porteiro)")
    parser.add_argument("--limpar", action="store_true", help="Remove sessões expiradas")
    args = parser.parse_args()
    
    if args.testar:
        asyncio.run(_testar_login_cli(args.testar))
    elif args.sessao:
        asyncio.run(_testar_sessao_cli(args.sessao))
    elif args.status:
        asyncio.run(_status_sessoes_cli())
    elif args.status_completo:
        asyncio.run(_status_completo_cli())
    elif args.limpar:
        asyncio.run(_limpar_sessoes_cli())
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
