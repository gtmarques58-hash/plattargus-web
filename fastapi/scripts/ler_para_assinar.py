#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ler_para_assinar.py - Ler Documento e Assinar com Confirmação

VERSÃO 4.1 - PRODUÇÃO + CREDENCIAIS DIRETAS

Melhorias v4.1:
- Suporte a credenciais diretas (--usuario, --senha, --orgao, --nome, --cargo)
- Mantém compatibilidade com chat_id/sigla (Telegram)

Melhorias v4.0:
- Captura mais conteúdo (scroll + múltiplos frames)
- Limite aumentado para 5000 chars no resumo
- Retorna conteúdo_completo além do resumo
- Tenta múltiplas estratégias de extração
- Faz scroll para carregar conteúdo lazy-load

Fluxo:
  1. Login via Porteiro (pool de sessões)
  2. Busca dados do assinante no banco
  3. Pesquisa pelo SEI nº
  4. Abre documento
  5. Faz scroll + extrai conteúdo (máximo possível)
  6. Retorna dados para confirmação (via Telegram/n8n)
  7. Se confirmado, assina com delicadeza humana
  8. JSON de resultado com foto

Uso:
    # NOVO - Credenciais diretas (Laravel/PlattArgus WEB)
    python ler_para_assinar.py "0018817258" --usuario gilmar.moura --senha xxx --nome "Gilmar Moura" --apenas-ler
    
    # LEGADO - Telegram
    python ler_para_assinar.py "0018817258" --sigla DRH --apenas-ler
    python ler_para_assinar.py "0018817258" --sigla DRH
    python ler_para_assinar.py "0018817258" --chat-id "8152690312"

Dependências:
    pip install playwright httpx
    playwright install chromium
