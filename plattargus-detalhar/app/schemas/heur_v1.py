"""
Schema heur_v1.py - Heurística, Score e Compressão

VERSÃO v1.2: Adicionado EstagioProcessual para ciclo de vida do processo

Ciclo de vida:
  ÂNCORA → FUNDAMENTO → DECISÃO → FORMALIZAÇÃO → ENCERRAMENTO
     ↑                                              |
     └──────────── (recurso = novo ciclo) ──────────┘

Este schema determina quais documentos são relevantes e por quê.
Usa regras determinísticas (sem LLM) para:
- Calcular score de relevância
- Comprimir cadeias repetitivas
- Selecionar top_docs para enviar ao LLM
- Garantir cobertura de todos os estágios
"""

from __future__ import annotations
from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field, field_validator
from enum import Enum


# =============================================================================
# ESTÁGIO PROCESSUAL - CICLO DE VIDA DO PROCESSO
# =============================================================================

class EstagioProcessual(str, Enum):
    """
    Estágio no ciclo de vida do processo.
    
    Todo processo segue este fluxo:
    1. ANCORA: O pedido inicial que origina o processo
    2. FUNDAMENTO: Análises técnicas que subsidiam a decisão
    3. DECISAO: O ato que resolve o pedido
    4. FORMALIZACAO: Publicação/registro oficial da decisão
    5. ENCERRAMENTO: Fechamento formal do processo/fase
    
    TRAMITE: Documentos de mero encaminhamento (sem novidade)
    """
    ANCORA = "ANCORA"           # Requerimento, Memorando, Ofício, Proposta
    FUNDAMENTO = "FUNDAMENTO"   # Parecer, Nota Técnica, Informação
    DECISAO = "DECISAO"         # Defiro, Indefiro, Autorizo, Decreto
    FORMALIZACAO = "FORMALIZACAO"  # Nota BG, Publicação
    ENCERRAMENTO = "ENCERRAMENTO"  # Termo de Encerramento, Arquive-se
    TRAMITE = "TRAMITE"         # Encaminhamentos sem novidade


# Mapeamento de tipo de documento para estágio
MAPA_TIPO_ESTAGIO: Dict[str, EstagioProcessual] = {
    # ÂNCORA - pedidos que iniciam
    "REQUERIMENTO": EstagioProcessual.ANCORA,
    "MEMORANDO": EstagioProcessual.ANCORA,
    "OFICIO": EstagioProcessual.ANCORA,
    "PROPOSTA": EstagioProcessual.ANCORA,
    "SOLICITACAO": EstagioProcessual.ANCORA,
    
    # FUNDAMENTO - análises técnicas
    "PARECER": EstagioProcessual.FUNDAMENTO,
    "NOTA_TECNICA": EstagioProcessual.FUNDAMENTO,
    "INFORMACAO": EstagioProcessual.FUNDAMENTO,
    
    # DECISÃO - atos decisórios
    "DECISAO": EstagioProcessual.DECISAO,
    "DECRETO": EstagioProcessual.DECISAO,
    "PORTARIA": EstagioProcessual.DECISAO,
    
    # FORMALIZAÇÃO - publicação
    "NOTA_BG": EstagioProcessual.FORMALIZACAO,
    "PUBLICACAO": EstagioProcessual.FORMALIZACAO,
    
    # ENCERRAMENTO
    "TERMO_ENCERRAMENTO": EstagioProcessual.ENCERRAMENTO,
}


# =============================================================================
# TIPOS E SINAIS (mantidos para compatibilidade)
# =============================================================================

class TipoAto(str, Enum):
    """Classificação do ato no documento (legado, mantido para compatibilidade)"""
    ATO_DECISAO = "ATO_DECISAO"
    ATO_COMANDO = "ATO_COMANDO"
    ATO_PEDIDO = "ATO_PEDIDO"
    ATO_FUNDAMENTACAO = "ATO_FUNDAMENTACAO"
    ATO_TRAMITE = "ATO_TRAMITE"
    ATO_INFORMATIVO = "ATO_INFORMATIVO"
    ATO_RECURSO = "ATO_RECURSO"
    ATO_ENCERRAMENTO = "ATO_ENCERRAMENTO"


class Sinal(str, Enum):
    """Sinais detectados no documento"""
    TEM_PRAZO = "TEM_PRAZO"
    TEM_RECURSO = "TEM_RECURSO"
    MUDA_DESTINO = "MUDA_DESTINO"
    REPETITIVO = "REPETITIVO"
    DECISAO_FINAL = "DECISAO_FINAL"
    URGENTE = "URGENTE"
    ARQUIVAMENTO = "ARQUIVAMENTO"


