#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
assinar_bloco.py - Assinatura de Bloco Completo no SEI

VERSÃO 2.2 - PRODUÇÃO + CREDENCIAIS DIRETAS

Fluxo:
  1. Login via sei_auth_multi 
  2. Busca dados do assinante no banco
  3. Navega: Menu → Blocos → Assinatura
  4. Pesquisa o bloco pelo número
  5. Seleciona checkbox do bloco (TODOS OS DOCS)
  6. Clica na caneta de assinatura
  7. Preenche modal e assina (ArrowDown + Enter)
  8. Captura evidência e envia ao Telegram

Uso:
    # NOVO - Credenciais diretas (Laravel/PlattArgus WEB)
    python assinar_bloco.py "845468" --usuario gilmar.moura --senha xxx --nome "Gilmar Moura" --cargo "Diretor"
    
    # LEGADO - Telegram
    python assinar_bloco.py "845468" --chat-id "8152690312"
    python assinar_bloco.py "845468" --sigla DRH
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

# Para descriptografar senha
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
ORGAO_PADRAO = "CBMAC"

# Evidência de assinatura (screenshot)
ARGUS_SAVE_SCREENSHOT = os.getenv("ARGUS_SAVE_SCREENSHOT", "0").strip() == "1"
ARGUS_SEND_PROOF_TELEGRAM = os.getenv("ARGUS_SEND_PROOF_TELEGRAM", "1").strip() == "1"

# Diretório para screenshots (só usado se ARGUS_SAVE_SCREENSHOT=1)
FOTOS_DIR = Path(os.getenv("ARGUS_FOTOS_DIR", "/tmp/argus_fotos"))
if ARGUS_SAVE_SCREENSHOT:
    FOTOS_DIR.mkdir(exist_ok=True)


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
# TELEGRAM - evidência
# =========================================================
def _telegram_api_base() -> Optional[str]:
    """Retorna base do Bot API."""
    base = os.getenv("TELEGRAM_BOT_API_BASE", "").strip()
    if base:
        return base.rstrip("/")
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if token:
        return f"https://api.telegram.org/bot{token}"
    return None


async def telegram_send_photo_bytes(chat_id: str, photo_bytes: bytes, caption: str = "") -> bool:
    """Envia foto para o Telegram usando bytes em memória."""
    base = _telegram_api_base()
    if not base or not chat_id or not photo_bytes:
        return False

    url = f"{base}/sendPhoto"
    data = {"chat_id": str(chat_id)}
    if caption:
        data["caption"] = caption[:1024]

    try:
        import httpx  # type: ignore
        async with httpx.AsyncClient(timeout=20) as client:
            files = {"photo": ("bloco_assinado.png", photo_bytes, "image/png")}
            r = await client.post(url, data=data, files=files)
            return r.status_code == 200
    except Exception:
        try:
            import requests  # type: ignore
            loop = asyncio.get_running_loop()
            def _post():
                files = {"photo": ("bloco_assinado.png", photo_bytes, "image/png")}
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
    """Busca dados do assinante no banco de diretorias (SQLite direto)."""
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
            debug_print("Sigla nao encontrada para buscar assinante")
            return dados
        
        debug_print(f"Buscando diretoria: {sigla}")
        
        # Busca dados da diretoria (login, senha)
        cursor.execute(
            "SELECT sei_usuario, sei_senha_encrypted, nome, cargo_assinatura FROM diretorias WHERE sigla = ? AND ativo = 1", 
            (sigla,)
        )
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
                    debug_print(f"Senha descriptografada: {len(dados['senha'])} chars")
                except Exception as e:
                    debug_print(f"[ERRO] Descriptografia: {e}")
            
            debug_print(f"Assinante encontrado: {dados['login_sei']}")
        else:
            debug_print(f"Diretoria {sigla} nao encontrada no banco")
        
        return dados
        
    except Exception as e:
        debug_print(f"[ERRO] buscar_dados_assinante: {e}")
        return dados


# =========================================================
# NAVEGAÇÃO
# =========================================================
async def navegar_para_blocos_assinatura(page):
    """Navega pelo menu até Blocos → Assinatura."""
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
    for f in page.frames:
        try:
            if await f.locator("#sbmPesquisar").count() > 0:
                return f
        except Exception:
            pass
    return None


