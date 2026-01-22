"""
Prompts para LLMs Estagiários

NOTA: Os estagiários A e B agora têm prompts próprios nos arquivos:
- estagiario_a.py (GPT-4o-mini)
- estagiario_b.py (GPT-4.1-mini)

Este arquivo mantém templates e funções auxiliares.
"""

# =============================================================================
# TEMPLATES DE EXTRAÇÃO
# =============================================================================

TEMPLATE_RESPOSTA_TRIAGEM = {
    "doc_id": "",
    "ato_semantico": "ENCAMINHAMENTO",
    "assunto_curto": "",
    "pedido_principal": None,
    "providencia_solicitada": None,
    "prazo": {"existe": False, "texto": None},
    "resultado": None,
    "unidade_origem": None,
    "unidade_destino": None,
    "citacoes": [],
    "status": "pendente",
    "confianca": 0.5
}

TEMPLATE_RESPOSTA_CONSOLIDACAO = {
    "situacao_atual": "EM TRAMITACAO",
    "situacao_descricao": "",
    "pedido_vigente": None,
    "ultimo_comando": None,
    "fluxo_tramitacao": {
        "demandante": None,
        "executora": None,
        "resposta": None,
        "caminho": []
    },
    "pendencias_abertas": [],
    "pendencias_encerradas": [],
    "timeline": [],
    "docs_relevantes": [],
    "alertas": [],
    "base_citada": []
}

# =============================================================================
# SIGLAS E HIERARQUIA
# =============================================================================

SIGLAS_CBMAC = {
    "CMDGER": "Comando Geral",
    "SUBCMD": "Subcomando Geral",
    "DRH": "Diretoria de Recursos Humanos",
    "COI": "Comando Operacional do Interior",
    "COC": "Comando Operacional da Capital",
    "DAL": "Diretoria de Apoio Logístico",
    "DEI": "Diretoria de Ensino e Instrução",
    "DPLAN": "Diretoria de Planejamento",
    "DS": "Diretoria de Saúde",
    "1BEPCIF": "1º Batalhão",
    "2BEPCIF": "2º Batalhão",
    "3BEPCIF": "3º Batalhão",
    "4BEPCIF": "4º Batalhão",
    "5BEPCIF": "5º Batalhão",
    "6BEPCIF": "6º Batalhão",
    "7BEPCIF": "7º Batalhão",
    "8BEPCIF": "8º Batalhão",
    "9BEPCIF": "9º Batalhão",
}

ORGAOS_EXTERNOS = {
    "TJAC": "Tribunal de Justiça do Estado do Acre",
    "ASMIL": "Assessoria Militar do TJAC",
    "CASACIVIL": "Casa Civil do Governo do Estado",
    "SEAD": "Secretaria de Estado de Administração",
    "DEVIDA": "Departamento de Vida Funcional (SEAD)",
    "DIRGEP": "Diretoria de Gestão de Pessoas (SEAD)",
    "GOVERNADOR": "Governador do Estado do Acre",
}

# Batalhões da Capital -> COC
BATALHOES_CAPITAL = ["1BEPCIF", "2BEPCIF", "3BEPCIF"]

# Batalhões do Interior -> COI
BATALHOES_INTERIOR = ["4BEPCIF", "5BEPCIF", "6BEPCIF", "7BEPCIF", "8BEPCIF", "9BEPCIF"]

# Diretorias -> CMDGER/SUBCMD
DIRETORIAS = ["DRH", "COI", "COC", "DAL", "DEI", "DPLAN", "DS"]

# =============================================================================
# SITUAÇÕES VÁLIDAS (sem OUTRO!)
# =============================================================================

SITUACOES_VALIDAS = [
    "AGUARDANDO ANALISE",      # Processo novo, sem manifestação
    "EM TRAMITACAO",           # Passando entre unidades
    "AGUARDANDO MANIFESTACAO", # Aguardando parecer/manifestação
    "RECURSO EM ANALISE",      # Recurso interposto
    "DEFERIDO",                # Aprovado
    "INDEFERIDO",              # Negado
    "ARQUIVADO",               # Encerrado
    "CONCLUIDO",               # Finalizado
    "PENDENTE PUBLICACAO",     # Deferido, aguarda publicação no BG
]

# =============================================================================
# FUNÇÕES AUXILIARES (compatibilidade)
# =============================================================================

def formatar_doc_para_triagem(doc) -> str:
    """
    Formata documento para prompt de triagem.
    NOTA: Usado pelo fallback, LLM usa prompt próprio.
    """
    unidade = getattr(doc, 'unidade_origem_real', None) or getattr(doc, 'sigla_origem', 'N/A')
    
    return f"""
DOCUMENTO:
- ID: {doc.doc_id}
- Tipo: {doc.tipo_documento.value if doc.tipo_documento else 'OUTROS'}
- Origem: {unidade}
- Título: {doc.titulo_arvore or 'N/A'}

TEXTO:
{doc.texto_limpo[:3000] if doc.texto_limpo else 'N/A'}
"""


def formatar_docs_para_consolidacao(triagens: list, cobertura: dict = None) -> str:
    """
    Formata triagens para prompt de consolidação.
    NOTA: Usado pelo fallback, LLM usa prompt próprio.
    """
    docs_str = ""
    for item in triagens:
        unidade = getattr(item, 'unidade_origem', 'N/A')
        destino = getattr(item, 'unidade_destino', 'N/A')
        resultado = item.resultado.value if item.resultado else 'N/A'
        
        docs_str += f"""
---
DOC_ID: {item.doc_id}
ORIGEM: {unidade}
DESTINO: {destino}
ATO: {item.ato_semantico.value}
ASSUNTO: {item.assunto_curto}
RESULTADO: {resultado}
STATUS: {item.status}
"""
    return docs_str
