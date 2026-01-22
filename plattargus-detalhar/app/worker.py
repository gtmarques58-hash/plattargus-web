"""
Worker ARGUS - Pipeline v2.0
"""

import asyncio
import os
import json
import sys
import time
import uuid
import threading
from pathlib import Path
from typing import Dict, Any, Optional

from fastapi import FastAPI
from pydantic import BaseModel
import uvicorn

# Imports diretos
from app.config import settings
from app.db import SessionLocal
from app.redisq import get_redis, ensure_group, read_one, ack
from app import models
from app.detalhar_runner import run_detalhar

# Pipeline v2.0 (path do container)
from app.pipeline_v2.heuristica_leve import processar_heuristica_leve
from app.pipeline_v2.curador_llm import curar_processo
from app.pipeline_v2.analista_llm import analisar_processo
from app.pipeline_v2.config import USAR_LLM


# =============================================================================
# DIRETORIOS
# =============================================================================
BASE_DIR = Path("/data/detalhar")
DIR_RAW = BASE_DIR / "raw"
DIR_HEUR_V2 = BASE_DIR / "heur_v2"
DIR_ANALISE_V2 = BASE_DIR / "analise_v2"
DIR_RESUMO = BASE_DIR / "resumo"

for d in [DIR_RAW, DIR_HEUR_V2, DIR_ANALISE_V2, DIR_RESUMO]:
    d.mkdir(parents=True, exist_ok=True)


# =============================================================================
# BANCO DE DADOS - CLAIM/FINISH
# =============================================================================

async def claim_job(job_id: str):
    """Busca job do banco de dados."""
    async with SessionLocal() as db:
        res = await db.execute(models.SQL_CLAIM_JOB, {
            "job_id": job_id,
            "locked_by": settings.CONSUMER_NAME,
            "lock_minutes": settings.LOCK_MINUTES
        })
        job = res.mappings().first()
        await db.commit()
        return job

async def finish_done(job_id: str, output_leve: dict):
    """Marca job como concluído."""
    result_path = f"/data/detalhar/resumo/{job_id}.json"
    async with SessionLocal() as db:
        await db.execute(models.SQL_FINISH_DONE, {
            "job_id": job_id,
            "result_json": json.dumps(output_leve, ensure_ascii=False, default=str),
            "result_path": result_path
        })
        await db.commit()

async def finish_error(job_id: str, err: str):
    """Marca job como erro final."""
    async with SessionLocal() as db:
        await db.execute(models.SQL_FINISH_ERROR, {"job_id": job_id, "error": err})
        await db.commit()


LIMITE_DOCS_DIRETO = 10
LIMITE_CHARS_DIRETO = 120000


# =============================================================================
# HELPERS
# =============================================================================

def salvar_json(filepath: Path, data: dict) -> bool:
    try:
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        return True
    except Exception as e:
        print(f"[WARN] Erro salvar: {e}", file=sys.stderr)
        return False


def carregar_json(filepath: Path) -> Optional[dict]:
    try:
        if filepath.exists():
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        print(f"[WARN] Erro carregar: {e}", file=sys.stderr)
    return None


async def update_stage(job_id: str, stage: str, path: str = None):
    try:
        async with SessionLocal() as session:
            from sqlalchemy import update
            stmt = update(models.DetalharJob).where(
                models.DetalharJob.job_id == job_id
            ).values(status_stage=stage)
            if path:
                if "raw" in stage:
                    stmt = stmt.values(result_path_raw=path)
                elif "heur" in stage:
                    stmt = stmt.values(heur_path=path)
                elif "analise" in stage:
                    stmt = stmt.values(resumo_path=path)
            await session.execute(stmt)
            await session.commit()
    except Exception as e:
        print(f"[WARN] update_stage: {e}", file=sys.stderr)


# =============================================================================
# RESUMO v2 - COMPATIBILIDADE COM ARGUS
# =============================================================================

