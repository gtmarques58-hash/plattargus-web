from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from pathlib import Path
import json

from app.config import settings
from app.db import SessionLocal
from app.util import sha1
from app import models
from app.redisq import get_redis, ensure_group, push_job

app = FastAPI(title="detalhar-service")

class EnqueueReq(BaseModel):
    nup: str = Field(..., description="NUP do processo (formato SEI)")
    sigla: str | None = None
    chat_id: str | None = None
    user_id: str | None = None
    priority: int = 5
    max_attempts: int = 3
    source: str = "monitor"   # monitor | user_click
    force: bool = False
    modo: str = "detalhar"     # reservado (se quiser outros modos depois)

def check_key(x_api_key: str | None):
    if settings.API_KEY and x_api_key != settings.API_KEY:
        raise HTTPException(status_code=401, detail="unauthorized")

@app.get("/health")
async def health():
    return {"ok": True}

@app.get("/nup/{nup}/cache")
async def cache_by_nup(nup: str, sigla: str | None = None, x_api_key: str | None = Header(default=None)):
    """Cache-first por NUP: retorna o último job DONE dentro do TTL, se existir."""
    check_key(x_api_key)
    async with SessionLocal() as db:
        r = await db.execute(models.SQL_LATEST_DONE_BY_NUP_TTL, {
            "nup": nup, "sigla": sigla, "ttl_seconds": settings.CACHE_TTL_SECONDS
        })
        row = r.first()
        if not row:
            return {"hit": False}
        return {"hit": True, "job_id": str(row[0]), "finished_at": row[1].isoformat() if row[1] else None}

@app.post("/enqueue")
async def enqueue(req: EnqueueReq, x_api_key: str | None = Header(default=None)):
    check_key(x_api_key)

    dedup_key = sha1(f"{req.nup}|{req.sigla}|{req.modo}|v1")

    # 1) cache hit done (TTL)
    if not req.force:
        async with SessionLocal() as db:
            r1 = await db.execute(models.SQL_FIND_DEDUP_DONE_TTL, {
                "dedup_key": dedup_key,
                "ttl_seconds": settings.CACHE_TTL_SECONDS
            })
            row_done = r1.first()
            if row_done:
                return {"job_id": str(row_done[0]), "status": "done", "dedup": True, "message": "cache hit"}

            # 2) dedup ativo
            r2 = await db.execute(models.SQL_FIND_DEDUP_ACTIVE, {"dedup_key": dedup_key})
            row_active = r2.first()
            if row_active:
                job_id, status = row_active
                # clique do usuário deve "furar fila": bump prioridade + poke stream hi
                if req.source == "user_click":
                    await db.execute(models.SQL_BUMP_PRIORITY, {"job_id": job_id, "priority": max(req.priority, 9)})
                    await db.commit()
                    r = await get_redis()
                    await ensure_group(r, settings.STREAM_HI)
                    await push_job(r, settings.STREAM_HI, str(job_id), priority=max(req.priority, 9))
                return {"job_id": str(job_id), "status": status, "dedup": True, "message": "dedup ativo"}

            # 3) cria novo job
            r3 = await db.execute(models.SQL_INSERT_JOB, {
                "nup": req.nup,
                "sigla": req.sigla,
                "chat_id": req.chat_id,
                "user_id": req.user_id,
                "priority": req.priority,
                "max_attempts": req.max_attempts,
                "dedup_key": dedup_key,
            })
            job_id = r3.scalar_one()
            await db.commit()
    else:
        async with SessionLocal() as db:
            r3 = await db.execute(models.SQL_INSERT_JOB, {
                "nup": req.nup,
                "sigla": req.sigla,
                "chat_id": req.chat_id,
                "user_id": req.user_id,
                "priority": req.priority,
                "max_attempts": req.max_attempts,
                "dedup_key": dedup_key,
            })
            job_id = r3.scalar_one()
            await db.commit()

    # 4) empurra para fila redis (hi se clique)
    r = await get_redis()
    stream = settings.STREAM_HI if req.source == "user_click" else settings.STREAM_LO
    await ensure_group(r, stream)
    await push_job(r, stream, str(job_id), priority=req.priority)

    return {"job_id": str(job_id), "status": "queued", "dedup": False, "message": "enfileirado"}

@app.get("/jobs/{job_id}")
async def job_status(job_id: str, x_api_key: str | None = Header(default=None)):
    check_key(x_api_key)
    async with SessionLocal() as db:
        r = await db.execute(models.SQL_GET_JOB, {"job_id": job_id})
        row = r.mappings().first()
        if not row:
            raise HTTPException(404, "job not found")
        return dict(row)

@app.get("/jobs/{job_id}/result")
async def job_result(job_id: str, x_api_key: str | None = Header(default=None)):
    check_key(x_api_key)
    async with SessionLocal() as db:
        r = await db.execute(models.SQL_GET_RESULT, {"job_id": job_id})
        row = r.first()
        if not row:
            raise HTTPException(404, "result not ready")
        return row[0]

@app.get("/jobs/{job_id}/result/full")
async def job_result_full(job_id: str, x_api_key: str | None = Header(default=None)):
    check_key(x_api_key)
    async with SessionLocal() as db:
        r = await db.execute(models.SQL_GET_RESULT_PATH, {"job_id": job_id})
        row = r.first()
        if not row or not row[0]:
            raise HTTPException(404, "result not ready")
        path = row[0]

    p = Path(path)
    if not p.exists():
        raise HTTPException(404, "result file missing")
    return json.loads(p.read_text(encoding="utf-8", errors="ignore"))



# =============================================================================
# ENDPOINTS PARA INTEGRAÇÃO N8N/ARGUS
# =============================================================================

