"""
Schema doc.v1 - Documento Enriquecido

Representa um documento do SEI com metadados ricos extraídos:
- Identificação e posição na árvore
- Autor, assinaturas e status
- Datas normalizadas
- Referências entre documentos
- Tags técnicas (determinísticas)

CORREÇÃO v1.1: Adicionadas novas TagTecnica para encerramento, decreto, etc.
               Adicionados campos para unidade_origem corrigida
"""

from __future__ import annotations
from typing import Optional, List, Any
from datetime import datetime
from pydantic import BaseModel, Field, field_validator
from enum import Enum
import hashlib


class TipoDocumento(str, Enum):
    """Tipos de documento do SEI"""
    DESPACHO = "DESPACHO"
    REQUERIMENTO = "REQUERIMENTO"
    MEMORANDO = "MEMORANDO"
    OFICIO = "OFICIO"
    INFORMACAO = "INFORMACAO"
    PARECER = "PARECER"
    NOTA_TECNICA = "NOTA_TECNICA"
    DECISAO = "DECISAO"
    TERMO_ENCERRAMENTO = "TERMO_ENCERRAMENTO"
    ANEXO = "ANEXO"
    NOTA_BG = "NOTA_BG"
    PORTARIA = "PORTARIA"
    ATA = "ATA"
    CERTIDAO = "CERTIDAO"
    DECRETO = "DECRETO"  # NOVO
    OUTROS = "OUTROS"


class SituacaoDocumento(str, Enum):
    """Status do documento no SEI"""
    ASSINADO = "ASSINADO"
    MINUTA = "MINUTA"
    CANCELADO = "CANCELADO"
    JUNTADO = "JUNTADO"
    RASCUNHO = "RASCUNHO"
    DESCONHECIDO = "DESCONHECIDO"


class MetodoExtracao(str, Enum):
    """Método usado para extrair o texto"""
    VIEWER_HTML = "viewer_html"
    PDF_TEXT = "pdf_text"
    OCR = "ocr"
    MIXED = "mixed"


class TagTecnica(str, Enum):
    """Tags técnicas detectadas por regex (determinísticas)"""
    # Tags existentes
    TEM_COMANDO = "TEM_COMANDO"              # DETERMINO, ENCAMINHE-SE, RETORNE-SE, CUMPRA-SE
    TEM_DECISAO = "TEM_DECISAO"              # AUTORIZO, DEFIRO, INDEFIRO, ARQUIVE-SE
    TEM_PRAZO = "TEM_PRAZO"                  # "no prazo", "em X dias", "até dd/mm"
    TEM_RECURSO = "TEM_RECURSO"              # recurso, reconsideração, retificação
    MUDA_DESTINO = "MUDA_DESTINO"            # mudou unidade destino
    REPETITIVO = "REPETITIVO"                # encaminhamento sem novidade
    TEM_DEFERIMENTO = "TEM_DEFERIMENTO"      # DEFERIDO, AUTORIZADO
    TEM_INDEFERIMENTO = "TEM_INDEFERIMENTO"  # INDEFERIDO, NEGADO
    TEM_ARQUIVAMENTO = "TEM_ARQUIVAMENTO"    # ARQUIVE-SE, arquivamento
    TEM_PUBLICACAO = "TEM_PUBLICACAO"        # publicar, publicação, BG
    
    # NOVAS TAGS - Correção v1.1
    TEM_ENCERRAMENTO = "TEM_ENCERRAMENTO"    # Termo de Encerramento
    TEM_DECRETO = "TEM_DECRETO"              # Decreto do Governador
    TEM_AGREGACAO = "TEM_AGREGACAO"          # Agregação de militar
    TEM_CESSAO = "TEM_CESSAO"                # Cessão/Disposição de militar
    TEM_FAVORAVEL = "TEM_FAVORAVEL"          # Manifestação favorável
    TEM_APRESENTACAO = "TEM_APRESENTACAO"    # Apresentação de militar
    TEM_LOTACAO = "TEM_LOTACAO"              # Lotação/Movimentação
    ORGAO_EXTERNO = "ORGAO_EXTERNO"          # Documento de órgão externo (TJAC, Casa Civil, SEAD)


class Autor(BaseModel):
    """Autor/assinante do documento"""
    nome: str
    unidade: Optional[str] = None
    cargo: Optional[str] = None


class Assinatura(BaseModel):
    """Assinatura coletada do documento"""
    nome: str
    cargo: Optional[str] = None
    unidade: Optional[str] = None
    datahora: Optional[datetime] = None
    datahora_raw: Optional[str] = None


class Referencias(BaseModel):
    """Referências a outros documentos"""
    responde_a: Optional[str] = None           # doc_id que este responde
    menciona_docs: List[str] = Field(default_factory=list)  # doc_ids mencionados
    encaminha_para: List[str] = Field(default_factory=list) # siglas/unidades destino


class InfoExtracao(BaseModel):
    """Informações sobre a extração"""
    metodo: MetodoExtracao = MetodoExtracao.VIEWER_HTML
    confianca: float = Field(default=1.0, ge=0.0, le=1.0)
    duracao_ms: int = 0
    erros: List[str] = Field(default_factory=list)


