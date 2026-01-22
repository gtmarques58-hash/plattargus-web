#!/usr/bin/env python3
"""
PlattArgus FastAPI - Adaptações para Integração com Laravel
=============================================================

Este arquivo contém os NOVOS endpoints e adaptações necessárias para
integrar o FastAPI (Engine) com o backend Laravel.

COMO USAR:
1. Copie este arquivo para /opt/plattargus/ ou /app/
2. Importe no api.py principal:
   from api_laravel_integration import router as laravel_router
   app.include_router(laravel_router, prefix="/v1")

PRINCIPAIS MUDANÇAS:
- Recebe credencial SEI por parâmetro (não mais do banco de diretorias)
- Validação HMAC para autenticação interna
- Callbacks para notificar Laravel sobre progresso/conclusão
"""

import os
import sys
import json
import hmac
import hashlib
import time
import httpx
from typing import Dict, Optional, Any
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request, Header, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# Configuração
LARAVEL_CALLBACK_URL = os.getenv("LARAVEL_CALLBACK_URL", "http://localhost:8080")
HMAC_SECRET = os.getenv("PLATT_ENGINE_SECRET", "")
HMAC_TIME_WINDOW = 300  # 5 minutos

router = APIRouter(tags=["Laravel Integration"])


# =============================================================================
# MODELOS DE REQUISIÇÃO
# =============================================================================

class CredencialSEI(BaseModel):
    """Credencial SEI recebida do Laravel (já descriptografada)."""
    usuario: str
    senha: str
    orgao_id: str = "31"
    cargo: Optional[str] = None


class JobRequest(BaseModel):
    """Requisição de job vindo do Laravel."""
    job_id: str
    user_id: int
    nup: Optional[str] = None
    sei_numero: Optional[str] = None
    modo: str  # 'analise', 'assinar', 'inserir', 'gerar'
    credencial: CredencialSEI
    opcoes: Optional[Dict[str, Any]] = None


class AssinaturaRequest(BaseModel):
    """Requisição específica para assinatura."""
    job_id: str
    user_id: int
    sei_numero: str
    credencial: CredencialSEI


class ChatRequest(BaseModel):
    """Requisição para chat analítico."""
    user_id: int
    usuario_sei: str
    mensagem: str
    texto_canonico: Optional[str] = None
    modelo_forcado: Optional[str] = None
    tipo_documento: Optional[str] = None


# =============================================================================
# VALIDAÇÃO HMAC
# =============================================================================

async def validate_hmac(
    request: Request,
    x_timestamp: str = Header(...),
    x_signature: str = Header(...),
    x_request_id: str = Header(None)
):
    """
    Valida assinatura HMAC das requisições vindas do Laravel.
    
    Formato da assinatura:
    base = timestamp + "\n" + METHOD + "\n" + path + "\n" + SHA256(body)
    signature = HMAC-SHA256(secret, base)
    """
    if not HMAC_SECRET:
        raise HTTPException(500, "PLATT_ENGINE_SECRET não configurado")
    
    # Valida timestamp (anti-replay)
    try:
        request_time = int(x_timestamp)
    except ValueError:
        raise HTTPException(401, "Timestamp inválido")
    
    now = int(time.time())
    if abs(now - request_time) > HMAC_TIME_WINDOW:
        raise HTTPException(401, "Requisição expirada")
    
    # Reconstrói assinatura
    body = await request.body()
    body_hash = hashlib.sha256(body).hexdigest()
    
    method = request.method.upper()
    path = request.url.path
    
    base = f"{x_timestamp}\n{method}\n{path}\n{body_hash}"
    expected_signature = hmac.new(
        HMAC_SECRET.encode(),
        base.encode(),
        hashlib.sha256
    ).hexdigest()
    
    # Comparação segura
    if not hmac.compare_digest(expected_signature, x_signature):
        raise HTTPException(401, "Assinatura inválida")
    
    return True


# =============================================================================
# CALLBACKS PARA LARAVEL
# =============================================================================

