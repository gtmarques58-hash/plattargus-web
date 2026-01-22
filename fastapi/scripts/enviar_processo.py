#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
enviar_processo.py - Envia processos SEI para outras unidades

VERSÃO 1.1 - PRODUÇÃO + CREDENCIAIS DIRETAS

Fluxo em 3 estágios:
  1. SEARCH: Busca unidades destino pelo filtro
  2. PREFLIGHT: Prepara envio, valida destinos, screenshot
  3. COMMIT: Executa o envio efetivo

Uso:
    # NOVO - Credenciais diretas (Laravel/PlattArgus WEB)
    python enviar_processo.py --stage search --nup "0609..." --filtro "DRH" --usuario gilmar.moura --senha xxx
    
    # LEGADO - Via função async (Telegram)
    resultado = await enviar_processo(
        nup="0609.012080.00003/2026-04",
        stage="search",
        filtro="DRH",
        chat_id="8152690312"
    )

    # Via CLI (debug)
    python enviar_processo.py --stage search --nup "0609..." --filtro "DRH" --chat-id "123"
"""

import sys
import os
import json
import asyncio
import argparse
import hashlib
import base64
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any

sys.path.insert(0, "/app/scripts")

from playwright.async_api import (
    async_playwright,
    TimeoutError as PWTimeoutError,
    Error as PWError,
    Page,
    Frame
)

from sei_auth_multi import criar_sessao_sei

# =========================================================
# CONFIG
# =========================================================
DEBUG = os.getenv("ARGUS_DEBUG", "0") == "1"
SELETOR_PESQUISA_RAPIDA = "#txtPesquisaRapida"


def debug_print(msg: str):
    if DEBUG:
        print(f"[DEBUG] {msg}", file=sys.stderr)


# =========================================================
# TELEGRAM - Enviar foto direto (igual assinar_documento)
# =========================================================
def _telegram_api_base() -> Optional[str]:
    base = os.getenv("TELEGRAM_BOT_API_BASE", "").strip()
    if base:
        return base.rstrip("/")
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if token:
        return f"https://api.telegram.org/bot{token}"
    return None


async def telegram_send_photo_bytes(
    chat_id: str, 
    photo_bytes: bytes, 
    caption: str = "",
    reply_markup: Dict = None
) -> bool:
    """Envia foto para o Telegram usando bytes em memória.
    Retorna True/False sem quebrar o fluxo principal.
    """
    base = _telegram_api_base()
    if not base or not chat_id or not photo_bytes:
        return False

    url = f"{base}/sendPhoto"
    data = {"chat_id": str(chat_id), "parse_mode": "HTML"}
    if caption:
        data["caption"] = caption[:1024]
    if reply_markup:
        data["reply_markup"] = json.dumps(reply_markup)

    # Preferência: httpx (async). Fallback: requests (sync em thread).
    try:
        import httpx  # type: ignore
        async with httpx.AsyncClient(timeout=20) as client:
            files = {"photo": ("envio.png", photo_bytes, "image/png")}
            r = await client.post(url, data=data, files=files)
            return r.status_code == 200
    except Exception:
        try:
            import requests  # type: ignore
            loop = asyncio.get_running_loop()
            def _post():
                files = {"photo": ("envio.png", photo_bytes, "image/png")}
                return requests.post(url, data=data, files=files, timeout=20)
            resp = await loop.run_in_executor(None, _post)
            return getattr(resp, "status_code", 0) == 200
        except Exception:
            return False


# =========================================================
# HELPERS - Normalização e Token
# =========================================================
def norm_space(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s+", " ", s)
    return s


def norm_upper(s: str) -> str:
    return norm_space(s).upper()


def token_from_list(nup: str, labels: List[str]) -> str:
    base = norm_upper(nup) + "|" + "|".join(sorted(norm_upper(x) for x in labels))
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:12]


def label_to_b64(label: str) -> str:
    return base64.urlsafe_b64encode(label.encode()).decode()


def b64_to_label(b64: str) -> str:
    try:
        return base64.urlsafe_b64decode(b64.encode()).decode()
    except Exception:
        return b64


async def screenshot_b64(page: Page, full_page: bool = True) -> str:
    try:
        png = await page.screenshot(full_page=full_page, type="png")
        return base64.b64encode(png).decode("ascii")
    except Exception:
        return ""


# =========================================================
# TELEGRAM PAYLOADS
# =========================================================
def mk_reply_markup_choices(nup: str, choices: List[Dict], limit_buttons: int = 10) -> Dict:
    kb = []
    for c in choices[:limit_buttons]:
        txt = c["label"]
        txt = (txt[:40] + "…") if len(txt) > 41 else txt
        # USA TOKEN (12 chars) ao invés de label_b64 (excedia limite de 64 bytes do Telegram)
        token = c.get("token", "")[:12]
        cb_data = f"enviar_pick:{nup}:{token}"
        kb.append([{"text": txt, "callback_data": cb_data}])
    kb.append([{"text": "❌ Cancelar", "callback_data": f"enviar_cancel:{nup}"}])
    return {"inline_keyboard": kb}


def mk_reply_markup_confirm(nup: str, token: str) -> Dict:
    return {
        "inline_keyboard": [[
            {"text": "✅ CONFIRMAR ENVIO", "callback_data": f"enviar_confirm:{nup}:{token}"},
            {"text": "🔁 Trocar destino", "callback_data": f"enviar_refinar:{nup}"}
        ], [
            {"text": "❌ Cancelar", "callback_data": f"enviar_cancel:{nup}"}
        ]]
    }


# =========================================================
# NAVEGAÇÃO SEI
# =========================================================
async def pesquisar_nup(page: Page, nup: str) -> bool:
    debug_print(f"Pesquisando NUP: {nup}")
    print(f"-> Pesquisando NUP: {nup}...", file=sys.stderr)
    try:
        await page.locator(SELETOR_PESQUISA_RAPIDA).wait_for(state="visible", timeout=10000)
        await page.locator(SELETOR_PESQUISA_RAPIDA).fill("")
        await page.locator(SELETOR_PESQUISA_RAPIDA).fill(nup)
        await page.locator(SELETOR_PESQUISA_RAPIDA).press("Enter")
        await page.wait_for_load_state("networkidle", timeout=30000)
        await page.wait_for_timeout(2000)
        print("-> Processo aberto.", file=sys.stderr)
        return True
    except Exception as e:
        print(f"-> Erro na pesquisa: {e}", file=sys.stderr)
        return False


async def abrir_tela_enviar(page: Page) -> bool:
    debug_print("Abrindo tela de envio...")
    print("-> Abrindo tela de envio...", file=sys.stderr)
    
    seletores = [
        'img[title="Enviar Processo"]',
        'img[alt="Enviar Processo"]',
        'a[title="Enviar Processo"]',
        "a[href*='procedimento_enviar']",
        'img[src*="enviar"]',
    ]
    
    for frame in page.frames:
        for sel in seletores:
            try:
                btn = frame.locator(sel).first
                if await btn.count() > 0:
                    await btn.click(force=True)
                    print("-> Clicou em Enviar Processo.", file=sys.stderr)
                    await page.wait_for_timeout(1000)
                    
                    for _ in range(30):
                        for fr in page.frames:
                            try:
                                if await fr.locator("#txtUnidade").count() > 0:
                                    print("-> Tela de envio aberta.", file=sys.stderr)
                                    return True
                            except Exception:
                                continue
                        await page.wait_for_timeout(300)
                    return False
            except Exception:
                continue
    
    print("-> Botão Enviar Processo não encontrado.", file=sys.stderr)
    return False


async def find_frame_envio(page: Page) -> Optional[Frame]:
    for fr in page.frames:
        try:
            if await fr.locator("#txtUnidade").count() > 0:
                return fr
        except Exception:
            continue
    return None


async def maybe_set_orgao(frame_envio: Frame, filtro_up: str) -> tuple:
    try:
        sel = frame_envio.locator("#selOrgao").first
        if await sel.count() == 0:
            return filtro_up, None

        opts = frame_envio.locator("#selOrgao option")
        n = await opts.count()
        if n <= 0:
            return filtro_up, None

        opt_texts = []
        for i in range(min(n, 300)):
            try:
                t = norm_upper(await opts.nth(i).inner_text())
                v = (await opts.nth(i).get_attribute("value")) or ""
                if t:
                    opt_texts.append((t, v))
            except Exception:
                continue

        tokens = filtro_up.split()
        if not tokens:
            return filtro_up, None

        cand1 = tokens[0]
        match = None
        for (t, v) in opt_texts:
            if t == cand1:
                match = (t, v, 1)
                break

        if not match:
            return filtro_up, None

        t, v, used_tokens = match
        await sel.select_option(value=v)
        await asyncio.sleep(0.2)
        rest = " ".join(tokens[used_tokens:]).strip()
        return (rest if rest else filtro_up), t
    except Exception:
        return filtro_up, None


async def digitar_filtro(frame_envio: Frame, filtro_txt: str):
    q = norm_upper(filtro_txt)
    inp = frame_envio.locator("#txtUnidade").first
    await inp.scroll_into_view_if_needed()
    await inp.click(force=True)
    await inp.fill("")
    await inp.type(q, delay=30)
    await asyncio.sleep(0.9)
    try:
        await frame_envio.wait_for_function(
            "(() => { const d=document.getElementById('divInfraAjaxtxtUnidade'); return d && d.innerText && d.innerText.trim().length>0; })()",
            timeout=2000
        )
    except Exception:
        pass


async def coletar_candidatos(frame_envio: Frame, nup: str, max_candidates: int = 10) -> tuple:
    box = frame_envio.locator("#divInfraAjaxtxtUnidade").first
    if await box.count() == 0:
        return 0, [], {"source": "infra", "note": "divInfraAjaxtxtUnidade não existe"}

    items = box.locator("a, div, span, li, td")
    cnt = await items.count()
    out = []
    seen = set()
    limit = min(cnt, max_candidates * 15 if max_candidates else 300)

    for i in range(limit):
        try:
            el = items.nth(i)
            if not await el.is_visible():
                continue
            text = norm_space(await el.inner_text())
            if not text:
                continue
            onclick = (await el.get_attribute("onclick")) or ""
            href = (await el.get_attribute("href")) or ""
            if (not onclick) and (not href):
                tag = (await el.evaluate("e => e.tagName")).upper()
                if tag != "A":
                    continue
            if text in seen:
                continue
            seen.add(text)
            out.append({"label": text, "token": token_from_list(nup, [text])})
            if len(out) >= max_candidates:
                break
        except Exception:
            continue
    return cnt, out, {"source": "infra"}


async def selecionar_item_exato(frame_envio: Frame, label: str) -> bool:
    want = norm_upper(label)
    box = frame_envio.locator("#divInfraAjaxtxtUnidade").first
    if await box.count() == 0:
        return False

    items = box.locator("a, div, span, li, td")
    cnt = await items.count()
    for i in range(min(cnt, 600)):
        try:
            el = items.nth(i)
            if not await el.is_visible():
                continue
            t = norm_upper(await el.inner_text())
            if t == want:
                await el.click()
                await asyncio.sleep(0.6)
                return True
        except Exception:
            continue
    return False


async def ler_sel_unidades(frame_envio: Frame) -> List[str]:
    try:
        data = await frame_envio.evaluate(r"""
        () => {
          const sel = document.querySelector("#selUnidades");
          if (!sel) return [];
          return Array.from(sel.options).map(o => (o.text || "").trim());
        }
        """)
        return [norm_space(x) for x in data if norm_space(x)]
    except Exception:
        return []


async def limpar_destinos(frame_envio: Frame):
    try:
        await frame_envio.evaluate(r"""
        () => {
          const sel = document.querySelector("#selUnidades");
          const hdn = document.querySelector("#hdnUnidades");
          if (sel) sel.innerHTML = "";
          if (hdn) hdn.value = "";
        }
        """)
    except Exception:
        pass


def extrair_filtro_forte(label: str) -> str:
    up = norm_upper(label)
    m = re.search(r"\b[A-Z0-9]{3,}\b", up)
    return m.group(0) if m else up


async def adicionar_destino(frame_envio: Frame, label: str) -> bool:
    filtro = extrair_filtro_forte(label)
    await digitar_filtro(frame_envio, filtro)
    ok = await selecionar_item_exato(frame_envio, label)
    if not ok:
        prefix = norm_space(norm_upper(label).split("-")[0]) if "-" in label else filtro
        if prefix:
            await digitar_filtro(frame_envio, prefix)
            ok = await selecionar_item_exato(frame_envio, label)
    if not ok:
        return False
    sel = await ler_sel_unidades(frame_envio)
    want = norm_upper(label)
    return any(norm_upper(x) == want for x in sel)


async def clicar_enviar(frame_envio: Frame, page: Page):
    page.once("dialog", lambda d: asyncio.create_task(d.accept()))
    btn = frame_envio.locator("#sbmEnviar").first
    if await btn.count() == 0:
        raise RuntimeError("Botão #sbmEnviar não encontrado.")
    await btn.click()
    await page.wait_for_timeout(1200)


async def wait_text_regex_any_frame(page: Page, pattern: str, timeout_ms: int = 15000) -> bool:
    rx = re.compile(pattern, re.I)
    start = asyncio.get_event_loop().time()
    while (asyncio.get_event_loop().time() - start) * 1000 < timeout_ms:
        for fr in page.frames:
            try:
                body = fr.locator("body")
                if await body.count() > 0:
                    txt = await body.inner_text()
                    if rx.search(txt):
                        return True
            except Exception:
                continue
        await page.wait_for_timeout(300)
    return False


async def extract_unidade_pos_envio(page: Page) -> str:
    for fr in page.frames:
        try:
            body = fr.locator("body")
            if await body.count() == 0:
                continue
            txt = await body.inner_text()
            m = re.search(r"Processo aberto somente na unidade\s+(.+?)[\.\n]", txt, re.I)
            if m:
                return norm_space(m.group(1))
        except Exception:
            continue
    return ""


# =========================================================
# STAGES
# =========================================================
async def stage_search(page: Page, frame_envio: Frame, nup: str, filtro: str, chat_id: str = None, max_candidates: int = 10) -> Dict:
    filtro_up = norm_upper(filtro)
    filtro_txt, orgao = await maybe_set_orgao(frame_envio, filtro_up)
    await digitar_filtro(frame_envio, filtro_txt if filtro_txt else filtro_up)
    total_raw, choices, meta = await coletar_candidatos(frame_envio, nup, max_candidates)
    
    # Prepara caption e reply_markup
    caption = (
        f"🔎 <b>Enviar Processo</b>\n"
        f"📋 NUP: <code>{nup}</code>\n"
        f"🏛️ Órgão: {orgao or 'N/A'}\n"
        f"🔍 Filtro: {filtro_up}\n\n"
        f"Selecione o destino:"
    )
    reply_markup = mk_reply_markup_choices(nup, choices)
    
    # Envia foto direto para o Telegram
    foto_enviada = False
    if chat_id:
        try:
            foto_bytes = await page.screenshot(full_page=True, type="png")
            foto_enviada = await telegram_send_photo_bytes(
                chat_id=chat_id,
                photo_bytes=foto_bytes,
                caption=caption,
                reply_markup=reply_markup
            )
        except Exception as e:
            debug_print(f"Erro ao capturar/enviar foto: {e}")

    return {
        "ok": True, 
        "stage": "search", 
        "nup": nup, 
        "filtro_recebido": filtro, 
        "filtro_usado": filtro_up,
        "orgao_aplicado": orgao, 
        "total_raw": total_raw, 
        "choices": choices, 
        "meta": meta,
        "foto_enviada": foto_enviada,
        "skip_telegram": foto_enviada  # N8N não precisa enviar se foto já foi
    }


async def stage_preflight(page: Page, frame_envio: Frame, nup: str, labels: List[str], chat_id: str = None, token: str = None) -> Dict:
    if not labels:
        return {"ok": False, "erro": "Nenhum destino informado", "stage": "preflight"}
    if len(labels) > 3:
        return {"ok": False, "erro": "Máximo 3 destinos", "stage": "preflight"}

    token_calc = token_from_list(nup, labels)
    if token and token.strip() != token_calc:
        return {"ok": False, "erro": f"Token inválido. Esperado={token_calc}", "stage": "preflight"}

    await limpar_destinos(frame_envio)

    prefixes = [norm_space(norm_upper(lb).split("-")[0]) for lb in labels if "-" in lb]
    if prefixes and all(p == prefixes[0] for p in prefixes):
        await maybe_set_orgao(frame_envio, prefixes[0])

    for lb in labels:
        if not await adicionar_destino(frame_envio, lb):
            return {"ok": False, "erro": f"Não consegui selecionar: {lb}", "stage": "preflight"}

    sel = await ler_sel_unidades(frame_envio)
    if sorted(norm_upper(x) for x in labels) != sorted(norm_upper(x) for x in sel):
        return {"ok": False, "erro": "Lista difere do esperado", "stage": "preflight"}

    # Prepara caption e reply_markup
    caption = (
        f"⚠️ <b>PRÉ-ENVIO</b>\n\n📋 NUP: <code>{nup}</code>\n"
        f"📍 Destinos ({len(labels)}/3):\n• " + "\n• ".join(labels) + "\n\nConfirme o envio."
    )
    reply_markup = mk_reply_markup_confirm(nup, token_calc)
    
    # Envia foto direto para o Telegram
    foto_enviada = False
    if chat_id:
        try:
            foto_bytes = await page.screenshot(full_page=True, type="png")
            foto_enviada = await telegram_send_photo_bytes(
                chat_id=chat_id,
                photo_bytes=foto_bytes,
                caption=caption,
                reply_markup=reply_markup
            )
        except Exception as e:
            debug_print(f"Erro ao capturar/enviar foto: {e}")

    return {
        "ok": True, 
        "stage": "preflight", 
        "nup": nup, 
        "labels": labels, 
        "token": token_calc,
        "selUnidades": sel,
        "foto_enviada": foto_enviada,
        "skip_telegram": foto_enviada
    }


async def stage_commit(page: Page, frame_envio: Frame, nup: str, labels: List[str], token: str, chat_id: str = None) -> Dict:
    if not labels:
        return {"ok": False, "erro": "Nenhum destino", "stage": "commit"}

    token_calc = token_from_list(nup, labels)
    if not token or token.strip() != token_calc:
        return {"ok": False, "erro": f"Token inválido. Esperado={token_calc}", "stage": "commit"}

    await limpar_destinos(frame_envio)

    prefixes = [norm_space(norm_upper(lb).split("-")[0]) for lb in labels if "-" in lb]
    if prefixes and all(p == prefixes[0] for p in prefixes):
        await maybe_set_orgao(frame_envio, prefixes[0])

    for lb in labels:
        if not await adicionar_destino(frame_envio, lb):
            return {"ok": False, "erro": f"Não consegui selecionar: {lb}", "stage": "commit"}

    sel = await ler_sel_unidades(frame_envio)
    if sorted(norm_upper(x) for x in labels) != sorted(norm_upper(x) for x in sel):
        return {"ok": False, "erro": "Lista difere do esperado", "stage": "commit"}

    await clicar_enviar(frame_envio, page)

    enviado = await wait_text_regex_any_frame(page, r"Processo aberto (somente na unidade|nas unidades)", timeout_ms=15000)
    unidade_final = await extract_unidade_pos_envio(page) if enviado else ""

    # Envia foto direto para o Telegram
    foto_enviada = False
    if chat_id:
        try:
            foto_bytes = await page.screenshot(full_page=True, type="png")
            if enviado:
                caption = (
                    f"✅ <b>ENVIADO!</b>\n\n📋 NUP: <code>{nup}</code>\n"
                    f"📍 Destinos:\n• " + "\n• ".join(labels) +
                    (f"\n\n📌 Aberto em: <b>{unidade_final}</b>" if unidade_final else "")
                )
            else:
                caption = (
                    f"❌ <b>Falha no Envio</b>\n\n📋 NUP: <code>{nup}</code>\n"
                    f"❗ Não foi possível confirmar o envio."
                )
            foto_enviada = await telegram_send_photo_bytes(
                chat_id=chat_id,
                photo_bytes=foto_bytes,
                caption=caption
            )
        except Exception as e:
            debug_print(f"Erro ao capturar/enviar foto: {e}")

    if enviado:
        return {
            "ok": True, 
            "stage": "commit", 
            "enviado": True, 
            "nup": nup, 
            "labels": labels,
            "token": token_calc, 
            "unidade_pos_envio": unidade_final,
            "foto_enviada": foto_enviada,
            "skip_telegram": foto_enviada
        }
    else:
        return {
            "ok": False, 
            "stage": "commit", 
            "enviado": False, 
            "nup": nup, 
            "labels": labels,
            "erro": "Não confirmou envio",
            "foto_enviada": foto_enviada
        }


# =========================================================
# FUNÇÃO PRINCIPAL
# =========================================================
async def enviar_processo(
    nup: str,
    stage: str,
    chat_id: str = None,
    sigla: str = None,
    filtro: str = None,
    labels: List[str] = None,
    token: str = None,
    max_candidates: int = 10,
    # NOVO v1.1: Credenciais diretas (Laravel/PlattArgus WEB)
    usuario: str = None,
    senha: str = None,
    orgao_id: str = "31"
) -> Dict[str, Any]:
    output = {"sucesso": False, "nup": nup, "stage": stage, "diretoria": sigla,
              "erro": None, "timestamp": datetime.now().isoformat()}
    
    try:
        async with criar_sessao_sei(chat_id=chat_id, sigla=sigla, usuario=usuario, senha=senha, orgao_id=orgao_id) as sessao:
            page = sessao['page']
            diretoria = sessao.get('diretoria', {})
            if diretoria:
                output['diretoria'] = diretoria.get('sigla')
            
            if not await pesquisar_nup(page, nup):
                output["erro"] = "Falha ao pesquisar processo"
                return output
            
            if not await abrir_tela_enviar(page):
                output["erro"] = "Falha ao abrir tela de envio"
                return output
            
            frame_envio = await find_frame_envio(page)
            if not frame_envio:
                output["erro"] = "Frame de envio não encontrado"
                return output
            
            stage_lower = stage.lower().strip()
            if stage_lower == "search":
                if not filtro:
                    output["erro"] = "Filtro obrigatório para search"
                    return output
                resultado = await stage_search(page, frame_envio, nup, filtro, chat_id, max_candidates)
            elif stage_lower == "preflight":
                if not labels:
                    output["erro"] = "Labels obrigatórios para preflight"
                    return output
                resultado = await stage_preflight(page, frame_envio, nup, labels, chat_id, token)
            elif stage_lower == "commit":
                if not labels or not token:
                    output["erro"] = "Labels e token obrigatórios para commit"
                    return output
                resultado = await stage_commit(page, frame_envio, nup, labels, token, chat_id)
            else:
                output["erro"] = f"Stage inválido: {stage}"
                return output
            
            output.update(resultado)
            output["sucesso"] = resultado.get("ok", False)
            return output
    
    except Exception as e:
        output["erro"] = str(e)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return output


# =========================================================
# CLI
# =========================================================
async def main_async():
    global DEBUG
    parser = argparse.ArgumentParser(description="ARGUS - Enviar Processo SEI v1.1 (Credenciais Diretas)")
    parser.add_argument("--stage", required=True, choices=["search", "preflight", "commit"])
    parser.add_argument("--nup", required=True)
    parser.add_argument("--chat-id")
    parser.add_argument("--sigla")
    # NOVO v1.1: Credenciais diretas
    parser.add_argument("--usuario", help="Usuário SEI (credencial direta)")
    parser.add_argument("--senha", help="Senha SEI (credencial direta)")
    parser.add_argument("--orgao", default="31", help="ID do órgão (default: 31)")
    parser.add_argument("--filtro", default="")
    parser.add_argument("--labels", action="append", default=[])
    parser.add_argument("--token", default="")
    parser.add_argument("--max-candidates", type=int, default=10)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    
    # Validação: precisa de credenciais diretas OU sigla/chat_id
    if not args.usuario and not args.chat_id and not args.sigla:
        parser.error("Informe --usuario + --senha OU --chat-id OU --sigla")
    
    if args.usuario and not args.senha:
        parser.error("--senha é obrigatório quando usar --usuario")
    
    DEBUG = args.debug
    resultado = await enviar_processo(
        nup=args.nup, stage=args.stage, chat_id=args.chat_id, sigla=args.sigla,
        filtro=args.filtro, labels=args.labels if args.labels else None,
        token=args.token, max_candidates=args.max_candidates,
        usuario=args.usuario, senha=args.senha, orgao_id=args.orgao
    )
    print(json.dumps(resultado, indent=2, ensure_ascii=False))


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
