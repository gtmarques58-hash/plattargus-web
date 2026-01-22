#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
detalhar_processo.py — SEI (Acre) | PRODUÇÃO v2.2
Login: padrão do detalhar antigo (sei_auth_multi.criar_sessao_sei)
Motor: Inteligente (PASTAS romanas ou RAIZ) + PDF real via Download (seta) + cache + JSONL incremental

NOVIDADES v2.2:
- Flag --full para retornar JSON completo no stdout (para versão Web)
- Quando --full é usado, retorna documentos com conteúdo completo

NOVIDADES v2.1:
- stdout retorna JSON LEVE (sem conteúdo dos documentos) ~10KB
- Arquivo JSON COMPLETO salvo automaticamente em /data/detalhar/
- Campo "arquivo_completo" aponta para dados completos
- Nunca trunca, sempre funciona

NOVIDADES v2.0:
- Envia mensagem inicial ao Telegram com estimativa de tempo
- Sempre retorna resumo útil, mesmo com PDFs escaneados
- Ressalvas em vez de erro fatal
- Sucesso parcial quando extrai pelo menos alguns documentos

Recursos:
- Detecta se o processo tem PASTA1..N (romanos) ou se é RAIZ.
- Não fecha pasta já aberta.
- Extração:
  - Primeiro tenta baixar o PDF real (download) e extrair todas as páginas (pdfplumber).
  - Se PDF for escaneado (texto fraco), tenta OCR opcional (pypdfium2 + pytesseract).
  - Se não conseguir PDF, cai para HTML do visualizador.
- Cache de downloads por id_documento (evita baixar repetido).
- Saída incremental JSONL + saída final JSON.
- Evidências (_evidencias/) somente em erro (modo debug).
- Headless configurável.

Uso (servidor):
  python detalhar_processo.py "0609.000046.00629/2025-50" --chat-id "-100..." --sigla "DRH" --out "/data/out.json"
  python detalhar_processo.py "0609.012088.00134/2025-03" --sigla "DIVCNT" --jsonl "/data/out.jsonl" --headless
  python detalhar_processo.py "..." --sigla "DRH" --only-ids "0018742644,0018743339"

Dependências mínimas:
  pip install playwright bs4 pdfplumber
  playwright install chromium

OCR opcional (para PDF escaneado):
  pip install pytesseract pypdfium2 pillow
  (e instalar Tesseract no SO: apt-get install tesseract-ocr  /  yum install tesseract)
