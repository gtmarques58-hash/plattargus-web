"""
Schema resumo.v1 - Resumo Executivo

Este schema é o OUTPUT FINAL do pipeline de pré-processamento.
É o que será enviado ao ARGUS (Sonnet) para análise final.

NÃO É UMA MINUTA - é o CONTEXTO estruturado para que
o ARGUS entenda o processo corretamente.
"""

from __future__ import annotations
from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field, field_validator


class ContextoParaIA(BaseModel):
    """Instruções para o ARGUS sobre como interpretar o processo"""
    foco: str = ""  # Em que a IA deve focar
    ignorar: str = ""  # O que ignorar (docs repetitivos, etc)
    docs_essenciais: List[str] = Field(default_factory=list)
    observacoes: List[str] = Field(default_factory=list)


class PrazoDestaque(BaseModel):
    """Prazo que merece destaque"""
    descricao: str
    data_limite: Optional[datetime] = None
    dias_restantes: Optional[int] = None
    doc_origem: str
    urgente: bool = False
    
    @field_validator('doc_origem', mode='before')
    @classmethod
    def converter_doc_id(cls, v: Any) -> str:
        return str(v) if v is not None else ""


class TrechoRelevante(BaseModel):
    """Trecho de documento para citação"""
    doc_id: str
    tipo_doc: str
    data_doc: Optional[datetime] = None
    trecho: str
    motivo_relevancia: str = ""
    
    @field_validator('doc_id', mode='before')
    @classmethod
    def converter_doc_id(cls, v: Any) -> str:
        return str(v) if v is not None else ""


class ResumoV1(BaseModel):
    """
    Schema resumo.v1 - Resumo Executivo
    
    Este é o output final do pipeline que será enviado
    ao ARGUS para análise do processo.
    """
    schema_version: str = "resumo.v1"
    nup: str
    
    # Resumo em texto livre (2-3 parágrafos)
    resumo_executivo: str = ""
    
    # Campos estruturados chave
    situacao_atual: str = ""
    pedido_vigente: str = ""
    ultimo_comando: str = ""
    
    # Prazos pendentes (destaque)
    prazos_pendentes: List[PrazoDestaque] = Field(default_factory=list)
    prazo_mais_urgente: Optional[str] = None
    
    # Contexto para a IA
    contexto_para_ia: ContextoParaIA = Field(default_factory=ContextoParaIA)
    
    # Trechos relevantes para citação
    trechos_relevantes: List[TrechoRelevante] = Field(default_factory=list)
    
    # Unidades envolvidas
    unidades: Dict[str, str] = Field(default_factory=dict)
    # Ex: {"demandante": "DRH", "executora": "CMDGER", "resposta_para": "DRH"}
    
    # Flags importantes
    flags: Dict[str, bool] = Field(default_factory=lambda: {
        "tem_prazo_pendente": False,
        "tem_recurso": False,
        "tem_decisao_final": False,
        "fluxo_regular": True,
        "requer_urgencia": False,
    })
    
    # Metadados do pipeline
    pipeline: Dict[str, Any] = Field(default_factory=lambda: {
        "docs_total": 0,
        "docs_analisados": 0,
        "docs_descartados": 0,
        "modelos_usados": [],
        "tempo_processamento_ms": 0,
    })
    
    processado_em: Optional[datetime] = None


# Funções auxiliares

def criar_resumo_v1(nup: str) -> ResumoV1:
    """Factory function para criar ResumoV1"""
    return ResumoV1(
        nup=nup,
        processado_em=datetime.now()
    )


def formatar_resumo_para_argus(resumo: ResumoV1) -> str:
    """
    Formata o resumo para enviar ao ARGUS como contexto
    """
    linhas = [
        "=" * 60,
        "RESUMO DO PROCESSO (Pré-processado)",
        "=" * 60,
        f"NUP: {resumo.nup}",
        "",
        "SITUAÇÃO ATUAL:",
        resumo.situacao_atual,
        "",
        "PEDIDO VIGENTE:",
        resumo.pedido_vigente or "(Não identificado)",
        "",
        "ÚLTIMO COMANDO:",
        resumo.ultimo_comando or "(Não identificado)",
        "",
    ]
    
    if resumo.prazos_pendentes:
        linhas.append("PRAZOS PENDENTES:")
        for prazo in resumo.prazos_pendentes:
            urgente = "⚠️ URGENTE" if prazo.urgente else ""
            linhas.append(f"  - {prazo.descricao} {urgente}")
        linhas.append("")
    
    if resumo.contexto_para_ia.foco:
        linhas.append("ATENÇÃO IA:")
        linhas.append(f"  Foco: {resumo.contexto_para_ia.foco}")
        if resumo.contexto_para_ia.ignorar:
            linhas.append(f"  Ignorar: {resumo.contexto_para_ia.ignorar}")
        linhas.append("")
    
    linhas.append("RESUMO EXECUTIVO:")
    linhas.append(resumo.resumo_executivo)
    linhas.append("")
    linhas.append("=" * 60)
    
    return "\n".join(linhas)
