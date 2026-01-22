#!/usr/bin/env python3
"""
PlattArgus - Adaptações para assinar_documento.py
==================================================

Este arquivo contém as MODIFICAÇÕES necessárias no assinar_documento.py
para aceitar credenciais por parâmetro (vindo do Laravel).

COMO APLICAR:
1. Abra o arquivo /opt/plattargus/scripts/assinar_documento.py
2. Localize a função assinar_documento()
3. Aplique as modificações indicadas abaixo

OU

1. Substitua a função assinar_documento() pela versão abaixo
"""

# =============================================================================
# VERSÃO ADAPTADA DA FUNÇÃO assinar_documento()
# =============================================================================

async def assinar_documento(
    sei_numero: str,
    # ========== NOVA FORMA (Laravel) ==========
    dados_assinante: dict = None,
    # ========== FORMA ANTIGA (Telegram) ==========
    chat_id: str = None,
    sigla: str = None,
) -> dict:
    """
    Assina um documento no SEI.
    
    NOVA FORMA (Laravel):
        dados_assinante = {
            "login_sei": "gilmar.moura",
            "senha": "senha_descriptografada",
            "orgao_id": "31",
            "cargo": "Diretor de RH"
        }
        resultado = await assinar_documento("0018817258", dados_assinante=dados_assinante)
    
    FORMA ANTIGA (Telegram - mantida para compatibilidade):
        resultado = await assinar_documento("0018817258", chat_id="-1001234567890")
        resultado = await assinar_documento("0018817258", sigla="DRH")
    
    Args:
        sei_numero: Número SEI do documento (ex: "0018817258")
        dados_assinante: Dicionário com credenciais (NOVO - Laravel)
        chat_id: ID do chat Telegram (LEGADO)
        sigla: Sigla da diretoria (LEGADO)
    
    Returns:
        dict: {"sucesso": bool, "mensagem": str, "erro": str}
    """
    import sys
    from playwright.async_api import async_playwright
    
    # =========================================================================
    # OBTER DADOS DO ASSINANTE
    # =========================================================================
    
    if dados_assinante:
        # NOVA FORMA: Credencial vem por parâmetro (Laravel)
        login_sei = dados_assinante.get("login_sei")
        senha = dados_assinante.get("senha")
        orgao_id = dados_assinante.get("orgao_id", "31")
        cargo = dados_assinante.get("cargo")
        
        if not login_sei or not senha:
            return {"sucesso": False, "erro": "Credencial incompleta"}
        
        print(f"🔐 Assinando como: {login_sei} (via Laravel)", file=sys.stderr)
        
    elif chat_id or sigla:
        # FORMA ANTIGA: Busca do banco de diretorias (Telegram)
        from diretorias_db import DiretoriasDB
        
        db = DiretoriasDB()
        
        if sigla:
            diretoria = db.buscar_por_sigla(sigla)
        else:
            diretoria = db.buscar_por_chat_id(chat_id)
        
        if not diretoria:
            return {"sucesso": False, "erro": "Diretoria não encontrada"}
        
        login_sei, senha, orgao_id = db.obter_credenciais(diretoria["sigla"])
        cargo = diretoria.get("cargo", "Assinante")
        
        print(f"🔐 Assinando como: {login_sei} (via Telegram)", file=sys.stderr)
        
    else:
        return {"sucesso": False, "erro": "Informe dados_assinante, chat_id ou sigla"}
    
    # =========================================================================
    # EXECUTAR ASSINATURA (código existente continua igual)
    # =========================================================================
    
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"]
            )
            
            context = await browser.new_context()
            page = await context.new_page()
            page.set_default_timeout(30000)
            
            # ... (resto do código de assinatura permanece igual)
            # ... fazer login
            # ... navegar até documento
            # ... abrir modal de assinatura
            # ... preencher campos
            # ... digitar senha caractere por caractere
            # ... clicar assinar
            # ... verificar sucesso
            
            # IMPORTANTE: Limpar senha da memória após uso
            senha = "x" * len(senha)
            
            return {
                "sucesso": True,
                "mensagem": f"Documento {sei_numero} assinado com sucesso",
            }
            
    except Exception as e:
        # Limpar senha em caso de erro também
        senha = "x" * len(senha) if senha else ""
        
        return {
            "sucesso": False,
            "erro": str(e),
        }


# =============================================================================
# EXEMPLO DE USO
# =============================================================================

if __name__ == "__main__":
    import asyncio
    
    # Teste com credencial direta (como o Laravel faria)
    async def teste():
        resultado = await assinar_documento(
            sei_numero="0018817258",
            dados_assinante={
                "login_sei": "gilmar.moura",
                "senha": "minha_senha_sei",
                "orgao_id": "31",
                "cargo": "Diretor de RH"
            }
        )
        print(resultado)
    
    asyncio.run(teste())
