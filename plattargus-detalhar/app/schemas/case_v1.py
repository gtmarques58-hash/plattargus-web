"""
Schema case.v1 - Camada B (Consolidação)

Este schema representa a consolidação feita pelo LLM:
- Situação atual do processo
- Pedido vigente (não o antigo já resolvido!)
- Último comando
- Timeline
- Pendências abertas e encerradas
- Fluxo de tramitação (demandante, executora, resposta)
"""

from __future__ import annotations
from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field, field_validator
from enum import Enum


class SituacaoAtual(str, Enum):
    """Status consolidado do processo"""
    AGUARDANDO_ANALISE = "AGUARDANDO ANÁLISE"
    EM_TRAMITACAO = "EM TRAMITAÇÃO"
    AGUARDANDO_MANIFESTACAO = "AGUARDANDO MANIFESTAÇÃO"
    RECURSO_EM_ANALISE = "RECURSO EM ANÁLISE"
    DEFERIDO = "DEFERIDO"
    INDEFERIDO = "INDEFERIDO"
    ARQUIVADO = "ARQUIVADO"
    CONCLUIDO = "CONCLUÍDO"
    PENDENTE_PUBLICACAO = "PENDENTE PUBLICAÇÃO"
    AGUARDANDO_PRAZO = "AGUARDANDO PRAZO"
    OUTRO = "OUTRO"


class PedidoVigente(BaseModel):
    """O pedido atual (não o antigo já resolvido)"""
    descricao: str
    doc_id_origem: str
    data_pedido: Optional[datetime] = None
    urgente: bool = False
    
    @field_validator('doc_id_origem', mode='before')
    @classmethod
    def converter_doc_id(cls, v: Any) -> str:
        """Converte int para str se necessário"""
        return str(v) if v is not None else ""


class UltimoComando(BaseModel):
    """Última determinação/comando no processo"""
    descricao: str
    doc_id: str
    prazo: Optional[str] = None
    data_limite: Optional[datetime] = None
    destino: Optional[str] = None
    
    @field_validator('doc_id', mode='before')
    @classmethod
    def converter_doc_id(cls, v: Any) -> str:
        """Converte int para str se necessário"""
        return str(v) if v is not None else ""


class Pendencia(BaseModel):
    """Uma pendência (aberta ou encerrada)"""
    descricao: str
    doc_id: str
    prazo: Optional[str] = None
    data_limite: Optional[datetime] = None
    responsavel: Optional[str] = None
    
    @field_validator('doc_id', mode='before')
    @classmethod
    def converter_doc_id(cls, v: Any) -> str:
        return str(v) if v is not None else ""


class EventoTimeline(BaseModel):
    """Evento na linha do tempo"""
    data_ref_doc: Optional[datetime] = None
    doc_id: str
    evento: str
    tipo: Optional[str] = None
    unidade: Optional[str] = None  # NOVO: unidade do evento
    
    @field_validator('doc_id', mode='before')
    @classmethod
    def converter_doc_id(cls, v: Any) -> str:
        return str(v) if v is not None else ""


class CitacaoBase(BaseModel):
    """Citação de base para as conclusões"""
    doc_id: str
    trecho: str
    
    @field_validator('doc_id', mode='before')
    @classmethod
    def converter_doc_id(cls, v: Any) -> str:
        return str(v) if v is not None else ""


class FluxoTramitacao(BaseModel):
    """Fluxo de tramitação do processo"""
    demandante: Optional[str] = None  # Unidade que originou
    executora: Optional[str] = None   # Unidade que deve executar
    resposta: Optional[str] = None    # Unidade que recebe resposta
    caminho: List[str] = Field(default_factory=list)  # Ex: ["COI", "CMDGER", "DRH"]


class CaseV1(BaseModel):
    """
    Schema case.v1 - Resultado da Camada B (Consolidação)
    """
    schema_version: str = "case.v1"
    nup: str
    
    # Situação consolidada
    situacao_atual: SituacaoAtual = SituacaoAtual.OUTRO
    situacao_descricao: str = ""
    
    # Pedido VIGENTE (não o antigo já resolvido)
    pedido_vigente: Optional[PedidoVigente] = None
    
    # Último comando/determinação
    ultimo_comando: Optional[UltimoComando] = None
    
    # NOVO: Fluxo de tramitação
    fluxo_tramitacao: Optional[FluxoTramitacao] = None
    
    # Pendências
    pendencias_abertas: List[Pendencia] = Field(default_factory=list)
    pendencias_encerradas: List[Pendencia] = Field(default_factory=list)
    
    # Timeline (mais recente primeiro)
    timeline: List[EventoTimeline] = Field(default_factory=list)
    
    # Documentos mais relevantes
    docs_relevantes: List[str] = Field(default_factory=list)
    
    # Alertas importantes
    alertas: List[str] = Field(default_factory=list)
    
    # Base citada
    base_citada: List[CitacaoBase] = Field(default_factory=list)
    
    # Metadados
    modelo_usado: str = "claude-3-haiku"
    confianca: float = Field(default=0.8, ge=0.0, le=1.0)
    processado_em: Optional[datetime] = None


def criar_case_v1(nup: str, modelo: str = "claude-3-haiku") -> CaseV1:
    """Factory function para criar CaseV1"""
    return CaseV1(
        nup=nup,
        modelo_usado=modelo,
        processado_em=datetime.now()
    )


def criar_pendencia(descricao: str, doc_id: str, prazo: Optional[str] = None) -> Pendencia:
    """Factory function para criar Pendência"""
    return Pendencia(
        descricao=descricao,
        doc_id=doc_id,
        prazo=prazo
    )