def salvar_resumo_v2(job_id: str, nup: str, analise: dict, metricas: dict) -> Path:
    """
    Salva resumo no formato compatível com API + campos ricos do v2.
    """
    # Tratamento defensivo - campos podem ser None
    sit = analise.get('situacao') or {}
    inter = analise.get('interessado') or {}
    ped = analise.get('pedido') or {}
    fluxo = analise.get('fluxo') or {}
    prazos = analise.get('prazos') or []
    legislacao = analise.get('legislacao') or []
    alertas = analise.get('alertas') or []
    
    # Montar resumo_texto rico
    partes = []
    partes.append(f"📋 NUP: {nup}")
    
    if inter.get('nome'):
        partes.append(f"👤 Interessado: {inter.get('nome')} | {inter.get('posto_grad', '')} | {inter.get('unidade', '')}")
    
    if ped.get('tipo') or ped.get('descricao'):
        partes.append(f"📝 Pedido: {ped.get('tipo', '')} - {ped.get('descricao', '')}")
    
    if sit.get('status'):
        partes.append(f"🚦 Situação: {sit.get('status')}")
    
    if sit.get('etapa_atual'):
        partes.append(f"   Etapa: {sit.get('etapa_atual')}")
    if sit.get('proximo_passo'):
        partes.append(f"   Próximo: {sit.get('proximo_passo')}")
    
    caminho = fluxo.get('caminho') or []
    if caminho and isinstance(caminho, list):
        partes.append(f"🔀 Fluxo: {' → '.join(str(c) for c in caminho)}")
    
    if prazos:
        partes.append("⏰ Prazos:")
        for p in prazos[:3]:
            if isinstance(p, dict):
                status_emoji = "🔴" if p.get('status') == 'PENDENTE' else "✅"
                partes.append(f"   {status_emoji} {p.get('descricao', '')} ({p.get('data', '')})")
            else:
                partes.append(f"   • {str(p)}")
    
    if legislacao:
        # Legislação pode ser lista de strings ou lista de dicts
        leg_strs = []
        for l in legislacao[:5]:
            if isinstance(l, dict):
                leg_strs.append(l.get('norma') or l.get('numero') or l.get('descricao') or f"{l.get('tipo', '')} {l.get('numero', '')}")
            else:
                leg_strs.append(str(l))
        partes.append(f"📚 Legislação: {', '.join(leg_strs)}")
    
    if analise.get('resumo_executivo'):
        partes.append(f"\n📝 RESUMO: {analise.get('resumo_executivo')}")
    
    if alertas:
        # Alertas pode ser lista de strings ou lista de dicts
        alert_strs = []
        for a in alertas:
            if isinstance(a, dict):
                alert_strs.append(a.get('mensagem') or a.get('descricao') or str(a))
            else:
                alert_strs.append(str(a))
        partes.append(f"\n⚠️ ALERTAS: {'; '.join(alert_strs)}")
    
    # Processar prazos de forma segura
    prazos_pendentes = []
    prazo_mais_urgente = None
    tem_prazo_pendente = False
    for p in prazos:
        if isinstance(p, dict) and p.get('status') == 'PENDENTE':
            tem_prazo_pendente = True
            prazos_pendentes.append(p.get('descricao', ''))
            if prazo_mais_urgente is None:
                prazo_mais_urgente = p.get('data')
    
    # Processar caminho de forma segura
    caminho_str = None
    caminho_list = fluxo.get('caminho') or []
    if caminho_list and isinstance(caminho_list, list):
        caminho_str = ' -> '.join(str(c) for c in caminho_list)
    
    resumo_texto = '\n'.join(partes)
    
    # Formato compatível com API + campos v2
    resumo_data = {
        "schema_version": "resumo.v2",
        "job_id": job_id,
        "nup": nup,
        
        # Campos que a API já usa (compatibilidade)
        "resumo_texto": resumo_texto,
        "resumo": {
            "schema_version": "resumo.v2",
            "nup": nup,
            "resumo_executivo": analise.get('resumo_executivo'),
            "situacao_atual": sit.get('status'),
            "pedido_vigente": ped.get('descricao'),
            "ultimo_comando": sit.get('proximo_passo'),
            "prazos_pendentes": prazos_pendentes,
            "prazo_mais_urgente": prazo_mais_urgente,
            
            # Campos novos v2
            "interessado": inter,
            "pedido": ped,
            "situacao": sit,
            "fluxo": fluxo,
            "prazos": prazos,
            "legislacao": legislacao,
            "alertas": alertas,
            
            # Unidades (compatibilidade)
            "unidades": {
                "demandante": fluxo.get('origem'),
                "executora": fluxo.get('unidade_atual'),
                "resposta": fluxo.get('destino_final'),
                "caminho": caminho_str
            },
            
            # Flags baseados nos dados reais
            "flags": {
                "tem_prazo_pendente": tem_prazo_pendente,
                "tem_recurso": False,
                "tem_decisao_final": sit.get('status') in ['DEFERIDO', 'INDEFERIDO', 'ARQUIVADO'] if sit.get('status') else False,
                "fluxo_regular": True,
                "requer_urgencia": any('URGENTE' in str(a).upper() for a in alertas) if alertas else False
            },
            
            "confianca": analise.get('confianca'),
            "pipeline_v2": True
        },
        
        "metricas": metricas
    }
    
    resumo_path = DIR_RESUMO / f"{job_id}.json"
    salvar_json(resumo_path, resumo_data)
    print(f"[RESUMO] Salvo em {resumo_path}", file=sys.stderr)
    return resumo_path


