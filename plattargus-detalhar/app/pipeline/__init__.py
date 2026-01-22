"""
Pipeline ARGUS

Versão: v1.1 (corrigido)

Correções principais:
- Extração de unidade_origem do CONTEÚDO do documento
- Novas tags: TEM_ENCERRAMENTO, TEM_DECRETO, TEM_AGREGACAO, etc.
- Detecção de fases do processo
- Pesos atualizados na heurística

Módulos:
- tags_detector: Detecção de tags técnicas (determinístico)
- heuristica: Score e compressão (determinístico)
- estagiario_a: Triagem por documento (LLM)
- estagiario_b: Consolidação (LLM)
- resumidor: Geração de resumo executivo
- orquestrador: Pipeline completo
- adaptador: Conversão do JSON atual para DocV1
"""

from .tags_detector import (
    detectar_tags,
    detectar_tags_com_detalhes,
    extrair_prazos,
    extrair_destinos,
    extrair_docs_mencionados,
    classificar_ato,
    classificar_documento_semantico,
)

from .heuristica import processar_heuristica

from .estagiario_a import (
    processar_triagem,
    processar_triagem_lote,
)

from .estagiario_b import (
    processar_consolidacao,
    processar_consolidacao_async,
)

from .resumidor import (
    gerar_resumo,
    formatar_para_argus,
    identificar_fases,
)

from .orquestrador import (
    PipelineARGUS,
    ConfigPipeline,
    processar_pipeline,
    processar_pipeline_async,
    processar_json_detalhar,
)

from .adaptador import (
    converter_documento_para_doc_v1,
    converter_json_para_docs_v1,
    extrair_unidade_do_conteudo,
)

__all__ = [
    # Tags
    "detectar_tags", "detectar_tags_com_detalhes",
    "extrair_prazos", "extrair_destinos", "extrair_docs_mencionados",
    "classificar_ato", "classificar_documento_semantico",
    
    # Heurística
    "processar_heuristica",
    
    # Estagiário A
    "processar_triagem", "processar_triagem_lote",
    
    # Estagiário B
    "processar_consolidacao", "processar_consolidacao_async",
    
    # Resumidor
    "gerar_resumo", "formatar_para_argus", "identificar_fases",
    
    # Orquestrador
    "PipelineARGUS", "ConfigPipeline",
    "processar_pipeline", "processar_pipeline_async",
    "processar_json_detalhar",
    
    # Adaptador
    "converter_documento_para_doc_v1", "converter_json_para_docs_v1",
    "extrair_unidade_do_conteudo",
]

from .orquestrador import processar_json_detalhar_async
