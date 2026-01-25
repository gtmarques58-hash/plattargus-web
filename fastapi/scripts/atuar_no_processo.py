#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
atuar_no_processo.py - Criação de Documentos SEI Multi-Diretoria

VERSÃO 4.1 - PRODUÇÃO COMPLETA + CREDENCIAIS DIRETAS

Recursos:
- Login via sei_auth_multi (multi-diretoria)
- Suporte a credenciais diretas (--usuario, --senha, --orgao)
- Suporte a templates
- Extração completa: SEI nº, Cabeçalho, Número do documento
- Hash SHA256 como prova jurídica
- Validação de conteúdo (overlap 60%)
- Envio opcional para Telegram
- JSON rico de retorno

Uso:
    # Credenciais diretas (Laravel/PlattArgus WEB)
    python atuar_no_processo.py "NUP" "Tipo" "Destinatário" "HTML" --usuario gilmar.moura --senha xxx --orgao 31

    # Telegram (legado)
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
        except Exception as e:
            debug_print(f"Erro HTML: {e}")
        
        # Se encontrou tudo, retorna
        if resultado["sei_numero_editor"] and resultado["cabecalho_doc"]:
            return resultado
        
        # Espera um pouco antes de tentar novamente
        await page_editor.wait_for_timeout(500)
    
    debug_print(f"Dados parciais extraídos: {resultado}")
    return resultado


async def ler_cabecalho_no_viewer(page) -> Optional[str]:
    """Lê o cabeçalho do documento no viewer após salvar."""
    debug_print("Lendo cabeçalho no viewer...")
    
    padrao = re.compile(
        r"((Despacho|Memorando|Ofício|Termo)\s*n[ºo°]\s*\d+/\d{4}/CBMAC\s*-\s*[A-Z0-9]+)",
        re.IGNORECASE
    )
    
    try:
        # Tenta no frame de visualização
        frame_pai = page.frame_locator(SELETOR_FRAME_CONTEUDO_PAI).first
        frame_viz = frame_pai.frame_locator(SELETOR_FRAME_VISUALIZACAO).first
        
        texto = await frame_viz.locator("body").inner_text(timeout=5000)
        match = padrao.search(texto)
        
        if match:
            cab = _norm_space(match.group(1))
            debug_print(f"Cabeçalho encontrado no viewer: {cab}")
            return cab
    except Exception as e:
        debug_print(f"Erro ao ler viewer: {e}")
    
    return None


async def extrair_sei_do_viewer(page) -> Optional[str]:
    """Extrai SEI nº do viewer."""
    debug_print("Buscando SEI nº no viewer...")
    
    padrao = re.compile(r"SEI\s*n[ºo°]?\s*(\d{10,})", re.IGNORECASE)
    
    try:
        frame_pai = page.frame_locator(SELETOR_FRAME_CONTEUDO_PAI).first
        frame_viz = frame_pai.frame_locator(SELETOR_FRAME_VISUALIZACAO).first
        
        texto = await frame_viz.locator("body").inner_text(timeout=5000)
        match = padrao.search(texto)
        
        if match:
            sei = match.group(1)
            debug_print(f"SEI nº no viewer: {sei}")
            return sei
    except Exception as e:
        debug_print(f"Erro ao buscar SEI nº: {e}")
    
    return None