# =============================================================================
# EXTRACAO
# =============================================================================

async def estagio_extracao(job: dict, job_id: str, update_db: bool = True) -> dict:
    nup = job.get("nup", "")
    sigla = job.get("sigla")
    chat_id = job.get("chat_id")
    
    raw_path = DIR_RAW / f"{job_id}.json"
    
    result = await run_detalhar(
        nup=nup,
        sigla=sigla,
        chat_id=chat_id,
        job_id=job_id,
        prefer_ocr=True
    )
    
    if not result.get("sucesso"):
        return result
    
    raw_data = carregar_json(raw_path)
    if not raw_data:
        return {"sucesso": False, "erro": "Falha carregar raw"}
    
    output = {
        "sucesso": True,
        "nup": nup,
        "job_id": job_id,
        "diretoria": sigla,
        "documentos_total": raw_data.get("documentos_total", 0),
        "extraidos_ok": raw_data.get("extraidos_ok", 0),
        "duracao_segundos": raw_data.get("duracao_segundos", 0),
        "arquivo_raw": str(raw_path),
    }
    
    if update_db:
        await update_stage(job_id, "extracted", str(raw_path))
    
    return output


# =============================================================================
# PIPELINE v2.0
# =============================================================================

async def processar_pipeline_v2(job_id: str, raw_data: dict, usar_llm: bool = True, update_db: bool = True) -> dict:
    t0 = time.time()
    nup = raw_data.get('nup', '?')
    documentos = raw_data.get('documentos', [])
    
    resultado = {"nup": nup, "job_id": job_id, "sucesso": False, "etapas": {}}
    
    if not documentos:
        resultado["erro"] = "Nenhum documento"
        return resultado
    
    # 1. HEURISTICA
    t1 = time.time()
    heur = processar_heuristica_leve(documentos, nup)
    resultado["etapas"]["heuristica"] = {
        "tempo_ms": int((time.time() - t1) * 1000),
        "total_docs": len(heur.get('documentos', [])),
        "total_chars": heur.get('metricas', {}).get('total_chars', 0)
    }
    
    heur_path = DIR_HEUR_V2 / f"{job_id}_heur.json"
    salvar_json(heur_path, heur)
    
    if not usar_llm:
        resultado["sucesso"] = True
        resultado["modo"] = "APENAS_HEURISTICA"
        return resultado
    
    # 2. CURADOR (se necessario)
    total_docs = len(heur.get('documentos', []))
    total_chars = heur.get('metricas', {}).get('total_chars', 0)
    precisa_curador = total_docs > LIMITE_DOCS_DIRETO or total_chars > LIMITE_CHARS_DIRETO
    
    heur_para_analista = heur
    
    if precisa_curador:
        t2 = time.time()
        curado = curar_processo(heur)
        
        if not curado.get('sucesso'):
            resultado["erro"] = f"Curador: {curado.get('erro')}"
            return resultado
        
        heur_para_analista = curado.get('heuristica_filtrada', heur)
        resultado["etapas"]["curador"] = {
            "tempo_ms": int((time.time() - t2) * 1000),
            "docs_original": total_docs,
            "docs_selecionados": curado.get('total_selecionado', 0),
            "reducao_percent": curado.get('reducao_percent', 0),
            "custo": curado.get('_meta', {}).get('custo', 0)
        }
    else:
        resultado["etapas"]["curador"] = {"pulado": True}
    
    # 3. ANALISTA
    t3 = time.time()
    analise = analisar_processo(heur_para_analista)
    
    if not analise.get('sucesso'):
        resultado["erro"] = f"Analista: {analise.get('erro')}"
        return resultado
    
    resultado["etapas"]["analista"] = {
        "tempo_ms": int((time.time() - t3) * 1000),
        "docs_analisados": analise.get('total_docs_analisados', 0),
        "custo": analise.get('_meta', {}).get('custo', 0),
        "confianca": analise.get('confianca', 0)
    }
    
    analise_path = DIR_ANALISE_V2 / f"{job_id}_analise.json"
    salvar_json(analise_path, analise)
    
    # Métricas
    custo_total = resultado["etapas"].get("curador", {}).get("custo", 0) + resultado["etapas"]["analista"]["custo"]
    resultado["metricas"] = {
        "tempo_total_ms": int((time.time() - t0) * 1000),
        "custo_total_usd": custo_total,
        "confianca": analise.get('confianca', 0)
    }
    
    # Salvar resumo compatível com ARGUS
    salvar_resumo_v2(job_id, nup, analise, resultado["metricas"])
    
    resultado["sucesso"] = True
    resultado["modo"] = "CURADOR+ANALISTA" if precisa_curador else "ANALISTA_DIRETO"
    resultado["analise"] = analise
    
    return resultado


