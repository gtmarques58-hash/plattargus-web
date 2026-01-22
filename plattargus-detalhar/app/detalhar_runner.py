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
    chat_id: Optional[str],
    sigla: Optional[str],
    only_ids: Optional[List[str]] = None,
    prefer_ocr: bool = True,
    debug: bool = False,
) -> Dict[str, Any]:
    """
    Executa o detalhar_processo e retorna o JSON LEVE.
    O JSON COMPLETO é salvo em /data/detalhar/raw/{job_id}.json (IMUTÁVEL).
    """
    # ========== NOVA ARQUITETURA: salvar em raw/ ==========
    out_json = f"/data/detalhar/raw/{job_id}.json"
    Path(out_json).parent.mkdir(parents=True, exist_ok=True)

    return await _detalhar_processo(
        nup=nup,
        chat_id=chat_id,
        sigla=sigla,
        out_json=out_json,
        out_jsonl=None,
        only_ids=only_ids,
        headless=True,
        debug=debug,
        prefer_ocr=prefer_ocr,
    )
