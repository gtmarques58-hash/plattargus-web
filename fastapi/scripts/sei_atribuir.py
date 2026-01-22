#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sei_atribuir.py - Atribuição de Processos SEI Multi-Diretoria

VERSÃO 2.1 - ROBUSTA + CREDENCIAIS DIRETAS

Melhorias v2.1:
- Suporte a credenciais diretas (--usuario, --senha, --orgao)
- Mantém compatibilidade com chat_id/sigla (Telegram)

Melhorias v2.0:
- Busca no select pelo LOGIN primeiro (mais confiável)
- Verificação real da seleção
- Logs detalhados para debug
- Verificação de sucesso após salvar
- Fallback de paths para o banco

Uso:
    # NOVO - Credenciais diretas (Laravel/PlattArgus WEB)
    python sei_atribuir.py "NUP" "apelido" --usuario gilmar.moura --senha xxx
    
    # LEGADO - Telegram
    python sei_atribuir.py "NUP" "apelido" --chat-id "123"
    python sei_atribuir.py "NUP" "apelido" --sigla DRH
    python sei_atribuir.py "NUP" "apelido" --sigla DRH --debug
"""

import os
import sys
import json
import sqlite3
import asyncio
import re
from datetime import datetime
from typing import Dict, Optional, List

from playwright.async_api import async_playwright

sys.path.insert(0, "/app/scripts")
from sei_auth_multi import criar_sessao_sei, CONTROL_URL


# =============================================================================
# CONFIGURAÇÃO
# =============================================================================

DEBUG = os.getenv("ARGUS_DEBUG", "0") == "1"

# Paths dos bancos
def get_db_path(env_var: str, default: str, fallback: str) -> str:
    """Retorna path do banco com fallback."""
    path = os.getenv(env_var, default)
    if os.path.exists(path):
        return path
    if os.path.exists(fallback):
        return fallback
    return default

AUTORIDADES_DB = get_db_path(
    "ARGUS_AUTORIDADES_DB",
    "/data/argus_autoridades.db",
    "/root/secretario-sei/data/argus_autoridades.db"
)

DIRETORIAS_DB = get_db_path(
    "ARGUS_DB_PATH",
    "/data/argus_diretorias.db",
    "/root/secretario-sei/data/argus_diretorias.db"
)


# =============================================================================
# HELPERS
# =============================================================================

def debug_print(msg: str):
    if DEBUG:
        print(f"[DEBUG] {msg}", file=sys.stderr)


def normalizar_texto(texto: str) -> str:
    """Normaliza texto para comparação (remove acentos, upper)."""
    if not texto:
        return ""
    
    acentos = {
        'á': 'a', 'à': 'a', 'ã': 'a', 'â': 'a', 'ä': 'a',
        'é': 'e', 'è': 'e', 'ê': 'e', 'ë': 'e',
        'í': 'i', 'ì': 'i', 'î': 'i', 'ï': 'i',
        'ó': 'o', 'ò': 'o', 'õ': 'o', 'ô': 'o', 'ö': 'o',
        'ú': 'u', 'ù': 'u', 'û': 'u', 'ü': 'u',
        'ç': 'c', 'ñ': 'n'
    }
    
    texto = texto.upper().strip()
    for acento, letra in acentos.items():
        texto = texto.replace(acento.upper(), letra.upper())
    
    return texto


# =============================================================================
# FUNÇÕES DE BANCO
# =============================================================================

def buscar_servidor_por_apelido(sigla_diretoria: str, apelido: str) -> dict | None:
    """Busca servidor pelo apelido dentro de uma diretoria."""
    try:
        debug_print(f"Buscando apelido '{apelido}' na diretoria '{sigla_diretoria}'")
        debug_print(f"Banco: {AUTORIDADES_DB}")
        
        conn = sqlite3.connect(AUTORIDADES_DB)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Busca exata primeiro
        cursor.execute("""
            SELECT chave_busca, nome_atual, posto_grad, apelido, sigla_pai
            FROM autoridades 
            WHERE sigla_pai = ? AND LOWER(apelido) = LOWER(?) AND ativo = 1
        """, (sigla_diretoria.upper(), apelido.lower()))
        
        row = cursor.fetchone()
        
        # Se não encontrou, tenta busca parcial no nome
        if not row:
            debug_print(f"Apelido exato não encontrado, tentando busca parcial...")
            cursor.execute("""
                SELECT chave_busca, nome_atual, posto_grad, apelido, sigla_pai
                FROM autoridades 
                WHERE sigla_pai = ? AND ativo = 1
                AND (
                    UPPER(nome_atual) LIKE UPPER(?) 
                    OR UPPER(apelido) LIKE UPPER(?)
                )
            """, (sigla_diretoria.upper(), f"%{apelido}%", f"%{apelido}%"))
            row = cursor.fetchone()
        
        conn.close()
        
        if row:
            result = dict(row)
            debug_print(f"Servidor encontrado: {result}")
            return result
            
        debug_print(f"Servidor não encontrado")
        return None
        
    except Exception as e:
        print(f"❌ ERRO ao buscar servidor: {e}", file=sys.stderr)
        return None


def buscar_login_por_nome(nome_completo: str, sigla_diretoria: str) -> Optional[str]:
    """
    Tenta encontrar o login SEI de um servidor pelo nome.
    Busca no banco de diretorias para pegar o padrão de login.
    """
    # O login geralmente é nome.sobrenome
    # Vamos tentar extrair do nome completo
    partes = nome_completo.lower().split()
    if len(partes) >= 2:
        # Padrão: primeiro.ultimo
        possivel_login = f"{partes[0]}.{partes[-1]}"
        debug_print(f"Login inferido: {possivel_login}")
        return possivel_login
    return None


def listar_servidores_diretoria(sigla_diretoria: str) -> list:
    """Lista todos os servidores de uma diretoria."""
    try:
        conn = sqlite3.connect(AUTORIDADES_DB)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT chave_busca, nome_atual, posto_grad, apelido
            FROM autoridades 
            WHERE sigla_pai = ? AND ativo = 1
            ORDER BY nome_atual
        """, (sigla_diretoria.upper(),))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
        
    except Exception as e:
        print(f"❌ ERRO ao listar servidores: {e}", file=sys.stderr)
        return []