def formatar_resumo(resultado: Dict) -> str:
    if not resultado.get('sucesso'):
        return f"❌ Erro: {resultado.get('erro')}"
    
    a = resultado.get('analise') or {}
    sit = a.get('situacao') or {}
    inter = a.get('interessado') or {}
    ped = a.get('pedido') or {}
    fluxo = a.get('fluxo') or {}
    
    partes = [
        "============================================================",
        "📋 CONTEXTO PRÉ-PROCESSADO",
        "============================================================",
        f"NUP: {resultado.get('nup')}",
        ""
    ]
    
    if inter.get('nome'):
        partes.append(f"👤 INTERESSADO: {inter.get('nome')} | {inter.get('posto_grad', '')} | {inter.get('unidade', '')}")
    
    if ped.get('tipo') or ped.get('descricao'):
        partes.append(f"📋 PEDIDO: {ped.get('tipo', '')} - {ped.get('descricao', '')}")
    
    if sit.get('status'):
        partes.append(f"🚦 SITUAÇÃO: {sit.get('status')}")
        if sit.get('etapa_atual'):
            partes.append(f"   Etapa: {sit.get('etapa_atual')}")
        if sit.get('proximo_passo'):
            partes.append(f"   Próximo: {sit.get('proximo_passo')}")
    
    caminho = fluxo.get('caminho') or []
    if caminho and isinstance(caminho, list):
        partes.append(f"🔀 FLUXO: {' → '.join(str(c) for c in caminho)}")
    
    if a.get('resumo_executivo'):
        partes.append(f"\n📝 RESUMO: {a.get('resumo_executivo')}")
    
    alertas = a.get('alertas', [])
    if alertas:
        alert_strs = []
        for al in alertas:
            if isinstance(al, dict):
                alert_strs.append(al.get('mensagem') or al.get('descricao') or str(al))
            else:
                alert_strs.append(str(al))
        partes.append(f"\n⚠️ ALERTAS: {', '.join(alert_strs)}")
    
    partes.append("============================================================")
    
    return '\n'.join(partes)


# =============================================================================
# PROCESSAMENTO PRINCIPAL
# =============================================================================

async def processar_job(job: dict, job_id: str, update_db: bool = True) -> dict:
    t0 = time.time()
    usar_llm = getattr(settings, 'USAR_LLM', False) or USAR_LLM
    
    # 1. EXTRACAO
    print(f"[1/2] Extraindo {job.get('nup')}...", file=sys.stderr)
    output = await estagio_extracao(job, job_id, update_db)
    
    if not output.get("sucesso"):
        return output
    
    raw_data = carregar_json(Path(output["arquivo_raw"]))
    if not raw_data:
        output["erro"] = "Falha carregar raw"
        return output
    
    # 2. PIPELINE v2
    print(f"[2/2] Pipeline v2...", file=sys.stderr)
    res = await processar_pipeline_v2(job_id, raw_data, usar_llm, update_db)
    
    if not res.get("sucesso"):
        output["pipeline_erro"] = res.get("erro")
        return output
    
    a = res.get("analise", {})
    output["pipeline"] = {
        "situacao": (a.get("situacao") or {}).get("status"),
        "interessado": (a.get("interessado") or {}).get("nome"),
        "pedido": (a.get("pedido") or {}).get("tipo"),
        "confianca": a.get("confianca"),
        "metricas": res.get("metricas", {})
    }
    output["resumo_processo"] = formatar_resumo(res)
    
    custo = res.get("metricas", {}).get("custo_total_usd", 0)
    print(f"[OK] {output['documentos_total']} docs | {time.time()-t0:.1f}s | ${custo:.4f}", file=sys.stderr)
    
    return output