"""

import os
import sys
import re
import json
import asyncio
import argparse
import hashlib
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import Optional, Literal, Dict, Any, Tuple, List
from io import BytesIO
from urllib.parse import urljoin, urlparse

# ---- caminho do projeto (igual ao antigo) ----
sys.path.insert(0, "/app/scripts")

from playwright.async_api import async_playwright

# Login/sessão do modelo antigo
from sei_auth_multi import criar_sessao_sei

# Optional deps
try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except Exception:
    HAS_BS4 = False

try:
    import pdfplumber
    HAS_PDFPLUMBER = True
    PDFPLUMBER_VERSION = getattr(pdfplumber, "__version__", "unknown")
    PDFPLUMBER_IMPORT_ERROR = None
except Exception as e:
    HAS_PDFPLUMBER = False
    PDFPLUMBER_VERSION = None
    PDFPLUMBER_IMPORT_ERROR = repr(e)

# OCR opcional (server-friendly)
try:
    import pytesseract
    HAS_TESSERACT = True
except Exception:
    HAS_TESSERACT = False

try:
    import pypdfium2 as pdfium
    HAS_PDFIUM = True
except Exception:
    HAS_PDFIUM = False

try:
    from PIL import Image
    HAS_PIL = True
except Exception:
    HAS_PIL = False


FileKind = Literal["pdf", "image", "html", "text", "office", "unknown"]

# Frames do SEI
SELETOR_FRAME_ARVORE = 'iframe[name="ifrArvore"]'
SELETOR_ARVORE = "#divArvore"
SELETOR_FRAME_CONTEUDO_PAI = 'iframe[name="ifrConteudoVisualizacao"]'
SELETOR_FRAME_CONTEUDO_INTERNO = 'iframe[name="ifrVisualizacao"]'

# limites e timeouts
MAX_TEXTO_POR_DOC = 3000
TIMEOUT_PADRAO = 15000

ROMANOS = ["I","II","III","IV","V","VI","VII","VIII","IX","X","XI","XII","XIII","XIV","XV","XVI","XVII","XVIII","XIX","XX"]

# pastas de saída / evidências (usar /tmp para evitar problemas de permissão)
SCRIPT_DIR = Path(__file__).parent.absolute()
EVID_DIR = Path("/tmp/_evidencias")
EVID_DIR.mkdir(exist_ok=True)

CACHE_DIR = Path("/tmp/_cache_downloads")
CACHE_DIR.mkdir(exist_ok=True)


# ============================================================
# Telegram Helper - Enviar mensagem de progresso (v2.0)
# ============================================================
def _telegram_api_base() -> Optional[str]:
    """Retorna base do Bot API."""
    base = os.getenv("TELEGRAM_BOT_API_BASE", "").strip()
    if base:
        return base.rstrip("/")
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if token:
        return f"https://api.telegram.org/bot{token}"
    return None


async def telegram_send_text(chat_id: str, text: str, parse_mode: str = "HTML") -> bool:
    """Envia mensagem de texto para o Telegram."""
    base = _telegram_api_base()
    if not base or not chat_id or not text:
        return False

    url = f"{base}/sendMessage"
    data = {
        "chat_id": str(chat_id),
        "text": text[:4096],  # Limite do Telegram
        "parse_mode": parse_mode
    }

    try:
        import httpx
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(url, json=data)
            return r.status_code == 200
    except Exception:
        try:
            import requests
            r = requests.post(url, json=data, timeout=15)
            return r.status_code == 200
        except Exception:
            return False


def estimar_tempo_processamento(num_pastas: int, docs_por_pasta: int = 20) -> str:
    """Estima tempo de processamento baseado no número de pastas."""
    total_docs = num_pastas * docs_por_pasta
    # ~2-4 segundos por documento em média
    tempo_min = (total_docs * 2) // 60
    tempo_max = (total_docs * 4) // 60
    
    if tempo_max < 1:
        return "menos de 1 minuto"
    elif tempo_min == tempo_max:
        return f"~{tempo_min} minutos"
    else:
        return f"{max(1, tempo_min)}-{tempo_max} minutos"


# ============================================================
# Helpers robustos
# ============================================================
def now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"

def romano_from_idx(i: int) -> str:
    if 1 <= i <= len(ROMANOS):
        return ROMANOS[i-1]
    return str(i)

def doc_id_from_any(s: str) -> Optional[str]:
    if not s:
        return None
    m = re.search(r"id_documento=(\d+)", s)
    return m.group(1) if m else None

def clean_nup(nup: str) -> str:
    return (nup or "").replace('"', "").replace("'", "").strip()

def md5_bytes(b: bytes) -> str:
    return hashlib.md5(b).hexdigest()

async def close_any_popovers(page):
    try:
        await page.keyboard.press("Escape")
    except Exception:
        pass
    try:
        await page.evaluate("""
        () => {
          const sels = ['.popover', '.tooltip', '[role="tooltip"]', '.ui-tooltip'];
          for (const s of sels) document.querySelectorAll(s).forEach(el => el.remove());
        }""")
    except Exception:
        pass

async def safe_click(locator, page, *, timeout=8000, retries=4, label=""):
    last_err = None
    for i in range(retries):
        try:
            await close_any_popovers(page)
            await locator.scroll_into_view_if_needed(timeout=timeout)
            await locator.click(timeout=timeout)
            return True
        except Exception as e:
            last_err = e
            try:
                await close_any_popovers(page)
                await locator.scroll_into_view_if_needed(timeout=timeout)
                await locator.click(timeout=timeout, force=True)
                return True
            except Exception as e2:
                last_err = e2
            await page.wait_for_timeout(250 + i * 250)
    raise last_err

async def is_locator_visible(locator) -> bool:
    try:
        return await locator.is_visible()
    except Exception:
        try:
            style = await locator.get_attribute("style") or ""
            return "display: none" not in style
        except Exception:
            return False

async def save_evidence(page, frame_arvore, label: str, debug: bool):
    if not debug:
        return None
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    shot = EVID_DIR / f"{ts}_{label}.png"
    htmlf = EVID_DIR / f"{ts}_{label}_divArvore.html"
    try:
        await page.screenshot(path=str(shot), full_page=True)
    except Exception:
        pass
    try:
        tree_html = await frame_arvore.locator(SELETOR_ARVORE).inner_html()
        htmlf.write_text(tree_html, encoding="utf-8")
    except Exception:
        pass
    return {"screenshot": str(shot), "arvore_html": str(htmlf)}


# ============================================================
# Detectores / Extratores
# ============================================================
def detect_kind_from_bytes(b: bytes) -> Tuple[FileKind, Dict[str, Any]]:
    meta: Dict[str, Any] = {"bytes_total": len(b)}
    if len(b) < 8:
        return "unknown", {**meta, "detector": "too_small"}

    head = b[:64]
    if head.startswith(b"%PDF-"):
        return "pdf", {**meta, "detector": "magic", "format": "pdf"}
    if head.startswith(b"\x89PNG\r\n\x1a\n") or head.startswith(b"\xFF\xD8\xFF"):
        return "image", {**meta, "detector": "magic"}

    # Detecta HTML ANTES de tentar UTF-8 (importante!)
    sample = b[:8192].lower()
    if (b"<!doctype html" in sample or 
        b"<html" in sample or 
        b"<div" in sample or 
        b"<body" in sample or
        b"<p " in sample or
        b"<table" in sample or
        b"<span" in sample or
        b"<img" in sample):
        return "html", {**meta, "detector": "heuristic_html"}

    try:
        b[:8192].decode("utf-8", errors="strict")
        return "text", {**meta, "detector": "utf8"}
    except Exception:
        return "unknown", meta

def extract_html_text(data: bytes) -> Dict[str, Any]:
    try:
        raw = data.decode("utf-8", errors="ignore")
        
        # Remove base64 de imagens ANTES de processar
        raw = re.sub(r'src="data:image/[^"]*"', 'src=""', raw)
        raw = re.sub(r"src='data:image/[^']*'", "src=''", raw)
        
        if HAS_BS4:
            soup = BeautifulSoup(raw, "html.parser")
            
            for tag in soup(["script", "style", "noscript", "head", "meta", "link", "img", "svg", "iframe", "button", "input"]):
                tag.extract()
            
            for tag in soup.find_all(True):
                if tag.get("style"):
                    del tag["style"]
            
            text = soup.get_text(separator="\n")
            
            lines = []
            for line in text.splitlines():
                line = line.strip()
                if line and len(line) > 2:
                    if re.search(r'[a-zA-ZÀ-ú]{3,}', line):
                        lines.append(line)
            
            cleaned = "\n".join(lines)
            return {"text": cleaned, "method": "beautifulsoup_clean"}
        else:
            raw = re.sub(r'data:image/[^"\'>\s]+', '', raw)
            text = re.sub(r"<[^>]+>", " ", raw)
            text = re.sub(r"\s+", " ", text).strip()
            return {"text": text, "method": "regex"}
    except Exception as e:
        return {"text": "", "error": str(e)}

def extract_text_file(data: bytes) -> Dict[str, Any]:
    for enc in ["utf-8", "latin-1", "cp1252"]:
        try:
            return {"text": data.decode(enc), "encoding": enc, "method": "decode"}
        except Exception:
            continue
    return {"text": data.decode("utf-8", errors="ignore"), "encoding": "utf-8-forced", "method": "decode"}

def extract_pdf_text(data: bytes) -> Dict[str, Any]:
    if not HAS_PDFPLUMBER:
        return {"text": "", "error": f"pdfplumber FAIL: {PDFPLUMBER_IMPORT_ERROR}"}
    try:
        texts = []
        with pdfplumber.open(BytesIO(data)) as pdf:
            for p in pdf.pages:
                t = p.extract_text() or ""
                texts.append(t.strip())
        full_text = "\n\n".join(t for t in texts if t)

        pages = max(1, len(texts))
        avg = len(full_text) / pages
        is_scanned = avg < 80
        return {"text": full_text, "pages": len(texts), "avg_chars_per_page": avg, "is_scanned": is_scanned, "method": "pdfplumber"}
    except Exception as e:
        return {"text": "", "error": str(e)}

def ocr_pdf_with_pdfium(data: bytes, *, max_pages: int = 10) -> Dict[str, Any]:
    if not (HAS_PDFIUM and HAS_TESSERACT and HAS_PIL):
        missing = []
        if not HAS_PDFIUM: missing.append("pypdfium2")
        if not HAS_TESSERACT: missing.append("pytesseract/tesseract")
        if not HAS_PIL: missing.append("Pillow")
        return {"text": "", "error": f"OCR indisponível (faltando: {', '.join(missing)})", "method": "ocr_none"}

    try:
        pdf = pdfium.PdfDocument(BytesIO(data))
        n_pages = len(pdf)
        used = min(n_pages, max_pages)

        out_texts = []
        for i in range(used):
            page = pdf[i]
            pil_img = page.render(scale=2.0).to_pil()
            txt = pytesseract.image_to_string(pil_img, lang="por")
            txt = (txt or "").strip()
            if txt:
                out_texts.append(txt)

        full = "\n\n".join(out_texts).strip()
        return {"text": full, "pages_ocr": used, "pages_total": n_pages, "method": "pdfium+pytesseract"}
    except Exception as e:
        return {"text": "", "error": str(e), "method": "ocr_fail"}

def extrair_conteudo_por_bytes(data: bytes, *, prefer_ocr: bool = True) -> Tuple[FileKind, Dict[str, Any], str, Dict[str, Any]]:
    kind, meta = detect_kind_from_bytes(data)

    if kind == "pdf":
        r = extract_pdf_text(data)
        txt = (r.get("text") or "").strip()

        if prefer_ocr and r.get("is_scanned") and (len(txt) < 200):
            o = ocr_pdf_with_pdfium(data, max_pages=10)
            o_txt = (o.get("text") or "").strip()
            if o_txt:
                r["ocr_used"] = True
                r["ocr_method"] = o.get("method")
                r["ocr_pages"] = o.get("pages_ocr")
                txt = o_txt

        txt_out = txt[:MAX_TEXTO_POR_DOC]
        return kind, meta, txt_out, r

    if kind == "html":
        r = extract_html_text(data)
        txt_out = (r.get("text") or "")[:MAX_TEXTO_POR_DOC]
        return kind, meta, txt_out, r

    if kind == "text":
        r = extract_text_file(data)
        txt_out = (r.get("text") or "")[:MAX_TEXTO_POR_DOC]
        return kind, meta, txt_out, r

    return kind, meta, f"[{kind.upper()}] Conteúdo não extraído nesta etapa", {"method": "none"}


# ============================================================
# Pastas (não fecha se já estiver aberta)
# ============================================================
async def ensure_pasta_open(frame_arvore, page, pasta_idx: int):
    div_pasta = frame_arvore.locator(f"#divPASTA{pasta_idx}")
    if await is_locator_visible(div_pasta):
        return

    botao = frame_arvore.locator(f"#ancjoinPASTA{pasta_idx}")
    await safe_click(botao, page, label=f"expand_pasta_{pasta_idx}")

    aguarde = frame_arvore.locator(f"#spanAGUARDE{pasta_idx}")
    try:
        await aguarde.wait_for(state="hidden", timeout=30000)
    except Exception:
        pass

    try:
        await div_pasta.wait_for(state="visible", timeout=15000)
    except Exception:
        pass

async def detect_tree_mode(frame_arvore) -> str:
    botoes = frame_arvore.locator("a[id^='ancjoinPASTA']")
    try:
        n = await botoes.count()
        return "pastas" if n > 0 else "raiz"
    except Exception:
        return "raiz"


# ============================================================
# PDF real via Download (seta) + cache
# ============================================================
def cache_path_for_doc(doc_id: str) -> Path:
    return CACHE_DIR / f"{doc_id}.bin"

async def try_download_pdf_bytes(context, page, frame_interno, base_url: str) -> Optional[bytes]:
    candidates = [
        frame_interno.locator("a[href*='documento_download']").first,
        frame_interno.locator("a[href*='download']").first,
        frame_interno.locator("a[title*='Download']").first,
        frame_interno.locator("a[title*='Baixar']").first,
        frame_interno.locator("a[aria-label*='Download']").first,
    ]
    for loc in candidates:
        try:
            if await loc.count() > 0:
                href = await loc.get_attribute("href")
                if href:
                    url = urljoin(base_url, href)
                    resp = await context.request.get(url)
                    data = await resp.body()
                    if data and data.startswith(b"%PDF-"):
                        return data
        except Exception:
            continue

    try:
        embed = frame_interno.locator("embed[src], iframe[src], object[data]").first
        if await embed.count() > 0:
            src = await embed.get_attribute("src") or await embed.get_attribute("data")
            if src:
                url = urljoin(base_url, src)
                resp = await context.request.get(url)
                data = await resp.body()
                if data and data.startswith(b"%PDF-"):
                    return data
    except Exception:
        pass

    download_btn_candidates = [
        frame_interno.locator("button[title*='Download'], button[aria-label*='Download']").first,
        frame_interno.locator("text=/download/i").first,
        frame_interno.locator("text=/baixar/i").first,
    ]

    for btn in download_btn_candidates:
        try:
            if await btn.count() > 0:
                async with page.expect_download(timeout=12000) as dl_info:
                    await safe_click(btn, page, label="click_download")
                dl = await dl_info.value
                pth = await dl.path()
                if pth:
                    b = Path(pth).read_bytes()
                    if b.startswith(b"%PDF-"):
                        return b
        except Exception:
            continue

    return None


# ============================================================
# Modelo de saída
# ============================================================
@dataclass
class DocumentoExtraido:
    indice: int
    pasta: str
    titulo: str
    id_documento: Optional[str] = None
    href: Optional[str] = None
    tipo_detectado: FileKind = "unknown"
    tipo_meta: Dict[str, Any] = field(default_factory=dict)
    conteudo: str = ""
    tamanho_bytes: int = 0
    tamanho_texto: int = 0
    paginas: Optional[int] = None
    is_scanned: bool = False
    multi_pagina: bool = False
    extraido_com_sucesso: bool = False
    metodo_extracao: str = "none"
    origem_conteudo: str = "viewer_html"
    erro: Optional[str] = None
    hash_md5: Optional[str] = None
    evidencias: Optional[Dict[str, Any]] = None


# ============================================================
# Busca (modelo do antigo)
# ============================================================
async def buscar_processo_modelo_antigo(page, nup: str):
    nup_limpo = clean_nup(nup)
    campo = page.get_by_role("textbox", name="Pesquisar...")
    await campo.wait_for(state="visible", timeout=15000)
    await campo.fill(nup_limpo)

    botao = page.get_by_role("img", name="Pesquisa Rápida")
    await botao.click()

    await page.wait_for_load_state("networkidle", timeout=30000)
    await page.wait_for_timeout(900)


# ============================================================
# Execução principal
# ============================================================
async def detalhar_processo(
    nup: str,
    *,
    chat_id: Optional[str] = None,
    sigla: Optional[str] = None,
    usuario: Optional[str] = None,
    senha: Optional[str] = None,
    orgao_id: str = "31",
    out_json: Optional[str],
    out_jsonl: Optional[str],
    only_ids: Optional[List[str]],
    headless: bool,
    debug: bool,
    prefer_ocr: bool,
    full_output: bool = False,
) -> Dict[str, Any]:

    inicio = datetime.now()

    output: Dict[str, Any] = {
        "sucesso": False,
        "nup": nup,
        "diretoria": sigla,
        "modo": None,
        "pastas_total": 0,
        "documentos_total": 0,
        "extraidos_ok": 0,
        "erros_click": 0,
        "erro": None,
        "timestamp": now_iso(),
        "duracao_segundos": 0,
        "diagnostico": {
            "python": sys.executable,
            "pdfplumber": f"OK v{PDFPLUMBER_VERSION}" if HAS_PDFPLUMBER else f"FAIL {PDFPLUMBER_IMPORT_ERROR}",
            "ocr_pdfium": bool(HAS_PDFIUM),
            "ocr_tesseract": bool(HAS_TESSERACT),
            "bs4": bool(HAS_BS4),
        }
    }

    docs_out: List[DocumentoExtraido] = []
    seen_ids = set()

    # JSONL writer (incremental)
    jsonl_fp = None
    if out_jsonl:
        Path(out_jsonl).parent.mkdir(parents=True, exist_ok=True)
        jsonl_fp = open(out_jsonl, "a", encoding="utf-8")

    def write_jsonl_event(event: Dict[str, Any]):
        if not jsonl_fp:
            return
        jsonl_fp.write(json.dumps(event, ensure_ascii=False) + "\n")
        jsonl_fp.flush()

    try:
        async with criar_sessao_sei(chat_id=chat_id, sigla=sigla, usuario=usuario, senha=senha, orgao_id=orgao_id) as sessao:
            page = sessao["page"]
            context = sessao.get("context")
            diretoria = sessao.get("diretoria")
            if diretoria:
                output["diretoria"] = diretoria.get("sigla") or output["diretoria"]

            if context is None:
                context = page.context

            await page.wait_for_load_state("networkidle", timeout=30000)

            print(f"Buscando NUP: {nup}...", file=sys.stderr)
            await buscar_processo_modelo_antigo(page, nup)

            frame_arvore = page.frame_locator(SELETOR_FRAME_ARVORE).first
            frame_conteudo = page.frame_locator(SELETOR_FRAME_CONTEUDO_PAI).first

            arvore = frame_arvore.locator(SELETOR_ARVORE)
            await arvore.wait_for(state="visible", timeout=TIMEOUT_PADRAO)
            await page.wait_for_timeout(500)

            modo = await detect_tree_mode(frame_arvore)
            output["modo"] = modo
            print(f"✅ Modo detectado: {modo.upper()}", file=sys.stderr)

            base_url = f"{urlparse(page.url).scheme}://{urlparse(page.url).netloc}"

            doc_global_idx = 0

            async def processar_documento(pasta_label: str, link, href: str, onclick: str):
                nonlocal doc_global_idx
                did = doc_id_from_any(href) or doc_id_from_any(onclick)
                if not did:
                    return
                if only_ids and did not in only_ids:
                    return
                if did in seen_ids:
                    return

                seen_ids.add(did)
                doc_global_idx += 1

                try:
                    titulo = (await link.inner_text()).strip()
                except Exception:
                    titulo = f"Documento {did}"

                doc = DocumentoExtraido(
                    indice=doc_global_idx,
                    pasta=pasta_label,
                    titulo=titulo,
                    id_documento=did,
                    href=href or None
                )

                print(f"  [{doc_global_idx}] {titulo[:80]} ({did})", file=sys.stderr)

                try:
                    link_re = frame_arvore.locator(
                        f"xpath=//a[contains(@href,'id_documento={did}') or contains(@onclick,'id_documento={did}')]"
                    ).first

                    await safe_click(link_re, page, label=f"doc_{did}")
                    await page.wait_for_timeout(700)

                    frame_interno = frame_conteudo.frame_locator(SELETOR_FRAME_CONTEUDO_INTERNO).first
                    body = frame_interno.locator("body")
                    await body.wait_for(state="visible", timeout=15000)
                    await page.wait_for_timeout(400)

                    cpath = cache_path_for_doc(did)
                    pdf_bytes = None
                    if cpath.exists():
                        b = cpath.read_bytes()
                        if b.startswith(b"%PDF-"):
                            pdf_bytes = b
                            doc.origem_conteudo = "cache"

                    if pdf_bytes is None:
                        pdf_bytes = await try_download_pdf_bytes(context, page, frame_interno, base_url)
                        if pdf_bytes and pdf_bytes.startswith(b"%PDF-"):
                            cpath.write_bytes(pdf_bytes)
                            doc.origem_conteudo = "sei_download"

                    if pdf_bytes:
                        kind, meta, txt, extra = extrair_conteudo_por_bytes(pdf_bytes, prefer_ocr=prefer_ocr)
                        doc.tipo_detectado = kind
                        doc.tipo_meta = meta
                        doc.conteudo = txt
                        doc.tamanho_bytes = len(pdf_bytes)
                        doc.tamanho_texto = len(txt)
                        doc.hash_md5 = md5_bytes(pdf_bytes)
                        doc.metodo_extracao = extra.get("method", "none")
                        doc.paginas = extra.get("pages")
                        doc.is_scanned = bool(extra.get("is_scanned", False))
                        doc.multi_pagina = bool(doc.paginas and doc.paginas > 1)
                        doc.erro = extra.get("error")
                        doc.extraido_com_sucesso = bool(txt.strip()) and not doc.erro

                    else:
                        html_content = await body.inner_html()
                        data = html_content.encode("utf-8", errors="ignore")
                        kind, meta, txt, extra = extrair_conteudo_por_bytes(data, prefer_ocr=False)

                        doc.origem_conteudo = "viewer_html"
                        doc.tipo_detectado = kind
                        doc.tipo_meta = meta
                        doc.conteudo = txt
                        doc.tamanho_bytes = len(data)
                        doc.tamanho_texto = len(txt)
                        doc.hash_md5 = md5_bytes(data)
                        doc.metodo_extracao = extra.get("method", "none")
                        doc.paginas = extra.get("pages")
                        doc.is_scanned = bool(extra.get("is_scanned", False))
                        doc.multi_pagina = bool(doc.paginas and doc.paginas > 1)
                        doc.erro = extra.get("error")
                        doc.extraido_com_sucesso = bool(txt.strip()) and not doc.erro

                    output["documentos_total"] += 1
                    if doc.extraido_com_sucesso:
                        output["extraidos_ok"] += 1
                        pages = doc.paginas or "-"
                        print(f"      [OK] {doc.tipo_detectado} | pages={pages} | origem={doc.origem_conteudo} | {doc.tamanho_texto} chars", file=sys.stderr)
                    else:
                        print(f"      [AVISO] extração fraca | erro={doc.erro}", file=sys.stderr)

                    docs_out.append(doc)
                    write_jsonl_event({"type": "doc", "ts": now_iso(), "data": asdict(doc)})

                except Exception as e:
                    output["erros_click"] += 1
                    doc.erro = str(e)[:300]
                    doc.evidencias = await save_evidence(page, frame_arvore, f"erro_doc_{did}", debug)
                    docs_out.append(doc)
                    output["documentos_total"] += 1
                    write_jsonl_event({"type": "doc_error", "ts": now_iso(), "data": asdict(doc)})

            # -------------------- MODO PASTAS --------------------
            if modo == "pastas":
                botoes_pasta = frame_arvore.locator("a[id^='ancjoinPASTA']")
                num_pastas = await botoes_pasta.count()
                output["pastas_total"] = num_pastas

                print(f"✅ Pastas detectadas: {num_pastas}", file=sys.stderr)
                write_jsonl_event({"type": "start", "ts": now_iso(), "modo": "pastas", "pastas_total": num_pastas})

                # Mensagem inicial ao Telegram (v2.0)
                if chat_id and num_pastas > 0:
                    tempo_est = estimar_tempo_processamento(num_pastas)
                    docs_est = num_pastas * 20
                    msg_inicial = (
                        f"📂 <b>Processo localizado!</b>\n\n"
                        f"📁 <b>Pastas:</b> {num_pastas}\n"
                        f"📄 <b>Documentos estimados:</b> ~{docs_est}\n"
                        f"⏳ <b>Tempo estimado:</b> {tempo_est}\n\n"
                        f"<i>Aguarde a análise completa...</i>"
                    )
                    await telegram_send_text(chat_id, msg_inicial)
                    print(f"📤 Mensagem inicial enviada ao Telegram", file=sys.stderr)

                for pasta_idx in range(1, num_pastas + 1):
                    pasta_rom = romano_from_idx(pasta_idx)
                    print(f"\n[PASTA {pasta_rom} | {pasta_idx}/{num_pastas}]", file=sys.stderr)
                    write_jsonl_event({"type": "pasta_start", "ts": now_iso(), "pasta": pasta_rom, "idx": pasta_idx})

                    try:
                        await ensure_pasta_open(frame_arvore, page, pasta_idx)
                        await page.wait_for_timeout(300)
                    except Exception as e:
                        ev = await save_evidence(page, frame_arvore, f"erro_expand_pasta_{pasta_idx}", debug)
                        write_jsonl_event({"type": "pasta_error", "ts": now_iso(), "pasta": pasta_rom, "erro": str(e), "evid": ev})
                        continue

                    div_pasta = frame_arvore.locator(f"#divPASTA{pasta_idx}")
                    links_docs = div_pasta.locator(
                        "a[href*='id_documento='], a[onclick*='id_documento='], a[href*='arvore_visualizar'], a[onclick*='arvore_visualizar']"
                    )
                    total_links = await links_docs.count()
                    print(f"  Documentos encontrados: {total_links}", file=sys.stderr)

                    for i in range(total_links):
                        link = links_docs.nth(i)
                        href = (await link.get_attribute("href")) or ""
                        onclick = (await link.get_attribute("onclick")) or ""
                        await processar_documento(pasta_rom, link, href, onclick)

                    write_jsonl_event({"type": "pasta_end", "ts": now_iso(), "pasta": pasta_rom})

            # -------------------- MODO RAIZ --------------------
            else:
                write_jsonl_event({"type": "start", "ts": now_iso(), "modo": "raiz"})
                
                if chat_id:
                    msg_inicial = (
                        f"📂 <b>Processo localizado!</b>\n\n"
                        f"📁 <b>Modo:</b> Raiz (sem pastas)\n"
                        f"⏳ <b>Analisando documentos...</b>"
                    )
                    await telegram_send_text(chat_id, msg_inicial)
                
                root = frame_arvore.locator(SELETOR_ARVORE)
                links_docs = root.locator(
                    "a[href*='id_documento='], a[onclick*='id_documento='], a[href*='arvore_visualizar'], a[onclick*='arvore_visualizar']"
                )
                total_links = await links_docs.count()
                print(f"Documentos na raiz: {total_links}", file=sys.stderr)

                for i in range(total_links):
                    link = links_docs.nth(i)
                    href = (await link.get_attribute("href")) or ""
                    onclick = (await link.get_attribute("onclick")) or ""
                    await processar_documento("RAIZ", link, href, onclick)

            output["sucesso"] = True

    except Exception as e:
        output["erro"] = str(e)
        write_jsonl_event({"type": "fatal", "ts": now_iso(), "erro": str(e)})
    finally:
        output["duracao_segundos"] = round((datetime.now() - inicio).total_seconds(), 1)
        
        if jsonl_fp:
            jsonl_fp.close()

    # ============================================================
    # v2.1: Separação de dados (leve no stdout, completo em arquivo)
    # ============================================================
    partes_resumo = []
    docs_escaneados = []
    docs_ok = []
    lista_documentos_resumida = []
    
    for doc in docs_out:
        titulo = doc.titulo or "Documento sem título"
        conteudo = doc.conteudo or ""
        
        # Lista resumida (só metadados, sem conteúdo)
        lista_documentos_resumida.append({
            "indice": doc.indice,
            "pasta": doc.pasta,
            "titulo": titulo,
            "id_documento": doc.id_documento,
            "tipo": doc.tipo_detectado,
            "extraido": doc.extraido_com_sucesso,
            "tamanho_texto": doc.tamanho_texto,
            "paginas": doc.paginas,
            "is_scanned": doc.is_scanned
        })
        
        # Separa docs escaneados
        if doc.is_scanned or (doc.tipo_detectado == "pdf" and not doc.extraido_com_sucesso):
            docs_escaneados.append(titulo)
            continue
        
        MAX_RESUMO_DOC = 1500
        if len(conteudo) > MAX_RESUMO_DOC:
            conteudo_resumo = conteudo[:MAX_RESUMO_DOC].rstrip() + " [...]"
        else:
            conteudo_resumo = conteudo
        
        if doc.extraido_com_sucesso and conteudo.strip():
            partes_resumo.append(f"📄 {titulo}\n{conteudo_resumo}")
            docs_ok.append(titulo)
        elif doc.tipo_detectado in ("pdf", "image"):
            partes_resumo.append(f"[ANEXO {doc.tipo_detectado.upper()}] {titulo}")
        else:
            partes_resumo.append(f"[ANEXO] {titulo}")
    
    resumo_total = "\n\n".join(partes_resumo).strip()
    
    MAX_RESUMO_TOTAL = 8000
    if len(resumo_total) > MAX_RESUMO_TOTAL:
        resumo_total = resumo_total[:MAX_RESUMO_TOTAL].rstrip() + "\n\n[Resumo truncado...]"
    
    ressalvas = []
    if docs_escaneados:
        ressalvas.append(f"⚠️ {len(docs_escaneados)} documento(s) são PDFs escaneados (imagens) e não puderam ser lidos automaticamente.")
    
    # JSON COMPLETO (para arquivo)
    output_completo = {
        **output,
        "documentos": [asdict(d) for d in docs_out],
        "resumo_processo": resumo_total,
        "ressalvas": ressalvas,
        "docs_escaneados": len(docs_escaneados),
        "docs_extraidos": len(docs_ok),
    }
    
    # Salva JSON completo em arquivo (sempre)
    nup_safe = (nup or "unknown").replace("/", "-").replace(" ", "_")
    ts_file = datetime.now().strftime("%Y%m%d_%H%M%S")
    arquivo_completo = Path(f"/data/detalhar/{nup_safe}_{ts_file}.json")
    arquivo_completo.parent.mkdir(parents=True, exist_ok=True)
    arquivo_completo.write_text(json.dumps(output_completo, indent=2, ensure_ascii=False), encoding="utf-8")
    
    # JSON LEVE (para stdout)
    output_leve = {
        "sucesso": output.get("sucesso", False),
        "nup": output.get("nup"),
        "diretoria": output.get("diretoria"),
        "modo": output.get("modo"),
        "pastas_total": output.get("pastas_total", 0),
        "documentos_total": output.get("documentos_total", 0),
        "extraidos_ok": output.get("extraidos_ok", 0),
        "erros_click": output.get("erros_click", 0),
        "docs_escaneados": len(docs_escaneados),
        "docs_extraidos": len(docs_ok),
        "duracao_segundos": output.get("duracao_segundos", 0),
        "resumo_processo": resumo_total,
        "ressalvas": ressalvas,
        "documentos": lista_documentos_resumida,
        "arquivo_completo": str(arquivo_completo),
        "erro": output.get("erro"),
        "mensagem": None,
        "timestamp": output.get("timestamp"),
    }
    
    # Define mensagem baseada no resultado
    if output_leve["extraidos_ok"] > 0:
        output_leve["sucesso"] = True
        if docs_escaneados:
            output_leve["sucesso_parcial"] = True
            output_leve["mensagem"] = f"Análise concluída. {len(docs_ok)} documentos extraídos, {len(docs_escaneados)} são PDFs escaneados."
        else:
            output_leve["mensagem"] = f"Análise concluída com sucesso. {len(docs_ok)} documentos extraídos."
    elif output_leve["documentos_total"] == 0:
        output_leve["sucesso"] = False
        output_leve["erro"] = "PROCESSO_VAZIO"
        output_leve["mensagem"] = "O processo não contém documentos."
    else:
        output_leve["sucesso"] = False
        output_leve["erro"] = "PDF_IMAGEM_DETECTADO"
        output_leve["mensagem"] = "O processo contém apenas documentos escaneados (imagens) que não puderam ser lidos automaticamente."

    # Também salva no arquivo especificado pelo usuário (se --out foi passado)
    if out_json:
        Path(out_json).parent.mkdir(parents=True, exist_ok=True)
        Path(out_json).write_text(json.dumps(output_completo, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"📁 Arquivo completo salvo em: {arquivo_completo}", file=sys.stderr)
    
    # Retorna JSON completo ou leve baseado na flag
    if full_output:
        print(f"📤 Retornando JSON COMPLETO (--full)", file=sys.stderr)
        return output_completo
    else:
        return output_leve


# ============================================================
# CLI
# ============================================================
def parse_only_ids(s: Optional[str]) -> Optional[List[str]]:
    if not s:
        return None
    return [x.strip() for x in s.split(",") if x.strip()]

async def main_async():
    parser = argparse.ArgumentParser(description="SEI — Detalhar Processo (produção v2.1)")
    parser.add_argument("nup", help="Número do processo (NUP)")
    parser.add_argument("--chat-id", help="Chat ID do Telegram (multi-diretoria)")
    parser.add_argument("--sigla", help="Sigla da diretoria (multi-diretoria)")
    parser.add_argument("--usuario", help="Usuário SEI (credencial direta)")
    parser.add_argument("--senha", help="Senha SEI (credencial direta)")
    parser.add_argument("--orgao", default="31", help="ID do órgão (default: 31)")
    parser.add_argument("--out", dest="out_json", help="Arquivo JSON final de saída (ex: /data/out.json)")
    parser.add_argument("--jsonl", dest="out_jsonl", help="Arquivo JSONL incremental (ex: /data/out.jsonl)")
    parser.add_argument("--only-ids", help="Processar apenas estes id_documento (separados por vírgula)")
    parser.add_argument("--headless", action="store_true", help="Rodar headless (produção)")
    parser.add_argument("--debug", action="store_true", help="Salvar evidências em erro (_evidencias/)")
    parser.add_argument("--no-ocr", action="store_true", help="Desliga OCR (mesmo se PDF escaneado)")
    parser.add_argument("--full", action="store_true", help="Retorna JSON completo com conteúdo dos documentos (para versão Web)")
    args = parser.parse_args()

    if not args.chat_id and not args.sigla and not (args.usuario and args.senha):
        parser.error("Informe --chat-id ou --sigla OU --usuario + --senha")

    only_ids = parse_only_ids(args.only_ids)

    # banner diagnóstico
    print("="*60, file=sys.stderr)
    print("PLATTARGUS — DETALHAR PROCESSO (PRODUÇÃO v2.1)", file=sys.stderr)
    print("="*60, file=sys.stderr)
    print(f"Python: {sys.executable}", file=sys.stderr)
    print("pdfplumber:", "OK" if HAS_PDFPLUMBER else f"FAIL {PDFPLUMBER_IMPORT_ERROR}", file=sys.stderr)
    print("OCR (pypdfium2+pytesseract):", "OK" if (HAS_PDFIUM and HAS_TESSERACT and HAS_PIL) else "OFF", file=sys.stderr)
    print("="*60, file=sys.stderr)

    out = await detalhar_processo(
        nup=args.nup,
        chat_id=args.chat_id,
        sigla=args.sigla,
        usuario=getattr(args, 'usuario', None),
        senha=getattr(args, 'senha', None),
        orgao_id=getattr(args, 'orgao', '31'),
        out_json=args.out_json,
        out_jsonl=args.out_jsonl,
        only_ids=only_ids,
        headless=bool(args.headless),
        debug=bool(args.debug),
        prefer_ocr=not args.no_ocr,
        full_output=bool(args.full),
    )

    # sempre imprime JSON LEVE no stdout (útil pro n8n)
    print(json.dumps(out, ensure_ascii=False))

def main():
    asyncio.run(main_async())

if __name__ == "__main__":
    main()
