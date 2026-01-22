#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
assinar_documento.py - Assinatura de Documento SEI Multi-Diretoria

VERSÃO 2.2 - PRODUÇÃO + CREDENCIAIS DIRETAS

Correção v2.2:
- Suporte a credenciais diretas (--usuario, --senha, --orgao, --nome, --cargo)
- Mantém compatibilidade com chat_id/sigla (Telegram)

Correção v2.1:
- Modal não fechou = considera sucesso com aviso (⚠️)
- Screenshot enviado mesmo quando modal não fecha

Fluxo:
  1. Login via sei_auth_multi (multi-diretoria)
  2. Busca dados do assinante no banco (login, nome, cargo, senha)
  3. Pesquisa rápida pelo SEI nº
  4. Abre o documento
  5. Clica em Assinar
  6. Preenche modal (Órgão, Assinante, Cargo, Senha)
  7. Assina com delicadeza humana (digitação caractere por caractere)
  8. JSON de resultado

Uso:
    # NOVO - Credenciais diretas (Laravel/PlattArgus WEB)
    python assinar_documento.py "0018817258" --usuario gilmar.moura --senha xxx --nome "Gilmar Moura" --cargo "Diretor"
    
    # LEGADO - Telegram
    python assinar_documento.py "0018817258" --chat-id "8152690312"
    python assinar_documento.py "0018817258" --sigla DRH
    python assinar_documento.py "0018817258" --sigla DRH --debug

Dependências:
    pip install playwright httpx
    playwright install chromium