@app.get("/nup/{nup:path}/status")
async def status_by_nup(nup: str, sigla: str | None = None, x_api_key: str | None = Header(default=None)):
    """
    Retorna status do processamento por NUP.
    
    Respostas:
    - ready: resumo disponível
    - processing: job em andamento
    - queued: job na fila
    - not_found: nenhum job para este NUP
    """
    check_key(x_api_key)
    async with SessionLocal() as db:
        # Busca último job (qualquer status)
        r = await db.execute(models.SQL_LATEST_BY_NUP, {"nup": nup, "sigla": sigla})
        row = r.mappings().first()
        
        if not row:
            return {"status": "not_found", "nup": nup}
        
        job_id = str(row["job_id"])
        status = row["status"]
        
        if status == "done":
            # Verifica se resumo existe
            resumo_path = Path(f"/data/detalhar/resumo/{job_id}.json")
            if resumo_path.exists():
                return {
                    "status": "ready",
                    "nup": nup,
                    "job_id": job_id,
                    "finished_at": row["finished_at"].isoformat() if row["finished_at"] else None
                }
            else:
                return {"status": "done_sem_resumo", "nup": nup, "job_id": job_id}
        
        elif status in ("running", "queued", "retry"):
            return {
                "status": "processing",
                "nup": nup,
                "job_id": job_id,
                "status_detalhado": status
            }
        
        else:  # error
            return {
                "status": "error",
                "nup": nup,
                "job_id": job_id,
                "erro": row.get("error")
            }


@app.get("/nup/{nup:path}/resumo")
async def resumo_by_nup(
    nup: str, 
    sigla: str | None = None, 
    sync: bool = False,
    chat_id: str | None = None,
    x_api_key: str | None = Header(default=None)
):
    """
    Retorna resumo do processo por NUP.
    
    Parâmetros:
    - sync=false (default): retorna status se não pronto
    - sync=true: aguarda processamento se não existir (modo online)
    
    Respostas:
    - ready: inclui resumo_texto e dados
    - processing: job em andamento
    - queued: job criado/enfileirado (quando sync=true)
    - not_found: nenhum job (quando sync=false)
    """
    check_key(x_api_key)
    
    async with SessionLocal() as db:
        # Busca último job done (sem TTL - se arquivo existe, é válido)
        r = await db.execute(models.SQL_LATEST_BY_NUP, {
            "nup": nup, "sigla": sigla
        })
        row_done = r.mappings().first()
        
        if row_done and row_done["status"] == "done":
            job_id = str(row_done["job_id"])
            resumo_path = Path(f"/data/detalhar/resumo/{job_id}.json")
            
            if resumo_path.exists():
                resumo_data = json.loads(resumo_path.read_text(encoding="utf-8"))
                return {
                    "status": "ready",
                    "nup": nup,
                    "job_id": job_id,
                    "resumo_texto": resumo_data.get("resumo_texto", ""),
                    "situacao": resumo_data.get("resumo", {}).get("situacao_atual"),
                    "pedido_vigente": resumo_data.get("resumo", {}).get("pedido_vigente"),
                    "ultimo_comando": resumo_data.get("resumo", {}).get("ultimo_comando"),
                    "flags": resumo_data.get("resumo", {}).get("flags"),
                    "metricas": resumo_data.get("metricas")
                }
        
        # Verifica se tem job em andamento
        r2 = await db.execute(models.SQL_LATEST_BY_NUP, {"nup": nup, "sigla": sigla})
        row_any = r2.mappings().first()
        
        if row_any:
            status = row_any["status"]
            if status in ("running", "queued", "retry"):
                return {
                    "status": "processing",
                    "nup": nup,
                    "job_id": str(row_any["job_id"]),
                    "mensagem": "Processo sendo analisado. Aguarde alguns segundos."
                }
            elif status == "error":
                # Se erro e sync=true, tenta novamente
                if not sync:
                    return {
                        "status": "error",
                        "nup": nup,
                        "job_id": str(row_any["job_id"]),
                        "erro": row_any.get("error")
                    }
    
    # Não encontrou ou sync=true com erro anterior
    if not sync:
        return {"status": "not_found", "nup": nup}
    
    # sync=true: cria job e aguarda (para modo online)
    dedup_key = sha1(f"{nup}|{sigla}|detalhar|v1")
    
    async with SessionLocal() as db:
        # Cria novo job com prioridade alta
        r3 = await db.execute(models.SQL_INSERT_JOB, {
            "nup": nup,
            "sigla": sigla,
            "chat_id": chat_id,
            "user_id": None,
            "priority": 9,  # Alta prioridade para sync
            "max_attempts": 3,
            "dedup_key": dedup_key,
        })
        job_id = r3.scalar_one()
        await db.commit()
    
    # Empurra para fila HI (prioridade)
    r = await get_redis()
    await ensure_group(r, settings.STREAM_HI)
    await push_job(r, settings.STREAM_HI, str(job_id), priority=9)
    
    return {
        "status": "queued",
        "nup": nup,
        "job_id": str(job_id),
        "mensagem": "Processo enfileirado com prioridade. Aguarde ~45 segundos e consulte novamente."
    }

@app.get("/nup/{nup}/latest")
async def latest_by_nup(nup: str, sigla: str | None = None, x_api_key: str | None = Header(default=None)):
    check_key(x_api_key)
    async with SessionLocal() as db:
        r = await db.execute(models.SQL_LATEST_BY_NUP, {"nup": nup, "sigla": sigla})
        row = r.mappings().first()
        if not row:
            raise HTTPException(404, "no jobs for nup")
        return dict(row)
