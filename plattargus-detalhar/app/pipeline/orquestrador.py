"""
Orquestrador do Pipeline ARGUS

Une todas as etapas:
1. doc.v1 - Documentos enriquecidos (entrada)
2. heur.v1 - Heurística e score (determinístico)
3. triage.v1 - Triagem por documento (LLM Camada A)
4. case.v1 - Consolidação (LLM Camada B)
5. resumo.v1 - Resumo executivo (saída)
"""

import asyncio
from typing import List, Optional, Dict, Any
from datetime import datetime
import time

from ..schemas import (
    DocV1, HeurV1, TriageV1, CaseV1, ResumoV1,
    ParametrosHeuristica
)

from .tags_detector import detectar_tags
from .heuristica import processar_heuristica
from .estagiario_a import processar_triagem_lote
from .estagiario_b import processar_consolidacao_async
from .resumidor import gerar_resumo, formatar_para_argus


# =============================================================================
# CONFIGURAÇÃO DO PIPELINE
# =============================================================================

class ConfigPipeline:
    """Configuração global do pipeline"""
    # LLM
    usar_llm: bool = True
    api_key: str = ""
    modelo_triagem: str = "gpt-4o-mini"
    modelo_consolidacao: str = "gpt-4.1-mini"
    
    # Heurística
    top_k: int = 10
    
    # Performance
    max_concurrent_triagem: int = 5
    
    # Debug
    debug: bool = False
    salvar_intermediarios: bool = False


# =============================================================================
# PIPELINE COMPLETO
# =============================================================================

class PipelineARGUS:
    """
    Pipeline completo de processamento de processos SEI.
    
    Transforma documentos brutos em resumo estruturado para o ARGUS.
    """
    
    def __init__(self, config: Optional[ConfigPipeline] = None):
        self.config = config or ConfigPipeline()
        self.metricas: Dict[str, Any] = {}
    
    async def processar_async(
        self,
        docs: List[DocV1],
        api_key: str = None
    ) -> Dict[str, Any]:
        """
        Processa lista de documentos de forma assíncrona.
        
        Args:
            docs: Lista de DocV1 (documentos enriquecidos)
            api_key: API key do LLM (opcional, usa config se não fornecida)
            
        Returns:
            Dict com todos os resultados:
            - heur: HeurV1
            - triage: TriageV1
            - case: CaseV1
            - resumo: ResumoV1
            - resumo_texto: str (formatado para ARGUS)
            - metricas: Dict
        """
        inicio = time.time()
        api_key = api_key or self.config.api_key
        nup = docs[0].nup if docs else ""
        
        self.metricas = {
            "nup": nup,
            "docs_total": len(docs),
            "inicio": datetime.now().isoformat(),
            "etapas": {}
        }
        
        # -----------------------------------------------------------------
        # ETAPA 1: Enriquecer documentos com tags (se não tiver)
        # -----------------------------------------------------------------
        t1 = time.time()
        for doc in docs:
            if not doc.tags_tecnicas:
                doc.tags_tecnicas = detectar_tags(doc.texto_limpo)
                doc.atualizar_hash()
                doc.definir_data_ref()
        
        self.metricas["etapas"]["tags"] = {
            "tempo_ms": int((time.time() - t1) * 1000),
            "docs_processados": len(docs)
        }
        
        # -----------------------------------------------------------------
        # ETAPA 2: Heurística (determinística)
        # -----------------------------------------------------------------
        t2 = time.time()
        params = ParametrosHeuristica(top_k=self.config.top_k)
        heur = processar_heuristica(docs, params)
        
        self.metricas["etapas"]["heuristica"] = {
            "tempo_ms": int((time.time() - t2) * 1000),
            "docs_filtrados": heur.total_docs_filtrados,
            "docs_descartados": heur.compressao.total_descartados
        }
        
        # -----------------------------------------------------------------
        # ETAPA 3: Triagem - Camada A (LLM ou fallback)
        # -----------------------------------------------------------------
        t3 = time.time()
        
        # Filtrar apenas top_docs para triagem
        top_doc_ids = set(td.doc_id for td in heur.top_docs)
        docs_para_triagem = [d for d in docs if d.doc_id in top_doc_ids]
        
        triage = await processar_triagem_lote(
            docs=docs_para_triagem,
            api_key=api_key,
            usar_llm=self.config.usar_llm and bool(api_key),
            max_concurrent=self.config.max_concurrent_triagem
        )
        
        self.metricas["etapas"]["triagem"] = {
            "tempo_ms": int((time.time() - t3) * 1000),
            "docs_triados": len(triage.itens),
            "modelo": triage.modelo_usado,
            "tokens": triage.tokens_usados
        }
        
        # -----------------------------------------------------------------
        # ETAPA 4: Consolidação - Camada B (LLM ou fallback)
        # -----------------------------------------------------------------
        t4 = time.time()
        
        case = await processar_consolidacao_async(
            triage=triage,
            heur=heur,
            api_key=api_key,
            usar_llm=self.config.usar_llm and bool(api_key)
        )
        
        self.metricas["etapas"]["consolidacao"] = {
            "tempo_ms": int((time.time() - t4) * 1000),
            "modelo": case.modelo_usado,
            "situacao": case.situacao_atual.value
        }
        
        # -----------------------------------------------------------------
        # ETAPA 5: Resumo
        # -----------------------------------------------------------------
        t5 = time.time()
        
        pipeline_info = {
            "docs_total": len(docs),
            "docs_analisados": len(docs_para_triagem),
            "docs_descartados": heur.compressao.total_descartados,
            "modelos_usados": [triage.modelo_usado, case.modelo_usado],
            "tempo_processamento_ms": int((time.time() - inicio) * 1000)
        }
        
        resumo = gerar_resumo(case, docs, pipeline_info)
        resumo_texto = formatar_para_argus(resumo, docs)
        
        self.metricas["etapas"]["resumo"] = {
            "tempo_ms": int((time.time() - t5) * 1000)
        }
        
        # -----------------------------------------------------------------
        # RESULTADO FINAL
        # -----------------------------------------------------------------
        self.metricas["tempo_total_ms"] = int((time.time() - inicio) * 1000)
        self.metricas["fim"] = datetime.now().isoformat()
        
        return {
            "nup": nup,
            "heur": heur,
            "triage": triage,
            "case": case,
            "resumo": resumo,
            "resumo_texto": resumo_texto,
            "metricas": self.metricas
        }
    
    def processar(
        self,
        docs: List[DocV1],
        api_key: str = None
    ) -> Dict[str, Any]:
        """
        Versão síncrona do processamento.
        """
        return asyncio.run(self.processar_async(docs, api_key))


