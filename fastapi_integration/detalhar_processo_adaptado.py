#!/usr/bin/env python3
"""
PlattArgus - Adaptações para detalhar_processo.py
==================================================

Este arquivo contém as MODIFICAÇÕES necessárias no detalhar_processo.py
para aceitar credenciais por parâmetro (vindo do Laravel).

COMO APLICAR:
1. Abra o arquivo /opt/plattargus/scripts/detalhar_processo.py
2. Localize a função detalhar_processo_completo()
3. Adicione o parâmetro 'credencial' conforme mostrado abaixo
"""

# =============================================================================
# MODIFICAÇÃO NA FUNÇÃO detalhar_processo_completo()
# =============================================================================

async def detalhar_processo_completo(
    nup: str,
    # ========== NOVA FORMA (Laravel) ==========
    credencial: dict = None,
    # ========== FORMA ANTIGA (Telegram) ==========
    chat_id: str = None,
    sigla: str = None,
    # ========== OPÇÕES ==========
    opcoes: dict = None,
) -> dict:
    """
    Detalha um processo do SEI extraindo todos os documentos.
    
    NOVA FORMA (Laravel):
        credencial = {
            "usuario": "gilmar.moura",
            "senha": "senha_descriptografada",
            "orgao_id": "31"
        }
        resultado = await detalhar_processo_completo("0609.012080.00284/2025-14", credencial=credencial)
    
    FORMA ANTIGA (Telegram - mantida para compatibilidade):
        resultado = await detalhar_processo_completo("0609.012080.00284/2025-14", chat_id="-1001234567890")
        resultado = await detalhar_processo_completo("0609.012080.00284/2025-14", sigla="DRH")
    
    Args:
        nup: NUP do processo
        credencial: Dicionário com credenciais (NOVO - Laravel)
        chat_id: ID do chat Telegram (LEGADO)
        sigla: Sigla da diretoria (LEGADO)
        opcoes: Opções adicionais (baixar_pdf, rodar_ocr, rodar_rag)
    
    Returns:
        dict com análise do processo
    """
    import sys
    
    opcoes = opcoes or {}
    
    # =========================================================================
    # OBTER CREDENCIAIS
    # =========================================================================
    
    if credencial:
        # NOVA FORMA: Credencial vem por parâmetro (Laravel)
        usuario = credencial.get("usuario")
        senha = credencial.get("senha")
        orgao_id = credencial.get("orgao_id", "31")
        
        if not usuario or not senha:
            return {"sucesso": False, "erro": "Credencial incompleta"}
        
        print(f"🔍 Detalhando processo como: {usuario} (via Laravel)", file=sys.stderr)
        
    elif chat_id or sigla:
        # FORMA ANTIGA: Busca do banco de diretorias (Telegram)
        from diretorias_db import DiretoriasDB
        
        db = DiretoriasDB()
        
        if sigla:
            dados = db.obter_credenciais(sigla)
        else:
            dados = db.obter_credenciais_por_chat(chat_id)
        
        if not dados:
            return {"sucesso": False, "erro": "Credenciais não encontradas"}
        
        if len(dados) == 4:
            sigla_dir, usuario, senha, orgao_id = dados
        else:
            usuario, senha, orgao_id = dados
        
        print(f"🔍 Detalhando processo como: {usuario} (via Telegram)", file=sys.stderr)
        
    else:
        return {"sucesso": False, "erro": "Informe credencial, chat_id ou sigla"}
    
    # =========================================================================
    # CRIAR SESSÃO E EXECUTAR (código existente adaptado)
    # =========================================================================
    
    try:
        from playwright.async_api import async_playwright
        from sei_auth_multi import fazer_login_completo
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"]
            )
            
            context = await browser.new_context()
            page = await context.new_page()
            page.set_default_timeout(60000)
            
            # Login
            sucesso_login = await fazer_login_completo(page, usuario, senha, orgao_id)
            
            if not sucesso_login:
                return {"sucesso": False, "erro": "Falha no login do SEI"}
            
            # =========================================================
            # NAVEGAR ATÉ O PROCESSO
            # (código existente para navegar e extrair documentos)
            # =========================================================
            
            # ... buscar processo por NUP
            # ... extrair árvore de documentos
            # ... baixar PDFs se opcoes["baixar_pdf"]
            # ... rodar OCR se opcoes["rodar_ocr"]
            # ... rodar RAG se opcoes["rodar_rag"]
            
            # Limpar senha da memória
            senha = "x" * len(senha)
            
            return {
                "sucesso": True,
                "nup": nup,
                "texto": "...",  # texto extraído
                "analise": {
                    "resumo": "...",
                    "conclusao": "...",
                    "interessado": {},
                    "pedido": {},
                    "legislacao": [],
                    "documentos": [],
                    "alertas": [],
                },
            }
            
    except Exception as e:
        # Limpar senha em caso de erro
        if 'senha' in dir():
            senha = "x" * len(senha) if senha else ""
        
        return {
            "sucesso": False,
            "erro": str(e),
        }


# =============================================================================
# MODIFICAÇÃO EM criar_sessao_sei (sei_auth_multi.py)
# =============================================================================

"""
A função criar_sessao_sei também precisa ser adaptada para aceitar credencial
por parâmetro. Aqui está a versão modificada:
"""

from contextlib import asynccontextmanager

@asynccontextmanager
async def criar_sessao_sei(
    # NOVA FORMA (Laravel)
    credencial: dict = None,
    # FORMA ANTIGA (Telegram)
    chat_id: str = None,
    sigla: str = None,
):
    """
    Context manager para criar sessão autenticada no SEI.
    
    NOVA FORMA (Laravel):
        async with criar_sessao_sei(credencial={"usuario": "x", "senha": "y", "orgao_id": "31"}) as sessao:
            page = sessao["page"]
            ...
    
    FORMA ANTIGA (Telegram):
        async with criar_sessao_sei(chat_id="-1001234567890") as sessao:
            page = sessao["page"]
            ...
    """
    from playwright.async_api import async_playwright
    from sei_auth_multi import fazer_login_completo
    
    # Obter credenciais
    if credencial:
        usuario = credencial["usuario"]
        senha = credencial["senha"]
        orgao_id = credencial.get("orgao_id", "31")
    elif chat_id or sigla:
        from diretorias_db import DiretoriasDB
        db = DiretoriasDB()
        
        if sigla:
            usuario, senha, orgao_id = db.obter_credenciais(sigla)
        else:
            _, usuario, senha, orgao_id = db.obter_credenciais_por_chat(chat_id)
    else:
        raise ValueError("Informe credencial, chat_id ou sigla")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        
        try:
            context = await browser.new_context()
            page = await context.new_page()
            page.set_default_timeout(60000)
            
            sucesso = await fazer_login_completo(page, usuario, senha, orgao_id)
            
            if not sucesso:
                raise RuntimeError("Falha no login")
            
            # Limpa senha da memória
            senha = "x" * len(senha)
            
            yield {
                "page": page,
                "browser": browser,
                "context": context,
            }
            
        finally:
            try:
                await context.close()
            except:
                pass
            try:
                await browser.close()
            except:
                pass