# =============================================================================
# PARÂMETROS DA HEURÍSTICA
# =============================================================================

class ParametrosHeuristica(BaseModel):
    """Parâmetros configuráveis da heurística"""
    top_k: int = 12
    bonus_recencia_top3: int = 25
    bonus_recencia_top10: int = 15
    
    # Pesos por estágio processual (NOVO)
    pesos_estagio: Dict[str, int] = Field(default_factory=lambda: {
        "ANCORA": 70,         # Pedido inicial é importante
        "FUNDAMENTO": 50,     # Pareceres têm peso médio
        "DECISAO": 90,        # Decisões têm peso alto
        "FORMALIZACAO": 40,   # Publicação tem peso médio
        "ENCERRAMENTO": 95,   # Encerramento é crucial
        "TRAMITE": 10,        # Trâmite tem peso baixo
    })
    
    # Pesos por tipo de ato (legado, mantido)
    pesos: Dict[str, int] = Field(default_factory=lambda: {
        "ATO_DECISAO": 80,
        "ATO_COMANDO": 60,
        "ATO_PEDIDO": 50,
        "ATO_FUNDAMENTACAO": 40,
        "ATO_RECURSO": 45,
        "ATO_TRAMITE": 10,
        "ATO_INFORMATIVO": 5,
        "ATO_ENCERRAMENTO": 90,
        # Sinais adicionais
        "TEM_PRAZO": 20,
        "TEM_RECURSO": 25,
        "MUDA_DESTINO": 15,
        "DECISAO_FINAL": 30,
        "URGENTE": 20,
        "ARQUIVAMENTO": 10,
        # Novas tags v1.1
        "TEM_DECRETO": 100,
        "TEM_ENCERRAMENTO": 90,
        "TEM_FAVORAVEL": 70,
        "TEM_APRESENTACAO": 60,
        "TEM_AGREGACAO": 50,
        "TEM_CESSAO": 50,
        "TEM_LOTACAO": 40,
        "ORGAO_EXTERNO": 30,
    })


# =============================================================================
# SCORE POR DOCUMENTO
# =============================================================================

class DocScore(BaseModel):
    """Score e análise de um documento"""
    doc_id: str
    tipo_documento: str
    data_ref_doc: Optional[datetime] = None
    
    # Estágio processual (NOVO v1.2)
    estagio: EstagioProcessual = EstagioProcessual.TRAMITE
    
    # Classificação (legado)
    ato: TipoAto = TipoAto.ATO_INFORMATIVO
    sinais: List[Sinal] = Field(default_factory=list)
    
    # Score
    score: int = 0
    motivos: List[str] = Field(default_factory=list)
    
    # Compressão
    grupo_compressao: Optional[str] = None
    compressao: Dict[str, Any] = Field(default_factory=lambda: {
        "descartado": False,
        "motivo": None
    })
    
    @field_validator('doc_id', mode='before')
    @classmethod
    def converter_doc_id(cls, v: Any) -> str:
        return str(v) if v is not None else ""


# =============================================================================
# COMPRESSÃO
# =============================================================================

class GrupoCompressao(BaseModel):
    """Grupo de documentos comprimidos"""
    grupo_id: str
    regra: str
    docs_descartados: List[str] = Field(default_factory=list)
    docs_mantidos: List[str] = Field(default_factory=list)
    justificativa: str = ""


class Compressao(BaseModel):
    """Resultado da compressão"""
    grupos: List[GrupoCompressao] = Field(default_factory=list)
    total_descartados: int = 0
    total_mantidos: int = 0


# =============================================================================
# SELEÇÃO TOP-K
# =============================================================================

class TopDoc(BaseModel):
    """Documento selecionado para o top-k"""
    doc_id: str
    motivos: List[str] = Field(default_factory=list)
    score: int = 0
    estagio: Optional[EstagioProcessual] = None  # NOVO v1.2
    
    @field_validator('doc_id', mode='before')
    @classmethod
    def converter_doc_id(cls, v: Any) -> str:
        return str(v) if v is not None else ""


# =============================================================================
# COBERTURA OBRIGATÓRIA
# =============================================================================

