"""
Schemas do Pipeline ARGUS

Versão: v1.1 (compatível com v1)

Correções aplicadas em doc_v1.py:
- Novas TagTecnica: TEM_ENCERRAMENTO, TEM_DECRETO, TEM_AGREGACAO, etc.
- Novos campos: unidade_origem_real, is_decreto, is_encerramento, etc.
- Método get_sigla_efetiva() para obter sigla corrigida
"""

from .doc_v1 import (
    DocV1,
    TipoDocumento,
    SituacaoDocumento,
    MetodoExtracao,
    TagTecnica,
    Autor,
    Assinatura,
    Referencias,
    InfoExtracao,
    criar_doc_v1,
)

from .heur_v1 import (
    HeurV1,
    TipoAto,
    Sinal,
    ParametrosHeuristica,
    DocScore,
    GrupoCompressao,
    Compressao,
    TopDoc,
    CoberturaObrigatoria,
    criar_heur_v1,
    # NOVO v1.2: Estágio Processual
    EstagioProcessual,
    CicloProcessual,
    MAPA_TIPO_ESTAGIO,
    classificar_estagio,
    identificar_ciclos,
)

from .triage_v1 import (
    TriageV1,
    AtoSemantico,
    ResultadoAto,
    Prazo,
    Citacao,
    ItemTriagem,
    criar_item_triagem,
    criar_triage_v1,
)

from .case_v1 import (
    CaseV1,
    SituacaoAtual,
    PedidoVigente,
    UltimoComando,
    Pendencia,
    EventoTimeline,
    CitacaoBase,
    FluxoTramitacao,
    criar_case_v1,
    criar_pendencia,
)

from .resumo_v1 import (
    ResumoV1,
    ContextoParaIA,
    PrazoDestaque,
    TrechoRelevante,
    criar_resumo_v1,
    formatar_resumo_para_argus,
)

__all__ = [
    # doc.v1
    "DocV1", "TipoDocumento", "SituacaoDocumento", "MetodoExtracao",
    "TagTecnica", "Autor", "Assinatura", "Referencias", "InfoExtracao",
    "criar_doc_v1",
    
    # heur.v1
    "HeurV1", "TipoAto", "Sinal", "ParametrosHeuristica",
    "DocScore", "GrupoCompressao", "Compressao", "TopDoc",
    "CoberturaObrigatoria", "criar_heur_v1",
    # Estágio Processual (v1.2)
    "EstagioProcessual", "CicloProcessual", "MAPA_TIPO_ESTAGIO",
    "classificar_estagio", "identificar_ciclos",
    
    # triage.v1
    "TriageV1", "AtoSemantico", "ResultadoAto", "Prazo", "Citacao",
    "ItemTriagem", "criar_item_triagem", "criar_triage_v1",
    
    # case.v1
    "CaseV1", "SituacaoAtual", "PedidoVigente", "UltimoComando",
    "Pendencia", "EventoTimeline", "CitacaoBase", "FluxoTramitacao",
    "criar_case_v1", "criar_pendencia",
    
    # resumo.v1
    "ResumoV1", "ContextoParaIA", "PrazoDestaque", "TrechoRelevante",
    "criar_resumo_v1", "formatar_resumo_para_argus",
]
