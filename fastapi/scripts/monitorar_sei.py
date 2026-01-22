#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
monitorar_sei.py - Monitor SEI Multi-Diretoria

VERSÃO 3.1 - Login completo + CREDENCIAIS DIRETAS

Uso:
    # NOVO - Credenciais diretas (Laravel/PlattArgus WEB)
    python monitorar_sei.py --usuario gilmar.moura --senha xxx --sigla DRH
    
    # LEGADO - Monitorar por chat_id
    python monitorar_sei.py --chat-id "-1001234567890"
    
    # LEGADO - Monitorar por sigla
    python monitorar_sei.py --sigla DRH
    
    # Monitorar todas as diretorias ativas
    python monitorar_sei.py --todas
"""

import os
import sys
import re
import json
import asyncio
from datetime import datetime
from typing import Optional, Dict, List

from playwright.async_api import async_playwright

# Importa módulos do ARGUS
from sei_auth_multi import criar_sessao_sei
CONTROL_URL = "https://app.sei.ac.gov.br/sei/controlador.php?acao=procedimento_controlar&reset=1"
from diretorias_db import DiretoriasDB


# =============================================================================
# CONFIGURAÇÃO
# =============================================================================

SEEN_NUPS_DIR = os.getenv("SEEN_NUPS_DIR", "/data/seen_nups")
NUP_RE = re.compile(r"\b\d{4}\.\d{4,7}\.\d{4,7}/\d{4}-\d{2}\b")


# =============================================================================
# MEMÓRIA DE NUPS POR DIRETORIA
# =============================================================================

def get_seen_nups_path(sigla: str) -> str:
    """Retorna caminho do arquivo de NUPs vistos para uma diretoria."""
    os.makedirs(SEEN_NUPS_DIR, exist_ok=True)
    return os.path.join(SEEN_NUPS_DIR, f"{sigla.lower()}_seen_nups.json")


def load_seen_nups(sigla: str) -> set:
    """Carrega NUPs já vistos de uma diretoria."""
    path = get_seen_nups_path(sigla)
    if not os.path.exists(path):
        return set()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f) or {}
        arr = data.get("nups") or []
        return {str(n).strip() for n in arr if n}
    except Exception as e:
        print(f"⚠ Falha ao carregar seen_nups de {sigla}: {e}", file=sys.stderr)
        return set()


def save_seen_nups(sigla: str, seen: set) -> None:
    """Salva NUPs já vistos de uma diretoria."""
    path = get_seen_nups_path(sigla)
    try:
        arr = sorted(str(n).strip() for n in seen if n)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"nups": arr, "atualizado_em": datetime.now().isoformat()}, f, indent=2)
        os.replace(tmp, path)
    except Exception as e:
        print(f"⚠ Falha ao salvar seen_nups de {sigla}: {e}", file=sys.stderr)


# =============================================================================
# FUNÇÕES DE EXTRAÇÃO
# =============================================================================

async def localizar_container_recebidos(alvo):
    """Localiza o container com processos recebidos."""
    try:
        tabela = alvo.locator("table").filter(has_text=re.compile(r"Recebidos", re.IGNORECASE)).first
        if await tabela.count():
            return tabela
    except Exception:
        pass
    
    try:
        corpo = alvo.locator("body")
        if await corpo.count():
            return corpo.first
    except Exception:
        pass
    
    return alvo


async def buscar_processos_recebidos(container) -> List[Dict]:
    """Extrai lista de processos da caixa de recebidos."""
    processos = []
    
    # Primeiro tenta .processoAberto
    links = container.locator("a.processoAberto")
    total = await links.count()
    
    if total == 0:
        links = container.locator("a")
        total = await links.count()
    
    for i in range(total):
        link = links.nth(i)
        try:
            txt = (await link.inner_text()).strip()
            if not txt:
                continue
            
            m = NUP_RE.search(txt)
            if not m:
                continue
            
            nup = m.group(0).strip()
            titulo = await link.get_attribute("title") or ""
            
            processos.append({
                "nup": nup,
                "titulo": titulo,
                "texto": txt
            })
        except Exception:
            continue
    
    return processos


async def extrair_total_recebidos(alvo, fallback: int) -> int:
    """Extrai total de recebidos do cabeçalho."""
    try:
        body = alvo.locator("body")
        txt = await body.inner_text(timeout=5000) if await body.count() else ""
    except Exception:
        return fallback
    
    m = re.search(r"Recebidos\s*[:(]\s*(\d+)", txt, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return fallback


# =============================================================================
# MONITORAMENTO
# =============================================================================

async def monitorar_diretoria(
    chat_id: str = None,
    sigla: str = None,
    # NOVO v3.1: Credenciais diretas (Laravel/PlattArgus WEB)
    usuario: str = None,
    senha: str = None,
    orgao_id: str = "31"
) -> Dict:
    """
    Monitora processos de uma diretoria específica.
    
    Args:
        chat_id: ID do chat do Telegram
        sigla: Sigla da diretoria
        usuario: Usuário SEI (credencial direta - NOVO v3.1)
        senha: Senha SEI (credencial direta - NOVO v3.1)
        orgao_id: ID do órgão (credencial direta - NOVO v3.1)
    
    Returns:
        Dict com resultado do monitoramento
    """
    output = {
        "sucesso": False,
        "diretoria": sigla,
        "chat_id": chat_id,
        "novo": False,
        "nup": None,
        "titulo": None,
        "erro": None,
        "timestamp": datetime.now().isoformat()
    }
    
    try:
        # Cria sessão autenticada
        async with criar_sessao_sei(chat_id=chat_id, sigla=sigla, usuario=usuario, senha=senha, orgao_id=orgao_id) as sessao:
            page = sessao['page']
            diretoria = sessao['diretoria']
            
            if diretoria:
                output['diretoria'] = diretoria['sigla']
                output['chat_id'] = diretoria['telegram_chat_id']
                sigla = diretoria['sigla']
            
            # Carrega NUPs já vistos
            seen_nups = load_seen_nups(sigla)
            
            # Navega para controle de processos
            if "procedimento_controlar" not in (page.url or ""):
                await page.goto(CONTROL_URL, wait_until="domcontentloaded", timeout=60000)
            
            await page.wait_for_load_state("networkidle", timeout=30000)
            
            # Localiza frame de conteúdo
            alvo = page
            for frame_name in ["ifrConteudoVisualizacao", "ifrConteudo", "ifrVisualizacao"]:
                frame = page.frame(name=frame_name)
                if frame:
                    alvo = frame
                    break
            
            # Extrai processos
            container = await localizar_container_recebidos(alvo)
            processos = await buscar_processos_recebidos(container)
            
            if processos:
                total_listados = len(processos)
                total_recebidos = await extrair_total_recebidos(alvo, total_listados)
                
                # Identifica novos
                novos = []
                novos_nups = set()
                
                for proc in processos:
                    nup = proc.get("nup")
                    if nup and nup not in seen_nups:
                        proc["novo"] = True
                        novos.append(proc)
                        novos_nups.add(nup)
                    else:
                        proc["novo"] = False
                
                # Salva novos NUPs
                if novos_nups:
                    seen_nups.update(novos_nups)
                    save_seen_nups(sigla, seen_nups)
                
                output["sucesso"] = True
                output["total_recebidos"] = total_recebidos
                output["total_listados"] = total_listados
                output["total_novos"] = len(novos)
                output["novos"] = novos
                
                if novos:
                    output["novo"] = True
                    output["nup"] = novos[0].get("nup")
                    output["titulo"] = novos[0].get("titulo")
            else:
                output["sucesso"] = True
                output["total_recebidos"] = 0
                output["total_listados"] = 0
                output["total_novos"] = 0
                output["novos"] = []
    
    except Exception as e:
        output["erro"] = str(e)
        print(f"❌ Erro ao monitorar: {e}", file=sys.stderr)
    
    return output


async def monitorar_todas_diretorias() -> List[Dict]:
    """Monitora todas as diretorias ativas."""
    db = DiretoriasDB()
    diretorias = db.listar_todas(apenas_ativas=True)
    
    resultados = []
    
    for diretoria in diretorias:
        print(f"\n{'='*50}", file=sys.stderr)
        print(f"📋 Monitorando: {diretoria['sigla']} - {diretoria['nome']}", file=sys.stderr)
        print(f"{'='*50}", file=sys.stderr)
        
        resultado = await monitorar_diretoria(sigla=diretoria['sigla'])
        resultados.append(resultado)
        
        # Pequena pausa entre diretorias
        await asyncio.sleep(2)
    
    return resultados


# =============================================================================
# MAIN
# =============================================================================

async def main_async():
    import argparse
    
    parser = argparse.ArgumentParser(description="Monitor SEI Multi-Diretoria v3.1 (Credenciais Diretas)")
    parser.add_argument("--chat-id", help="Monitora por chat_id do Telegram")
    parser.add_argument("--sigla", help="Monitora por sigla da diretoria")
    # NOVO v3.1: Credenciais diretas
    parser.add_argument("--usuario", help="Usuário SEI (credencial direta)")
    parser.add_argument("--senha", help="Senha SEI (credencial direta)")
    parser.add_argument("--orgao", default="31", help="ID do órgão (default: 31)")
    parser.add_argument("--todas", action="store_true", help="Monitora todas as diretorias")
    
    args = parser.parse_args()
    
    if args.todas:
        resultados = await monitorar_todas_diretorias()
        print(json.dumps(resultados, indent=2, ensure_ascii=False))
    
    elif args.usuario or args.chat_id or args.sigla:
        # Validação
        if args.usuario and not args.senha:
            parser.error("--senha é obrigatório quando usar --usuario")
        
        if args.usuario and not args.sigla:
            parser.error("--sigla é obrigatório para identificar diretoria (para seen_nups)")
        
        resultado = await monitorar_diretoria(
            chat_id=args.chat_id,
            sigla=args.sigla,
            usuario=args.usuario,
            senha=args.senha,
            orgao_id=args.orgao
        )
        print(json.dumps(resultado, indent=2, ensure_ascii=False))
    
    else:
        parser.print_help()


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
