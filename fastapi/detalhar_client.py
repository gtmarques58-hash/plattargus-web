"""
=============================================================================
PLATTARGUS-DETALHAR CLIENT v2
=============================================================================
Cliente para integração do FastAPI principal com o serviço plattargus-detalhar.

Ajustado para a API real do detalhar-service:
    POST /enqueue           → Criar job
    GET  /jobs/{job_id}     → Status do job
    GET  /jobs/{job_id}/result → Resultado (resumo)
    GET  /jobs/{job_id}/result/full → Resultado completo
    GET  /nup/{nup}/cache   → Verificar cache
    GET  /nup/{nup}/status  → Status por NUP

Coloque este arquivo em: /opt/plattargus-web/fastapi/detalhar_client.py
=============================================================================
"""

import os
import asyncio
from typing import Optional, Dict, Any
from dataclasses import dataclass
from pathlib import Path
import json

import httpx

# =============================================================================
# CONFIGURAÇÃO
# =============================================================================

DETALHAR_API_URL = os.getenv("DETALHAR_API_URL", "http://plattargus-detalhar-api:8000")
DETALHAR_TIMEOUT_SYNC = int(os.getenv("DETALHAR_TIMEOUT_SYNC", "720"))  # 12 min
DETALHAR_POLL_INTERVAL = int(os.getenv("DETALHAR_POLL_INTERVAL", "5"))  # 5 seg
DETALHAR_API_KEY = os.getenv("DETALHAR_API_KEY", "")  # Opcional


@dataclass
class DetalharResult:
    """Resultado do detalhar"""
    sucesso: bool
    from_cache: bool = False
    job_id: Optional[str] = None
    resultado: Optional[Dict[str, Any]] = None
    erro: Optional[str] = None
    duracao_segundos: Optional[float] = None