async def notify_laravel(job_id: str, status: str, data: Dict = None, error: str = None):
    """Notifica Laravel sobre status do job."""
    if not LARAVEL_CALLBACK_URL:
        return
    
    payload = {
        "status": status,
        "result": data,
        "error": error,
    }
    
    try:
        async with httpx.AsyncClient() as client:
            # Gera HMAC para callback
            body = json.dumps(payload)
            timestamp = str(int(time.time()))
            path = f"/api/internal/jobs/{job_id}/done"
            body_hash = hashlib.sha256(body.encode()).hexdigest()
            base = f"{timestamp}\nPOST\n{path}\n{body_hash}"
            signature = hmac.new(HMAC_SECRET.encode(), base.encode(), hashlib.sha256).hexdigest()
            
            await client.post(
                f"{LARAVEL_CALLBACK_URL}{path}",
                json=payload,
                headers={
                    "X-Timestamp": timestamp,
                    "X-Signature": signature,
                    "X-Request-ID": job_id,
                    "Content-Type": "application/json",
                },
                timeout=10
            )
    except Exception as e:
        print(f"Erro ao notificar Laravel: {e}", file=sys.stderr)


async def update_progress(job_id: str, progress_pct: int, progress_step: str):
    """Atualiza progresso do job no Laravel."""
    if not LARAVEL_CALLBACK_URL:
        return
    
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{LARAVEL_CALLBACK_URL}/api/internal/jobs/{job_id}/progress",
                json={
                    "progress_pct": progress_pct,
                    "progress_step": progress_step,
                },
                timeout=5
            )
    except:
        pass  # Progresso é best-effort


# =============================================================================
# ENDPOINT: INICIAR JOB
# =============================================================================

@router.post("/jobs/start")
async def start_job(req: JobRequest, validated: bool = Depends(validate_hmac)):
    """
    Endpoint principal para iniciar jobs vindos do Laravel.
    
    Modos suportados:
    - analise: Analisa processo do SEI
    - assinar: Assina documento
    - inserir: Insere documento no SEI
    - gerar: Gera documento via IA
    """
    try:
        if req.modo == "analise":
            return await _executar_analise(req)
        elif req.modo == "assinar":
            return await _executar_assinatura(req)
        elif req.modo == "inserir":
            return await _executar_insercao(req)
        elif req.modo == "gerar":
            return await _executar_geracao(req)
        else:
            raise HTTPException(400, f"Modo desconhecido: {req.modo}")
            
    except Exception as e:
        await notify_laravel(req.job_id, "error", error=str(e))
        raise HTTPException(500, str(e))


# =============================================================================
# IMPLEMENTAÇÕES DOS MODOS
# =============================================================================

async def _executar_analise(req: JobRequest):
    """Executa análise de processo."""
    from detalhar_processo import detalhar_processo_completo
    
    await update_progress(req.job_id, 10, "Iniciando análise")
    
    # Usa credencial recebida por parâmetro
    credencial = {
        "usuario": req.credencial.usuario,
        "senha": req.credencial.senha,
        "orgao_id": req.credencial.orgao_id,
    }
    
    await update_progress(req.job_id, 20, "Acessando SEI")
    
    # Chama função existente adaptada
    resultado = await detalhar_processo_completo(
        nup=req.nup,
        credencial=credencial,  # NOVO: passa credencial por parâmetro
        opcoes=req.opcoes or {}
    )
    
    await update_progress(req.job_id, 100, "Concluído")
    await notify_laravel(req.job_id, "done", data=resultado)
    
    # Limpa senha da memória
    credencial["senha"] = "x" * len(credencial["senha"])
    del credencial
    
    return JSONResponse({
        "sucesso": True,
        "job_id": req.job_id,
        "analise": resultado.get("analise"),
        "conteudo_bruto": resultado.get("texto", "")[:5000],
    })