"""

import os
import sys
import re
import json
import asyncio
import argparse
from datetime import datetime
from typing import Optional, Dict, Any
from pathlib import Path

# Caminho do projeto
sys.path.insert(0, "/app/scripts")

from playwright.async_api import async_playwright

# Login/sessão via Porteiro
from sei_auth_multi import criar_sessao_sei

# Para buscar dados do membro
try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False

# Para descriptografar senha
try:
    from crypto_utils import descriptografar_senha, decrypt_password
    HAS_CRYPTO = True
except ImportError:
    try:
        from sei_auth_multi import descriptografar_senha
        HAS_CRYPTO = True
    except ImportError:
        HAS_CRYPTO = False


# =========================================================
# CONFIG
# =========================================================
DEBUG = os.getenv("ARGUS_DEBUG", "0") == "1"

# URL da API de membros
API_MEMBROS_URL = os.getenv("API_MEMBROS_URL", "http://localhost:8000")

# Órgão padrão
ORGAO_PADRAO = "CBMAC"

# Diretório para screenshots
FOTOS_DIR = Path(os.getenv("ARGUS_FOTOS_DIR", "/tmp/argus_fotos"))
FOTOS_DIR.mkdir(exist_ok=True)

# Seletores SEI
SELETOR_PESQUISA_RAPIDA = "#txtPesquisaRapida"

# Limite de caracteres para resumo (cabe no Telegram com margem para formatação)
MAX_RESUMO_CHARS = 3500

# Limite máximo de conteúdo completo (para não estourar memória)
MAX_CONTEUDO_COMPLETO = 50000


# =========================================================
# HELPERS
# =========================================================
def debug_print(msg: str):
    if DEBUG:
        print(f"[DEBUG] {msg}", file=sys.stderr)


def _norm_space(s: str) -> str:
    """Normaliza espaços em uma string."""
    s = (s or "").strip()
    s = re.sub(r"\s+", " ", s)
    return s


# =========================================================
# EXTRAÇÃO DE TEXTO (VERSÃO 4.0 - MELHORADA)
# =========================================================
async def fazer_scroll_documento(frame) -> None:
    """
    Faz scroll no frame do documento para carregar conteúdo lazy-load.
    """
    try:
        # Tenta scroll via JavaScript
        await frame.evaluate("""
            () => {
                const body = document.body;
                if (body) {
                    // Scroll até o final
                    body.scrollTop = body.scrollHeight;
                    
                    // Scroll de volta (para garantir que carregou)
                    setTimeout(() => { body.scrollTop = 0; }, 200);
                }
                
                // Tenta também no documentElement
                const doc = document.documentElement;
                if (doc) {
                    doc.scrollTop = doc.scrollHeight;
                    setTimeout(() => { doc.scrollTop = 0; }, 200);
                }
            }
        """)
        await asyncio.sleep(0.5)
    except Exception as e:
        debug_print(f"Scroll falhou (ignorando): {e}")


async def extrair_texto_completo_frame(frame) -> str:
    """
    Extrai o máximo de texto possível de um frame.
    Tenta múltiplas estratégias.
    """
    textos = []
    
    # Estratégia 1: inner_text do body
    try:
        body = frame.locator("body").first
        if await body.count() > 0:
            texto = (await body.inner_text()).strip()
            if texto:
                textos.append(texto)
    except Exception as e:
        debug_print(f"body.inner_text falhou: {e}")
    
    # Estratégia 2: innerHTML convertido para texto (pega mais conteúdo)
    try:
        html = await frame.evaluate("() => document.body?.innerHTML || ''")
        if html:
            # Remove tags mas preserva quebras
            texto_html = re.sub(r'<br\s*/?>', '\n', html)
            texto_html = re.sub(r'</(p|div|tr|li)>', '\n', texto_html, flags=re.IGNORECASE)
            texto_html = re.sub(r'<[^>]+>', '', texto_html)
            texto_html = re.sub(r'&nbsp;', ' ', texto_html)
            texto_html = re.sub(r'&amp;', '&', texto_html)
            texto_html = re.sub(r'&lt;', '<', texto_html)
            texto_html = re.sub(r'&gt;', '>', texto_html)
            texto_html = texto_html.strip()
            if texto_html and len(texto_html) > len(textos[0] if textos else ""):
                textos = [texto_html]  # Usa o maior
    except Exception as e:
        debug_print(f"innerHTML falhou: {e}")
    
    # Estratégia 3: Busca em elementos específicos de documento
    seletores_conteudo = [
        "#divConteudo",
        "#conteudo",
        ".documento-conteudo",
        ".conteudo-documento",
        "article",
        "main",
        "#corpo",
    ]
    
    for seletor in seletores_conteudo:
        try:
            elem = frame.locator(seletor).first
            if await elem.count() > 0:
                texto = (await elem.inner_text()).strip()
                if texto and len(texto) > 100:
                    if not textos or len(texto) > len(textos[0]):
                        textos = [texto]
                        debug_print(f"Texto encontrado via {seletor}: {len(texto)} chars")
        except Exception:
            continue
    
    # Retorna o maior texto encontrado
    if textos:
        return max(textos, key=len)
    return ""


async def extrair_texto_viewer(page) -> dict:
    """
    Identifica o frame do viewer e extrai o máximo de texto.
    Versão 4.0 - Com scroll e múltiplas estratégias.
    """
    debug_print("Buscando frame do documento...")
    
    # 1) Tenta pelo nome do frame (ifrVisualizacao - case insensitive)
    for fr in page.frames:
        frame_name = (fr.name or "").lower()
        if frame_name == "ifrvisualizacao":
            debug_print(f"Frame encontrado pelo nome: {fr.name}")
            try:
                # Faz scroll para carregar todo o conteúdo
                await fazer_scroll_documento(fr)
                
                text = await extrair_texto_completo_frame(fr)
                if text:
                    return {"frame_name": fr.name, "viewer_url": fr.url, "text": text}
            except Exception as e:
                debug_print(f"Erro ao extrair do frame {fr.name}: {e}")

    # 2) Heurística por URL
    keywords = ["visualizar", "documento", "documento_visualizar", "documento_consultar", 
                "protocolo", "conteudo", "viewer"]
    scored = []
    for fr in page.frames:
        u = (fr.url or "").lower()
        score = sum(1 for k in keywords if k in u)
        if score > 0:
            scored.append((score, fr))
    scored.sort(key=lambda t: t[0], reverse=True)

    for score, fr in scored:
        debug_print(f"Frame candidato por URL: score={score}, url={fr.url[:80]}...")
        try:
            await fazer_scroll_documento(fr)
            text = await extrair_texto_completo_frame(fr)
            if text and len(text) > 100:
                return {"frame_name": fr.name, "viewer_url": fr.url, "text": text}
        except Exception:
            continue

    # 3) Fallback: busca frame com maior conteúdo (exceto menus)
    debug_print("Tentando fallback: maior conteúdo...")
    best_text = ""
    best_frame = None
    
    for fr in page.frames:
        try:
            # Ignora frames de menu/navegação
            url_lower = (fr.url or "").lower()
            if "menu" in url_lower or "arvore" in url_lower:
                continue
            
            await fazer_scroll_documento(fr)
            text = await extrair_texto_completo_frame(fr)
            
            # Ignora frames de menu/navegação pelo conteúdo
            if "txtPesquisaRapida" in text or "infraMenu" in text:
                continue
            
            if len(text) > len(best_text):
                best_text = text
                best_frame = fr
        except Exception:
            continue
    
    if best_frame:
        debug_print(f"Frame selecionado por tamanho: {len(best_text)} chars")
        return {"frame_name": best_frame.name, "viewer_url": best_frame.url, "text": best_text}

    return {"frame_name": None, "viewer_url": None, "text": ""}


def limpar_texto_sei(texto: str) -> str:
    """
    Limpeza heurística (segura) para remover rodapé/metadados do SEI e ruídos comuns.
    Mantém o conteúdo principal.
    Versão 4.0 - Limpeza mais completa.
    """
    if not texto:
        return ""

    t = texto.replace("\r\n", "\n").replace("\r", "\n")

    # 1) Remove rodapé de assinatura eletrônica
    t = re.split(r"Documento assinado eletronicamente por", t, maxsplit=1, flags=re.IGNORECASE)[0]
    
    # 2) Remove rodapé de autenticidade
    t = re.split(r"A autenticidade deste documento pode ser conferida", t, maxsplit=1, flags=re.IGNORECASE)[0]

    # 3) Remove tudo a partir de "Criado por ..." (rodapé do SEI)
    t = re.split(r"\n\s*Criado por\b", t, maxsplit=1, flags=re.IGNORECASE)[0]

    # 4) Remove linha "Referência: Processo nº ... SEI nº ..."
    t = re.sub(r"\n\s*Referência:\s*Processo\s*n[ºo]\s*.*?(?:\n|$)", "\n", t, flags=re.IGNORECASE)

    # 5) Remove linhas com "SEI nº 00...." quando soltas
    t = re.sub(r"\n\s*SEI\s*n[ºo]\s*\d+\s*(?:\n|$)", "\n", t, flags=re.IGNORECASE)

    # 6) Remove blocos típicos de cabeçalho institucional
    header_patterns = [
        r"^\s*ESTADO DO ACRE\s*$",
        r"^\s*GOVERNO DO ESTADO DO ACRE\s*$",
        r"^\s*CORPO DE BOMBEIROS MILITAR\s*$",
        r"^\s*Estrada da Usina,.*$",
        r"^\s*Avenida Governador Edmundo Pinto,.*$",
        r"^\s*Av\.?\s+Governador\s+Edmundo\s+Pinto.*$",
        r"^\s*-\s*Bairro\s+.*CEP.*$",
        r"^\s*Bairro\s+.*CEP.*$",
        r"^\s*CEP\s*[\d.\-]+\s*$",
        r"^\s*Telefone:\s*.*$",
        r"^\s*\(?\d{2}\)?\s*\d{4}[\-.]?\d{4}\s*-?\s*www\..*$",
        r"^\s*\(?\d{2}\)?\s*\d{4}[\-.]?\d{4}\s*$",
        r"^\s*www\.cbmac\.acre\.gov\.br\s*$",
        r"^\s*\d{10,}\s*-\s*www\.cbmac\.acre\.gov\.br\s*$",
        r"^\s*Rio Branco/AC.*$",
    ]
    lines = t.split("\n")
    cleaned_lines = []
    for ln in lines:
        ln_stripped = ln.strip()
        if any(re.match(pat, ln_stripped, flags=re.IGNORECASE) for pat in header_patterns):
            continue
        # Remove linhas que são só telefone/site
        if re.match(r"^\s*\(?\d{2}\)?\d{4,5}[\-.]?\d{4}\s*$", ln_stripped):
            continue
        cleaned_lines.append(ln)
    t = "\n".join(cleaned_lines)

    # 7) Remove múltiplas linhas em branco
    t = re.sub(r"\n{3,}", "\n\n", t)
    
    # 8) Remove espaços em branco no início e fim
    t = t.strip()

    return t


# =========================================================
# BUSCAR DADOS DO ASSINANTE
# =========================================================
async def buscar_dados_assinante(chat_id: str = None, sigla: str = None) -> Dict:
    """
    Busca dados do assinante no banco de diretorias (SQLite direto).
    """
    dados = {
        "login_sei": None,
        "nome_completo": None,
        "cargo_assinatura": "Diretor(a)",
        "senha": None,
        "orgao": ORGAO_PADRAO
    }
    
    try:
        import sqlite3
        
        # Paths dos bancos
        db_diretorias = os.getenv("ARGUS_DIRETORIAS_DB") or os.getenv("ARGUS_DB_PATH") or "/data/argus_diretorias.db"
        db_autoridades = os.getenv("ARGUS_AUTORIDADES_DB", "/data/argus_autoridades.db")
        
        # Fallback para paths do host
        if not os.path.exists(db_diretorias):
            db_diretorias = "/root/secretario-sei/data/argus_diretorias.db"
        if not os.path.exists(db_autoridades):
            db_autoridades = "/root/secretario-sei/data/argus_autoridades.db"
        
        conn = sqlite3.connect(db_diretorias)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Primeiro busca a sigla pelo chat_id se necessário
        if chat_id and not sigla:
            cursor.execute(
                "SELECT sigla FROM membros_diretoria WHERE chat_id = ? AND ativo = 1", 
                (str(chat_id),)
            )
            row = cursor.fetchone()
            if row:
                sigla = row["sigla"]
        
        if not sigla:
            conn.close()
            debug_print("Sigla não encontrada para buscar assinante")
            return dados
        
        debug_print(f"Buscando diretoria: {sigla}")
        
        # Busca dados da diretoria (login, senha, cargo)
        cursor.execute(
            "SELECT sei_usuario, sei_senha_encrypted, nome, cargo_assinatura FROM diretorias WHERE sigla = ? AND ativo = 1", 
            (sigla,)
        )
        row = cursor.fetchone()
        conn.close()
        
        if row:
            dados["login_sei"] = row["sei_usuario"]
            dados["cargo_assinatura"] = row["cargo_assinatura"] or "Diretor(a)"
            
            # Descriptografa senha
            if row["sei_senha_encrypted"]:
                try:
                    from crypto_utils import decrypt_password
                    dados["senha"] = decrypt_password(row["sei_senha_encrypted"])
                    debug_print(f"Senha descriptografada: {len(dados['senha'])} chars")
                except Exception as e:
                    debug_print(f"[ERRO] Descriptografia: {e}")
            
            # Busca nome_atual no banco de autoridades (nome completo)
            try:
                conn_aut = sqlite3.connect(db_autoridades)
                conn_aut.row_factory = sqlite3.Row
                cursor_aut = conn_aut.cursor()
                cursor_aut.execute(
                    "SELECT nome_atual FROM autoridades WHERE chave_busca = ? AND ativo = 1",
                    (sigla,)
                )
                row_aut = cursor_aut.fetchone()
                conn_aut.close()
                
                if row_aut:
                    dados["nome_completo"] = row_aut["nome_atual"]
                else:
                    dados["nome_completo"] = row["nome"]  # Fallback para nome da diretoria
            except Exception:
                dados["nome_completo"] = row["nome"]
            
            debug_print(f"Assinante encontrado: {dados['login_sei']} ({dados['nome_completo']})")
        else:
            debug_print(f"Diretoria {sigla} não encontrada no banco")
        
        return dados
        
    except Exception as e:
        debug_print(f"[ERRO] buscar_dados_assinante: {e}")
        return dados


# =========================================================
# PESQUISA
# =========================================================
async def pesquisar_documento(page, sei_numero: str) -> bool:
    """Pesquisa documento pelo SEI nº."""
    print(f"-> Pesquisando documento SEI nº {sei_numero}...", file=sys.stderr)
    
    try:
        await page.locator(SELETOR_PESQUISA_RAPIDA).wait_for(state="visible", timeout=10000)
        await page.locator(SELETOR_PESQUISA_RAPIDA).fill("")
        await page.locator(SELETOR_PESQUISA_RAPIDA).fill(sei_numero)
        await page.locator(SELETOR_PESQUISA_RAPIDA).press("Enter")
        
        await page.wait_for_load_state("networkidle", timeout=30000)
        await page.wait_for_timeout(2000)
        
        print("-> Documento aberto.", file=sys.stderr)
        return True
        
    except Exception as e:
        print(f"-> Erro na pesquisa: {e}", file=sys.stderr)
        return False


# =========================================================
# EXTRAÇÃO DE DADOS DO DOCUMENTO (VERSÃO 4.0)
# =========================================================
async def extrair_dados_documento(page) -> Dict[str, Any]:
    """
    Extrai todos os dados visíveis do documento.
    Versão 4.0 - Com extração melhorada.
    """
    dados = {
        "cabecalho": None,
        "numero_documento": None,
        "tipo_documento": None,
        "sigla": None,
        "sei_numero": None,
        "conteudo_resumo": None,
        "conteudo_completo": None,
        "conteudo_tamanho": 0,
        "destinatario": None,
        "referencia": None,
        "nup": None,
        "criado_por": None,
        "data_criacao": None,
    }
    
    print("-> Extraindo dados do documento...", file=sys.stderr)
    
    # =========================================================
    # PADRÕES REGEX
    # =========================================================
    
    # Tipos de documento conhecidos no SEI/CBMAC
    tipos_documento = (
        "Despacho|Memorando|Ofício|Termo|Certidão|Ata|Declaração|Parecer|"
        "Nota|Informação|Portaria|Ordem de Serviço|Comunicado|Relatório|"
        "Requerimento|Solicitação|Edital|Contrato|Convênio|Ata de Reunião|"
        "Boletim|Circular|Instrução|Resolução|Deliberação|Aviso|Notificação"
    )
    
    # Padrão para cabeçalho (flexível)
    padrao_cabecalho = re.compile(
        rf"(({tipos_documento})\s*(?:de\s+\w+\s*)?n[ºo°]?\s*(\d+)(?:/\d{{4}})?(?:/CBMAC)?\s*(?:-\s*([A-Z0-9]+))?)",
        re.IGNORECASE
    )
    
    # Padrão alternativo: Nº X/ANO/CBMAC - SIGLA
    padrao_cabecalho_alt = re.compile(
        r"(N[ºo°]\s*(\d+)/(\d{4})/CBMAC\s*-\s*([A-Z0-9]+))",
        re.IGNORECASE
    )
    
    # SEI nº
    padrao_sei = re.compile(r"SEI\s*n[ºo°]?\s*(\d{10,})", re.IGNORECASE)
    
    # Referência / NUP
    padrao_referencia = re.compile(
        r"Refer[êe]ncia:\s*Processo\s*n[ºo°]?\s*([\d.\-/]+)", 
        re.IGNORECASE
    )
    
    # NUP alternativo
    padrao_nup_alt = re.compile(r"(\d{4}\.\d{6}\.\d{5}/\d{4}-\d{2})")
    
    # Criado por
    padrao_criado = re.compile(
        r"Criado por\s+(\S+).*?em\s+(\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}:\d{2})", 
        re.IGNORECASE
    )
    
    # Destinatário
    padroes_destinatario = [
        re.compile(r"Ao?\s*(?:\(À\))?\s*Sr\.?\s*(?:\(a\))?\.?\s*(.+?)(?:\n|Assunto)", re.IGNORECASE),
        re.compile(r"Ao?\s+Senhor\s+(.+?)(?:\n|Assunto)", re.IGNORECASE),
        re.compile(r"Destinatário:\s*(.+?)(?:\n|$)", re.IGNORECASE),
    ]
    
    # =========================================================
    # EXTRAI TEXTO DO VIEWER (VERSÃO MELHORADA)
    # =========================================================
    viewer = await extrair_texto_viewer(page)
    texto_bruto = viewer.get("text", "")
    
    debug_print(f"Texto bruto extraído: {len(texto_bruto)} chars")
    
    if not texto_bruto:
        debug_print("Nenhum texto extraído do viewer")
        return dados
    
    # Salva tamanho do conteúdo original
    dados["conteudo_tamanho"] = len(texto_bruto)
    
    # =========================================================
    # EXTRAI METADADOS (ANTES DA LIMPEZA)
    # =========================================================
    
    # SEI nº
    match = padrao_sei.search(texto_bruto)
    if match:
        dados["sei_numero"] = match.group(1)
        debug_print(f"SEI nº: {dados['sei_numero']}")
    
    # Referência / NUP
    match = padrao_referencia.search(texto_bruto)
    if match:
        dados["referencia"] = _norm_space(match.group(1))
        dados["nup"] = dados["referencia"]
        debug_print(f"Referência: {dados['referencia']}")
    else:
        match = padrao_nup_alt.search(texto_bruto)
        if match:
            dados["nup"] = match.group(1)
            debug_print(f"NUP (alt): {dados['nup']}")
    
    # Criado por
    match = padrao_criado.search(texto_bruto)
    if match:
        dados["criado_por"] = match.group(1)
        dados["data_criacao"] = match.group(2)
        debug_print(f"Criado por: {dados['criado_por']} em {dados['data_criacao']}")
    
    # Cabeçalho
    match = padrao_cabecalho.search(texto_bruto)
    if match:
        dados["cabecalho"] = _norm_space(match.group(1))
        dados["tipo_documento"] = match.group(2)
        dados["numero_documento"] = match.group(3) if match.group(3) else None
        dados["sigla"] = match.group(4).upper() if match.group(4) else None
        debug_print(f"Cabeçalho: {dados['cabecalho']}")
    else:
        match = padrao_cabecalho_alt.search(texto_bruto)
        if match:
            dados["cabecalho"] = _norm_space(match.group(1))
            dados["numero_documento"] = match.group(2)
            dados["sigla"] = match.group(4).upper() if match.group(4) else None
            debug_print(f"Cabeçalho (alt): {dados['cabecalho']}")
    
    # Destinatário
    for padrao in padroes_destinatario:
        match = padrao.search(texto_bruto)
        if match:
            dados["destinatario"] = _norm_space(match.group(1))
            debug_print(f"Destinatário: {dados['destinatario']}")
            break
    
    # =========================================================
    # LIMPA E GERA RESUMO
    # =========================================================
    texto_limpo = limpar_texto_sei(texto_bruto)
    
    # Conteúdo completo (limitado para não estourar memória)
    if len(texto_limpo) > MAX_CONTEUDO_COMPLETO:
        dados["conteudo_completo"] = texto_limpo[:MAX_CONTEUDO_COMPLETO] + "\n\n[...TRUNCADO...]"
    else:
        dados["conteudo_completo"] = texto_limpo
    
    # Gera resumo (primeiros N caracteres do texto limpo)
    if texto_limpo:
        if len(texto_limpo) > MAX_RESUMO_CHARS:
            dados["conteudo_resumo"] = texto_limpo[:MAX_RESUMO_CHARS] + "..."
        else:
            dados["conteudo_resumo"] = texto_limpo
        
        debug_print(f"Resumo gerado: {len(dados['conteudo_resumo'])} chars")
        debug_print(f"Conteúdo completo: {len(dados['conteudo_completo'])} chars")
    
    return dados


# =========================================================
# CLICAR EM ASSINAR
# =========================================================
async def clicar_botao_assinar(page) -> bool:
    """Clica no botão/ícone de Assinar."""
    debug_print("Procurando botão Assinar...")
    
    seletores = [
        'img[title="Assinar Documento"]',
        'img[alt="Assinar Documento"]',
        'a[title="Assinar Documento"]',
        '#btnAssinar',
        'img[src*="assinar"]',
    ]
    
    for frame in page.frames:
        for seletor in seletores:
            try:
                btn = frame.locator(seletor).first
                if await btn.count() > 0:
                    await btn.click(force=True)
                    print("-> Clicou em Assinar", file=sys.stderr)
                    await page.wait_for_timeout(1000)
                    return True
            except Exception:
                continue
    
    # Fallback via role
    for frame in page.frames:
        try:
            btn = frame.get_by_role("img", name="Assinar Documento").first
            if await btn.count() > 0:
                await btn.click(force=True)
                print("-> Clicou em Assinar (via role)", file=sys.stderr)
                await page.wait_for_timeout(1000)
                return True
        except Exception:
            continue
    
    print("-> Botão Assinar não encontrado.", file=sys.stderr)
    return False


# =========================================================
# PREENCHER MODAL E ASSINAR
# =========================================================
async def preencher_modal_e_assinar(
    page,
    orgao: str,
    login_sei: str,
    nome_completo: str,
    cargo: str,
    senha: str
) -> dict:
    """
    Preenche o modal de assinatura e confirma.
    """
    resultado = {"assinado": False, "erro": None}
    
    try:
        # 1) AGUARDA MODAL
        print("-> Aguardando modal de assinatura...", file=sys.stderr)
        frame_modal = None
        for _ in range(30):
            frame_modal = page.frame(name="modal-frame")
            if frame_modal:
                break
            await page.wait_for_timeout(300)
        
        if not frame_modal:
            resultado["erro"] = "Modal de assinatura não apareceu."
            return resultado
        
        await page.wait_for_timeout(500)
        
        # 2) SELECIONA CARGO (Diretor, etc.)
        print("-> Selecionando cargo...", file=sys.stderr)
        select_cargo = frame_modal.locator("#selCargoFuncao, select[name*='cargo'], select[name*='Cargo']").first
        if await select_cargo.count() > 0:
            options = select_cargo.locator("option")
            for i in range(await options.count()):
                opt_text = await options.nth(i).text_content()
                opt_value = await options.nth(i).get_attribute("value")
                if opt_value and cargo.lower() in (opt_text or "").lower():
                    await select_cargo.select_option(value=opt_value)
                    print(f"   Cargo selecionado: {opt_text}", file=sys.stderr)
                    break
        
        await page.wait_for_timeout(300)
        
        # 3) SELECIONA USUÁRIO
        print("-> Selecionando usuário...", file=sys.stderr)
        select_usuario = frame_modal.locator("#selUsuario, select[name*='usuario'], select[name*='Usuario']").first
        if await select_usuario.count() > 0:
            await page.wait_for_timeout(500)
            options = select_usuario.locator("option")
            login_lower = login_sei.lower()
            nome_lower = nome_completo.lower() if nome_completo else ""
            
            for i in range(await options.count()):
                opt_text = (await options.nth(i).text_content() or "").lower()
                opt_value = await options.nth(i).get_attribute("value")
                
                if opt_value and (login_lower in opt_text or nome_lower in opt_text):
                    await select_usuario.select_option(value=opt_value)
                    print(f"   Usuário selecionado: {opt_text}", file=sys.stderr)
                    break
        
        await page.wait_for_timeout(300)
        
        # 4) PREENCHE SENHA
        print("-> Preenchendo senha...", file=sys.stderr)
        input_senha = frame_modal.locator("#txtSenha, input[type='password'], input[name*='senha'], input[name*='Senha']").first
        if await input_senha.count() > 0:
            await input_senha.fill(senha)
            print(f"   Senha preenchida: {'*' * len(senha)}", file=sys.stderr)
        else:
            resultado["erro"] = "Campo de senha não encontrado."
            return resultado
        
        await page.wait_for_timeout(500)
        
        # 5) CLICA EM ASSINAR
        print("-> Clicando em Assinar...", file=sys.stderr)
        btn_assinar = frame_modal.locator("#btnAssinar, button:has-text('Assinar'), input[value='Assinar']").first
        if await btn_assinar.count() > 0:
            await btn_assinar.click()
        else:
            # Fallback
            btn_assinar = frame_modal.get_by_role("button", name="Assinar").first
            if await btn_assinar.count() > 0:
                await btn_assinar.click()
            else:
                resultado["erro"] = "Botão Assinar do modal não encontrado."
                return resultado
        
        await page.wait_for_timeout(2000)
        
        # 6) VERIFICA SE DEU CERTO
        # Pode aparecer mensagem de erro
        try:
            erro_elem = frame_modal.locator(".infraErro, .erro, #divErro, .alert-danger").first
            if await erro_elem.count() > 0 and await erro_elem.is_visible():
                erro_texto = await erro_elem.inner_text()
                if erro_texto.strip():
                    resultado["erro"] = erro_texto.strip()
                    return resultado
        except Exception:
            pass
        
        # 7) FECHA MODAL DE CONFIRMAÇÃO (se houver)
        for texto in ["OK", "Confirmar", "Fechar"]:
            try:
                btn_conf = frame_modal.get_by_role("button", name=texto).first
                if await btn_conf.count() > 0 and await btn_conf.is_visible():
                    await btn_conf.click()
                    break
            except Exception:
                pass
        
        # 8) AGUARDA FECHAR
        for _ in range(80):
            if page.frame(name="modal-frame") is None:
                print("-> Modal fechado: assinatura concluída!", file=sys.stderr)
                resultado["assinado"] = True
                return resultado
            await page.wait_for_timeout(200)
        
        resultado["erro"] = "Modal não fechou."
        return resultado
        
    except Exception as e:
        resultado["erro"] = str(e)
        return resultado


# =========================================================
# FUNÇÃO PRINCIPAL
# =========================================================
async def ler_para_assinar(
    sei_numero: str,
    chat_id: str = None,
    sigla: str = None,
    apenas_ler: bool = False,
    # NOVO v4.1: Credenciais diretas (Laravel/PlattArgus WEB)
    usuario: str = None,
    senha: str = None,
    orgao_id: str = "31",
    nome_completo: str = None,
    cargo: str = None
) -> Dict[str, Any]:
    """
    Lê documento e opcionalmente assina.
    """
    output = {
        "sucesso": False,
        "ok": False,
        "sei_numero": sei_numero,
        "cabecalho": None,
        "tipo_documento": None,
        "numero_documento": None,
        "sigla": None,
        "nup": None,
        "referencia": None,
        "destinatario": None,
        "criado_por": None,
        "data_criacao": None,
        "conteudo_resumo": None,
        "conteudo_completo": None,
        "conteudo_tamanho": 0,
        "assinante": None,
        "cargo": None,
        "diretoria": sigla,
        "apenas_leitura": apenas_ler,
        "documento_aberto": False,
        "dados_extraidos": False,
        "assinado": False,
        "foto": None,
        "erro": None,
        "timestamp": datetime.now().isoformat()
    }
    
    senha_temp = None
    
    try:
        # =====================================================
        # NOVO v4.1: Credenciais diretas OU busca do banco
        # =====================================================
        if usuario and senha:
            # Credenciais diretas (Laravel/PlattArgus WEB)
            print(f"-> Usando credenciais diretas: {usuario}", file=sys.stderr)
            dados_assinante = {
                "login_sei": usuario,
                "senha": senha,
                "nome_completo": nome_completo or usuario,
                "cargo_assinatura": cargo or "Diretor(a)",
                "orgao": "CBMAC" if orgao_id == "31" else f"Órgão {orgao_id}"
            }
        else:
            # LEGADO: Busca dados do assinante no banco (Telegram)
            print("-> Buscando dados do assinante...", file=sys.stderr)
            dados_assinante = await buscar_dados_assinante(chat_id=chat_id, sigla=sigla)
        
        # Se vai assinar, precisa de senha
        if not apenas_ler:
            if not dados_assinante.get("senha"):
                output["erro"] = "Senha do assinante não encontrada"
                return output
            
            if not dados_assinante.get("login_sei"):
                output["erro"] = "Login SEI do assinante não encontrado"
                return output
            
            senha_temp = dados_assinante["senha"]
        
        output["assinante"] = dados_assinante.get("nome_completo")
        output["cargo"] = dados_assinante.get("cargo_assinatura")
        
        # 2) ABRE SESSÃO SEI (com credenciais diretas ou sigla/chat_id)
        async with criar_sessao_sei(chat_id=chat_id, sigla=sigla, usuario=usuario, senha=senha, orgao_id=orgao_id) as sessao:
            page = sessao['page']
            diretoria = sessao.get('diretoria', {})
            
            if diretoria:
                output['diretoria'] = diretoria.get('sigla')
            
            # 3) PESQUISA DOCUMENTO
            if not await pesquisar_documento(page, sei_numero):
                output["erro"] = "Falha ao pesquisar documento"
                return output
            
            output["documento_aberto"] = True
            
            # 4) EXTRAI DADOS (versão 4.0)
            dados = await extrair_dados_documento(page)
            
            output["cabecalho"] = dados["cabecalho"]
            output["tipo_documento"] = dados["tipo_documento"]
            output["numero_documento"] = dados["numero_documento"]
            output["sigla"] = dados["sigla"]
            output["sei_numero"] = dados["sei_numero"] or sei_numero
            output["nup"] = dados["nup"]
            output["referencia"] = dados["referencia"]
            output["destinatario"] = dados["destinatario"]
            output["criado_por"] = dados["criado_por"]
            output["data_criacao"] = dados["data_criacao"]
            output["conteudo_resumo"] = dados["conteudo_resumo"]
            output["conteudo_completo"] = dados["conteudo_completo"]
            output["conteudo_tamanho"] = dados["conteudo_tamanho"]
            output["dados_extraidos"] = True
            
            # Log dos dados
            print(f"\n{'=' * 60}", file=sys.stderr)
            print("  📄 DADOS DO DOCUMENTO", file=sys.stderr)
            print("=" * 60, file=sys.stderr)
            if output["cabecalho"]:
                print(f"  📋 Cabeçalho: {output['cabecalho']}", file=sys.stderr)
            if output["sei_numero"]:
                print(f"  🔢 SEI nº: {output['sei_numero']}", file=sys.stderr)
            if output["nup"]:
                print(f"  📁 Processo: {output['nup']}", file=sys.stderr)
            if output["destinatario"]:
                print(f"  👤 Destinatário: {output['destinatario']}", file=sys.stderr)
            if output["criado_por"]:
                print(f"  ✍️  Criado por: {output['criado_por']}", file=sys.stderr)
            if output["conteudo_tamanho"]:
                print(f"  📏 Tamanho: {output['conteudo_tamanho']} chars", file=sys.stderr)
            if output["conteudo_resumo"]:
                print(f"  📝 Conteúdo (resumo):", file=sys.stderr)
                print("  " + "-" * 40, file=sys.stderr)
                for linha in output["conteudo_resumo"].split('\n')[:10]:
                    print(f"  {linha[:70]}{'...' if len(linha) > 70 else ''}", file=sys.stderr)
                if len(output["conteudo_resumo"].split('\n')) > 10:
                    print(f"  ... e mais {len(output['conteudo_resumo'].split(chr(10))) - 10} linhas", file=sys.stderr)
                print("  " + "-" * 40, file=sys.stderr)
            print("=" * 60, file=sys.stderr)
            
            # 5) SE APENAS LEITURA, RETORNA AQUI
            if apenas_ler:
                output["sucesso"] = True
                output["ok"] = True
                return output
            
            # 6) ASSINA
            print("\n-> Iniciando assinatura...", file=sys.stderr)
            
            if not await clicar_botao_assinar(page):
                output["erro"] = "Botão Assinar não encontrado"
                return output
            
            resultado_modal = await preencher_modal_e_assinar(
                page=page,
                orgao=dados_assinante.get("orgao", ORGAO_PADRAO),
                login_sei=dados_assinante["login_sei"],
                nome_completo=dados_assinante["nome_completo"],
                cargo=dados_assinante["cargo_assinatura"],
                senha=senha_temp
            )
            
            output["assinado"] = resultado_modal.get("assinado", False)
            
            if resultado_modal.get("erro"):
                output["erro"] = resultado_modal["erro"]
            
            # 7) SCREENSHOT
            if output["assinado"]:
                await page.wait_for_timeout(2000)
                foto_nome = f"assinado_{sei_numero}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                output["foto"] = str(FOTOS_DIR / foto_nome)
                try:
                    await page.screenshot(path=output["foto"], full_page=True)
                    debug_print(f"Foto salva: {output['foto']}")
                except Exception:
                    pass
            
            # 8) RESULTADO
            output["sucesso"] = output["assinado"] if not apenas_ler else True
            output["ok"] = output["sucesso"]
            
            if output["assinado"]:
                output["mensagem"] = f"Documento {sei_numero} assinado com sucesso!"
                print(f"\n✅ DOCUMENTO {sei_numero} ASSINADO COM SUCESSO!\n", file=sys.stderr)
            
            return output
    
    except Exception as e:
        output["erro"] = str(e)
        debug_print(f"Erro: {e}")
        import traceback
        traceback.print_exc(file=sys.stderr)
        return output
    
    finally:
        if senha_temp:
            senha_temp = None
            del senha_temp


# =========================================================
# CLI
# =========================================================
async def main_async():
    global DEBUG
    
    parser = argparse.ArgumentParser(description="ARGUS - Ler e Assinar Documento SEI v4.1 (Credenciais Diretas)")
    parser.add_argument("sei_numero", help="Número SEI do documento")
    parser.add_argument("--chat-id", help="Chat ID do Telegram")
    parser.add_argument("--sigla", help="Sigla da diretoria")
    parser.add_argument("--apenas-ler", action="store_true", help="Só lê, não assina")
    # NOVO v4.1: Credenciais diretas
    parser.add_argument("--usuario", help="Usuário SEI (credencial direta)")
    parser.add_argument("--senha", help="Senha SEI (credencial direta)")
    parser.add_argument("--orgao", default="31", help="ID do órgão (default: 31)")
    parser.add_argument("--nome", help="Nome completo para assinatura")
    parser.add_argument("--cargo", help="Cargo para assinatura")
    parser.add_argument("--debug", action="store_true", help="Mostra diagnósticos")
    
    args = parser.parse_args()
    
    # Validação: precisa de credenciais diretas OU sigla/chat_id
    if not args.usuario and not args.chat_id and not args.sigla:
        parser.error("Informe --usuario + --senha OU --chat-id OU --sigla")
    
    if args.usuario and not args.senha:
        parser.error("--senha é obrigatório quando usar --usuario")
    
    DEBUG = args.debug
    
    resultado = await ler_para_assinar(
        sei_numero=args.sei_numero,
        chat_id=args.chat_id,
        sigla=args.sigla,
        apenas_ler=args.apenas_ler,
        usuario=args.usuario,
        senha=args.senha,
        orgao_id=args.orgao,
        nome_completo=args.nome,
        cargo=args.cargo
    )
    
    print(json.dumps(resultado, indent=2, ensure_ascii=False))


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