class DetalharClient:
    """
    Cliente para comunicação com o serviço plattargus-detalhar.
    
    O serviço detalhar processa operações longas (10-12 min) de forma
    isolada, sem travar o sistema principal.
    """
    
    def __init__(self, base_url: str = None, api_key: str = None):
        self.base_url = base_url or DETALHAR_API_URL
        self.api_key = api_key or DETALHAR_API_KEY
        self._client: Optional[httpx.AsyncClient] = None
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Retorna cliente HTTP reutilizável"""
        if self._client is None or self._client.is_closed:
            headers = {}
            if self.api_key:
                headers["x-api-key"] = self.api_key
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=30.0,
                headers=headers
            )
        return self._client
    
    async def close(self):
        """Fecha conexões"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
    
    # =========================================================================
    # HEALTH CHECK
    # =========================================================================
    
    async def health_check(self) -> Dict[str, Any]:
        """Verifica se o serviço está online"""
        try:
            client = await self._get_client()
            resp = await client.get("/health")
            return resp.json()
        except Exception as e:
            return {"ok": False, "error": str(e)}
    
    async def is_online(self) -> bool:
        """Verifica se o serviço está online"""
        health = await self.health_check()
        return health.get("ok", False)
    
    # =========================================================================
    # CACHE
    # =========================================================================
    
    async def check_cache(self, nup: str, sigla: str = None) -> Optional[Dict[str, Any]]:
        """
        Verifica se o processo está em cache.
        
        Returns:
            Dict com hit=True e job_id se em cache, hit=False se não
        """
        try:
            client = await self._get_client()
            params = {}
            if sigla:
                params["sigla"] = sigla
            resp = await client.get(f"/nup/{nup}/cache", params=params)
            return resp.json()
        except:
            return {"hit": False}
    
    # =========================================================================
    # CRIAR JOB
    # =========================================================================
    
    async def enqueue(
        self,
        nup: str,
        sigla: str = None,
        user_id: str = None,
        priority: int = 5,
        source: str = "user_click",  # user_click tem prioridade alta
        force: bool = False
    ) -> Dict[str, Any]:
        """
        Enfileira um job de detalhar.
        
        Args:
            nup: Número do processo (ex: "0609.000000.00000/2025-00")
            sigla: Sigla do usuário no SEI
            user_id: ID do usuário
            priority: Prioridade (1-10, maior = mais urgente)
            source: "user_click" (prioridade alta) ou "monitor" (baixa)
            force: Se True, ignora cache e reprocessa
        
        Returns:
            Dict com job_id, status, dedup, message
        """
        client = await self._get_client()
        
        payload = {
            "nup": nup,
            "sigla": sigla,
            "user_id": user_id,
            "priority": priority,
            "source": source,
            "force": force,
            "modo": "detalhar"
        }
        
        resp = await client.post("/enqueue", json=payload)
        return resp.json()
    
    # =========================================================================
    # STATUS E RESULTADO
    # =========================================================================
    
    async def get_status(self, job_id: str) -> Dict[str, Any]:
        """Retorna status atual do job"""
        client = await self._get_client()
        resp = await client.get(f"/jobs/{job_id}")
        
        if resp.status_code == 404:
            return {"status": "not_found", "error": "Job não encontrado"}
        
        return resp.json()
    
    async def get_status_by_nup(self, nup: str, sigla: str = None) -> Dict[str, Any]:
        """Retorna status do processamento por NUP"""
        client = await self._get_client()
        params = {}
        if sigla:
            params["sigla"] = sigla
        resp = await client.get(f"/nup/{nup}/status", params=params)
        return resp.json()
    
    async def get_result(self, job_id: str, full: bool = True) -> Dict[str, Any]:
        """
        Retorna resultado do job (se concluído).
        
        Args:
            job_id: ID do job
            full: Se True, retorna resultado completo (/result/full)
        """
        client = await self._get_client()
        
        endpoint = f"/jobs/{job_id}/result/full" if full else f"/jobs/{job_id}/result"
        resp = await client.get(endpoint)
        
        if resp.status_code == 404:
            raise Exception("Resultado não disponível ainda")
        
        return resp.json()
    
    # =========================================================================
    # DETALHAR SÍNCRONO (aguarda resultado)
    # =========================================================================
    
    async def detalhar_sync(
        self,
        nup: str,
        credenciais: Dict[str, str] = None,
        user_id: str = None,
        timeout: int = None,
        force: bool = False,
        on_progress: callable = None
    ) -> DetalharResult:
        """
        Executa detalhamento e aguarda resultado (com polling).
        
        Args:
            nup: Número do processo
            credenciais: Dict com usuario, senha, sigla (sigla é o importante aqui)
            user_id: ID do usuário
            timeout: Timeout em segundos (default: 720 = 12 min)
            force: Se True, ignora cache
            on_progress: Callback chamado a cada atualização de status
        
        Returns:
            DetalharResult com resultado completo ou erro
        """
        timeout = timeout or DETALHAR_TIMEOUT_SYNC
        sigla = credenciais.get("sigla") if credenciais else None
        
        # 1. Verificar cache primeiro (se não for forçado)
        if not force:
            cache_result = await self.check_cache(nup, sigla)
            if cache_result.get("hit"):
                cached_job_id = cache_result.get("job_id")
                try:
                    resultado = await self.get_result(cached_job_id, full=True)
                    return DetalharResult(
                        sucesso=True,
                        from_cache=True,
                        job_id=cached_job_id,
                        resultado=resultado
                    )
                except:
                    pass  # Cache inválido, continua para enfileirar
        
        # 2. Enfileirar job
        try:
            enqueue_result = await self.enqueue(
                nup=nup,
                sigla=sigla,
                user_id=user_id,
                priority=9,  # Prioridade alta para clique do usuário
                source="user_click",
                force=force
            )
        except Exception as e:
            return DetalharResult(sucesso=False, erro=f"Erro ao enfileirar: {e}")
        
        job_id = enqueue_result.get("job_id")
        
        if not job_id:
            return DetalharResult(sucesso=False, erro="Não recebeu job_id")
        
        # Se já estava pronto (dedup com done)
        if enqueue_result.get("status") == "done":
            try:
                resultado = await self.get_result(job_id, full=True)
                return DetalharResult(
                    sucesso=True,
                    from_cache=True,
                    job_id=job_id,
                    resultado=resultado
                )
            except:
                pass  # Continua para polling
        
        # 3. Polling até completar ou timeout
        start_time = asyncio.get_event_loop().time()
        
        while True:
            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed > timeout:
                return DetalharResult(
                    sucesso=False,
                    job_id=job_id,
                    erro=f"Timeout após {timeout} segundos"
                )
            
            try:
                status = await self.get_status(job_id)
                status_value = status.get("status", "unknown")
                
                # Callback de progresso
                if on_progress:
                    try:
                        progress = 50 if status_value == "running" else 10
                        on_progress(progress, f"Status: {status_value}")
                    except:
                        pass
                
                # Concluído com sucesso
                if status_value == "done":
                    try:
                        resultado = await self.get_result(job_id, full=True)
                        return DetalharResult(
                            sucesso=True,
                            from_cache=False,
                            job_id=job_id,
                            resultado=resultado,
                            duracao_segundos=elapsed
                        )
                    except Exception as e:
                        return DetalharResult(
                            sucesso=False,
                            job_id=job_id,
                            erro=f"Erro ao obter resultado: {e}"
                        )
                
                # Erro
                if status_value == "error":
                    return DetalharResult(
                        sucesso=False,
                        job_id=job_id,
                        erro=status.get("error_msg", "Erro no processamento")
                    )
                
            except Exception as e:
                # Erro de conexão, tentar novamente
                pass
            
            # Aguardar antes do próximo poll
            await asyncio.sleep(DETALHAR_POLL_INTERVAL)
    
    # =========================================================================
    # DETALHAR ASSÍNCRONO (retorna job_id)
    # =========================================================================
    
    async def detalhar_async(
        self,
        nup: str,
        credenciais: Dict[str, str] = None,
        user_id: str = None
    ) -> DetalharResult:
        """
        Inicia detalhamento assíncrono - retorna job_id imediatamente.
        
        Use get_status() e get_result() para acompanhar.
        """
        sigla = credenciais.get("sigla") if credenciais else None
        
        # Verificar cache
        cache_result = await self.check_cache(nup, sigla)
        if cache_result.get("hit"):
            cached_job_id = cache_result.get("job_id")
            try:
                resultado = await self.get_result(cached_job_id, full=True)
                return DetalharResult(
                    sucesso=True,
                    from_cache=True,
                    job_id=cached_job_id,
                    resultado=resultado
                )
            except:
                pass
        
        # Enfileirar
        try:
            enqueue_result = await self.enqueue(
                nup=nup,
                sigla=sigla,
                user_id=user_id,
                priority=9,
                source="user_click"
            )
            
            return DetalharResult(
                sucesso=True,
                job_id=enqueue_result.get("job_id"),
                from_cache=enqueue_result.get("status") == "done"
            )
        except Exception as e:
            return DetalharResult(sucesso=False, erro=str(e))


# =============================================================================
# INSTÂNCIA GLOBAL (singleton)
# =============================================================================

_client: Optional[DetalharClient] = None

def get_detalhar_client() -> DetalharClient:
    """Retorna instância singleton do cliente"""
    global _client
    if _client is None:
        _client = DetalharClient()
    return _client