class CoberturaObrigatoria(BaseModel):
    """
    Documentos que devem sempre ser incluídos.
    
    NOVO v1.2: Cobertura por estágio processual
    """
    # Por estágio (NOVO)
    ultimo_ancora: Optional[str] = None      # Último pedido/requerimento
    ultimo_fundamento: Optional[str] = None  # Último parecer/nota técnica
    ultimo_decisao: Optional[str] = None     # Última decisão
    ultimo_formalizacao: Optional[str] = None  # Última publicação
    ultimo_encerramento: Optional[str] = None  # Último encerramento
    
    # Legado (mantido para compatibilidade)
    ultimo_decisorio: Optional[str] = None
    ultimo_pedido: Optional[str] = None
    ultimo_parecer: Optional[str] = None
    ultimo_recurso: Optional[str] = None
    ultimos_3_recentes: List[str] = Field(default_factory=list)
    docs_com_prazo: List[str] = Field(default_factory=list)
    
    # Todos de cada tipo crítico
    todos_decretos: List[str] = Field(default_factory=list)
    todos_encerramentos: List[str] = Field(default_factory=list)


# =============================================================================
# CICLO PROCESSUAL (NOVO v1.2)
# =============================================================================

class CicloProcessual(BaseModel):
    """
    Representa um ciclo completo do processo.
    
    Um processo pode ter múltiplos ciclos:
    - Ciclo 1: Pedido inicial → Decisão → Encerramento
    - Ciclo 2: Recurso → Nova Decisão → Novo Encerramento
    """
    numero: int = 1
    ancora_doc_id: Optional[str] = None
    fundamento_doc_ids: List[str] = Field(default_factory=list)
    decisao_doc_id: Optional[str] = None
    formalizacao_doc_id: Optional[str] = None
    encerramento_doc_id: Optional[str] = None
    
    # Status do ciclo
    completo: bool = False  # True se tem ÂNCORA + DECISÃO + ENCERRAMENTO
    status: str = "EM_ANDAMENTO"  # EM_ANDAMENTO, DEFERIDO, INDEFERIDO, ENCERRADO
    
    @field_validator('ancora_doc_id', 'decisao_doc_id', 'formalizacao_doc_id', 'encerramento_doc_id', mode='before')
    @classmethod
    def converter_doc_id(cls, v: Any) -> Optional[str]:
        if v is None:
            return None
        return str(v)


# =============================================================================
# SCHEMA PRINCIPAL
# =============================================================================

class HeurV1(BaseModel):
    """
    Schema heur.v1 - Heurística e Score
    
    VERSÃO v1.2: Inclui estágios processuais e ciclos
    """
    schema_version: str = "heur.v1.2"
    nup: str
    
    # Parâmetros usados
    parametros: ParametrosHeuristica = Field(default_factory=ParametrosHeuristica)
    
    # Score por documento
    docs: List[DocScore] = Field(default_factory=list)
    
    # Compressão
    compressao: Compressao = Field(default_factory=Compressao)
    
    # Seleção final
    top_docs: List[TopDoc] = Field(default_factory=list)
    
    # Cobertura obrigatória
    cobertura_obrigatoria: CoberturaObrigatoria = Field(default_factory=CoberturaObrigatoria)
    
    # Ciclos processuais (NOVO v1.2)
    ciclos: List[CicloProcessual] = Field(default_factory=list)
    ciclo_atual: int = 1  # Número do ciclo em andamento
    
    # Metadados
    total_docs_original: int = 0
    total_docs_filtrados: int = 0
    processado_em: Optional[datetime] = None


# =============================================================================
# FUNÇÕES AUXILIARES
# =============================================================================

def criar_heur_v1(nup: str, parametros: Optional[ParametrosHeuristica] = None) -> HeurV1:
    """Factory function para criar HeurV1"""
    return HeurV1(
        nup=nup,
        parametros=parametros or ParametrosHeuristica(),
        processado_em=datetime.now()
    )


