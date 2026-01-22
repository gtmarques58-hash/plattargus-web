#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
listar_docs_bloco.py - Listagem de Documentos em Bloco de Assinatura SEI

VERSÃO 3.2 - PRODUÇÃO + CREDENCIAIS DIRETAS

Melhorias v3.2:
  - Suporte a credenciais diretas (--usuario, --senha, --orgao, --nome)
  - Mantém compatibilidade com chat_id/sigla (Telegram)

Melhorias v3.1:
  - Busca nome do assinante no banco de AUTORIDADES (nome_atual)
  - Fluxo: chat_id → membros_diretoria.sigla → autoridades.nome_atual
  - Verifica se SEU NOME (do banco) está nas assinaturas do documento
  - Lista TODOS os documentos, mesmo com múltiplas assinaturas
  - Retorna número SEI do documento para permitir "ver documento"
  - Separa assinaturas em lista para visualização
  - Fallback automático de paths para funcionar em host ou container

Fluxo:
  1. Busca nome do assinante: chat_id → sigla → nome_atual
  2. Login via sei_auth_multi (multi-diretoria)
  3. Navega: Menu → Blocos → Assinatura
  4. Pesquisa o bloco pelo número
  5. Abre o bloco
  6. Lê a tabela de documentos
  7. Identifica PENDENTES (você ainda não assinou) vs JÁ ASSINADOS (você já assinou)
  8. Retorna JSON estruturado

Bancos utilizados:
  - argus_diretorias.db: membros_diretoria (chat_id → sigla)
  - argus_autoridades.db: autoridades (sigla/chave_busca → nome_atual)

Uso:
    # NOVO - Credenciais diretas (Laravel/PlattArgus WEB)
    python listar_docs_bloco.py "845468" --usuario gilmar.moura --senha xxx --nome "Gilmar Moura"
    
    # LEGADO - Telegram
    python listar_docs_bloco.py "845468" --chat-id "8152690312"
    python listar_docs_bloco.py "845468" --sigla DRH
    python listar_docs_bloco.py "845468" --sigla DRH --debug

Dependências:
    pip install playwright httpx
    playwright install chromium
