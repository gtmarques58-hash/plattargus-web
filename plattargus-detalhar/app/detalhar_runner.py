from __future__ import annotations
from typing import Any, Dict, Optional, List
from pathlib import Path
import sys

# garante acesso aos seus scripts
sys.path.insert(0, "/app/scripts")

from detalhar_processo import detalhar_processo as _detalhar_processo

async def run_detalhar(
    *,
    nup: str,
    job_id: str,
    chat_id: Optional[str] = None,
    sigla: Optional[str] = None,
    # Credenciais diretas (para integração web)
    usuario: Optional[str] = None,
    senha: Optional[str] = None,
    orgao_id: str = "31",
    only_ids: Optional[List[str]] = None,
    prefer_ocr: bool = True,
    debug: bool = False,
) -> Dict[str, Any]:
    """
    Executa o detalhar_processo e retorna o JSON LEVE.
    O JSON COMPLETO é salvo em /data/detalhar/raw/{job_id}.json (IMUTÁVEL).

    Suporta dois modos de autenticação:
    1. sigla/chat_id: busca credenciais no banco (Telegram)
    2. usuario/senha: credenciais diretas (Web)
    """
    # ========== NOVA ARQUITETURA: salvar em raw/ ==========
    out_json = f"/data/detalhar/raw/{job_id}.json"
    Path(out_json).parent.mkdir(parents=True, exist_ok=True)

    return await _detalhar_processo(
        nup=nup,
        chat_id=chat_id,
        sigla=sigla,
        usuario=usuario,
        senha=senha,
        orgao_id=orgao_id,
        out_json=out_json,
        out_jsonl=None,
        only_ids=only_ids,
        headless=True,
        debug=debug,
        prefer_ocr=prefer_ocr,
    )