async def extrair_ultimo_documento_arvore(page, tipo_documento: str = "Despacho") -> Dict[str, Optional[str]]:
    """Extrai o último documento da árvore do processo."""
    debug_print("Extraindo último documento da árvore...")
    
    resultado = {
        "ultimo_item_arvore_texto": None,
        "numero_arvore": None,
        "sei_numero_arvore": None,
    }
    
    # Padrão: "Despacho 86 (0018817133)"
    padrao = re.compile(
        rf"({tipo_documento})\s*(\d+)\s*\((\d{{10,}})\)",
        re.IGNORECASE
    )
    
    try:
        frame_arvore = page.frame_locator(SELETOR_FRAME_ARVORE).first
        texto = await frame_arvore.locator("#divArvore").inner_text(timeout=5000)
        
        # Encontra todas as ocorrências e pega a última
        matches = list(padrao.finditer(texto))
        
        if matches:
            ultimo = matches[-1]
            resultado["ultimo_item_arvore_texto"] = _norm_space(ultimo.group(0))
            resultado["numero_arvore"] = ultimo.group(2)
            resultado["sei_numero_arvore"] = ultimo.group(3)
            debug_print(f"Árvore: {resultado['ultimo_item_arvore_texto']}")
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
        usuario: Usuário SEI (credencial direta)
        senha: Senha SEI (credencial direta)
        orgao_id: ID do órgão (credencial direta)
    
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
        async with criar_sessao_sei(
            chat_id=chat_id, sigla=sigla,
            usuario=usuario, senha=senha, orgao_id=orgao_id
        ) as sessao:
            page = sessao['page']
            context = sessao['context']
            diretoria = sessao['diretoria']
            
            if diretoria:
                output['diretoria'] = diretoria['sigla']
            
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
            btn_incluir = frame_pai.get_by_role("img", name="Incluir Documento", exact=True).first
            await btn_incluir.wait_for(state="visible", timeout=15000)
            await btn_incluir.click()
            await page.wait_for_timeout(1500)
            
            # =================================================================
            # 3. SELECIONAR TIPO DE DOCUMENTO
            # =================================================================
            debug_print(f"Selecionando tipo: {tipo_documento}")
            frame_selecao = frame_pai.frame_locator(SELETOR_FRAME_VISUALIZACAO).first
            
            await frame_selecao.locator("#txtFiltro").click()
            await frame_selecao.locator("#txtFiltro").fill(tipo_documento)
            await page.wait_for_timeout(1000)
            await frame_selecao.locator("#txtFiltro").press("Enter")
            await page.wait_for_timeout(500)
            
            await frame_selecao.get_by_role("link", name=tipo_documento, exact=True).first.click()
            
            # =================================================================
            # 4. NÍVEL DE ACESSO: PÚBLICO
            # =================================================================
            debug_print("Configurando nível de acesso...")
            try:
                await frame_selecao.locator("#divOptPublico").wait_for(state="visible", timeout=2000)
                await frame_selecao.locator("#divOptPublico > .infraRadioDiv > .infraRadioLabel").click()
                debug_print("Marcado como público")
            except Exception:
                debug_print("Opção público não encontrada (ok)")
            
            # =================================================================
            # 5. ABRIR EDITOR (NOVA JANELA)
            # =================================================================
            debug_print("Abrindo editor...")
            async with context.expect_page() as page_promise:
                try:
                    await frame_selecao.get_by_role("button", name="Confirmar Dados").first.click(timeout=5000, force=True)
                except Exception:
                    try:
                        await frame_selecao.get_by_role("button", name="Salvar").first.click(timeout=5000, force=True)
                    except Exception:
                        await frame_selecao.locator("#btnSalvar, #btnConfirmar, button[value='Salvar'], button[value='Confirmar Dados']").first.click(timeout=5000, force=True)
            
            page_editor = await page_promise.value
            await page_editor.wait_for_load_state("domcontentloaded")
            debug_print("Editor aberto")
            
            # =================================================================
            # 6. ENDEREÇAMENTO (SE HOUVER)
            # =================================================================
            if destinatario and destinatario.strip():
                debug_print(f"Preenchendo destinatário: {destinatario}")
                try:
                    frame_end = page_editor.frame_locator(
                        'iframe[title*="Endereçamento"], iframe[title*="Destinatário"]'
                    ).first

                    # Formata o destinatário como HTML válido
                    # Converte quebras de linha para <br> e envolve em <p>
                    dest_html = destinatario.strip()
                    dest_html = dest_html.replace("\n", "<br>")
                    dest_html = f"<p>{dest_html}</p>"

                    # Escapa backticks para uso em template string JS
                    dest_escapado = dest_html.replace("`", "\\`")

                    await frame_end.locator("body").evaluate(
                        f"el => el.innerHTML = `{dest_escapado}`"
                    )
                    debug_print(f"Destinatário injetado: {dest_html[:100]}...")
                except Exception as e:
                    # Se não conseguir, adiciona no corpo
                    debug_print(f"Erro ao preencher endereçamento: {e}")
                    corpo_html = f"<p><strong>AO SR(A). {destinatario}</strong></p><br>{corpo_html}"
            
            # =================================================================
            # 7. INJETAR CONTEÚDO
            # =================================================================
            debug_print("Injetando conteúdo...")
            await page_editor.wait_for_selector(SELETOR_IFRAME_CORPO_TEXTO, timeout=30000)
            frame_editor = page_editor.frame_locator(SELETOR_IFRAME_CORPO_TEXTO).first
            
            corpo_escapado = corpo_html.replace("`", "\\`")
            await frame_editor.locator("body").evaluate(f"el => el.innerHTML = `{corpo_escapado}`")
            debug_print("Conteúdo injetado")
            
            # =================================================================
            # 8. COLETAR PROVA ANTES DE SALVAR
            # =================================================================
            prova = await coletar_prova_editor(frame_editor)
            output.update(prova)
            
            # Validação de conteúdo
            esperado_txt = strip_tags(corpo_html)
            got_txt = _norm_space(output["preview_texto_editor"] or "")
            
            if esperado_txt and esperado_txt not in got_txt:
                exp_words = {w for w in re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9]+", esperado_txt.lower()) if len(w) >= 3}
                got_words = {w for w in re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9]+", got_txt.lower()) if len(w) >= 3}
                
                if exp_words:
                    overlap = len(exp_words & got_words) / max(1, len(exp_words))
                    if overlap < 0.60:
                        output["erro"] = "Conteúdo no editor não corresponde ao esperado. Abortado."
                        await page_editor.close()
                        return output
            
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
    parser.add_argument("--usuario", help="Usuário SEI (credencial direta)")
    parser.add_argument("--senha", help="Senha SEI (credencial direta)")
    parser.add_argument("--orgao", default="31", help="ID do órgão (default: 31)")

    args = parser.parse_args()

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