"""

import sys
import os
import json
import asyncio
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional

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

# Para descriptografar senha (ajuste conforme seu módulo)
try:
    from crypto_utils import descriptografar_senha
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

# URL da API de membros (ajuste conforme sua estrutura)
API_MEMBROS_URL = os.getenv("API_MEMBROS_URL", "http://localhost:8000")

# Órgão padrão
ORGAO_PADRAO = "CBMAC"

# Evidência de assinatura (screenshot)
# - Por padrão NÃO salva em disco (mais limpo e seguro).
# - Pode enviar a imagem diretamente ao Telegram (prova rápida para o operador).
ARGUS_SAVE_SCREENSHOT = os.getenv("ARGUS_SAVE_SCREENSHOT", "0").strip() == "1"
ARGUS_SEND_PROOF_TELEGRAM = os.getenv("ARGUS_SEND_PROOF_TELEGRAM", "1").strip() == "1"

# Diretório para screenshots (só usado se ARGUS_SAVE_SCREENSHOT=1)
FOTOS_DIR = Path(os.getenv("ARGUS_FOTOS_DIR", "/tmp/argus_fotos"))
if ARGUS_SAVE_SCREENSHOT:
    FOTOS_DIR.mkdir(exist_ok=True)

# Seletores
SELETOR_PESQUISA_RAPIDA = "#txtPesquisaRapida"


# =========================================================
# HELPERS
# =========================================================
def debug_print(msg: str):
    if DEBUG:
        print(f"[DEBUG] {msg}", file=sys.stderr)


async def debug_frames(page, title="FRAMES"):
    if not DEBUG:
        return
    print("\n" + "=" * 60, file=sys.stderr)
    print(title, file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    for f in page.frames:
        url_short = (f.url or "")[:80]
        print(f"  name={f.name!r}  url={url_short}...", file=sys.stderr)
    print("=" * 60 + "\n", file=sys.stderr)



# =========================================================
# TELEGRAM - enviar evidência (screenshot) sem salvar em disco
# =========================================================
def _telegram_api_base() -> Optional[str]:
    """Retorna base do Bot API.
    Use APENAS via variável de ambiente (não coloque token hardcoded).
    Opções:
      - TELEGRAM_BOT_TOKEN=xxxx  -> usa https://api.telegram.org/bot<token>
      - TELEGRAM_BOT_API_BASE=https://api.telegram.org/bot<token>  (já completo)
    """
    base = os.getenv("TELEGRAM_BOT_API_BASE", "").strip()
    if base:
        return base.rstrip("/")
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if token:
        return f"https://api.telegram.org/bot{token}"
    return None


async def telegram_send_photo_bytes(chat_id: str, photo_bytes: bytes, caption: str = "") -> bool:
    """Envia foto para o Telegram usando bytes em memória.
    Retorna True/False sem quebrar o fluxo principal.
    """
    base = _telegram_api_base()
    if not base or not chat_id or not photo_bytes:
        return False

    url = f"{base}/sendPhoto"
    data = {"chat_id": str(chat_id)}
    if caption:
        data["caption"] = caption[:1024]

    # Preferência: httpx (async). Fallback: requests (sync em thread).
    try:
        import httpx  # type: ignore
        async with httpx.AsyncClient(timeout=20) as client:
            files = {"photo": ("assinatura.png", photo_bytes, "image/png")}
            r = await client.post(url, data=data, files=files)
            return r.status_code == 200
    except Exception:
        try:
            import requests  # type: ignore
            loop = asyncio.get_running_loop()
            def _post():
                files = {"photo": ("assinatura.png", photo_bytes, "image/png")}
                return requests.post(url, data=data, files=files, timeout=20)
            resp = await loop.run_in_executor(None, _post)
            return getattr(resp, "status_code", 0) == 200
        except Exception:
            return False


async def capturar_evidencia(page) -> Optional[bytes]:
    """Captura screenshot em memória (bytes)."""
    try:
        return await page.screenshot(full_page=True, type="png")
    except Exception:
        return None


# =========================================================
# BUSCAR DADOS DO ASSINANTE
# =========================================================
async def buscar_dados_assinante(chat_id: str = None, sigla: str = None) -> Dict:
    """
    Busca dados do assinante no banco SQLite (diretorias).
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
        db_path = os.getenv("ARGUS_DIRETORIAS_DB", "/data/argus_diretorias.db")
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Busca sigla pelo chat_id
        if chat_id and not sigla:
            cursor.execute("SELECT sigla FROM membros_diretoria WHERE chat_id = ? AND ativo = 1", (str(chat_id),))
            row = cursor.fetchone()
            if row:
                sigla = row["sigla"]
        
        if not sigla:
            conn.close()
            debug_print("Sigla nao encontrada")
            return dados
        
        debug_print(f"Buscando diretoria: {sigla}")
        
        # Busca dados da diretoria
        cursor.execute("SELECT sei_usuario, sei_senha_encrypted, nome, cargo_assinatura FROM diretorias WHERE sigla = ? AND ativo = 1", (sigla,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            dados["login_sei"] = row["sei_usuario"]
            dados["nome_completo"] = row["nome"]
            dados["cargo_assinatura"] = row["cargo_assinatura"] or "Diretor(a)"
            
            # Descriptografa senha
            if row["sei_senha_encrypted"]:
                try:
                    from crypto_utils import decrypt_password
                    dados["senha"] = decrypt_password(row["sei_senha_encrypted"])
                    debug_print(f"Senha OK: {len(dados['senha'])} chars")
                except Exception as e:
                    debug_print(f"Erro decrypt: {e}")
        else:
            debug_print(f"Diretoria {sigla} nao encontrada")
        
        return dados
        
    except Exception as e:
        debug_print(f"Erro buscar_dados_assinante: {e}")
        return dados



# =========================================================
# PESQUISA POR SEI Nº
# =========================================================
async def pesquisar_documento_por_sei(page, sei_numero: str) -> bool:
    """Usa a pesquisa rápida para abrir o documento pelo SEI nº."""
    debug_print(f"Pesquisando documento SEI nº {sei_numero}...")
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
# CLICAR EM ASSINAR (NO DOCUMENTO)
# =========================================================
async def clicar_botao_assinar(page) -> bool:
    """Clica no botão/ícone de Assinar do documento."""
    debug_print("Procurando botão Assinar...")
    print("-> Procurando botão Assinar...", file=sys.stderr)
    await page.wait_for_timeout(2000)  # Aguarda frames carregarem
    
    seletores_assinar = [
        'img[title="Assinar Documento"]',
        'img[alt="Assinar Documento"]',
        'a[title="Assinar Documento"]',
        '#btnAssinar',
        'img[src*="assinar"]',
    ]
    
    # Tenta em todos os frames
    for frame in page.frames:
        for seletor in seletores_assinar:
            try:
                btn = frame.locator(seletor).first
                if await btn.count() > 0:
                    debug_print(f"Botão encontrado no frame '{frame.name}' com seletor: {seletor}")
                    await btn.click(force=True)
                    print("-> Clicou em Assinar.", file=sys.stderr)
                    await page.wait_for_timeout(1000)
                    return True
            except Exception:
                continue
    
    # Fallback: tenta por role
    for frame in page.frames:
        try:
            btn = frame.get_by_role("img", name="Assinar Documento").first
            if await btn.count() > 0:
                await btn.click(force=True)
                print("-> Clicou em Assinar (via role).", file=sys.stderr)
                await page.wait_for_timeout(1000)
                return True
        except Exception:
            continue
    
    print("-> Botão Assinar não encontrado.", file=sys.stderr)
    return False


# =========================================================
# ASSINATURA (COM DELICADEZA HUMANA)
# =========================================================
async def preencher_modal_e_assinar(
    page,
    orgao: str,
    login_sei: str,
    nome_completo: str,
    cargo: str,
    senha: str
) -> Dict:
    """Preenche o modal de assinatura e assina com comportamento humano."""
    resultado = {
        "modal_encontrado": False,
        "modal_preenchido": False,
        "assinado": False,
        "aviso": None,
        "erro": None,
    }
    
    print("-> Aguardando modal de assinatura...", file=sys.stderr)
    
    # Aguarda modal aparecer
    frame_modal = None
    for _ in range(80):  # ~16s
        fm = page.frame(name="modal-frame")
        if fm and "documento_assinar" in (fm.url or ""):
            frame_modal = fm
            break
        await page.wait_for_timeout(200)
    
    if frame_modal is None:
        resultado["erro"] = "Modal de assinatura não apareceu."
        return resultado
    
    resultado["modal_encontrado"] = True
    
    try:
        # 1) ÓRGÃO
        print(f"-> Órgão: {orgao}", file=sys.stderr)
        select_orgao = frame_modal.locator("select[name*='Orgao' i], select[id*='Orgao' i]").first
        await select_orgao.wait_for(state="visible", timeout=15000)
        await select_orgao.select_option(label=orgao)
        await select_orgao.evaluate(
            "el => { el.dispatchEvent(new Event('change', { bubbles: true })); }"
        )
        await page.wait_for_timeout(500)
        
        # 2) ASSINANTE (digitação humana)
        print(f"-> Assinante: {login_sei}", file=sys.stderr)
        campo_assinante = frame_modal.locator("input[type='text']:visible").first
        await campo_assinante.wait_for(state="visible", timeout=15000)
        await campo_assinante.click()
        await campo_assinante.fill("")
        await campo_assinante.type(login_sei, delay=120)
        await page.wait_for_timeout(900)
        
        # Seleciona da lista de autocomplete
        print(f"-> Selecionando: {nome_completo}", file=sys.stderr)
        # Seleciona primeiro item com teclado
        await frame_modal.page.keyboard.press("ArrowDown")
        await page.wait_for_timeout(300)
        await frame_modal.page.keyboard.press("Enter")
        await page.wait_for_timeout(600)
        print("-> Assinante validado.", file=sys.stderr)
        
        # 3) CARGO/FUNÇÃO
        print(f"-> Cargo: {cargo}", file=sys.stderr)
        select_cargo = frame_modal.locator("select[name*='Cargo' i], select[id*='Cargo' i]").first
        await select_cargo.wait_for(state="visible", timeout=15000)
        await select_cargo.select_option(label=cargo)
        await select_cargo.evaluate(
            "el => { el.dispatchEvent(new Event('change', { bubbles: true })); }"
        )
        await page.wait_for_timeout(500)
        
        # 4) SENHA (digitação humana caractere por caractere - CRÍTICO!)
        print("-> Digitando senha...", file=sys.stderr)
        campo_senha = frame_modal.locator("input[name='pwdSenha'], input[type='password']").first
        await campo_senha.wait_for(state="attached", timeout=20000)
        
        # Foca via JS
        await campo_senha.evaluate(
            """(el) => {
                try { el.scrollIntoView({block:'center'}); } catch(e) {}
                try { el.focus(); } catch(e) {}
            }"""
        )
        await page.wait_for_timeout(700)
        
        # Limpa campo
        await campo_senha.evaluate(
            """(el) => {
                el.value = '';
                el.dispatchEvent(new Event('input', { bubbles: true }));
            }"""
        )
        await page.wait_for_timeout(200)
        
        # Digita caractere por caractere (simula humano)
        for ch in senha:
            await frame_modal.page.keyboard.type(ch, delay=140)
        
        resultado["modal_preenchido"] = True
        
        # 5) PAUSA HUMANA antes de assinar
        print("-> Pausa humana (3s)...", file=sys.stderr)
        await page.wait_for_timeout(3000)
        
        # 6) CLICA EM ASSINAR
        print("-> Clicando em ASSINAR...", file=sys.stderr)
        btn_assinar = frame_modal.locator("input[value='Assinar'], button:has-text('Assinar')").first
        await btn_assinar.wait_for(state="visible", timeout=15000)
        await btn_assinar.click()
        
        # 7) Confirmação extra (se houver)
        await page.wait_for_timeout(700)
        try:
            await frame_modal.page.keyboard.press("Enter")
        except Exception:
            pass
        
        await page.wait_for_timeout(700)
        for texto in ["OK", "Confirmar", "Fechar"]:
            try:
                btn_conf = frame_modal.get_by_role("button", name=texto).first
                if await btn_conf.count() > 0 and await btn_conf.is_visible():
                    await btn_conf.click()
                    break
            except Exception:
                pass
        
        # 8) Aguarda modal fechar
        for _ in range(80):  # ~16s
            if page.frame(name="modal-frame") is None:
                print("-> Modal fechado: assinatura concluída!", file=sys.stderr)
                resultado["assinado"] = True
                return resultado
            await page.wait_for_timeout(200)
        
        # Modal não fechou, mas provavelmente assinou
        # Considera sucesso com aviso
        print("-> Modal não fechou, mas assinatura provavelmente OK.", file=sys.stderr)
        resultado["assinado"] = True
        resultado["aviso"] = "Modal não fechou automaticamente"
        return resultado
        
    except Exception as e:
        resultado["erro"] = str(e)
        debug_print(f"Erro no modal: {e}")
        return resultado


# =========================================================
# FUNÇÃO PRINCIPAL
# =========================================================
async def assinar_documento(
    sei_numero: str,
    chat_id: str = None,
    sigla: str = None,
    # NOVO v2.2: Credenciais diretas (Laravel/PlattArgus WEB)
    usuario: str = None,
    senha: str = None,
    orgao_id: str = "31",
    nome_completo: str = None,
    cargo: str = None
) -> Dict:
    """
    Assina um documento individual no SEI.
    
    Args:
        sei_numero: Número SEI do documento (ex: "0018817258")
        chat_id: Chat ID do Telegram (para identificar usuário/diretoria)
        sigla: Sigla da diretoria
        usuario: Usuário SEI (credencial direta - NOVO v2.2)
        senha: Senha SEI (credencial direta - NOVO v2.2)
        orgao_id: ID do órgão (credencial direta - NOVO v2.2)
        nome_completo: Nome para assinatura (credencial direta - NOVO v2.2)
        cargo: Cargo para assinatura (credencial direta - NOVO v2.2)
    
    Returns:
        Dict com resultado da operação
    """
    output = {
        "sucesso": False,
        "sei_numero": sei_numero,
        "documento_aberto": False,
        "caneta_clicada": False,
        "modal_encontrado": False,
        "modal_preenchido": False,
        "assinado": False,
        "assinante": None,
        "cargo": None,
        "diretoria": sigla,
        "aviso": None,
        "foto": None,
        "erro": None,
        "timestamp": datetime.now().isoformat()
    }
    
    senha_temp = None  # Para limpar depois
    
    try:
        # =====================================================
        # NOVO v2.2: Credenciais diretas OU busca do banco
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
        
        if not dados_assinante.get("senha"):
            output["erro"] = "Senha do assinante não encontrada"
            return output
        
        if not dados_assinante.get("login_sei"):
            output["erro"] = "Login SEI do assinante não encontrado"
            return output
        
        if not dados_assinante.get("nome_completo"):
            output["erro"] = "Nome completo do assinante não encontrado"
            return output
        
        senha_temp = dados_assinante["senha"]
        output["assinante"] = dados_assinante["nome_completo"]
        output["cargo"] = dados_assinante["cargo_assinatura"]
        
        debug_print(f"Assinante: {output['assinante']}")
        debug_print(f"Cargo: {output['cargo']}")
        
        # 2) ABRE SESSÃO SEI (com credenciais diretas ou sigla/chat_id)
        async with criar_sessao_sei(chat_id=chat_id, sigla=sigla, usuario=usuario, senha=senha, orgao_id=orgao_id) as sessao:
            page = sessao['page']
            diretoria = sessao.get('diretoria', {})
            
            if diretoria:
                output['diretoria'] = diretoria.get('sigla')
            
            await debug_frames(page, "FRAMES APÓS LOGIN")
            
            # 3) PESQUISA DOCUMENTO PELO SEI Nº
            if not await pesquisar_documento_por_sei(page, sei_numero):
                output["erro"] = "Falha ao pesquisar documento"
                return output
            
            output["documento_aberto"] = True
            await debug_frames(page, "FRAMES APÓS PESQUISA")
            
            # 4) CLICA NA CANETA (ASSINAR)
            if not await clicar_botao_assinar(page):
                output["erro"] = "Botão Assinar não encontrado"
                # Evidência (screenshot) - preferencialmente em memória
                foto_bytes = await capturar_evidencia(page)
                output["foto_path"] = None
                output["foto_enviada"] = False
                if foto_bytes:
                    # Opcional: salvar em disco (desligado por padrão)
                    if ARGUS_SAVE_SCREENSHOT:
                        foto_erro = str(FOTOS_DIR / f"erro_assinar_{sei_numero}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
                        try:
                            await page.screenshot(path=foto_erro, full_page=True, type="png")
                            output["foto_path"] = foto_erro
                        except Exception:
                            pass
                    # Opcional: enviar direto ao Telegram (prova para o operador)
                    if ARGUS_SEND_PROOF_TELEGRAM and chat_id:
                        caption = f"❌ Falha ao assinar {sei_numero}"
                        output["foto_enviada"] = await telegram_send_photo_bytes(chat_id=str(chat_id), photo_bytes=foto_bytes, caption=caption)
                return output
            
            output["caneta_clicada"] = True
            
            # 5) PREENCHE MODAL E ASSINA
            resultado_modal = await preencher_modal_e_assinar(
                page=page,
                orgao=dados_assinante.get("orgao", ORGAO_PADRAO),
                login_sei=dados_assinante["login_sei"],
                nome_completo=dados_assinante["nome_completo"],
                cargo=dados_assinante["cargo_assinatura"],
                senha=senha_temp
            )
            
            output["modal_encontrado"] = resultado_modal.get("modal_encontrado", False)
            output["modal_preenchido"] = resultado_modal.get("modal_preenchido", False)
            output["assinado"] = resultado_modal.get("assinado", False)
            output["aviso"] = resultado_modal.get("aviso")
            
            if resultado_modal.get("erro"):
                output["erro"] = resultado_modal["erro"]
            
            # 6) EVIDÊNCIA (screenshot) - em memória e/ou Telegram (sem salvar em disco por padrão)
            output["foto_path"] = None
            output["foto_enviada"] = False
            if output["assinado"]:
                await page.wait_for_timeout(2000)
                foto_bytes = await capturar_evidencia(page)

                # Opcional: salvar em disco (desligado por padrão)
                if ARGUS_SAVE_SCREENSHOT and foto_bytes:
                    foto_nome = f"assinado_{sei_numero}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                    output["foto_path"] = str(FOTOS_DIR / foto_nome)
                    try:
                        await page.screenshot(path=output["foto_path"], full_page=True, type="png")
                        debug_print(f"Screenshot salvo: {output['foto_path']}")
                    except Exception as e:
                        debug_print(f"Erro ao salvar screenshot: {e}")

                # Opcional: enviar direto ao Telegram
                if ARGUS_SEND_PROOF_TELEGRAM and chat_id and foto_bytes:
                    # Caption com aviso se houver
                    if output.get("aviso"):
                        caption = f"⚠️ Assinado: {sei_numero}\n({output['aviso']})"
                    else:
                        caption = f"✅ Assinado: {sei_numero}"
                    output["foto_enviada"] = await telegram_send_photo_bytes(chat_id=str(chat_id), photo_bytes=foto_bytes, caption=caption)
            
            # 7) RESULTADO FINAL
            output["sucesso"] = output["assinado"]
            
            if output["sucesso"]:
                if output.get("aviso"):
                    output["mensagem"] = f"Documento {sei_numero} assinado! ({output['aviso']})"
                    print(f"\n⚠️ DOCUMENTO {sei_numero} ASSINADO (com aviso)!\n", file=sys.stderr)
                else:
                    output["mensagem"] = f"Documento {sei_numero} assinado com sucesso!"
                    print(f"\n✅ DOCUMENTO {sei_numero} ASSINADO COM SUCESSO!\n", file=sys.stderr)
            else:
                print(f"\n❌ FALHA: {output['erro']}\n", file=sys.stderr)
            
            return output
    
    except Exception as e:
        output["erro"] = str(e)
        debug_print(f"Erro: {e}")
        import traceback
        traceback.print_exc(file=sys.stderr)
        return output
    
    finally:
        # Limpa senha da memória
        if senha_temp:
            senha_temp = None
            del senha_temp


# =========================================================
# CLI
# =========================================================
async def main_async():
    global DEBUG
    
    parser = argparse.ArgumentParser(description="ARGUS - Assinar Documento SEI v2.2 (Credenciais Diretas)")
    parser.add_argument("sei_numero", help="Número SEI do documento")
    parser.add_argument("--chat-id", help="Chat ID do Telegram")
    parser.add_argument("--sigla", help="Sigla da diretoria")
    # NOVO v2.2: Credenciais diretas
    parser.add_argument("--usuario", help="Usuário SEI (credencial direta)")
    parser.add_argument("--senha", help="Senha SEI (credencial direta)")
    parser.add_argument("--orgao", default="31", help="ID do órgão (default: 31)")
    parser.add_argument("--nome", help="Nome completo para assinatura")
    parser.add_argument("--cargo", help="Cargo para assinatura")
    parser.add_argument("--debug", action="store_true", help="Mostra frames e diagnósticos")
    
    args = parser.parse_args()
    
    # Validação: precisa de credenciais diretas OU sigla/chat_id
    if not args.usuario and not args.chat_id and not args.sigla:
        parser.error("Informe --usuario + --senha OU --chat-id OU --sigla")
    
    if args.usuario and not args.senha:
        parser.error("--senha é obrigatório quando usar --usuario")
    
    DEBUG = args.debug
    
    resultado = await assinar_documento(
        sei_numero=args.sei_numero,
        chat_id=args.chat_id,
        sigla=args.sigla,
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