"""

import sys
import os
import json
import asyncio
import argparse
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

# Caminho do projeto
sys.path.insert(0, "/app/scripts")

from playwright.async_api import (
    async_playwright,
    TimeoutError as PWTimeoutError,
    Error as PWError
)

# Login/sessão multi-diretoria
from sei_auth_multi import criar_sessao_sei

# Para buscar dados do membro
try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False


# =========================================================
# CONFIG
# =========================================================
DEBUG = os.getenv("ARGUS_DEBUG", "0") == "1"

# URL da API de membros
API_MEMBROS_URL = os.getenv("API_MEMBROS_URL", "http://localhost:8000")


# =========================================================
# HELPERS
# =========================================================
def debug_print(msg: str):
    if DEBUG:
        print(f"[DEBUG] {msg}", file=sys.stderr)


async def debug_frames(page, title="FRAMES"):
    if not DEBUG:
        return
    print("\n" + "=" * 70, file=sys.stderr)
    print(title, file=sys.stderr)
    print("=" * 70, file=sys.stderr)
    for f in page.frames:
        url_short = (f.url or "")[:80]
        print(f"  name={f.name!r}  url={url_short}...", file=sys.stderr)
    print("=" * 70 + "\n", file=sys.stderr)


def normalizar_nome(nome: str) -> str:
    """Normaliza nome para comparação (remove acentos, upper, etc.)"""
    if not nome:
        return ""
    
    # Mapa de acentos
    acentos = {
        'á': 'a', 'à': 'a', 'ã': 'a', 'â': 'a', 'ä': 'a',
        'é': 'e', 'è': 'e', 'ê': 'e', 'ë': 'e',
        'í': 'i', 'ì': 'i', 'î': 'i', 'ï': 'i',
        'ó': 'o', 'ò': 'o', 'õ': 'o', 'ô': 'o', 'ö': 'o',
        'ú': 'u', 'ù': 'u', 'û': 'u', 'ü': 'u',
        'ç': 'c', 'ñ': 'n'
    }
    
    nome = nome.upper().strip()
    for acento, letra in acentos.items():
        nome = nome.replace(acento.upper(), letra.upper())
    
    # Remove múltiplos espaços
    nome = " ".join(nome.split())
    
    return nome


def extrair_sei_numero(documento_texto: str) -> str:
    """Extrai o número SEI do texto do documento."""
    # Padrão: 10 dígitos seguidos
    match = re.search(r'\b(\d{10})\b', documento_texto)
    if match:
        return match.group(1)
    
    # Padrão: número com hífen (ex: 0019076772)
    match = re.search(r'(\d{7,10})', documento_texto)
    if match:
        return match.group(1).zfill(10)
    
    return documento_texto.strip()


def verificar_assinatura_presente(assinaturas_texto: str, nome_assinante: str) -> bool:
    """
    Verifica se o nome do assinante está presente nas assinaturas.
    
    Faz verificação flexível considerando:
    - Nome completo
    - Partes do nome (primeiro + último)
    - Nome da unidade/diretoria
    """
    if not assinaturas_texto or not nome_assinante:
        return False
    
    assinaturas_norm = normalizar_nome(assinaturas_texto)
    nome_norm = normalizar_nome(nome_assinante)
    
    # Verifica nome completo
    if nome_norm in assinaturas_norm:
        return True
    
    # Verifica partes do nome (pelo menos 2 partes consecutivas)
    partes_nome = nome_norm.split()
    if len(partes_nome) >= 2:
        # Primeiro e último nome
        primeiro_ultimo = f"{partes_nome[0]} {partes_nome[-1]}"
        if primeiro_ultimo in assinaturas_norm:
            return True
        
        # Duas primeiras partes
        duas_primeiras = f"{partes_nome[0]} {partes_nome[1]}"
        if duas_primeiras in assinaturas_norm:
            return True
    
    # Verifica cada parte individual (mínimo 4 caracteres para evitar falsos positivos)
    for parte in partes_nome:
        if len(parte) >= 4 and parte in assinaturas_norm:
            # Verifica se é uma palavra inteira (não parte de outra palavra)
            pattern = r'\b' + re.escape(parte) + r'\b'
            if re.search(pattern, assinaturas_norm):
                return True
    
    return False


def parse_assinaturas(assinaturas_texto: str) -> List[str]:
    """Converte texto de assinaturas em lista de assinantes."""
    if not assinaturas_texto or assinaturas_texto.strip() == "":
        return []
    
    # Separa por quebra de linha ou vírgula
    assinaturas = []
    for linha in assinaturas_texto.replace('\n', ',').split(','):
        linha = linha.strip()
        if linha and len(linha) > 2:
            assinaturas.append(linha)
    
    # Se não separou, pode ser um texto contínuo
    if not assinaturas and assinaturas_texto.strip():
        assinaturas = [assinaturas_texto.strip()]
    
    return assinaturas


# =========================================================
# BUSCAR NOME DO ASSINANTE
# =========================================================
async def buscar_nome_assinante(chat_id: str = None, sigla: str = None) -> tuple:
    """
    Busca o nome completo do assinante nos bancos SQLite.
    
    Fluxo:
        chat_id → membros_diretoria.sigla → autoridades.nome_atual
    
    Returns:
        tuple: (nome_completo, sigla) ou ("", "")
    """
    
    try:
        import sqlite3
        
        # Paths dos bancos (ajustar conforme ambiente)
        # Aceita ARGUS_DB_PATH ou ARGUS_DIRETORIAS_DB para compatibilidade
        db_diretorias = os.getenv("ARGUS_DIRETORIAS_DB") or os.getenv("ARGUS_DB_PATH") or "/data/argus_diretorias.db"
        db_autoridades = os.getenv("ARGUS_AUTORIDADES_DB", "/data/argus_autoridades.db")
        
        # Fallback para paths do host se não existir no container
        if not os.path.exists(db_diretorias):
            db_diretorias = "/root/secretario-sei/data/argus_diretorias.db"
        if not os.path.exists(db_autoridades):
            db_autoridades = "/root/secretario-sei/data/argus_autoridades.db"
        
        debug_print(f"DB Diretorias: {db_diretorias}")
        debug_print(f"DB Autoridades: {db_autoridades}")
        
        # 1) Busca sigla pelo chat_id no banco de diretorias
        if chat_id and not sigla:
            conn_dir = sqlite3.connect(db_diretorias)
            conn_dir.row_factory = sqlite3.Row
            cursor_dir = conn_dir.cursor()
            
            cursor_dir.execute(
                "SELECT sigla FROM membros_diretoria WHERE chat_id = ? AND ativo = 1", 
                (str(chat_id),)
            )
            row = cursor_dir.fetchone()
            conn_dir.close()
            
            if row:
                sigla = row["sigla"]
                debug_print(f"Sigla encontrada: {sigla}")
            else:
                debug_print(f"Chat ID {chat_id} não encontrado em membros_diretoria")
                return ("", "")
        
        if not sigla:
            debug_print("Sigla não informada e não encontrada")
            return ("", "")
        
        # 2) Busca nome_atual pelo sigla/chave_busca no banco de autoridades
        conn_aut = sqlite3.connect(db_autoridades)
        conn_aut.row_factory = sqlite3.Row
        cursor_aut = conn_aut.cursor()
        
        cursor_aut.execute(
            "SELECT nome_atual FROM autoridades WHERE chave_busca = ? AND ativo = 1", 
            (sigla,)
        )
        row = cursor_aut.fetchone()
        conn_aut.close()
        
        if row:
            nome = row["nome_atual"]
            debug_print(f"Nome do assinante encontrado: {nome}")
            return (nome, sigla)
        
        # Fallback: tenta buscar com sigla em uppercase
        conn_aut = sqlite3.connect(db_autoridades)
        conn_aut.row_factory = sqlite3.Row
        cursor_aut = conn_aut.cursor()
        
        cursor_aut.execute(
            "SELECT nome_atual FROM autoridades WHERE UPPER(chave_busca) = UPPER(?) AND ativo = 1", 
            (sigla,)
        )
        row = cursor_aut.fetchone()
        conn_aut.close()
        
        if row:
            nome = row["nome_atual"]
            debug_print(f"Nome do assinante (fallback): {nome}")
            return (nome, sigla)
        
        debug_print(f"Sigla {sigla} não encontrada em autoridades")
        return ("", sigla)
        
    except Exception as e:
        debug_print(f"Erro ao buscar nome: {e}")
        import traceback
        traceback.print_exc(file=sys.stderr)
        return ("", "")


# =========================================================
# NAVEGAÇÃO
# =========================================================
async def navegar_para_blocos_assinatura(page):
    """Navega pelo menu até Blocos → Assinatura."""
    
    # Se já estiver na tela, ok
    if "bloco_assinatura_listar" in (page.url or ""):
        return

    print("-> Navegando pelo menu: Blocos -> Assinatura...", file=sys.stderr)

    menu_blocos = page.locator("span:has-text('Blocos')").first
    if not await menu_blocos.is_visible():
        menu_blocos = page.locator("text=Blocos").first

    if not await menu_blocos.is_visible():
        raise Exception("Menu 'Blocos' não encontrado.")

    await menu_blocos.click()
    await page.wait_for_timeout(800)

    submenu = page.locator("text=Assinatura").first
    if not await submenu.is_visible():
        submenu = page.locator("a:has-text('Assinatura')").first

    if not await submenu.is_visible():
        raise Exception("Submenu 'Assinatura' não apareceu.")

    await submenu.click()
    await page.wait_for_load_state("networkidle")
    await page.wait_for_timeout(900)
    print("-> Tela 'Blocos de Assinatura' carregada.", file=sys.stderr)


async def achar_frame_lista_blocos(page):
    """Encontra o frame da lista de blocos."""
    for f in page.frames:
        if "bloco_assinatura_listar" in (f.url or ""):
            return f
    # fallback: frame que contém o botão Pesquisar
    for f in page.frames:
        try:
            if await f.locator("#sbmPesquisar").count() > 0:
                return f
        except Exception:
            pass
    return None

async def marcar_todos_estados(frame_lista):
    """Marca todos os checkboxes de Estado para garantir que todos os blocos apareçam."""
    print("-> Marcando todos os filtros de Estado...", file=sys.stderr)
    
    # Checkboxes de estado no SEI
    estados_ids = [
        "chkSinGerado",
        "chkSinDisponibilizado", 
        "chkSinRetornado",
        "chkSinRecebido",
        "chkSinConcluido"
    ]
    
    marcados = 0
    for estado_id in estados_ids:
        try:
            checkbox = frame_lista.locator(f"#{estado_id}")
            if await checkbox.count() > 0:
                if not await checkbox.is_checked():
                    await checkbox.check()
                    marcados += 1
        except Exception:
            pass
    
    # Fallback: tenta por texto/label se IDs não funcionarem
    if marcados == 0:
        labels = ["Gerado", "Disponibilizado", "Retornado", "Recebido", "Concluído"]
        for label in labels:
            try:
                # Busca checkbox próximo ao texto
                cb = frame_lista.locator(f"input[type='checkbox'][id*='{label[:4]}' i]").first
                if await cb.count() > 0 and not await cb.is_checked():
                    await cb.check()
                    marcados += 1
            except Exception:
                pass
    
    print(f"-> Filtros de Estado: {marcados} marcados.", file=sys.stderr)
    await frame_lista.page.wait_for_timeout(500)



async def pesquisar_bloco(frame_lista, numero_bloco: str):
    """Pesquisa um bloco pelo número."""
    print(f"-> Pesquisando bloco {numero_bloco}...", file=sys.stderr)

    campo = frame_lista.locator(
        "label:has-text('Palavras-chave para pesquisa')"
    ).locator("xpath=following::input[@type='text'][1]")

    await campo.wait_for(state="visible", timeout=15000)
    await campo.click()
    await campo.fill(numero_bloco)

    # Usa barra superior para evitar strict mode violation
    btn = frame_lista.locator("#divInfraBarraComandosSuperior #sbmPesquisar").first
    await btn.wait_for(state="visible", timeout=15000)
    await btn.click()

    await frame_lista.page.wait_for_timeout(1200)
    print("-> Pesquisa executada.", file=sys.stderr)


async def abrir_bloco_clicando_no_numero(frame_lista, numero_bloco: str):
    """Abre o bloco clicando no número (não na caneta)."""
    print(f"-> Abrindo bloco {numero_bloco}...", file=sys.stderr)

    linha = frame_lista.locator("tr[class*=\"infraTr\"], tr[class*=\"infraLinha\"], tbody tr").filter(
        has_text=numero_bloco
    ).first
    await linha.wait_for(state="visible", timeout=15000)

    # O número geralmente é um link na coluna "Número"
    link_numero = linha.locator(f"a:has-text('{numero_bloco}')").first
    if await link_numero.count() == 0 or not await link_numero.is_visible():
        # fallback: 2ª coluna (Número)
        link_numero = linha.locator("td").nth(1).locator("a").first

    await link_numero.wait_for(state="visible", timeout=15000)
    await link_numero.click()

    await frame_lista.page.wait_for_load_state("networkidle")
    await frame_lista.page.wait_for_timeout(900)
    print("-> Dentro do bloco. Tela de documentos carregada.", file=sys.stderr)


# =========================================================
# LEITURA DOS DOCUMENTOS
# =========================================================
async def ler_docs_dentro_do_bloco(page, nome_assinante: str) -> List[Dict]:
    """
    Lê a tabela 'Lista de Processos/Documentos' e retorna itens:
    processo (NUP), documento, sei_numero, tipo, assinaturas_texto, 
    assinaturas_lista, voce_ja_assinou, pendente_para_voce
    """
    # Frame da tela interna do bloco
    frame = None
    for f in page.frames:
        if "rel_bloco_protocolo_listar" in (f.url or ""):
            frame = f
            break
    if frame is None:
        frame = page.main_frame

    # Localiza a tabela pelo cabeçalho "Lista de Processos/Documentos"
    tabela = frame.locator("table").filter(
        has=frame.locator("th:has-text('Processo')")
    ).first
    await tabela.wait_for(state="attached", timeout=15000)

    # Descobre índices das colunas pelo header
    headers = tabela.locator("tr").first.locator("th")
    hcount = await headers.count()
    if hcount == 0:
        headers = tabela.locator("th")
        hcount = await headers.count()

    mapa = {}
    for i in range(hcount):
        txt = (await headers.nth(i).inner_text()).strip().lower()
        txt = " ".join(txt.split())
        if "processo" in txt:
            mapa["processo"] = i
        elif "documento" in txt:
            mapa["documento"] = i
        elif txt == "tipo" or " tipo" in txt or "tipo " in txt:
            mapa["tipo"] = i
        elif "assinatura" in txt:
            mapa["assinaturas"] = i

    obrig = ["processo", "documento", "tipo", "assinaturas"]
    faltando = [k for k in obrig if k not in mapa]
    if faltando:
        raise Exception(f"Não consegui mapear colunas. Faltando: {faltando}")

    # Lê linhas
    linhas = tabela.locator('tr[class*="infraTr"], tr[class*="infraLinha"], tbody tr')
    await linhas.first.wait_for(state="attached", timeout=15000)
    n = await linhas.count()

    itens = []
    nome_norm = normalizar_nome(nome_assinante)

    for i in range(n):
        ln = linhas.nth(i)
        tds = ln.locator("td")
        tdcount = await tds.count()
        if tdcount <= max(mapa.values()):
            continue

        processo = (await tds.nth(mapa["processo"]).inner_text()).strip()
        documento_texto = (await tds.nth(mapa["documento"]).inner_text()).strip()
        tipo = (await tds.nth(mapa["tipo"]).inner_text()).strip()
        assinaturas_texto = (await tds.nth(mapa["assinaturas"]).inner_text()).strip()

        # Extrai número SEI do documento
        sei_numero = extrair_sei_numero(documento_texto)
        
        # Parse das assinaturas em lista
        assinaturas_lista = parse_assinaturas(assinaturas_texto)
        
        # Verifica se VOCÊ já assinou (não se alguém assinou)
        voce_ja_assinou = verificar_assinatura_presente(assinaturas_texto, nome_assinante)
        
        # Pendente se você ainda NÃO assinou
        pendente_para_voce = not voce_ja_assinou

        itens.append({
            "processo": processo,
            "documento": documento_texto,
            "sei_numero": sei_numero,
            "tipo": tipo,
            "assinaturas_texto": assinaturas_texto,
            "assinaturas_lista": assinaturas_lista,
            "total_assinaturas": len(assinaturas_lista),
            "voce_ja_assinou": voce_ja_assinou,
            "pendente_para_voce": pendente_para_voce,
        })

    return itens


# =========================================================
# FUNÇÃO PRINCIPAL
# =========================================================
async def listar_docs_bloco(
    numero_bloco: str,
    chat_id: str = None,
    sigla: str = None,
    # NOVO v3.2: Credenciais diretas (Laravel/PlattArgus WEB)
    usuario: str = None,
    senha: str = None,
    orgao_id: str = "31",
    nome_completo: str = None
) -> Dict:
    """
    Lista documentos de um bloco de assinatura.
    
    Args:
        numero_bloco: Número do bloco (ex: "845468")
        chat_id: Chat ID do Telegram
        sigla: Sigla da diretoria
        usuario: Usuário SEI (credencial direta - NOVO v3.2)
        senha: Senha SEI (credencial direta - NOVO v3.2)
        orgao_id: ID do órgão (credencial direta - NOVO v3.2)
        nome_completo: Nome para verificar assinatura (credencial direta - NOVO v3.2)
    
    Returns:
        Dict com lista de documentos e status
    """
    output = {
        "sucesso": False,
        "ok": False,
        "bloco_id": numero_bloco,
        "bloco": numero_bloco,
        "total": 0,
        "pendentes": 0,
        "assinados": 0,
        "itens": [],
        "itens_pendentes": [],
        "itens_assinados": [],
        "diretoria": sigla,
        "assinante": None,
        "erro": None,
        "timestamp": datetime.now().isoformat()
    }
    
    try:
        # =====================================================
        # NOVO v3.2: Credenciais diretas OU busca do banco
        # =====================================================
        if usuario and senha:
            # Credenciais diretas (Laravel/PlattArgus WEB)
            print(f"-> Usando credenciais diretas: {usuario}", file=sys.stderr)
            nome_assinante = nome_completo or usuario
            sigla_encontrada = None
        else:
            # LEGADO: Busca dados do assinante no banco (Telegram)
            print("-> Buscando dados do assinante...", file=sys.stderr)
            nome_assinante, sigla_encontrada = await buscar_nome_assinante(chat_id=chat_id, sigla=sigla)
        
        # Atualiza sigla se veio do banco
        if sigla_encontrada and not sigla:
            sigla = sigla_encontrada
            output["diretoria"] = sigla
        
        if not nome_assinante:
            output["erro"] = f"Nome do assinante não encontrado para sigla '{sigla}' no banco de autoridades"
            return output
        
        output["assinante"] = nome_assinante
        print(f"-> Assinante identificado: {nome_assinante} ({sigla or usuario})", file=sys.stderr)
        
        # 2) ABRE SESSÃO SEI (com credenciais diretas ou sigla/chat_id)
        async with criar_sessao_sei(chat_id=chat_id, sigla=sigla, usuario=usuario, senha=senha, orgao_id=orgao_id) as sessao:
            page = sessao['page']
            diretoria = sessao.get('diretoria', {})
            
            if diretoria:
                output['diretoria'] = diretoria.get('sigla')
            
            await debug_frames(page, "FRAMES APÓS LOGIN")
            
            # 3) NAVEGA PARA BLOCOS DE ASSINATURA
            await navegar_para_blocos_assinatura(page)
            
            # 4) ENCONTRA FRAME DA LISTA
            frame_lista = await achar_frame_lista_blocos(page)
            if frame_lista is None:
                await page.wait_for_timeout(1200)
                frame_lista = await achar_frame_lista_blocos(page)
            
            if frame_lista is None:
                output["erro"] = "Frame da lista de blocos não encontrado"
                return output
            
            await debug_frames(page, "FRAMES NA TELA DE BLOCOS")
            
            # 5) PESQUISA E ABRE O BLOCO
            await marcar_todos_estados(frame_lista)
            await pesquisar_bloco(frame_lista, numero_bloco)
            await abrir_bloco_clicando_no_numero(frame_lista, numero_bloco)
            
            # 6) LÊ DOCUMENTOS DO BLOCO
            itens = await ler_docs_dentro_do_bloco(page, nome_assinante)
            
            # 7) SEPARA PENDENTES E ASSINADOS (por você)
            pendentes = [x for x in itens if x["pendente_para_voce"]]
            assinados = [x for x in itens if not x["pendente_para_voce"]]
            
            output["sucesso"] = True
            output["ok"] = True
            output["itens"] = itens
            output["itens_pendentes"] = pendentes
            output["itens_assinados"] = assinados
            output["total"] = len(itens)
            output["pendentes"] = len(pendentes)
            output["assinados"] = len(assinados)
            
            # Log resumo
            print(f"\n{'=' * 70}", file=sys.stderr)
            print(f"BLOCO {numero_bloco} — Total: {len(itens)} | Pendentes p/ você: {len(pendentes)} | Já assinados: {len(assinados)}", file=sys.stderr)
            print(f"Assinante verificado: {nome_assinante}", file=sys.stderr)
            print("=" * 70, file=sys.stderr)
            
            for x in itens:
                flag = "⏳ PENDENTE" if x["pendente_para_voce"] else "✅ ASSINADO"
                assin_info = f"({x['total_assinaturas']} assinatura(s))" if x['total_assinaturas'] > 0 else "(sem assinaturas)"
                print(f"[{flag}] SEI {x['sei_numero']} | {x['tipo']} | NUP {x['processo']} {assin_info}", file=sys.stderr)
            
            return output
    
    except Exception as e:
        output["erro"] = str(e)
        debug_print(f"Erro: {e}")
        import traceback
        traceback.print_exc(file=sys.stderr)
        return output


# =========================================================
# CLI
# =========================================================
async def main_async():
    global DEBUG
    
    parser = argparse.ArgumentParser(description="ARGUS - Listar Documentos de Bloco v3.2 (Credenciais Diretas)")
    parser.add_argument("numero_bloco", help="Número do bloco")
    parser.add_argument("--chat-id", help="Chat ID do Telegram")
    parser.add_argument("--sigla", help="Sigla da diretoria")
    # NOVO v3.2: Credenciais diretas
    parser.add_argument("--usuario", help="Usuário SEI (credencial direta)")
    parser.add_argument("--senha", help="Senha SEI (credencial direta)")
    parser.add_argument("--orgao", default="31", help="ID do órgão (default: 31)")
    parser.add_argument("--nome", help="Nome completo para verificar assinatura")
    parser.add_argument("--debug", action="store_true", help="Mostra frames e diagnósticos")
    
    args = parser.parse_args()
    
    # Validação: precisa de credenciais diretas OU sigla/chat_id
    if not args.usuario and not args.chat_id and not args.sigla:
        parser.error("Informe --usuario + --senha OU --chat-id OU --sigla")
    
    if args.usuario and not args.senha:
        parser.error("--senha é obrigatório quando usar --usuario")
    
    DEBUG = args.debug
    
    resultado = await listar_docs_bloco(
        numero_bloco=args.numero_bloco,
        chat_id=args.chat_id,
        sigla=args.sigla,
        usuario=args.usuario,
        senha=args.senha,
        orgao_id=args.orgao,
        nome_completo=args.nome
    )
    
    print(json.dumps(resultado, indent=2, ensure_ascii=False))


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