class DocV1(BaseModel):
    """
    Schema doc.v1 - Documento Enriquecido
    
    Representa um documento do SEI com todos os metadados
    necessários para o pipeline de análise.
    """
    schema_version: str = "doc.v1"
    
    # Identificação
    nup: str
    doc_id: str
    numero_sei: str  # mantido por compatibilidade
    
    # Tipo e posição
    tipo_documento: TipoDocumento = TipoDocumento.OUTROS
    tipo_documento_raw: Optional[str] = None  # texto original do SEI
    titulo_arvore: Optional[str] = None
    ordem_arvore: int = 0
    tree_path: List[str] = Field(default_factory=list)
    
    # Unidade de origem - CAMPOS ORIGINAIS (podem estar errados!)
    unidade_origem: Optional[str] = None      # Valor original do SEI (pode estar errado)
    sigla_origem: Optional[str] = None        # Valor original do SEI (pode estar errado)
    
    # Unidade de origem - CAMPOS CORRIGIDOS (extraídos do conteúdo)
    unidade_origem_real: Optional[str] = None      # Sigla corrigida (ex: "CASACIVIL", "TJAC")
    unidade_origem_detalhe: Optional[str] = None   # Subdivisão (ex: "GABIN", "DEVIDA")
    unidade_origem_completa: Optional[str] = None  # Formato completo (ex: "CASACIVIL - GABIN")
    metodo_extracao_unidade: Optional[str] = None  # Como foi extraída a unidade
    
    # Classificação semântica do documento
    tipo_semantico: Optional[str] = None      # PEDIDO, DECISAO, ENCAMINHAMENTO, ENCERRAMENTO
    is_decisorio: bool = False                # Se é documento de decisão
    is_encerramento: bool = False             # Se é termo de encerramento
    is_decreto: bool = False                  # Se é decreto
    is_pedido: bool = False                   # Se é pedido/solicitação
    is_favoravel: Optional[bool] = None       # Se manifestação é favorável (True/False/None)
    is_orgao_externo: bool = False            # Se é de órgão externo ao CBMAC
    
    # Autor e status
    autor: Optional[Autor] = None
    situacao_documento: SituacaoDocumento = SituacaoDocumento.DESCONHECIDO
    assinaturas: List[Assinatura] = Field(default_factory=list)
    
    # Datas
    data_inclusao: Optional[datetime] = None
    data_inclusao_raw: Optional[str] = None
    data_ref_doc: Optional[datetime] = None  # assinatura mais recente ou criação
    
    # Referências
    referencias: Referencias = Field(default_factory=Referencias)
    
    # Texto
    texto_raw: str = ""
    texto_limpo: str = ""
    hash_texto: str = ""
    
    # Extração
    extracao: InfoExtracao = Field(default_factory=InfoExtracao)
    
    # Tags técnicas (determinísticas)
    tags_tecnicas: List[TagTecnica] = Field(default_factory=list)
    
    # Campos extras para compatibilidade
    paginas: int = 0
    tamanho_bytes: int = 0
    
    @field_validator('doc_id', 'numero_sei', mode='before')
    @classmethod
    def converter_doc_id(cls, v: Any) -> str:
        return str(v) if v is not None else ""
    
    def calcular_hash(self) -> str:
        """Calcula hash SHA1 do texto limpo"""
        return hashlib.sha1(self.texto_limpo.encode('utf-8')).hexdigest()
    
    def atualizar_hash(self):
        """Atualiza o hash_texto"""
        self.hash_texto = self.calcular_hash()
    
    def definir_data_ref(self):
        """
        Define data_ref_doc seguindo a regra:
        - Se há assinaturas: max(assinaturas[].datahora)
        - Senão: data_inclusao
        """
        if self.assinaturas:
            datas = [a.datahora for a in self.assinaturas if a.datahora]
            if datas:
                self.data_ref_doc = max(datas)
                return
        self.data_ref_doc = self.data_inclusao
    
    def get_sigla_efetiva(self) -> Optional[str]:
        """
        Retorna a sigla efetiva do documento.
        Prioriza unidade_origem_real (corrigida) sobre sigla_origem (original).
        """
        return self.unidade_origem_real or self.sigla_origem


# Funções auxiliares para criação

def criar_doc_v1(
    nup: str,
    doc_id: str,
    texto: str,
    tipo: str = "OUTROS",
    ordem: int = 0,
    **kwargs
) -> DocV1:
    """
    Factory function para criar DocV1 a partir de dados básicos
    """
    doc = DocV1(
        nup=nup,
        doc_id=doc_id,
        numero_sei=doc_id,
        texto_raw=texto,
        texto_limpo=texto.strip(),
        ordem_arvore=ordem,
        **kwargs
    )
    
    # Tentar mapear tipo
    try:
        doc.tipo_documento = TipoDocumento(tipo.upper())
    except ValueError:
        doc.tipo_documento = TipoDocumento.OUTROS
        doc.tipo_documento_raw = tipo
    
    doc.atualizar_hash()
    doc.definir_data_ref()
    
    return doc
