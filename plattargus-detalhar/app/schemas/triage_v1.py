"""
Schema triage.v1 - Camada A (Triagem por documento)
"""
from __future__ import annotations
from typing import Optional, List, Any
from datetime import datetime
from pydantic import BaseModel, Field, field_validator
from enum import Enum


class AtoSemantico(str, Enum):
    """Classificação semântica do ato"""
    PEDIDO = "PEDIDO"
    COMANDO = "COMANDO"
    DECISAO = "DECISAO"
    PARECER = "PARECER"
    INFORMACAO = "INFORMACAO"
    ENCAMINHAMENTO = "ENCAMINHAMENTO"
    RECURSO = "RECURSO"
    PUBLICACAO = "PUBLICACAO"
    ARQUIVAMENTO = "ARQUIVAMENTO"
    OUTRO = "OUTRO"


class ResultadoAto(str, Enum):
    """Resultado de uma decisão"""
    DEFERIDO = "DEFERIDO"
    INDEFERIDO = "INDEFERIDO"
    PARCIALMENTE_DEFERIDO = "PARCIALMENTE_DEFERIDO"
    ARQUIVADO = "ARQUIVADO"
    PENDENTE = "PENDENTE"
    NAO_APLICAVEL = "NAO_APLICAVEL"


class Prazo(BaseModel):
    """Informação de prazo"""
    existe: bool = False
    texto: Optional[str] = None
    data_limite: Optional[datetime] = None
    dias: Optional[int] = None


class Citacao(BaseModel):
    """Citação de trecho relevante"""
    doc_id: str
    trecho: str
    relevancia: Optional[str] = None
    
    @field_validator('doc_id', mode='before')
    @classmethod
    def converter_doc_id(cls, v: Any) -> str:
        return str(v) if v is not None else ""


class ItemTriagem(BaseModel):
    """Resultado da triagem de um documento"""
    doc_id: str
    
    # Classificação semântica
    ato_semantico: AtoSemantico = AtoSemantico.OUTRO
    
    # Resumo
    assunto_curto: str = ""
    
    # Pedido e providência
    pedido_principal: Optional[str] = None
    providencia_solicitada: Optional[str] = None
    
    # Prazo
    prazo: Prazo = Field(default_factory=Prazo)
    
    # Resultado (se for decisão)
    resultado: Optional[ResultadoAto] = None
    
    # NOVO: Unidades de origem e destino
    unidade_origem: Optional[str] = None
    unidade_destino: Optional[str] = None
    
    # Citações relevantes
    citacoes: List[Citacao] = Field(default_factory=list)
    
    # Confiança do LLM na análise
    confianca: float = Field(default=0.8, ge=0.0, le=1.0)
    
    # Se está resolvido ou pendente
    status: str = "pendente"
    
    @field_validator('doc_id', mode='before')
    @classmethod
    def converter_doc_id(cls, v: Any) -> str:
        return str(v) if v is not None else ""


class TriageV1(BaseModel):
    """Schema triage.v1 - Resultado da Camada A"""
    schema_version: str = "triage.v1"
    nup: str
    
    itens: List[ItemTriagem] = Field(default_factory=list)
    
    modelo_usado: str = "claude-3-haiku"
    total_docs_analisados: int = 0
    tokens_usados: int = 0
    processado_em: Optional[datetime] = None


def criar_item_triagem(
    doc_id: str,
    ato: str = "OUTRO",
    assunto: str = "",
    **kwargs
) -> ItemTriagem:
    """Factory function para criar ItemTriagem"""
    try:
        ato_enum = AtoSemantico(ato.upper())
    except ValueError:
        ato_enum = AtoSemantico.OUTRO
    
    return ItemTriagem(
        doc_id=doc_id,
        ato_semantico=ato_enum,
        assunto_curto=assunto,
        **kwargs
    )


def criar_triage_v1(nup: str, modelo: str = "claude-3-haiku") -> TriageV1:
    """Factory function para criar TriageV1"""
    return TriageV1(
        nup=nup,
        modelo_usado=modelo,
        processado_em=datetime.now()
    )
