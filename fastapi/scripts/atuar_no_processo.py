#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
atuar_no_processo.py - Criação de Documentos SEI Multi-Diretoria

VERSÃO 4.1 - PRODUÇÃO COMPLETA + CREDENCIAIS DIRETAS

Melhorias v4.1:
- Suporte a credenciais diretas (--usuario, --senha, --orgao)
- Mantém compatibilidade com chat_id/sigla (Telegram)

Recursos:
- Login via sei_auth_multi (multi-diretoria)
- Suporte a templates
- Extração completa: SEI nº, Cabeçalho, Número do documento
- Hash SHA256 como prova jurídica
- Validação de conteúdo (overlap 60%)
- Screenshot automático como prova
- Envio opcional para Telegram
- JSON rico de retorno

Uso:
    # NOVO - Credenciais diretas (Laravel/PlattArgus WEB)
    python atuar_no_processo.py "NUP" "Tipo" "Destinatário" "HTML" --usuario gilmar.moura --senha xxx --orgao 31
    
    # LEGADO - Telegram
    python atuar_no_processo.py "NUP" "Tipo" "Destinatário" "HTML" --chat-id "123"
    python atuar_no_processo.py "NUP" "Tipo" "Destinatário" "HTML" --sigla DRH

Dependências:
    pip install playwright requests
    playwright install chromium