# =========================================================
# BLOCO
# =========================================================
async def pesquisar_bloco(frame, numero_bloco: str):
    """Pesquisa um bloco pelo número."""
    print(f"-> Pesquisando bloco {numero_bloco}...", file=sys.stderr)

    campo = frame.locator(
        "label:has-text('Palavras-chave para pesquisa')"
    ).locator("xpath=following::input[1]")

    await campo.wait_for(state="visible", timeout=10000)
    await campo.fill(numero_bloco)

    # CORREÇÃO: Usar seletor específico para evitar duplicação
    btn = frame.locator("#divInfraBarraComandosSuperior #sbmPesquisar").first
    await btn.wait_for(state="visible", timeout=8000)
    await btn.click()

    await frame.wait_for_load_state("networkidle")
    await frame.wait_for_timeout(1500)
    print("-> Pesquisa executada.", file=sys.stderr)


async def selecionar_checkbox_do_bloco(frame, numero_bloco: str):
    """Seleciona o checkbox do bloco (TODOS OS DOCUMENTOS)."""
    print(f"-> Selecionando checkbox do bloco {numero_bloco}...", file=sys.stderr)

    chk = frame.locator(
        f"input[type='checkbox'][value='{numero_bloco}'], "
        f"input[type='checkbox'][title='{numero_bloco}']"
    ).first

    await chk.wait_for(state="attached", timeout=10000)

    container = chk.locator("xpath=..")
    try:
        await container.scroll_into_view_if_needed()
    except Exception:
        pass

    await container.click(force=True)
    print("-> Checkbox selecionado.", file=sys.stderr)


async def clicar_na_caneta(frame, numero_bloco: str):
    """Clica na caneta de assinatura (ASSINA TODOS OS DOCS DO BLOCO)."""
    print(f"-> Clicando na caneta do bloco {numero_bloco}...", file=sys.stderr)

    linha = frame.locator("tr", has=frame.locator(f"text={numero_bloco}")).first
    await linha.wait_for(state="visible", timeout=10000)

    caneta = linha.locator("td:last-child a").first
    if await caneta.count() == 0:
        raise Exception("Caneta não encontrada.")

    await caneta.click(force=True)
    await frame.wait_for_timeout(2000)
    print("-> Caneta clicada.", file=sys.stderr)


# =========================================================
# ASSINATURA - LÓGICA CORRETA (ArrowDown + Enter)
# =========================================================
async def preencher_modal_e_assinar(page, orgao: str, login_sei: str, nome_completo: str, cargo: str, senha: str) -> Dict:
    """Preenche o modal de assinatura e assina."""
    resultado = {
        "modal_encontrado": False,
        "modal_preenchido": False,
        "assinado": False,
        "erro": None,
    }

    print("-> Aguardando modal de assinatura...", file=sys.stderr)

    frame_modal = None
    for _ in range(80):
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
        select_orgao = frame_modal.locator("select[name*='Orgao' i]").first
        await select_orgao.wait_for(state="visible", timeout=15000)
        await select_orgao.select_option(label=orgao)
        await page.wait_for_timeout(400)

        # 2) ASSINANTE (digitação humana)
        print(f"-> Assinante: {login_sei}", file=sys.stderr)
        campo_assinante = frame_modal.locator("input[type='text']:visible").first
        await campo_assinante.wait_for(state="visible", timeout=15000)
        await campo_assinante.click()
        await campo_assinante.fill("")
        await campo_assinante.type(login_sei, delay=120)
        await page.wait_for_timeout(900)

        # CORREÇÃO: Seleciona da lista de autocomplete (ArrowDown + Enter)
        print(f"-> Selecionando: {nome_completo}", file=sys.stderr)
        # Seleciona primeiro item com teclado (IGUAL AO ASSINAR_DOCUMENTO)
        await frame_modal.page.keyboard.press("ArrowDown")
        await page.wait_for_timeout(300)
        await frame_modal.page.keyboard.press("Enter")
        await page.wait_for_timeout(600)
        print("-> Assinante validado.", file=sys.stderr)

        # 3) CARGO
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
        
        # Digitação caractere por caractere (IGUAL AO ASSINAR_DOCUMENTO)
        for ch in senha:
            await frame_modal.page.keyboard.type(ch, delay=140)

        resultado["modal_preenchido"] = True

        # 5) PAUSA HUMANA
        print("-> Pausa humana (3s)...", file=sys.stderr)
        await page.wait_for_timeout(3000)

        # 6) ASSINAR
        print("-> Clicando em ASSINAR...", file=sys.stderr)
        btn = frame_modal.locator("input[value='Assinar'], button:has-text('Assinar')").first
        await btn.wait_for(state="visible", timeout=15000)
        await btn.click()

        # 7) CONFIRMAÇÃO
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

        # 8) AGUARDA FECHAMENTO
        for _ in range(80):
            if page.frame(name="modal-frame") is None:
                print("-> Modal fechado: assinatura concluída!", file=sys.stderr)
                resultado["assinado"] = True
                return resultado
            await page.wait_for_timeout(200)

        resultado["erro"] = "Modal não fechou após assinatura."
        return resultado

    except Exception as e:
        resultado["erro"] = str(e)
        return resultado


