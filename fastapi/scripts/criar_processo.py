#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
criar_processo.py - Criação de Processos no SEI

VERSÃO 1.0

Cria um novo processo no SEI e retorna o NUP gerado.

Tipos suportados:
- Acesso à Informação: Boletim Geral
- Diária: No País - Interestadual - Solicitação
- Diária: No País - Intermunicipal - Solicitação

Uso:
    python criar_processo.py "Acesso à Informação: Boletim Geral" --usuario xxx --senha xxx --orgao 31

Retorno JSON:
    {
        "sucesso": true,
        "nup": "0609.012080.00027/2026-55",
        "tipo_processo": "Acesso à Informação: Boletim Geral",
        "mensagem": "Processo criado com sucesso"
    }
"""

import os
import sys
import json
import re
import asyncio
import argparse
from datetime import datetime
from typing import Optional, Dict

sys.path.insert(0, "/app/scripts")

from playwright.async_api import async_playwright, Page, TimeoutError as PlaywrightTimeout
from sei_auth_multi import criar_sessao_sei, CONTROL_URL

# =============================================================================
# CONFIGURAÇÃO
# =============================================================================

DEBUG = os.getenv("ARGUS_DEBUG", "1") == "1"

# Seletores
SELETOR_MENU_TOGGLE = 'a[onclick*="infraMenuSistema"]'
SELETOR_MENU_INICIAR = 'a:has-text("Iniciar Processo")'
SELETOR_CAMPO_TIPO = '#txtFiltro'
SELETOR_OPCAO_TIPO = 'a.ancoraOpcao'
SELETOR_RADIO_PUBLICO = '#optPublico'
SELETOR_BTN_SALVAR = 'button[name="sbmSalvar"], input[name="sbmSalvar"], #btnSalvar'
SELETOR_ARVORE_NUP = '#divArvore a[href*="procedimento_trabalhar"]'
SELETOR_FRAME_ARVORE = 'iframe[name="ifrArvore"]'


def debug_print(msg: str):
    """Print de debug."""
    if DEBUG:
        print(f"[DEBUG] {msg}", file=sys.stderr)


def resultado_json(sucesso: bool, **kwargs):
    """Retorna resultado em JSON."""
    data = {"sucesso": sucesso, **kwargs}
    print(json.dumps(data, ensure_ascii=False))
    return data


# =============================================================================
# FUNÇÕES AUXILIARES
# =============================================================================

async def garantir_menu_aberto(page: Page):
    """Garante que o menu lateral está visível."""
    debug_print("Verificando menu lateral...")

    # Verifica se "Iniciar Processo" está visível
    iniciar = page.locator('text="Iniciar Processo"').first

    try:
        if await iniciar.is_visible(timeout=2000):
            debug_print("Menu já está aberto")
            return True
    except:
        pass

    # Tenta clicar no toggle do menu
    debug_print("Abrindo menu...")
    try:
        # Procura pelo botão de menu de várias formas
        menu_btn = page.locator('a:has-text("Menu")').first
        if await menu_btn.is_visible(timeout=2000):
            await menu_btn.click()
            await page.wait_for_timeout(500)
            return True
    except:
        pass

    # Tenta pelo título "Exibir/Ocultar"
    try:
        toggle = page.locator('img[title*="Ocultar"], img[title*="Exibir"]').first
        if await toggle.is_visible(timeout=2000):
            await toggle.click()
            await page.wait_for_timeout(500)
            return True
    except:
        pass

    return True


async def clicar_iniciar_processo(page: Page):
    """Clica em 'Iniciar Processo' no menu."""
    debug_print("Clicando em 'Iniciar Processo'...")

    # Tenta localizar pelo texto
    iniciar = page.locator('a:has-text("Iniciar Processo")').first

    try:
        await iniciar.wait_for(state="visible", timeout=5000)
        await iniciar.click()
        await page.wait_for_timeout(1000)
        return True
    except Exception as e:
        debug_print(f"Erro ao clicar em Iniciar Processo: {e}")

        # Tenta pesquisar no menu
        try:
            pesquisa = page.locator('input[placeholder*="Pesquisar"]').first
            if await pesquisa.is_visible(timeout=2000):
                await pesquisa.fill("Iniciar Processo")
                await page.wait_for_timeout(500)
                await iniciar.click()
                return True
        except:
            pass

        return False


async def selecionar_tipo_processo(page: Page, tipo: str):
    """Seleciona o tipo de processo no campo de busca."""
    debug_print(f"Selecionando tipo: {tipo}")

    # Aguarda o campo de filtro
    campo = page.locator('#txtFiltro, input[name="txtFiltro"], input[placeholder*="Escolha"]').first

    try:
        await campo.wait_for(state="visible", timeout=10000)
        await campo.fill("")
        await page.wait_for_timeout(300)
        await campo.fill(tipo)
        await page.wait_for_timeout(1500)  # Aguarda mais tempo para o autocomplete

        # Aguarda as opções aparecerem
        await page.wait_for_selector('a.ancoraOpcao', timeout=5000)
        await page.wait_for_timeout(500)

        # Busca todas as opções disponíveis
        opcoes = await page.locator('a.ancoraOpcao').all()
        debug_print(f"Encontradas {len(opcoes)} opções")

        # Procura a opção que corresponde ao tipo solicitado
        for opcao in opcoes:
            texto = await opcao.inner_text()
            texto_limpo = texto.strip()
            debug_print(f"Opção encontrada: '{texto_limpo}'")

            # Verifica se o texto da opção corresponde ao tipo (case insensitive)
            if tipo.lower() in texto_limpo.lower() or texto_limpo.lower() in tipo.lower():
                debug_print(f"Match encontrado: '{texto_limpo}'")
                await opcao.click()
                await page.wait_for_timeout(1000)
                return True

        # Se não encontrou match exato, tenta buscar por partes do nome
        # Ex: "Diária: No País - Interestadual" pode estar como "Diária: No País - Interestadual - Solicitação"
        tipo_lower = tipo.lower()
        for opcao in opcoes:
            texto = await opcao.inner_text()
            texto_limpo = texto.strip().lower()

            # Verifica se contém palavras-chave importantes
            if "diária" in tipo_lower and "diária" in texto_limpo:
                if "interestadual" in tipo_lower and "interestadual" in texto_limpo:
                    debug_print(f"Match por palavras-chave (interestadual): '{texto}'")
                    await opcao.click()
                    await page.wait_for_timeout(1000)
                    return True
                elif "intermunicipal" in tipo_lower and "intermunicipal" in texto_limpo:
                    debug_print(f"Match por palavras-chave (intermunicipal): '{texto}'")
                    await opcao.click()
                    await page.wait_for_timeout(1000)
                    return True
            elif "boletim" in tipo_lower and "boletim" in texto_limpo:
                debug_print(f"Match por palavras-chave (boletim): '{texto}'")
                await opcao.click()
                await page.wait_for_timeout(1000)
                return True

        debug_print(f"Nenhum match encontrado para tipo: {tipo}")
        return False

    except Exception as e:
        debug_print(f"Erro ao selecionar tipo: {e}")
        return False


async def marcar_publico(page: Page):
    """Marca o nível de acesso como Público."""
    debug_print("Marcando nível de acesso: Público")

    try:
        # Tenta pelo radio button
        radio = page.locator('#optPublico, input[value="0"][name*="Acesso"], label:has-text("Público") input').first

        if await radio.is_visible(timeout=5000):
            await radio.click()
            return True

        # Tenta pelo label
        label = page.locator('label:has-text("Público")').first
        if await label.is_visible(timeout=2000):
            await label.click()
            return True

        return False
    except Exception as e:
        debug_print(f"Erro ao marcar público: {e}")
        return False


async def salvar_processo(page: Page):
    """Clica no botão Salvar."""
    debug_print("Salvando processo...")

    try:
        # Tenta várias formas de encontrar o botão
        btn = page.locator('button:has-text("Salvar"), input[value="Salvar"], #btnSalvar').first

        if await btn.is_visible(timeout=5000):
            await btn.click()
            await page.wait_for_timeout(3000)
            return True

        return False
    except Exception as e:
        debug_print(f"Erro ao salvar: {e}")
        return False


async def capturar_nup(page: Page) -> Optional[str]:
    """Captura o NUP do processo criado da árvore."""
    debug_print("Capturando NUP...")

    await page.wait_for_timeout(2000)

    # O NUP aparece na árvore lateral no formato 0609.012080.00027/2026-55
    # Padrão: XXXX.XXXXXX.XXXXX/XXXX-XX

    try:
        # Primeiro, tenta na URL atual
        url = page.url
        nup_match = re.search(r'(\d{4}\.\d{6}\.\d{5}/\d{4}-\d{2})', url)
        if nup_match:
            return nup_match.group(1)

        # Tenta no frame da árvore
        try:
            frame_arvore = page.frame_locator('iframe[name="ifrArvore"]')
            arvore_text = await frame_arvore.locator('body').inner_text(timeout=5000)
            nup_match = re.search(r'(\d{4}\.\d{6}\.\d{5}/\d{4}-\d{2})', arvore_text)
            if nup_match:
                return nup_match.group(1)
        except:
            pass

        # Tenta no corpo da página
        body_text = await page.locator('body').inner_text(timeout=5000)
        nup_match = re.search(r'(\d{4}\.\d{6}\.\d{5}/\d{4}-\d{2})', body_text)
        if nup_match:
            return nup_match.group(1)

        # Tenta nos links
        links = await page.locator('a[href*="procedimento"]').all()
        for link in links:
            href = await link.get_attribute('href')
            if href:
                nup_match = re.search(r'(\d{4}\.\d{6}\.\d{5}/\d{4}-\d{2})', href)
                if nup_match:
                    return nup_match.group(1)

            text = await link.inner_text()
            nup_match = re.search(r'(\d{4}\.\d{6}\.\d{5}/\d{4}-\d{2})', text)
            if nup_match:
                return nup_match.group(1)

        return None
    except Exception as e:
        debug_print(f"Erro ao capturar NUP: {e}")
        return None


# =============================================================================
# FUNÇÃO PRINCIPAL
# =============================================================================

async def criar_processo(
    tipo_processo: str,
    usuario: str = None,
    senha: str = None,
    orgao_id: str = "31",
    sigla: str = None,
    chat_id: str = None,
    interessados: str = None,
    observacoes: str = None,
) -> Dict:
    """
    Cria um processo no SEI.

    Args:
        tipo_processo: Nome do tipo de processo
        usuario: Usuário SEI (credencial direta)
        senha: Senha SEI
        orgao_id: ID do órgão
        sigla: Sigla da diretoria (legado)
        chat_id: Chat ID Telegram (legado)
        interessados: Campo interessados (opcional)
        observacoes: Observações (opcional)

    Returns:
        Dict com resultado
    """

    debug_print(f"Iniciando criação de processo: {tipo_processo}")

    # Monta kwargs para autenticação
    auth_kwargs = {}
    if usuario and senha:
        auth_kwargs = {"usuario": usuario, "senha": senha, "orgao_id": orgao_id}
    elif sigla:
        auth_kwargs = {"sigla": sigla}
    elif chat_id:
        auth_kwargs = {"chat_id": chat_id}
    else:
        return resultado_json(False, erro="Credenciais não fornecidas")

    try:
        async with criar_sessao_sei(**auth_kwargs) as sessao:
            page: Page = sessao["page"]

            # 1. Garante que o menu está aberto
            await garantir_menu_aberto(page)

            # 2. Clica em Iniciar Processo
            if not await clicar_iniciar_processo(page):
                # Tenta navegar diretamente
                debug_print("Tentando navegação direta...")
                await page.goto("https://app.sei.ac.gov.br/sei/controlador.php?acao=procedimento_escolher_tipo")
                await page.wait_for_timeout(2000)

            # 3. Seleciona o tipo de processo
            if not await selecionar_tipo_processo(page, tipo_processo):
                # Screenshot para debug
                await page.screenshot(path="/tmp/erro_tipo_processo.png")
                return resultado_json(False, erro=f"Não foi possível selecionar o tipo: {tipo_processo}")

            # 4. Preenche interessados se fornecido
            if interessados:
                try:
                    campo_int = page.locator('#txtInteressadoProcedimento, input[name*="Interessado"]').first
                    if await campo_int.is_visible(timeout=2000):
                        await campo_int.fill(interessados)
                except:
                    pass

            # 5. Preenche observações se fornecido
            if observacoes:
                try:
                    campo_obs = page.locator('#txaObservacoes, textarea[name*="Observ"]').first
                    if await campo_obs.is_visible(timeout=2000):
                        await campo_obs.fill(observacoes)
                except:
                    pass

            # 6. Marca como Público
            if not await marcar_publico(page):
                debug_print("Aviso: Não conseguiu marcar como Público, continuando...")

            # 7. Salva
            if not await salvar_processo(page):
                await page.screenshot(path="/tmp/erro_salvar_processo.png")
                return resultado_json(False, erro="Não foi possível salvar o processo")

            # 8. Captura o NUP
            nup = await capturar_nup(page)

            if not nup:
                # Tenta screenshot e busca novamente
                await page.screenshot(path="/tmp/processo_criado.png")
                await page.wait_for_timeout(2000)
                nup = await capturar_nup(page)

            if nup:
                return resultado_json(
                    True,
                    nup=nup,
                    tipo_processo=tipo_processo,
                    mensagem="Processo criado com sucesso"
                )
            else:
                return resultado_json(
                    False,
                    erro="Processo pode ter sido criado, mas não foi possível capturar o NUP",
                    screenshot="/tmp/processo_criado.png"
                )

    except PlaywrightTimeout as e:
        return resultado_json(False, erro=f"Timeout: {str(e)}")
    except Exception as e:
        return resultado_json(False, erro=f"Erro: {str(e)}")


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Criar processo no SEI")
    parser.add_argument("tipo_processo", help="Tipo do processo a ser criado")

    # Autenticação
    parser.add_argument("--usuario", help="Usuário SEI")
    parser.add_argument("--senha", help="Senha SEI")
    parser.add_argument("--orgao", default="31", help="ID do órgão (default: 31)")
    parser.add_argument("--sigla", help="Sigla da diretoria (legado)")
    parser.add_argument("--chat-id", help="Chat ID Telegram (legado)")

    # Campos opcionais
    parser.add_argument("--interessados", help="Interessados do processo")
    parser.add_argument("--observacoes", help="Observações")

    args = parser.parse_args()

    result = asyncio.run(criar_processo(
        tipo_processo=args.tipo_processo,
        usuario=args.usuario,
        senha=args.senha,
        orgao_id=args.orgao,
        sigla=args.sigla,
        chat_id=args.chat_id,
        interessados=args.interessados,
        observacoes=args.observacoes,
    ))

    sys.exit(0 if result.get("sucesso") else 1)


if __name__ == "__main__":
    main()