# =============================================================================
# FUNÇÕES DE CONVENIÊNCIA
# =============================================================================

def processar_pipeline(
    docs: List[DocV1],
    api_key: str = None,
    usar_llm: bool = True,
    top_k: int = 10
) -> Dict[str, Any]:
    """
    Função de conveniência para processar pipeline.
    
    Args:
        docs: Lista de DocV1
        api_key: API key do LLM
        usar_llm: Se False, usa apenas determinístico
        top_k: Quantos documentos selecionar
        
    Returns:
        Dict com todos os resultados
    """
    config = ConfigPipeline()
    config.usar_llm = usar_llm
    config.top_k = top_k
    
    pipeline = PipelineARGUS(config)
    return pipeline.processar(docs, api_key)


async def processar_pipeline_async(
    docs: List[DocV1],
    api_key: str = None,
    usar_llm: bool = True,
    top_k: int = 10
) -> Dict[str, Any]:
    """
    Versão assíncrona da função de conveniência.
    """
    config = ConfigPipeline()
    config.usar_llm = usar_llm
    config.top_k = top_k
    
    pipeline = PipelineARGUS(config)
    return await pipeline.processar_async(docs, api_key)


# =============================================================================
# INTEGRAÇÃO COM DETALHAR EXISTENTE
# =============================================================================

def processar_json_detalhar(
    json_detalhar: Dict[str, Any],
    api_key: str = None,
    usar_llm: bool = True
) -> Dict[str, Any]:
    """
    Processa output do detalhar atual e enriquece com pipeline.
    
    Args:
        json_detalhar: JSON retornado pelo detalhar_processo.py atual
        api_key: API key do LLM
        usar_llm: Se usar LLM ou apenas determinístico
        
    Returns:
        JSON enriquecido com resumo estruturado
    """
    from .adaptador import converter_json_para_docs_v1
    
    # Converter JSON atual para DocV1
    docs = converter_json_para_docs_v1(json_detalhar)
    
    if not docs:
        return json_detalhar  # Retorna original se não conseguir converter
    
    # Processar pipeline
    resultado = processar_pipeline(docs, api_key, usar_llm)
    
    # Adicionar ao JSON original
    json_detalhar["pipeline"] = {
        "resumo": resultado["resumo"].model_dump(),
        "resumo_texto": resultado["resumo_texto"],
        "metricas": resultado["metricas"]
    }
    
    # Substituir resumo_processo pelo novo
    json_detalhar["resumo_processo"] = resultado["resumo_texto"]
    
    return json_detalhar

async def processar_json_detalhar_async(
    json_detalhar: Dict[str, Any],
    api_key: str = None,
    usar_llm: bool = True
) -> Dict[str, Any]:
    """Versão async do processar_json_detalhar."""
    from .adaptador import converter_json_para_docs_v1
    
    docs = converter_json_para_docs_v1(json_detalhar)
    
    if not docs:
        return json_detalhar
    
    resultado = await processar_pipeline_async(docs, api_key, usar_llm)
    
    json_detalhar["pipeline"] = {
        "resumo": resultado["resumo"].model_dump(),
        "resumo_texto": resultado["resumo_texto"],
        "metricas": resultado["metricas"]
    }
    json_detalhar["resumo_processo"] = resultado["resumo_texto"]
    
    return json_detalhar