"""

import os
import sys
import json
import re
import asyncio
import hashlib
from datetime import datetime
from typing import Dict, Optional, Any
from urllib.parse import urlparse, parse_qs
from pathlib import Path

# Caminho do projeto
sys.path.insert(0, "/app/scripts")

from playwright.async_api import async_playwright
from sei_auth_multi import criar_sessao_sei, CONTROL_URL

# Opcional: requests para Telegram
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


# =============================================================================
# CONFIGURAÇÃO
# =============================================================================

DEBUG = os.getenv("ARGUS_DEBUG", "1") == "1"
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Diretório para fotos/evidências
FOTOS_DIR = Path(os.getenv("ARGUS_FOTOS_DIR", "/tmp/argus_fotos"))
FOTOS_DIR.mkdir(exist_ok=True)

# Seletores SEI
SELETOR_FRAME_CONTEUDO_PAI = 'iframe[name="ifrConteudoVisualizacao"]'
SELETOR_FRAME_VISUALIZACAO = 'iframe[name="ifrVisualizacao"]'
SELETOR_FRAME_ARVORE = 'iframe[name="ifrArvore"]'
SELETOR_IFRAME_CORPO_TEXTO = 'iframe[title="Corpo do Texto"]'


# =============================================================================
# HELPERS
# =============================================================================

def debug_print(msg: str):
    """Print de debug condicional."""
    if DEBUG:
        print(f"[DEBUG] {msg}", file=sys.stderr)


def _norm_space(s: str) -> str:
    """Normaliza espaços em uma string."""
    s = (s or "").strip()
    s = re.sub(r"\s+", " ", s)
    return s


def strip_tags(html: str) -> str:
    """Remove tags HTML de uma string."""
    txt = re.sub(r"<[^>]+>", " ", html or "")
    return _norm_space(txt)


def hash_texto(s: str) -> str:
    """Gera hash SHA256 de um texto."""
    s = (s or "").strip().encode("utf-8", errors="ignore")
    return hashlib.sha256(s).hexdigest()


def _extrair_id_documento_de_url(url: str) -> Optional[str]:
    """Extrai id_documento de uma URL."""
    try:
        qs = parse_qs(urlparse(url).query)
        for key in ("id_documento", "idDocumento", "id_doc"):
            if key in qs and qs[key]:
                return str(qs[key][0])
    except Exception:
        pass
    return None


def extrair_numero_e_sigla_do_cabecalho(cab: str) -> Dict[str, Optional[str]]:
    """Extrai número do documento e sigla do cabeçalho."""
    if not cab:
        return {"numero_doc": None, "sigla_doc": None}
    
    # Padrão: "Despacho nº 86/2025/CBMAC - DRH" ou "Memorando nº 123/2025/CBMAC - COC"
    m_num = re.search(r"n[ºo°]\s*(\d+)", cab, re.IGNORECASE)
    m_sigla = re.search(r"/CBMAC\s*-\s*([A-Z0-9]+)", cab)
    
    return {
        "numero_doc": m_num.group(1) if m_num else None,
        "sigla_doc": m_sigla.group(1) if m_sigla else None,
    }


# =============================================================================
# TELEGRAM
# =============================================================================

def telegram_send_photo(token: str, chat_id: str, foto_path: str, caption: str) -> dict:
    """Envia foto para o Telegram."""
    if not HAS_REQUESTS:
        return {"ok": False, "error": "requests não instalado"}
    
    try:
        url = f"https://api.telegram.org/bot{token}/sendPhoto"
        with open(foto_path, "rb") as f:
            resp = requests.post(
                url,
                data={"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"},
                files={"photo": f},
                timeout=30
            )
        return resp.json()
    except Exception as e:
        return {"ok": False, "error": str(e)}


# =============================================================================
# TEMPLATES
# =============================================================================

def carregar_template(template_id: str) -> tuple:
    """Carrega template do banco de templates."""
    try:
        from templates_meta import get_template_path, get_tipo_sei
        
        path = get_template_path(template_id)
        if path and path.exists():
            with open(path, "r", encoding="utf-8") as f:
                conteudo = f.read()
            tipo = get_tipo_sei(template_id)
            return conteudo, tipo
    except ImportError:
        pass
    
    # Fallback
    fallback_dir = os.getenv("MODELOS_DIR", "/app/modelos/memorandos")
    fallback_path = os.path.join(fallback_dir, f"{template_id}.txt")
    
    if os.path.exists(fallback_path):
        with open(fallback_path, "r", encoding="utf-8") as f:
            return f.read(), "Memorando"
    
    return None, None


def processar_template(template_str: str, dados: dict) -> str:
    """Preenche placeholders do template."""
    placeholders = re.findall(r'\{(\w+)\}', template_str)
    
    for ph in placeholders:
        if ph not in dados:
            dados[ph] = ""
    
    return template_str.format(**dados)


# =============================================================================
# EXTRAÇÃO DE DADOS
# =============================================================================

async def coletar_prova_editor(frame_editor) -> dict:
    """Coleta prova do conteúdo no editor antes de salvar."""
    try:
        preview = await frame_editor.locator("body").evaluate("el => el.innerText")
        preview = (preview or "").strip()
        linhas = [ln.strip() for ln in preview.splitlines() if ln.strip()]
        return {
            "preview_texto_editor": preview,
            "hash_preview_editor": hash_texto(preview),
            "primeiras_10_linhas": linhas[:10],
        }
    except Exception as e:
        debug_print(f"Erro ao coletar prova: {e}")
        return {
            "preview_texto_editor": "",
            "hash_preview_editor": "",
            "primeiras_10_linhas": [],
        }


async def capturar_dados_completos_editor(page_editor) -> Dict[str, Optional[str]]:
    """
    Captura TODOS os dados do documento no editor antes de salvar/fechar:
    - SEI nº (rodapé)
    - Cabeçalho: "Despacho nº N/2025/CBMAC - SIGLA"
    - Número do documento
    - Sigla
    """
    resultado = {
        "sei_numero_editor": None,
        "cabecalho_doc": None,
        "numero_doc": None,
        "sigla_doc": None,
    }
    
    debug_print("Extraindo dados completos do editor...")
    
    # Padrões de busca
    padrao_sei = re.compile(r"SEI\s*n[ºo°]?\s*(\d{10,})", re.IGNORECASE)
    padrao_cabecalho = re.compile(
        r"((Despacho|Memorando|Ofício|Termo)\s*n[ºo°]\s*(\d+)/\d{4}/CBMAC\s*-\s*([A-Z0-9]+))",
        re.IGNORECASE
    )
    
    for tentativa in range(5):
        # Estratégia 1: Buscar em TODOS os frames do editor
        debug_print(f"Editor tem {len(page_editor.frames)} frames")
        
        for frame in page_editor.frames:
            try:
                texto = await frame.locator("body").inner_text(timeout=1000)
                
                # Busca SEI nº
                if not resultado["sei_numero_editor"]:
                    match_sei = padrao_sei.search(texto)
                    if match_sei:
                        resultado["sei_numero_editor"] = match_sei.group(1)
                        debug_print(f"SEI nº (frame '{frame.name}'): {resultado['sei_numero_editor']}")
                
                # Busca cabeçalho
                if not resultado["cabecalho_doc"]:
                    match_cab = padrao_cabecalho.search(texto)
                    if match_cab:
                        resultado["cabecalho_doc"] = _norm_space(match_cab.group(1))
                        resultado["numero_doc"] = match_cab.group(3)
                        resultado["sigla_doc"] = match_cab.group(4).upper()
                        debug_print(f"Cabeçalho (frame '{frame.name}'): {resultado['cabecalho_doc']}")
                
            except Exception:
                continue
        
        # Se encontrou tudo, retorna
        if resultado["sei_numero_editor"] and resultado["cabecalho_doc"]:
            debug_print("✓ Dados completos extraídos do editor!")
            return resultado
        
        # Estratégia 2: HTML completo da página
        try:
            html = await page_editor.content()
            
            if not resultado["sei_numero_editor"]:
                match_sei = padrao_sei.search(html)
                if match_sei:
                    resultado["sei_numero_editor"] = match_sei.group(1)
                    debug_print(f"SEI nº (HTML): {resultado['sei_numero_editor']}")
            
            if not resultado["cabecalho_doc"]:
                match_cab = padrao_cabecalho.search(html)
                if match_cab:
                    resultado["cabecalho_doc"] = _norm_space(match_cab.group(1))
                    resultado["numero_doc"] = match_cab.group(3)
                    resultado["sigla_doc"] = match_cab.group(4).upper()
                    debug_print(f"Cabeçalho (HTML): {resultado['cabecalho_doc']}")
        except Exception:
            pass
        
        if resultado["sei_numero_editor"] and resultado["cabecalho_doc"]:
            return resultado
        
        # Aguarda e tenta novamente
        await page_editor.wait_for_timeout(1000)
    
    debug_print("⚠ Não conseguiu extrair todos os dados do editor")
    return resultado


async def ler_cabecalho_no_viewer(page) -> Optional[str]:
    """Lê o cabeçalho do documento no viewer."""
    padrao = re.compile(
        r"((Despacho|Memorando|Ofício|Termo)\s*n[ºo°]\s*\d+/\d{4}/CBMAC\s*-\s*[A-Z0-9]+)",
        re.IGNORECASE
    )
    
    try:
        frame_pai = page.frame_locator(SELETOR_FRAME_CONTEUDO_PAI).first
        frame_viz = frame_pai.frame_locator(SELETOR_FRAME_VISUALIZACAO).first
        
        texto = await frame_viz.locator("body").inner_text(timeout=5000)
        match = padrao.search(texto)
        if match:
            return _norm_space(match.group(1))
    except Exception as e:
        debug_print(f"Erro ao ler cabeçalho viewer: {e}")
    
    return None


async def extrair_sei_do_viewer(page) -> Optional[str]:
    """Extrai SEI nº do viewer."""
    padrao = re.compile(r"SEI\s*n[ºo°]?\s*(\d{10,})", re.IGNORECASE)
    
    try:
        frame_pai = page.frame_locator(SELETOR_FRAME_CONTEUDO_PAI).first
        frame_viz = frame_pai.frame_locator(SELETOR_FRAME_VISUALIZACAO).first
        
        texto = await frame_viz.locator("body").inner_text(timeout=5000)
        match = padrao.search(texto)
        if match:
            return match.group(1)
    except Exception:
        pass
    
    return None


async def extrair_ultimo_documento_arvore(page, tipo_esperado: str) -> Dict[str, Optional[str]]:
    """Extrai último documento da árvore."""
    resultado = {
        "ultimo_item_arvore_texto": None,
        "numero_arvore": None,
        "sei_numero_arvore": None,
    }
    
    padrao_sei = re.compile(r"(\d{10,})")
    padrao_num = re.compile(r"n[ºo°]\s*(\d+)", re.IGNORECASE)
    
    try:
        frame_arvore = page.frame(name="ifrArvore")
        if not frame_arvore:
            return resultado
        
        # Busca links de documentos
        links = frame_arvore.locator("#divArvore a")
        total = await links.count()
        
        # Percorre do último para o primeiro
        for i in range(total - 1, -1, -1):
            link = links.nth(i)
            texto = await link.inner_text()
            texto = _norm_space(texto)
            
            # Verifica se é do tipo esperado
            if tipo_esperado.lower() in texto.lower():
                resultado["ultimo_item_arvore_texto"] = texto
                
                # Extrai número
                match_num = padrao_num.search(texto)
                if match_num:
                    resultado["numero_arvore"] = match_num.group(1)
                
                # Extrai SEI nº
                href = await link.get_attribute("href") or ""
                match_sei = padrao_sei.search(href)
                if match_sei:
                    resultado["sei_numero_arvore"] = match_sei.group(1)
                
                break
    
    except Exception as e:
        debug_print(f"Erro ao ler árvore: {e}")
    
    return resultado


async def tirar_foto_viewer(page, caminho: str) -> bool:
    """Tira screenshot do viewer como prova."""
    debug_print(f"Tirando foto: {caminho}")
    
    try:
        # Tenta foto só do frame de visualização
        frame_pai = page.frame_locator(SELETOR_FRAME_CONTEUDO_PAI).first
        frame_viz = frame_pai.frame_locator(SELETOR_FRAME_VISUALIZACAO).first
        
        elemento = frame_viz.locator("body")
        await elemento.screenshot(path=caminho, timeout=10000)
        return True
    except Exception:
        try:
            # Fallback: foto da página inteira
            await page.screenshot(path=caminho, full_page=True)
            return True
        except Exception as e:
            debug_print(f"Erro ao tirar foto: {e}")
            return False


# =============================================================================
# ATUAÇÃO PRINCIPAL
# =============================================================================

async def atuar_no_processo(
    nup: str,
    tipo_documento: str,
    destinatario: str,
    corpo_html: str,
    chat_id: str = None,
    sigla: str = None,
    # NOVO v4.1: Credenciais diretas
    usuario: str = None,
    senha: str = None,
    orgao_id: str = "31"
) -> Dict:
    """
    Cria um documento em um processo SEI.
    
    Args:
        nup: Número do processo
        tipo_documento: Tipo de documento no SEI (ex: "Memorando", "Despacho")
        destinatario: Destinatário do documento
        corpo_html: Conteúdo HTML do documento
        chat_id: Chat ID do Telegram (para identificar diretoria)
        sigla: Sigla da diretoria
        usuario: Usuário SEI (credencial direta - NOVO v4.1)
        senha: Senha SEI (credencial direta - NOVO v4.1)
        orgao_id: ID do órgão (credencial direta - NOVO v4.1)
    
    Returns:
        Dict com resultado completo da operação
    """
    output = {
        "sucesso": False,
        "nup": nup,
        "tipo_documento": tipo_documento,
        "diretoria": sigla,
        "cabecalho_doc": None,
        "numero_doc": None,
        "sigla_doc": None,
        "sei_numero_editor": None,
        "sei_numero_arvore": None,
        "ultimo_item_arvore_texto": None,
        "numero_arvore": None,
        "id_documento_editor": None,
        "conteudo_injetado": False,
        "preview_texto_editor": None,
        "hash_preview_editor": None,
        "primeiras_10_linhas": [],
        "foto": None,
        "telegram_result": None,
        "documento_criado": False,
        "erro": None,
        "timestamp": datetime.now().isoformat()
    }
    
    try:
        # NOVO v4.1: Passa credenciais diretas para criar_sessao_sei
        async with criar_sessao_sei(
            chat_id=chat_id, 
            sigla=sigla,
            usuario=usuario,
            senha=senha,
            orgao_id=orgao_id
        ) as sessao:
            page = sessao['page']
            context = sessao['context']
            diretoria = sessao['diretoria']
            
            if diretoria:
                output['diretoria'] = diretoria.get('sigla')
            
            # =================================================================
            # 1. BUSCA O PROCESSO
            # =================================================================
            debug_print(f"Buscando processo: {nup}")
            await page.locator("#txtPesquisaRapida").wait_for(state="visible", timeout=15000)
            await page.locator("#txtPesquisaRapida").fill(nup)
            await page.locator("#txtPesquisaRapida").press("Enter")
            await page.wait_for_load_state("networkidle", timeout=60000)
            
            # =================================================================
            # 2. INCLUIR DOCUMENTO
            # =================================================================
            debug_print("Clicando em Incluir Documento...")
            frame_pai = page.frame_locator(SELETOR_FRAME_CONTEUDO_PAI).first
            
            botao = frame_pai.locator("a#btnIncluirDocumento, a[onclick*='incluir_documento']").first
            await botao.wait_for(state="visible", timeout=15000)
            await botao.click()
            await page.wait_for_load_state("networkidle", timeout=30000)
            
            # =================================================================
            # 3. SELECIONAR TIPO DE DOCUMENTO
            # =================================================================
            debug_print(f"Selecionando tipo: {tipo_documento}")
            
            # Aguarda frame carregar
            await page.wait_for_timeout(2000)
            
            # Tenta encontrar o campo de pesquisa
            frame_conteudo = page.frame(name="ifrVisualizacao")
            if not frame_conteudo:
                frame_conteudo = page.frame(name="ifrConteudo")
            
            if frame_conteudo:
                # Pesquisa pelo tipo
                campo_pesq = frame_conteudo.locator("#txtFiltro, #txtPesquisaTipoDocumento, input[type='text']").first
                if await campo_pesq.count():
                    await campo_pesq.fill(tipo_documento)
                    await campo_pesq.press("Enter")
                    await page.wait_for_timeout(1000)
                
                # Clica no tipo
                link_tipo = frame_conteudo.locator(f"a:has-text('{tipo_documento}')").first
                await link_tipo.click(timeout=10000)
            else:
                # Fallback: tenta no frame pai
                link_tipo = frame_pai.locator(f"a:has-text('{tipo_documento}')").first
                await link_tipo.click(timeout=10000)
            
            await page.wait_for_load_state("networkidle", timeout=30000)
            
            # =================================================================
            # 4. FORMULÁRIO - DESTINATÁRIO
            # =================================================================
            if destinatario:
                debug_print(f"Preenchendo destinatário: {destinatario}")
                
                frame_form = page.frame(name="ifrVisualizacao") or page.frame(name="ifrConteudo")
                if frame_form:
                    campo_dest = frame_form.locator("#txtDestinatario, input[name='txtDestinatario']").first
                    if await campo_dest.count():
                        await campo_dest.fill(destinatario)
            
            # =================================================================
            # 5. SALVAR FORMULÁRIO (CONTINUAR)
            # =================================================================
            debug_print("Salvando formulário...")
            
            frame_form = page.frame(name="ifrVisualizacao") or page.frame(name="ifrConteudo")
            if frame_form:
                botao_salvar = frame_form.locator("button#btnSalvar, input[type='submit'][value*='Salvar'], button:has-text('Salvar')").first
                await botao_salvar.click(timeout=10000)
            
            await page.wait_for_load_state("networkidle", timeout=60000)
            
            # =================================================================
            # 6. AGUARDAR POPUP DO EDITOR
            # =================================================================
            debug_print("Aguardando popup do editor...")
            
            page_editor = None
            
            async with context.expect_page(timeout=30000) as page_info:
                # O editor abre em nova aba/popup
                pass
            
            page_editor = await page_info.value
            await page_editor.wait_for_load_state("domcontentloaded", timeout=30000)
            
            debug_print(f"Editor aberto: {page_editor.url}")
            
            # =================================================================
            # 7. ENCONTRAR IFRAME DO CORPO
            # =================================================================
            debug_print("Buscando iframe do corpo...")
            
            frame_corpo = None
            
            for tentativa in range(10):
                # Tenta localizar o iframe do corpo
                iframe = page_editor.frame_locator(SELETOR_IFRAME_CORPO_TEXTO).first
                
                try:
                    body = iframe.locator("body")
                    await body.wait_for(state="attached", timeout=3000)
                    frame_corpo = iframe
                    debug_print("✓ Iframe do corpo encontrado!")
                    break
                except Exception:
                    pass
                
                # Tenta por nome
                for frame in page_editor.frames:
                    if "corpo" in (frame.name or "").lower():
                        frame_corpo = page_editor.frame_locator(f'iframe[name="{frame.name}"]').first
                        debug_print(f"✓ Frame encontrado pelo nome: {frame.name}")
                        break
                
                if frame_corpo:
                    break
                
                await page_editor.wait_for_timeout(1000)
            
            if not frame_corpo:
                output["erro"] = "Não encontrou iframe do corpo do documento"
                await page_editor.close()
                return output
            
            # =================================================================
            # 8. INJETAR CONTEÚDO HTML
            # =================================================================
            debug_print("Injetando conteúdo HTML...")
            
            await frame_corpo.locator("body").evaluate(
                "el => el.innerHTML = arguments[0]",
                corpo_html
            )
            
            await page_editor.wait_for_timeout(1000)
            
            # Coleta prova do que foi inserido
            prova = await coletar_prova_editor(frame_corpo)
            output["preview_texto_editor"] = prova.get("preview_texto_editor", "")[:2000]
            output["hash_preview_editor"] = prova.get("hash_preview_editor")
            output["primeiras_10_linhas"] = prova.get("primeiras_10_linhas", [])
            
            # Validação de overlap (opcional)
            texto_esperado = strip_tags(corpo_html)
            texto_inserido = prova.get("preview_texto_editor", "")
            
            if texto_esperado and texto_inserido:
                # Verifica se pelo menos 60% do conteúdo foi inserido
                palavras_esperadas = set(texto_esperado.lower().split())
                palavras_inseridas = set(texto_inserido.lower().split())
                
                if palavras_esperadas:
                    overlap = len(palavras_esperadas & palavras_inseridas) / len(palavras_esperadas)
                    debug_print(f"Overlap de conteúdo: {overlap:.1%}")
                    
                    if overlap < 0.6:
                        debug_print("⚠ Overlap baixo, mas continuando...")
            
            output["conteudo_injetado"] = True
            
            # =================================================================
            # 9. CAPTURAR DADOS DO EDITOR (ANTES DE SALVAR)
            # =================================================================
            dados_editor = await capturar_dados_completos_editor(page_editor)
            output["sei_numero_editor"] = dados_editor["sei_numero_editor"]
            output["cabecalho_doc"] = dados_editor["cabecalho_doc"]
            output["numero_doc"] = dados_editor["numero_doc"]
            output["sigla_doc"] = dados_editor["sigla_doc"]
            output["id_documento_editor"] = _extrair_id_documento_de_url(page_editor.url or "")
            
            # =================================================================
            # 10. SALVAR DOCUMENTO
            # =================================================================
            debug_print("Salvando documento...")
            await page_editor.get_by_role("button", name="Salvar").click()
            await page_editor.wait_for_load_state("domcontentloaded")
            await page_editor.wait_for_timeout(2000)
            
            # Tenta capturar novamente após salvar (SEI nº pode aparecer só depois)
            if not output["sei_numero_editor"] or not output["cabecalho_doc"]:
                debug_print("Tentando capturar novamente após salvar...")
                dados_editor2 = await capturar_dados_completos_editor(page_editor)
                if not output["sei_numero_editor"]:
                    output["sei_numero_editor"] = dados_editor2["sei_numero_editor"]
                if not output["cabecalho_doc"]:
                    output["cabecalho_doc"] = dados_editor2["cabecalho_doc"]
                    output["numero_doc"] = dados_editor2["numero_doc"]
                    output["sigla_doc"] = dados_editor2["sigla_doc"]
            
            # =================================================================
            # 11. FECHAR EDITOR
            # =================================================================
            debug_print("Fechando editor...")
            await page_editor.close()
            
            # =================================================================
            # 12. AGUARDAR E CAPTURAR DADOS DO VIEWER
            # =================================================================
            debug_print("Aguardando 5 segundos...")
            await asyncio.sleep(5)
            
            debug_print("Capturando dados do viewer...")
            
            # Cabeçalho
            cabecalho = await ler_cabecalho_no_viewer(page)
            if cabecalho and not output["cabecalho_doc"]:
                output["cabecalho_doc"] = cabecalho
                dados_cab = extrair_numero_e_sigla_do_cabecalho(cabecalho)
                output["numero_doc"] = dados_cab["numero_doc"]
                output["sigla_doc"] = dados_cab["sigla_doc"]
            
            # SEI nº
            sei = await extrair_sei_do_viewer(page)
            if sei:
                output["sei_numero_arvore"] = sei
            
            # Árvore (complementar)
            arvore = await extrair_ultimo_documento_arvore(page, tipo_documento)
            if arvore["ultimo_item_arvore_texto"]:
                output["ultimo_item_arvore_texto"] = arvore["ultimo_item_arvore_texto"]
                output["numero_arvore"] = arvore["numero_arvore"]
            if arvore["sei_numero_arvore"] and not output["sei_numero_arvore"]:
                output["sei_numero_arvore"] = arvore["sei_numero_arvore"]
            
            # =================================================================
            # 13. SCREENSHOT (REMOVIDO NESTE SCRIPT)
            #    Confirmação visual ficará APENAS no script de ASSINATURA.
            # =================================================================
            output["foto"] = None
            
            # =================================================================
            # 14. VALIDAÇÕES
            # =================================================================
            erros = []
            if not output["sei_numero_arvore"] and not output["sei_numero_editor"]:
                erros.append("SEI nº não capturado")
            if not output["cabecalho_doc"]:
                erros.append("Cabeçalho não capturado")
            if not output["numero_doc"]:
                erros.append("Número do documento não capturado")
            
            if erros:
                output["erro"] = " | ".join(erros)
                debug_print(f"Erros: {output['erro']}")
            
            # =================================================================
            # 15. TELEGRAM (REMOVIDO NESTE SCRIPT)
            #    (atuar) não envia foto; apenas retorna dados do documento.
            # =================================================================
            output["telegram_result"] = None
            
            # =================================================================
            # 16. RESULTADO FINAL
            # =================================================================
            output["sucesso"] = bool(output["cabecalho_doc"] and output["numero_doc"])
            output["documento_criado"] = output["sucesso"]
            
            # Garante que sei_numero_arvore tenha algum valor
            if not output["sei_numero_arvore"] and output["sei_numero_editor"]:
                output["sei_numero_arvore"] = output["sei_numero_editor"]
            
            if output["sucesso"]:
                output["mensagem"] = f"Documento '{tipo_documento}' criado com sucesso!"
                debug_print(f"✅ Documento criado: {output['cabecalho_doc']}")
            
            return output
    
    except Exception as e:
        output["erro"] = str(e)
        debug_print(f"❌ Erro: {e}")
        import traceback
        traceback.print_exc(file=sys.stderr)
        return output


# =============================================================================
# CLI
# =============================================================================

async def main_async():
    import argparse
    
    parser = argparse.ArgumentParser(description="ARGUS - Atuação em Processo SEI v4.1 (Credenciais Diretas)")
    parser.add_argument("nup", help="Número do processo")
    parser.add_argument("tipo", help="Tipo de documento no SEI")
    parser.add_argument("destinatario", help="Destinatário (use '-' para vazio)")
    parser.add_argument("corpo", help="HTML do corpo OU JSON com template_id")
    parser.add_argument("--chat-id", help="Chat ID do Telegram")
    parser.add_argument("--sigla", help="Sigla da diretoria")
    # NOVO v4.1: Credenciais diretas
    parser.add_argument("--usuario", help="Usuário SEI (credencial direta)")
    parser.add_argument("--senha", help="Senha SEI (credencial direta)")
    parser.add_argument("--orgao", default="31", help="ID do órgão (default: 31)")
    
    args = parser.parse_args()
    
    # Validação: precisa de credenciais diretas OU sigla/chat_id
    if not args.usuario and not args.chat_id and not args.sigla:
        parser.error("Informe --usuario + --senha OU --chat-id OU --sigla")
    
    if args.usuario and not args.senha:
        parser.error("--senha é obrigatório quando usar --usuario")
    
    # Processa corpo (pode ser JSON com template)
    tipo_documento = args.tipo
    destinatario = args.destinatario if args.destinatario != "-" else ""
    corpo_html = args.corpo
    
    try:
        dados = json.loads(args.corpo)
        
        if isinstance(dados, dict):
            # Extrai documento se embrulhado
            if "documento" in dados:
                dados = dados["documento"]
            
            # Tipo SEI do JSON
            if "tipo_sei" in dados:
                tipo_documento = dados["tipo_sei"]
            
            # Destinatário do JSON
            nome_completo = str(dados.get("NOME_COMPLETO", "") or "").strip()
            dest_json = str(dados.get("destinatario", "") or "").strip()
            
            if nome_completo:
                destinatario = nome_completo
            elif dest_json and dest_json not in ("IGNORAR-DEST", "-"):
                destinatario = dest_json
            
            # Corpo HTML ou template
            if "corpo_html" in dados:
                corpo_html = dados["corpo_html"]
            elif "template_id" in dados:
                template_str, tipo_template = carregar_template(dados["template_id"])
                
                if template_str:
                    if not dados.get("tipo_sei") and tipo_template:
                        tipo_documento = tipo_template
                    
                    # Remove campos de controle
                    dados_template = {
                        k: v for k, v in dados.items()
                        if k not in ("template_id", "tipo_sei", "destinatario", "corpo_html")
                    }
                    
                    corpo_html = processar_template(template_str, dados_template)
                else:
                    corpo_html = f"<p>Erro: Template '{dados['template_id']}' não encontrado</p>"
    
    except json.JSONDecodeError:
        pass  # Corpo é HTML direto
    
    resultado = await atuar_no_processo(
        nup=args.nup,
        tipo_documento=tipo_documento,
        destinatario=destinatario,
        corpo_html=corpo_html,
        chat_id=args.chat_id,
        sigla=args.sigla,
        usuario=args.usuario,
        senha=args.senha,
        orgao_id=args.orgao
    )
    
    print(json.dumps(resultado, indent=2, ensure_ascii=False))


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