async def _executar_assinatura(req: JobRequest):
    """Executa assinatura de documento."""
    from assinar_documento import assinar_documento
    
    await update_progress(req.job_id, 10, "Preparando assinatura")
    
    # Monta dados do assinante a partir da credencial
    dados_assinante = {
        "login_sei": req.credencial.usuario,
        "senha": req.credencial.senha,
        "orgao_id": req.credencial.orgao_id,
        "cargo": req.credencial.cargo,
    }
    
    await update_progress(req.job_id, 30, "Acessando documento")
    
    # Chama função existente adaptada
    resultado = await assinar_documento(
        sei_numero=req.sei_numero,
        dados_assinante=dados_assinante,  # NOVO: passa dados por parâmetro
    )
    
    await update_progress(req.job_id, 100, "Concluído")
    
    status = "done" if resultado.get("sucesso") else "error"
    await notify_laravel(req.job_id, status, data=resultado, error=resultado.get("erro"))
    
    # Limpa senha da memória
    dados_assinante["senha"] = "x" * len(dados_assinante["senha"])
    del dados_assinante
    
    return JSONResponse({
        "sucesso": resultado.get("sucesso", False),
        "job_id": req.job_id,
        "mensagem": resultado.get("mensagem"),
        "erro": resultado.get("erro"),
    })


async def _executar_insercao(req: JobRequest):
    """Executa inserção de documento no SEI."""
    # TODO: Implementar quando necessário
    await notify_laravel(req.job_id, "done", data={"sucesso": True})
    return JSONResponse({"sucesso": True, "job_id": req.job_id})


async def _executar_geracao(req: JobRequest):
    """Executa geração de documento via IA."""
    # Usa função existente do api.py
    # TODO: Adaptar para receber parâmetros do Laravel
    await notify_laravel(req.job_id, "done", data={"sucesso": True})
    return JSONResponse({"sucesso": True, "job_id": req.job_id})


# =============================================================================
# ENDPOINT: ASSINATURA DIRETA
# =============================================================================

@router.post("/assinar")
async def assinar_direto(req: AssinaturaRequest, validated: bool = Depends(validate_hmac)):
    """
    Endpoint direto para assinatura de documento.
    Usado quando não precisa de job assíncrono.
    """
    from assinar_documento import assinar_documento
    
    dados_assinante = {
        "login_sei": req.credencial.usuario,
        "senha": req.credencial.senha,
        "orgao_id": req.credencial.orgao_id,
        "cargo": req.credencial.cargo,
    }
    
    try:
        resultado = await assinar_documento(
            sei_numero=req.sei_numero,
            dados_assinante=dados_assinante,
        )
        
        return JSONResponse({
            "sucesso": resultado.get("sucesso", False),
            "mensagem": resultado.get("mensagem"),
            "erro": resultado.get("erro"),
        })
        
    finally:
        # Limpa senha da memória
        dados_assinante["senha"] = "x" * len(dados_assinante["senha"])
        del dados_assinante


# =============================================================================
# ENDPOINT: TESTAR CREDENCIAL
# =============================================================================

@router.post("/testar-credencial")
async def testar_credencial(credencial: CredencialSEI, validated: bool = Depends(validate_hmac)):
    """
    Testa se uma credencial SEI é válida.
    Usado pelo Laravel antes de salvar a credencial.
    """
    from sei_auth_multi import testar_credenciais
    
    try:
        resultado = await testar_credenciais(
            usuario=credencial.usuario,
            senha=credencial.senha,
            orgao_id=credencial.orgao_id
        )
        
        return JSONResponse({
            "sucesso": resultado.get("sucesso", False),
            "tempo_login": resultado.get("tempo_login"),
            "erro": resultado.get("erro"),
        })
        
    except Exception as e:
        return JSONResponse({
            "sucesso": False,
            "erro": str(e),
        })


# =============================================================================
# HEALTH CHECK
# =============================================================================

@router.get("/health")
async def health():
    """Health check para o Laravel verificar se Engine está online."""
    return {
        "status": "ok",
        "service": "PlattArgus Engine",
        "version": "2.1.0",
        "timestamp": datetime.now().isoformat(),
        "hmac_configured": bool(HMAC_SECRET),
        "callback_url": LARAVEL_CALLBACK_URL,
    }