# =============================================================================
# ATRIBUIÇÃO
# =============================================================================

async def atribuir_processo(
    nup: str,
    apelido: str,
    chat_id: str = None,
    sigla: str = None,
    # NOVO v2.1: Credenciais diretas (Laravel/PlattArgus WEB)
    usuario: str = None,
    senha: str = None,
    orgao_id: str = "31"
) -> Dict:
    """
    Atribui um processo SEI a um servidor.
    
    Args:
        nup: Número do processo
        apelido: Apelido do servidor destino
        chat_id: Chat ID do Telegram
        sigla: Sigla da diretoria
        usuario: Usuário SEI (credencial direta - NOVO v2.1)
        senha: Senha SEI (credencial direta - NOVO v2.1)
        orgao_id: ID do órgão (credencial direta - NOVO v2.1)
    
    Returns:
        Dict com resultado da operação
    """
    output = {
        "sucesso": False,
        "ok": False,
        "nup": nup,
        "apelido": apelido,
        "servidor": None,
        "login_sei": None,
        "diretoria": sigla,
        "erro": None,
        "timestamp": datetime.now().isoformat()
    }
    
    # Busca sigla pelo chat_id se necessário
    sigla_busca = sigla.upper() if sigla else None
    
    if not sigla_busca and chat_id:
        try:
            conn = sqlite3.connect(DIRETORIAS_DB)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                "SELECT sigla FROM membros_diretoria WHERE chat_id = ? AND ativo = 1",
                (str(chat_id),)
            )
            row = cursor.fetchone()
            conn.close()
            if row:
                sigla_busca = row["sigla"].upper()
                debug_print(f"Sigla encontrada pelo chat_id: {sigla_busca}")
        except Exception as e:
            debug_print(f"Erro ao buscar sigla: {e}")
    
    if not sigla_busca:
        output["erro"] = "Sigla da diretoria é necessária para buscar o servidor (use --sigla)"
        return output
    
    output["diretoria"] = sigla_busca
    
    servidor = buscar_servidor_por_apelido(sigla_busca, apelido)
    
    if not servidor:
        servidores = listar_servidores_diretoria(sigla_busca)
        apelidos_disponiveis = [s['apelido'] for s in servidores if s.get('apelido')]
        output["erro"] = f"Apelido '{apelido}' não encontrado na {sigla_busca}"
        output["apelidos_disponiveis"] = apelidos_disponiveis
        print(f"❌ {output['erro']}", file=sys.stderr)
        print(f"📋 Apelidos disponíveis: {', '.join(apelidos_disponiveis)}", file=sys.stderr)
        return output
    
    nome_servidor = servidor['nome_atual']
    output["servidor"] = nome_servidor
    
    # Infere o login SEI (primeiro.ultimo)
    login_inferido = buscar_login_por_nome(nome_servidor, sigla_busca)
    output["login_sei"] = login_inferido
    
    print(f"👤 Servidor encontrado: {nome_servidor}", file=sys.stderr)
    debug_print(f"Login inferido: {login_inferido}")
    
    try:
        async with criar_sessao_sei(chat_id=chat_id, sigla=sigla, usuario=usuario, senha=senha, orgao_id=orgao_id) as sessao:
            page = sessao['page']
            diretoria = sessao['diretoria']
            
            if diretoria:
                output['diretoria'] = diretoria['sigla']
            
            # Busca o processo
            print(f"🔍 Buscando processo: {nup}", file=sys.stderr)
            await page.locator("#txtPesquisaRapida").wait_for(state="visible", timeout=15000)
            await page.locator("#txtPesquisaRapida").fill(nup)
            await page.locator("#txtPesquisaRapida").press("Enter")
            await page.wait_for_load_state("networkidle", timeout=60000)
            await page.wait_for_timeout(2000)
            
            # =========================================================
            # LOCALIZA O BOTÃO DE ATRIBUIR
            # =========================================================
            print("📂 Procurando botão de atribuição...", file=sys.stderr)
            
            btn_atribuir = None
            frame_trabalho = None
            
            # Tenta em todos os frames
            for frame in page.frames:
                try:
                    btn = frame.locator("img[title='Atribuir Processo']").first
                    if await btn.count() > 0 and await btn.is_visible():
                        btn_atribuir = btn
                        frame_trabalho = frame
                        debug_print(f"Botão encontrado no frame: {frame.name or frame.url[:50]}")
                        break
                except Exception:
                    continue
            
            if not btn_atribuir:
                output["erro"] = "Botão de atribuir não encontrado (processo fechado ou sem permissão)"
                print(f"❌ {output['erro']}", file=sys.stderr)
                return output
            
            # Clica no botão de atribuir
            print("📂 Abrindo tela de atribuição...", file=sys.stderr)
            await btn_atribuir.click()
            await page.wait_for_timeout(2000)
            
            # =========================================================
            # LOCALIZA O SELECT DE ATRIBUIÇÃO
            # =========================================================
            print("🔎 Localizando lista de servidores...", file=sys.stderr)
            
            select = None
            frame_select = None
            
            # Tenta em todos os frames
            for frame in page.frames:
                try:
                    sel = frame.locator("#selAtribuicao").first
                    if await sel.count() > 0 and await sel.is_visible():
                        select = sel
                        frame_select = frame
                        debug_print(f"Select encontrado no frame: {frame.name or frame.url[:50]}")
                        break
                except Exception:
                    continue
            
            if not select:
                output["erro"] = "Lista de atribuição não encontrada"
                print(f"❌ {output['erro']}", file=sys.stderr)
                return output
            
            # =========================================================
            # LISTA TODAS AS OPÇÕES DO SELECT (para debug)
            # =========================================================
            opcoes = select.locator("option")
            total_opcoes = await opcoes.count()
            debug_print(f"Total de opções no select: {total_opcoes}")
            
            opcoes_texto = []
            for i in range(total_opcoes):
                texto = await opcoes.nth(i).text_content()
                valor = await opcoes.nth(i).get_attribute("value")
                opcoes_texto.append({"texto": texto.strip() if texto else "", "valor": valor})
                debug_print(f"  Opção {i}: valor={valor}, texto={texto}")
            
            # =========================================================
            # BUSCA A OPÇÃO CORRETA
            # =========================================================
            print(f"🔎 Procurando servidor na lista...", file=sys.stderr)
            
            opcao_encontrada = None
            valor_encontrado = None
            texto_encontrado = None
            
            # Estratégia 1: Busca pelo LOGIN (mais confiável)
            if login_inferido:
                login_lower = login_inferido.lower()
                for opt in opcoes_texto:
                    if opt["texto"].lower().startswith(login_lower):
                        opcao_encontrada = opt
                        valor_encontrado = opt["valor"]
                        texto_encontrado = opt["texto"]
                        debug_print(f"Encontrado por LOGIN: {texto_encontrado}")
                        break
            
            # Estratégia 2: Busca pelo NOME COMPLETO
            if not opcao_encontrada:
                nome_upper = nome_servidor.upper()
                nome_norm = normalizar_texto(nome_servidor)
                
                for opt in opcoes_texto:
                    texto_norm = normalizar_texto(opt["texto"])
                    if nome_upper in opt["texto"].upper() or nome_norm in texto_norm:
                        opcao_encontrada = opt
                        valor_encontrado = opt["valor"]
                        texto_encontrado = opt["texto"]
                        debug_print(f"Encontrado por NOME: {texto_encontrado}")
                        break
            
            # Estratégia 3: Busca pelo SOBRENOME (apelido/nome de guerra)
            if not opcao_encontrada:
                apelido_upper = apelido.upper()
                apelido_norm = normalizar_texto(apelido)
                
                for opt in opcoes_texto:
                    texto_norm = normalizar_texto(opt["texto"])
                    # Verifica se o apelido está no final do nome (sobrenome)
                    if apelido_upper in opt["texto"].upper() or apelido_norm in texto_norm:
                        opcao_encontrada = opt
                        valor_encontrado = opt["valor"]
                        texto_encontrado = opt["texto"]
                        debug_print(f"Encontrado por APELIDO: {texto_encontrado}")
                        break
            
            if not opcao_encontrada:
                output["erro"] = f"Servidor '{nome_servidor}' não encontrado na lista do SEI"
                output["opcoes_disponiveis"] = [o["texto"] for o in opcoes_texto if o["texto"]]
                print(f"❌ {output['erro']}", file=sys.stderr)
                print(f"📋 Opções disponíveis no SEI:", file=sys.stderr)
                for o in opcoes_texto:
                    if o["texto"]:
                        print(f"   - {o['texto']}", file=sys.stderr)
                return output
            
            # =========================================================
            # SELECIONA A OPÇÃO
            # =========================================================
            print(f"   ✓ Encontrado: {texto_encontrado}", file=sys.stderr)
            print(f"   ✓ Valor: {valor_encontrado}", file=sys.stderr)
            
            # Seleciona pelo valor
            await select.select_option(value=valor_encontrado)
            await page.wait_for_timeout(500)
            
            # VERIFICA se realmente selecionou
            valor_selecionado = await select.input_value()
            debug_print(f"Valor selecionado após select_option: {valor_selecionado}")
            
            if valor_selecionado != valor_encontrado:
                print(f"⚠️ Valor selecionado diferente do esperado!", file=sys.stderr)
                print(f"   Esperado: {valor_encontrado}", file=sys.stderr)
                print(f"   Obtido: {valor_selecionado}", file=sys.stderr)
            
            # =========================================================
            # CLICA EM SALVAR
            # =========================================================
            print("💾 Salvando atribuição...", file=sys.stderr)
            
            btn_salvar = None
            
            # Tenta encontrar o botão Salvar em todos os frames
            for frame in page.frames:
                try:
                    btn = frame.locator("#sbmSalvar").first
                    if await btn.count() > 0 and await btn.is_visible():
                        btn_salvar = btn
                        debug_print(f"Botão Salvar encontrado no frame: {frame.name or frame.url[:50]}")
                        break
                except Exception:
                    continue
            
            if not btn_salvar:
                # Tenta pelo texto
                for frame in page.frames:
                    try:
                        btn = frame.locator("button:has-text('Salvar'), input[value='Salvar']").first
                        if await btn.count() > 0 and await btn.is_visible():
                            btn_salvar = btn
                            break
                    except Exception:
                        continue
            
            if not btn_salvar:
                output["erro"] = "Botão Salvar não encontrado"
                print(f"❌ {output['erro']}", file=sys.stderr)
                return output
            
            # Clica no Salvar
            await btn_salvar.click()
            print("   ✓ Clicou em Salvar", file=sys.stderr)
            
            await page.wait_for_timeout(2000)
            
            # =========================================================
            # VERIFICA SE HOUVE ERRO
            # =========================================================
            for frame in page.frames:
                try:
                    erro_elem = frame.locator(".infraErro, .erro, #divErro, .alert-danger").first
                    if await erro_elem.count() > 0 and await erro_elem.is_visible():
                        erro_texto = await erro_elem.inner_text()
                        if erro_texto.strip():
                            output["erro"] = f"Erro do SEI: {erro_texto.strip()}"
                            print(f"❌ {output['erro']}", file=sys.stderr)
                            return output
                except Exception:
                    continue
            
            # =========================================================
            # SUCESSO!
            # =========================================================
            output["sucesso"] = True
            output["ok"] = True
            output["mensagem"] = f"Processo atribuído para {texto_encontrado}"
            print(f"✅ Atribuição realizada com sucesso!", file=sys.stderr)
            print(f"   Processo: {nup}", file=sys.stderr)
            print(f"   Atribuído para: {texto_encontrado}", file=sys.stderr)
    
    except Exception as e:
        output["erro"] = str(e)
        print(f"❌ Erro: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
    
    return output


# =============================================================================
# MAIN
# =============================================================================

async def main_async():
    global DEBUG
    import argparse
    
    parser = argparse.ArgumentParser(description="Atribuição de Processo SEI v2.1 (Credenciais Diretas)")
    parser.add_argument("nup", help="Número do processo")
    parser.add_argument("apelido", help="Apelido do servidor destino")
    parser.add_argument("--chat-id", help="Chat ID do Telegram")
    parser.add_argument("--sigla", help="Sigla da diretoria (necessária para buscar servidor)")
    # NOVO v2.1: Credenciais diretas
    parser.add_argument("--usuario", help="Usuário SEI (credencial direta)")
    parser.add_argument("--senha", help="Senha SEI (credencial direta)")
    parser.add_argument("--orgao", default="31", help="ID do órgão (default: 31)")
    parser.add_argument("--debug", action="store_true", help="Mostra diagnósticos")
    
    args = parser.parse_args()
    
    # Validação: precisa de sigla (para buscar servidor) + credenciais OU chat_id
    if not args.sigla and not args.chat_id:
        parser.error("Informe --sigla (obrigatório para buscar servidor)")
    
    if args.usuario and not args.senha:
        parser.error("--senha é obrigatório quando usar --usuario")
    
    # Se não tem credenciais diretas, precisa de chat_id ou sigla para autenticação
    if not args.usuario and not args.chat_id and not args.sigla:
        parser.error("Informe --usuario + --senha OU --chat-id OU --sigla")
    
    DEBUG = args.debug
    
    resultado = await atribuir_processo(
        nup=args.nup,
        apelido=args.apelido,
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