# =============================================================================
# HTTP API
# =============================================================================

http_app = FastAPI(title="ARGUS Worker v2.0")

class ProcessRequest(BaseModel):
    nup: str
    sigla: str | None = None
    chat_id: str | None = None

@http_app.get("/health")
async def health():
    return {"ok": True, "service": "worker-v2.0"}

@http_app.post("/process-now")
async def process_now(req: ProcessRequest):
    job_id = str(uuid.uuid4())
    print(f"[DIRETO] {req.nup} ({job_id})", file=sys.stderr)
    
    try:
        result = await processar_job({"nup": req.nup, "sigla": req.sigla, "chat_id": req.chat_id}, job_id, update_db=False)
        p = result.get("pipeline", {})
        return {
            "status": "ok" if result.get("sucesso") else "erro",
            "nup": req.nup,
            "job_id": job_id,
            "resumo_texto": result.get("resumo_processo"),
            "situacao": p.get("situacao"),
            "interessado": p.get("interessado"),
            "pedido": p.get("pedido"),
            "confianca": p.get("confianca"),
            "metricas": p.get("metricas"),
            "erro": result.get("erro") or result.get("pipeline_erro")
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"status": "erro", "nup": req.nup, "job_id": job_id, "erro": str(e)}


# =============================================================================
# CONSUMER REDIS
# =============================================================================

async def consumer_loop():
    redis = await get_redis()
    stream_hi = settings.STREAM_HI
    stream_lo = settings.STREAM_LO
    
    await ensure_group(redis, stream_hi)
    await ensure_group(redis, stream_lo)
    
    print(f"[CONSUMER] Streams: {stream_hi}, {stream_lo}", file=sys.stderr)
    
    while True:
        try:
            # Tenta stream HI primeiro
            current_stream = stream_hi
            msg = await read_one(redis, stream_hi, block_ms=1000)
            
            # Se não tem no HI, tenta LO
            if not msg:
                current_stream = stream_lo
                msg = await read_one(redis, stream_lo, block_ms=5000)
            
            if not msg:
                continue
            
            # read_one retorna (msg_id, fields)
            msg_id, fields = msg
            job_id = fields.get("job_id")
            
            if not job_id:
                await ack(redis, current_stream, msg_id)
                continue
            
            # Buscar dados completos do BANCO
            job = await claim_job(job_id)
            if not job:
                print(f"[CONSUMER] Job {job_id} não encontrado ou já processado", file=sys.stderr)
                await ack(redis, current_stream, msg_id)
                continue
            
            nup = job.get("nup", "?")
            sigla = job.get("sigla")
            chat_id = job.get("chat_id")
            
            print(f"[CONSUMER] {nup} ({job_id})", file=sys.stderr)
            
            try:
                result = await processar_job({"nup": nup, "sigla": sigla, "chat_id": chat_id}, job_id, update_db=True)
                
                if result.get("sucesso"):
                    await finish_done(job_id, result)
                else:
                    await finish_error(job_id, result.get("erro", "Erro desconhecido"))
            except Exception as job_err:
                await finish_error(job_id, str(job_err))
            
            await ack(redis, current_stream, msg_id)
            
        except Exception as e:
            print(f"[CONSUMER] Erro: {e}", file=sys.stderr)
            await asyncio.sleep(5)


def start_consumer():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(consumer_loop())


# =============================================================================
# MAIN
# =============================================================================

def main():
    threading.Thread(target=start_consumer, daemon=True).start()
    print("[WORKER v2.0] HTTP :8102", file=sys.stderr)
    uvicorn.run(http_app, host="0.0.0.0", port=8102, log_level="warning")


if __name__ == "__main__":
    main()