# =========================================================
# FUNÇÃO PRINCIPAL
# =========================================================
async def assinar_bloco(
    numero_bloco: str,
    chat_id: str = None,
    sigla: str = None,
    # NOVO v2.2: Credenciais diretas (Laravel/PlattArgus WEB)
    usuario: str = None,
    senha: str = None,
    orgao_id: str = "31",
    nome_completo: str = None,
    cargo: str = None
) -> Dict:
    """Assina todos os documentos de um bloco."""
    output = {
        "sucesso": False,
        "bloco": numero_bloco,
        "checkbox_selecionado": False,
        "caneta_clicada": False,
        "modal_encontrado": False,
        "modal_preenchido": False,
        "assinado": False,
        "assinante": None,
        "cargo": None,
        "diretoria": sigla,
        "foto_path": None,
        "foto_enviada": False,
        "erro": None,
        "timestamp": datetime.now().isoformat()
    }
    
    senha_temp = None
    
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
            frame = await achar_frame_lista_blocos(page)
            if frame is None:
                output["erro"] = "Frame de blocos não encontrado."
                return output
            
            await debug_frames(page, "FRAMES NA TELA DE BLOCOS")
            
            # 5) PESQUISA O BLOCO
            await pesquisar_bloco(frame, numero_bloco)
            
            # 6) SELECIONA CHECKBOX (TODOS OS DOCS DO BLOCO)
            await selecionar_checkbox_do_bloco(frame, numero_bloco)
            output["checkbox_selecionado"] = True
            
            # 7) CLICA NA CANETA (ASSINAR TODOS OS DOCS)
            await clicar_na_caneta(frame, numero_bloco)
            output["caneta_clicada"] = True
            
            # 8) PREENCHE MODAL E ASSINA (LÓGICA CORRIGIDA)
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
            
            if resultado_modal.get("erro"):
                output["erro"] = resultado_modal["erro"]
                
                # Captura evidência de erro (opcional)
                if chat_id:
                    foto_bytes = await capturar_evidencia(page)
                    if foto_bytes and ARGUS_SEND_PROOF_TELEGRAM:
                        caption = f"❌ Falha ao assinar bloco {numero_bloco}"
                        output["foto_enviada"] = await telegram_send_photo_bytes(
                            chat_id=str(chat_id), 
                            photo_bytes=foto_bytes, 
                            caption=caption
                        )
                return output
            
            # 9) EVIDÊNCIA (screenshot) - em memória e/ou Telegram
            if output["assinado"]:
                await page.wait_for_timeout(2000)
                foto_bytes = await capturar_evidencia(page)

                # Opcional: salvar em disco (desligado por padrão)
                if ARGUS_SAVE_SCREENSHOT and foto_bytes:
                    foto_nome = f"bloco_assinado_{numero_bloco}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                    output["foto_path"] = str(FOTOS_DIR / foto_nome)
                    try:
                        with open(output["foto_path"], "wb") as f:
                            f.write(foto_bytes)
                        debug_print(f"Screenshot salvo: {output['foto_path']}")
                    except Exception as e:
                        debug_print(f"Erro ao salvar screenshot: {e}")

                # Opcional: enviar direto ao Telegram
                if ARGUS_SEND_PROOF_TELEGRAM and chat_id and foto_bytes:
                    caption = f"✅ Bloco assinado: {numero_bloco}"
                    output["foto_enviada"] = await telegram_send_photo_bytes(
                        chat_id=str(chat_id), 
                        photo_bytes=foto_bytes, 
                        caption=caption
                    )
            
            # 10) RESULTADO
            output["sucesso"] = output["assinado"]
            
            if output["sucesso"]:
                output["mensagem"] = f"Bloco {numero_bloco} assinado com sucesso!"
                print(f"\n✅ BLOCO {numero_bloco} ASSINADO COM SUCESSO!\n", file=sys.stderr)
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
        if senha_temp:
            senha_temp = None
            del senha_temp


# =========================================================
# CLI
# =========================================================
async def main_async():
    global DEBUG
    
    parser = argparse.ArgumentParser(description="ARGUS - Assinar Bloco SEI v2.2 (Credenciais Diretas)")
    parser.add_argument("numero_bloco", help="Número do bloco")
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
    
    resultado = await assinar_bloco(
        numero_bloco=args.numero_bloco,
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
