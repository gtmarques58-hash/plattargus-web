#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
capturar_editor_sei.py - Captura estrutura do editor de documentos SEI

Usa os mesmos seletores do atuar_no_processo.py para garantir compatibilidade.

Uso:
    python capturar_editor_sei.py "NUP" "TipoDocumento" --usuario xxx --senha yyy --orgao 31
"""

import os
import sys
import json
import asyncio
from datetime import datetime
from typing import Dict, Any
from pathlib import Path

sys.path.insert(0, "/app/scripts")

from playwright.async_api import async_playwright, Page
from sei_auth_multi import criar_sessao_sei, CONTROL_URL

DEBUG = True

# Seletores SEI (mesmos do atuar_no_processo.py)
SELETOR_FRAME_CONTEUDO_PAI = 'iframe[name="ifrConteudoVisualizacao"]'
SELETOR_FRAME_VISUALIZACAO = 'iframe[name="ifrVisualizacao"]'
SELETOR_IFRAME_CORPO_TEXTO = 'iframe[title="Corpo do Texto"]'


def debug_print(msg: str):
    if DEBUG:
        print(f"[DEBUG] {msg}", file=sys.stderr)


async def capturar_estrutura_editor(
    nup: str,
    tipo_documento: str,
    usuario: str,
    senha: str,
    orgao_id: str = "31"
) -> Dict[str, Any]:
    """Captura a estrutura do editor SEI para análise."""

    output = {
        "ok": False,
        "erro": None,
        "timestamp": datetime.now().isoformat(),
        "nup": nup,
        "tipo_documento": tipo_documento,
        "estrutura": {}
    }

    try:
        # 1. Login usando context manager
        debug_print("Fazendo login no SEI...")
        async with criar_sessao_sei(
            usuario=usuario,
            senha=senha,
            orgao_id=orgao_id
        ) as sessao:
            page = sessao["page"]
            context = sessao["context"]
            debug_print("Login OK")

            # 2. Busca o processo
            debug_print(f"Buscando processo {nup}...")
            await page.locator("#txtPesquisaRapida").wait_for(state="visible", timeout=15000)
            await page.locator("#txtPesquisaRapida").fill(nup)
            await page.locator("#txtPesquisaRapida").press("Enter")
            await page.wait_for_load_state("networkidle", timeout=60000)

            # 3. Clica em Incluir Documento
            debug_print("Clicando em Incluir Documento...")
            frame_pai = page.frame_locator(SELETOR_FRAME_CONTEUDO_PAI).first
            btn_incluir = frame_pai.get_by_role("img", name="Incluir Documento", exact=True).first
            await btn_incluir.wait_for(state="visible", timeout=15000)
            await btn_incluir.click()
            await page.wait_for_timeout(1500)

            # 4. Seleciona tipo de documento
            debug_print(f"Selecionando tipo: {tipo_documento}")
            frame_selecao = frame_pai.frame_locator(SELETOR_FRAME_VISUALIZACAO).first

            await frame_selecao.locator("#txtFiltro").click()
            await frame_selecao.locator("#txtFiltro").fill(tipo_documento)
            await page.wait_for_timeout(1000)
            await frame_selecao.locator("#txtFiltro").press("Enter")
            await page.wait_for_timeout(500)

            await frame_selecao.get_by_role("link", name=tipo_documento, exact=True).first.click()

            # 5. Marca nível de acesso público
            debug_print("Configurando nível de acesso...")
            try:
                await frame_selecao.locator("#divOptPublico").wait_for(state="visible", timeout=2000)
                await frame_selecao.locator("#divOptPublico > .infraRadioDiv > .infraRadioLabel").click()
                debug_print("Marcado como público")
            except Exception:
                debug_print("Opção público não encontrada (ok)")

            # 6. Abre editor (nova página)
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
            await page_editor.wait_for_timeout(2000)  # Aguarda carregamento completo
            debug_print("Editor aberto!")

            # 7. Captura estrutura do editor
            estrutura = {
                "url": page_editor.url,
                "title": await page_editor.title(),
                "html_length": len(await page_editor.content()),
                "iframes": [],
                "frames": [],
                "inputs": [],
                "campos_especiais": {}
            }

            # 7.1 Lista todos os iframes
            iframes = await page_editor.query_selector_all("iframe")
            debug_print(f"Encontrados {len(iframes)} iframes")

            for i, iframe in enumerate(iframes):
                iframe_info = {
                    "index": i,
                    "id": await iframe.get_attribute("id"),
                    "name": await iframe.get_attribute("name"),
                    "title": await iframe.get_attribute("title"),
                    "src": await iframe.get_attribute("src"),
                    "class": await iframe.get_attribute("class"),
                    "style": await iframe.get_attribute("style"),
                }
                estrutura["iframes"].append(iframe_info)

                # Log para debug
                debug_print(f"  iframe[{i}]: id={iframe_info['id']}, title={iframe_info['title']}, name={iframe_info['name']}")

                # Identifica campos especiais
                title = (iframe_info.get("title") or "").lower()
                if "endereç" in title or "destinat" in title:
                    estrutura["campos_especiais"]["iframe_destinatario"] = iframe_info
                    debug_print(f"  → ENCONTRADO IFRAME DESTINATÁRIO!")
                if "corpo" in title or "texto" in title:
                    estrutura["campos_especiais"]["iframe_corpo"] = iframe_info
                    debug_print(f"  → ENCONTRADO IFRAME CORPO!")

            # 7.2 Tenta capturar conteúdo do iframe de destinatário
            try:
                frame_dest = page_editor.frame_locator(
                    'iframe[title*="Endereçamento"], iframe[title*="Destinatário"]'
                ).first
                dest_body = await frame_dest.locator("body").inner_html(timeout=5000)
                estrutura["campos_especiais"]["destinatario_html"] = dest_body
                debug_print(f"Conteúdo iframe destinatário: {dest_body[:200]}...")
            except Exception as e:
                debug_print(f"Não encontrou iframe destinatário: {e}")
                estrutura["campos_especiais"]["destinatario_erro"] = str(e)

            # 7.3 Tenta capturar conteúdo do iframe de corpo
            try:
                frame_corpo = page_editor.frame_locator(SELETOR_IFRAME_CORPO_TEXTO).first
                corpo_body = await frame_corpo.locator("body").inner_html(timeout=5000)
                estrutura["campos_especiais"]["corpo_html"] = corpo_body[:2000]
                debug_print(f"Conteúdo iframe corpo: {corpo_body[:200]}...")
            except Exception as e:
                debug_print(f"Não encontrou iframe corpo: {e}")
                estrutura["campos_especiais"]["corpo_erro"] = str(e)

            # 7.4 Lista inputs
            inputs = await page_editor.query_selector_all("input")
            for inp in inputs:
                inp_info = {
                    "type": await inp.get_attribute("type"),
                    "id": await inp.get_attribute("id"),
                    "name": await inp.get_attribute("name"),
                    "value": await inp.get_attribute("value"),
                }
                if inp_info["id"] or inp_info["name"]:
                    estrutura["inputs"].append(inp_info)

            # 7.5 Screenshot do editor
            screenshot_path = f"/tmp/sei_editor_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            await page_editor.screenshot(path=screenshot_path, full_page=True)
            estrutura["screenshot_path"] = screenshot_path
            debug_print(f"Screenshot salvo em {screenshot_path}")

            # 7.6 HTML completo do editor
            html_completo = await page_editor.content()
            estrutura["html_completo"] = html_completo

            output["estrutura"] = estrutura
            output["ok"] = True

            # 8. Fecha editor SEM SALVAR
            debug_print("Fechando editor sem salvar...")
            await page_editor.close()

    except Exception as e:
        output["erro"] = str(e)
        import traceback
        output["traceback"] = traceback.format_exc()

    return output


async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("nup", help="Número do processo")
    parser.add_argument("tipo_documento", help="Tipo de documento (ex: Memorando)")
    parser.add_argument("--usuario", required=True, help="Usuário SEI")
    parser.add_argument("--senha", required=True, help="Senha SEI")
    parser.add_argument("--orgao", default="31", help="ID do órgão (default: 31)")
    args = parser.parse_args()

    result = await capturar_estrutura_editor(
        nup=args.nup,
        tipo_documento=args.tipo_documento,
        usuario=args.usuario,
        senha=args.senha,
        orgao_id=args.orgao
    )

    # Imprime JSON (sem html_completo para não poluir)
    result_clean = {k: v for k, v in result.items() if k != "estrutura"}
    if "estrutura" in result:
        est = result["estrutura"].copy()
        if "html_completo" in est:
            est["html_completo"] = f"[{len(est['html_completo'])} chars]"
        result_clean["estrutura"] = est

    print(json.dumps(result_clean, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
