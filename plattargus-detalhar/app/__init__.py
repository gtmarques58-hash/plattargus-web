"""
ARGUS Pipeline

Pipeline de pré-processamento inteligente para processos SEI.

Uso básico:
    from app import processar_json_detalhar
    
    resultado = processar_json_detalhar(json_detalhar, api_key="...")
"""

from .pipeline import (
    # Funções principais
    processar_pipeline,
    processar_pipeline_async,
    processar_json_detalhar,
    
    # Classes
    PipelineARGUS,
    ConfigPipeline,
    
    # Conversão
    converter_json_para_docs_v1,
    converter_documento_para_doc_v1,
    
    # Utilitários
    detectar_tags,
    processar_heuristica,
    gerar_resumo,
    formatar_para_argus,
)

from .schemas import (
    # doc.v1
    DocV1, TipoDocumento, SituacaoDocumento, TagTecnica,
    Autor, Assinatura, Referencias,
    
    # heur.v1
    HeurV1, TipoAto, Sinal, ParametrosHeuristica,
    
    # triage.v1
    TriageV1, ItemTriagem, AtoSemantico,
    
    # case.v1
    CaseV1, SituacaoAtual, PedidoVigente, UltimoComando, Pendencia,
    
    # resumo.v1
    ResumoV1, ContextoParaIA,
)

__version__ = "1.0.0"
__all__ = [
    # Funções principais
    "processar_pipeline",
    "processar_pipeline_async", 
    "processar_json_detalhar",
    
    # Classes
    "PipelineARGUS",
    "ConfigPipeline",
    
    # Schemas
    "DocV1", "HeurV1", "TriageV1", "CaseV1", "ResumoV1",
]