def classificar_estagio(
    tipo_documento: str,
    tags_tecnicas: List[str],
    is_decreto: bool = False,
    is_encerramento: bool = False,
    is_decisorio: bool = False,
    is_pedido: bool = False
) -> EstagioProcessual:
    """
    Classifica o estágio processual de um documento.
    
    Prioridade:
    1. Tags específicas (ENCERRAMENTO, DECRETO)
    2. Flags do documento (is_*)
    3. Tipo de documento
    4. Fallback: TRAMITE
    """
    # 1. Encerramento tem prioridade máxima
    if is_encerramento or "TEM_ENCERRAMENTO" in tags_tecnicas:
        return EstagioProcessual.ENCERRAMENTO
    
    if "TEM_ARQUIVAMENTO" in tags_tecnicas:
        return EstagioProcessual.ENCERRAMENTO
    
    # 2. Decisão (inclui Decreto)
    if is_decreto or "TEM_DECRETO" in tags_tecnicas:
        return EstagioProcessual.DECISAO
    
    if is_decisorio or "TEM_DECISAO" in tags_tecnicas:
        return EstagioProcessual.DECISAO
    
    if "TEM_DEFERIMENTO" in tags_tecnicas or "TEM_INDEFERIMENTO" in tags_tecnicas:
        return EstagioProcessual.DECISAO
    
    if "TEM_FAVORAVEL" in tags_tecnicas:
        return EstagioProcessual.DECISAO
    
    # 3. Publicação/Formalização
    if "TEM_PUBLICACAO" in tags_tecnicas:
        return EstagioProcessual.FORMALIZACAO
    
    # 4. Âncora (pedido)
    if is_pedido:
        return EstagioProcessual.ANCORA
    
    if "TEM_RECURSO" in tags_tecnicas:
        return EstagioProcessual.ANCORA  # Recurso é um novo pedido
    
    # 5. Por tipo de documento
    tipo_upper = tipo_documento.upper() if tipo_documento else ""
    
    if tipo_upper in MAPA_TIPO_ESTAGIO:
        return MAPA_TIPO_ESTAGIO[tipo_upper]
    
    # Busca parcial
    for tipo_key, estagio in MAPA_TIPO_ESTAGIO.items():
        if tipo_key in tipo_upper:
            return estagio
    
    # 6. Comando/Encaminhamento = TRÂMITE
    if "TEM_COMANDO" in tags_tecnicas or "MUDA_DESTINO" in tags_tecnicas:
        return EstagioProcessual.TRAMITE
    
    # 7. Fallback
    return EstagioProcessual.TRAMITE


def identificar_ciclos(docs_scores: List[DocScore]) -> List[CicloProcessual]:
    """
    Identifica ciclos processuais nos documentos.
    
    Um ciclo começa com ÂNCORA e termina com ENCERRAMENTO.
    Se há ENCERRAMENTO seguido de nova ÂNCORA, é novo ciclo.
    """
    if not docs_scores:
        return []
    
    # Ordenar por data (mais antigo primeiro)
    docs_ordenados = sorted(
        docs_scores,
        key=lambda d: d.data_ref_doc or datetime.min
    )
    
    ciclos = []
    ciclo_atual = CicloProcessual(numero=1)
    
    for doc in docs_ordenados:
        estagio = doc.estagio
        
        if estagio == EstagioProcessual.ANCORA:
            # Se já temos uma âncora e o ciclo anterior foi encerrado, começa novo
            if ciclo_atual.ancora_doc_id and ciclo_atual.encerramento_doc_id:
                ciclos.append(ciclo_atual)
                ciclo_atual = CicloProcessual(numero=len(ciclos) + 1)
            
            if not ciclo_atual.ancora_doc_id:
                ciclo_atual.ancora_doc_id = doc.doc_id
        
        elif estagio == EstagioProcessual.FUNDAMENTO:
            ciclo_atual.fundamento_doc_ids.append(doc.doc_id)
        
        elif estagio == EstagioProcessual.DECISAO:
            ciclo_atual.decisao_doc_id = doc.doc_id
            # Verificar se é deferimento ou indeferimento
            if Sinal.DECISAO_FINAL in doc.sinais:
                if "DEFERIDO" in " ".join(doc.motivos).upper():
                    ciclo_atual.status = "DEFERIDO"
                elif "INDEFERIDO" in " ".join(doc.motivos).upper():
                    ciclo_atual.status = "INDEFERIDO"
        
        elif estagio == EstagioProcessual.FORMALIZACAO:
            ciclo_atual.formalizacao_doc_id = doc.doc_id
        
        elif estagio == EstagioProcessual.ENCERRAMENTO:
            ciclo_atual.encerramento_doc_id = doc.doc_id
            ciclo_atual.status = "ENCERRADO"
            ciclo_atual.completo = bool(
                ciclo_atual.ancora_doc_id and 
                ciclo_atual.decisao_doc_id
            )
    
    # Adicionar último ciclo
    if ciclo_atual.ancora_doc_id or ciclo_atual.decisao_doc_id:
        ciclos.append(ciclo_atual)
    
    return ciclos
