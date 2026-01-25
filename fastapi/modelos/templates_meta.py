"""
templates_meta.py - Metadados dos templates de documentos do CBMAC

Este arquivo fica em /app/scripts dentro do container sei-runner.
Os templates ficam em /app/modelos/{tipo}/*.txt

Estrutura de pastas:
/app/modelos/
+-- memorandos/
+-- oficios/
+-- requerimentos/
+-- despachos/
+-- notas/
+-- termos/
+-- portarias/
"""

from pathlib import Path

# BASE_DIR = /app/scripts
BASE_DIR = Path(__file__).resolve().parent

# MODELOS_DIR = /app/modelos
MODELOS_DIR = BASE_DIR.parent / "modelos"


TEMPLATES_META = {
    # ==========================================================================
    # MEMORANDOS
    # ==========================================================================
    "MEMO_GENERICO": {
        "arquivo_path": MODELOS_DIR / "memorandos" / "MEMO_GENERICO.txt",
        "tipo_sei": "Memorando",
        "descricao": "Memorando gen�rico para qualquer finalidade",
        "campos": [
            "NOME_DESTINATARIO", "POSTO_GRAD_DESTINATARIO", "CARGO_DESTINATARIO",
            "VOCATIVO", "TEXTO_CORPO", "NOME_REMETENTE", "POSTO_GRAD_REMETENTE",
            "CARGO_REMETENTE", "NUMERO_PORTARIA"
        ],
    },
    "MEMO_ENCAMINHAMENTO": {
        "arquivo_path": MODELOS_DIR / "memorandos" / "MEMO_ENCAMINHAMENTO.txt",
        "tipo_sei": "Memorando",
        "descricao": "Memorando para encaminhamento de documentos",
        "campos": [
            "NOME_DESTINATARIO", "POSTO_GRAD_DESTINATARIO", "CARGO_DESTINATARIO",
            "VOCATIVO", "MOTIVO_ENCAMINHAMENTO", "NOME_REMETENTE", 
            "POSTO_GRAD_REMETENTE", "CARGO_REMETENTE", "NUMERO_PORTARIA"
        ],
    },
    "MEMO_TAF_DEI": {
        "arquivo_path": MODELOS_DIR / "memorandos" / "MEMO_TAF_DEI.txt",
        "tipo_sei": "Memorando",
        "descricao": "Memorando para DEI sobre TAF (condi��o cl�nica, isen��o)",
        "campos": [
            "NOME_DESTINATARIO", "POSTO_GRAD_DESTINATARIO", "CARGO_DESTINATARIO",
            "ASSUNTO", "VOCATIVO", "POSTO_MILITAR", "NOME_MILITAR", "SEMESTRE",
            "ANO", "MOTIVO_IMPEDIMENTO", "NOME_REMETENTE", "POSTO_GRAD_REMETENTE",
            "CARGO_REMETENTE", "NUMERO_PORTARIA"
        ],
    },
    "MEMO_DIARIAS": {
        "arquivo_path": MODELOS_DIR / "memorandos" / "MEMO_DIARIAS.txt",
        "tipo_sei": "Memorando",
        "descricao": "Memorando sobre di�rias para DPLAN",
        "campos": [
            "NOME_DESTINATARIO", "POSTO_GRAD_DESTINATARIO", "CARGO_DESTINATARIO",
            "VOCATIVO", "NUMERO_SEI_DIARIAS", "NOME_REMETENTE", 
            "POSTO_GRAD_REMETENTE", "CARGO_REMETENTE", "NUMERO_PORTARIA"
        ],
    },

    # ==========================================================================
    # OF�CIOS
    # ==========================================================================
    "OFICIO_EXTERNO": {
        "arquivo_path": MODELOS_DIR / "oficios" / "OFICIO_EXTERNO.txt",
        "tipo_sei": "Of�cio",
        "descricao": "Of�cio para �rg�os externos",
        "campos": [
            "NOME_DESTINATARIO", "CARGO_DESTINATARIO", "ASSUNTO", "VOCATIVO",
            "TEXTO_CORPO", "NOME_REMETENTE", "POSTO_GRAD_REMETENTE",
            "CARGO_REMETENTE", "NUMERO_PORTARIA"
        ],
    },
    "OFICIO_CONVOCACAO_FERIAS": {
        "arquivo_path": MODELOS_DIR / "oficios" / "OFICIO_CONVOCACAO_FERIAS.txt",
        "tipo_sei": "Of�cio",
        "descricao": "Of�cio de convoca��o para agendamento de f�rias pendentes",
        "campos": [
            "NOME_DESTINATARIO", "CARGO_DESTINATARIO", "VOCATIVO",
            "NOME_SERVIDOR", "NOME_REMETENTE", "POSTO_GRAD_REMETENTE",
            "CARGO_REMETENTE", "NUMERO_PORTARIA"
        ],
    },

    # ==========================================================================
    # REQUERIMENTOS
    # ==========================================================================
    "REQ_GENERICO": {
        "arquivo_path": MODELOS_DIR / "requerimentos" / "REQ_GENERICO.txt",
        "tipo_sei": "Requerimento",
        "descricao": "Requerimento gen�rico para qualquer solicita��o",
        "campos": [
            "NOME_COMANDANTE", "CARGO_COMANDANTE", "ASSUNTO", "NOME_REQUERENTE",
            "POSTO_GRAD_REQUERENTE", "MATRICULA", "UNIDADE_LOTACAO",
            "TEXTO_SOLICITACAO", "TEXTO_COMPLEMENTAR"
        ],
    },
    "REQ_LICENCA_NUPCIAS": {
        "arquivo_path": MODELOS_DIR / "requerimentos" / "REQ_LICENCA_NUPCIAS.txt",
        "tipo_sei": "Requerimento",
        "descricao": "Requerimento de licen�a por motivo de n�pcias (casamento)",
        "campos": [
            "NOME_COMANDANTE", "CARGO_COMANDANTE", "NOME_REQUERENTE",
            "POSTO_GRAD_REQUERENTE", "MATRICULA", "MATRICULA_CERTIDAO",
            "DATA_RETORNO"
        ],
    },
    "REQ_DISPENSA_LUTO": {
        "arquivo_path": MODELOS_DIR / "requerimentos" / "REQ_DISPENSA_LUTO.txt",
        "tipo_sei": "Requerimento",
        "descricao": "Requerimento de dispensa por motivo de luto (falecimento)",
        "campos": [
            "NOME_COMANDANTE", "CARGO_COMANDANTE", "NOME_REQUERENTE",
            "POSTO_GRAD_REQUERENTE", "MATRICULA", "UNIDADE_LOTACAO",
            "GRAU_PARENTESCO", "NOME_FALECIDO", "DATA_FALECIMENTO",
            "LOCAL_FALECIMENTO"
        ],
    },
    "REQ_LICENCA_PATERNIDADE": {
        "arquivo_path": MODELOS_DIR / "requerimentos" / "REQ_LICENCA_PATERNIDADE.txt",
        "tipo_sei": "Requerimento",
        "descricao": "Requerimento de licen�a paternidade",
        "campos": [
            "NOME_COMANDANTE", "CARGO_COMANDANTE", "NOME_REQUERENTE",
            "POSTO_GRAD_REQUERENTE", "MATRICULA", "UNIDADE_LOTACAO",
            "DATA_NASCIMENTO", "DATA_RETORNO"
        ],
    },
    "REQ_LICENCA_MATERNIDADE": {
        "arquivo_path": MODELOS_DIR / "requerimentos" / "REQ_LICENCA_MATERNIDADE.txt",
        "tipo_sei": "Requerimento",
        "descricao": "Requerimento de licen�a maternidade (180 dias)",
        "campos": [
            "NOME_COMANDANTE", "CARGO_COMANDANTE", "NOME_REQUERENTE",
            "POSTO_GRAD_REQUERENTE", "MATRICULA", "UNIDADE_LOTACAO",
            "DATA_NASCIMENTO"
        ],
    },
    "REQ_ADICIONAL_TITULACAO": {
        "arquivo_path": MODELOS_DIR / "requerimentos" / "REQ_ADICIONAL_TITULACAO.txt",
        "tipo_sei": "Requerimento",
        "descricao": "Requerimento de adicional de titula��o",
        "campos": [
            "NOME_COMANDANTE", "CARGO_COMANDANTE", "NOME_REQUERENTE",
            "POSTO_GRAD_REQUERENTE", "MATRICULA", "UNIDADE_LOTACAO",
            "NOME_CURSO", "NIVEL_CURSO", "NOME_INSTITUICAO", "DATA_CONCLUSAO"
        ],
    },
    "REQ_INCLUSAO_DEPENDENTE": {
        "arquivo_path": MODELOS_DIR / "requerimentos" / "REQ_INCLUSAO_DEPENDENTE.txt",
        "tipo_sei": "Requerimento",
        "descricao": "Requerimento de inclus�o no ROL de dependentes",
        "campos": [
            "NOME_COMANDANTE", "CARGO_COMANDANTE", "NOME_REQUERENTE",
            "POSTO_GRAD_REQUERENTE", "MATRICULA", "UNIDADE_LOTACAO",
            "NOME_DEPENDENTE", "GRAU_PARENTESCO", "DATA_NASCIMENTO_DEPENDENTE",
            "CPF_DEPENDENTE"
        ],
    },

    # ==========================================================================
    # DESPACHOS
    # ==========================================================================
    "DESPACHO_SIMPLES": {
        "arquivo_path": MODELOS_DIR / "despachos" / "DESPACHO_SIMPLES.txt",
        "tipo_sei": "Despacho",
        "descricao": "Despacho simples com texto livre",
        "campos": [
            "CARGO_DESTINATARIO", "SIGLA_UNIDADE_DESTINATARIO", "VOCATIVO",
            "TEXTO_DESPACHO", "NOME_REMETENTE", "POSTO_GRAD_REMETENTE",
            "CARGO_REMETENTE", "SIGLA_UNIDADE"
        ],
    },
    "DESPACHO_ENCAMINHAMENTO": {
        "arquivo_path": MODELOS_DIR / "despachos" / "DESPACHO_ENCAMINHAMENTO.txt",
        "tipo_sei": "Despacho",
        "descricao": "Despacho de encaminhamento para provid�ncias",
        "campos": [
            "CARGO_DESTINATARIO", "SIGLA_UNIDADE_DESTINATARIO", "VOCATIVO",
            "NOME_REMETENTE", "POSTO_GRAD_REMETENTE", "CARGO_REMETENTE",
            "SIGLA_UNIDADE"
        ],
    },
    "DESPACHO_CIENCIA_ARQUIVAMENTO": {
        "arquivo_path": MODELOS_DIR / "despachos" / "DESPACHO_CIENCIA_ARQUIVAMENTO.txt",
        "tipo_sei": "Despacho",
        "descricao": "Despacho de ci�ncia e arquivamento",
        "campos": [
            "NOME_REMETENTE", "POSTO_GRAD_REMETENTE", "CARGO_REMETENTE",
            "SIGLA_UNIDADE"
        ],
    },
    "DESPACHO_DEFERIMENTO": {
        "arquivo_path": MODELOS_DIR / "despachos" / "DESPACHO_DEFERIMENTO.txt",
        "tipo_sei": "Despacho",
        "descricao": "Despacho de deferimento de pedido",
        "campos": [
            "NOME_REMETENTE", "POSTO_GRAD_REMETENTE", "CARGO_REMETENTE",
            "SIGLA_UNIDADE"
        ],
    },
    "DESPACHO_INDEFERIMENTO": {
        "arquivo_path": MODELOS_DIR / "despachos" / "DESPACHO_INDEFERIMENTO.txt",
        "tipo_sei": "Despacho",
        "descricao": "Despacho de indeferimento de pedido",
        "campos": [
            "MOTIVOS_INDEFERIMENTO", "NOME_REMETENTE", "POSTO_GRAD_REMETENTE",
            "CARGO_REMETENTE", "SIGLA_UNIDADE"
        ],
    },

    # ==========================================================================
    # NOTAS PARA BOLETIM GERAL
    # ==========================================================================
    "NOTA_BG_VIAGEM": {
        "arquivo_path": MODELOS_DIR / "notas" / "NOTA_BG_VIAGEM.txt",
        "tipo_sei": "Nota para Boletim Geral - BG - CBMAC",
        "descricao": "Nota para BG sobre viagem a servi�o da corpora��o",
        "campos": [
            "TIPO_ONUS", "DATA_VIAGEM", "HORA_SAIDA", "POSTO_GRAD", "MATRICULA",
            "NOME_MILITAR", "CIDADE_DESTINO", "UF_DESTINO", "MOTIVO_VIAGEM",
            "TIPO_TRANSPORTE", "DATA_RETORNO", "HORA_RETORNO", "NUP_PROCESSO",
            "NOME_REMETENTE", "POSTO_GRAD_REMETENTE", "CARGO_REMETENTE",
            "NUMERO_PORTARIA"
        ],
    },
    "NOTA_BG_GENERICA": {
        "arquivo_path": MODELOS_DIR / "notas" / "NOTA_BG_GENERICA.txt",
        "tipo_sei": "Nota para Boletim Geral - BG - CBMAC",
        "descricao": "Nota gen�rica para Boletim Geral",
        "campos": [
            "ALTERACAO_ESCALA", "ALTERACAO_INSTRUCAO", "ALTERACAO_ASSUNTOS_GERAIS",
            "ALTERACAO_JUSTICA", "NOME_REMETENTE", "POSTO_GRAD_REMETENTE",
            "CARGO_REMETENTE", "NUMERO_PORTARIA"
        ],
    },

    # ==========================================================================
    # TERMOS
    # ==========================================================================
    "TERMO_ENCERRAMENTO": {
        "arquivo_path": MODELOS_DIR / "termos" / "TERMO_DE_ENCERRAMENTO_DE_PROCESSO_ELETRONICO.txt",
        "tipo_sei": "Termo de Encerramento de Processo Eletrônico",
        "descricao": "Termo de encerramento de tramitação de processo eletrônico",
        "campos": [
            "MOTIVO_ENCERRAMENTO", "NOME_RESPONSAVEL",
            "POSTO_GRAD_RESPONSAVEL", "CARGO_RESPONSAVEL", "MATRICULA"
        ],
    },

    # ==========================================================================
    # PORTARIAS
    # ==========================================================================
    "PORTARIA_COMISSAO": {
        "arquivo_path": MODELOS_DIR / "portarias" / "PORTARIA_COMISSAO.txt",
        "tipo_sei": "Portaria",
        "descricao": "Portaria de nomea��o de comiss�o",
        "campos": [
            "DECRETO_NOMEACAO", "CONSIDERANDOS", "FINALIDADE_COMISSAO",
            "LISTA_MEMBROS", "ATRIBUICOES_COMISSAO", "DATA_VIGENCIA",
            "NOME_COMANDANTE", "POSTO_COMANDANTE"
        ],
    },
    "PORTARIA_GENERICA": {
        "arquivo_path": MODELOS_DIR / "portarias" / "PORTARIA_GENERICA.txt",
        "tipo_sei": "Portaria",
        "descricao": "Portaria gen�rica",
        "campos": [
            "DECRETO_NOMEACAO", "CONSIDERANDOS", "TEXTO_RESOLUCAO",
            "NOME_COMANDANTE", "POSTO_COMANDANTE"
        ],
    },
}


# =============================================================================
# FUN��ES UTILIT�RIAS
# =============================================================================

def listar_templates() -> list:
    """Lista todos os IDs de templates dispon�veis"""
    return list(TEMPLATES_META.keys())


def listar_templates_por_tipo(tipo_sei: str) -> list:
    """Lista templates filtrados por tipo SEI (Memorando, Despacho, etc.)"""
    return [
        tid for tid, meta in TEMPLATES_META.items()
        if meta.get("tipo_sei", "").lower() == tipo_sei.lower()
    ]


def get_template_info(template_id: str) -> dict:
    """Retorna informa��es de um template espec�fico"""
    return TEMPLATES_META.get(template_id)


def template_existe(template_id: str) -> bool:
    """Verifica se o template existe e o arquivo est� acess�vel"""
    if template_id not in TEMPLATES_META:
        return False
    meta = TEMPLATES_META[template_id]
    caminho = meta.get("arquivo_path")
    return caminho is not None and caminho.exists()


def carregar_template(template_id: str) -> str:
    """Carrega o conte�do de um template"""
    if not template_existe(template_id):
        raise FileNotFoundError(f"Template '{template_id}' n�o encontrado")
    
    meta = TEMPLATES_META[template_id]
    caminho = meta["arquivo_path"]
    
    with open(caminho, "r", encoding="utf-8") as f:
        return f.read()


def preencher_template(template_id: str, dados: dict) -> str:
    """
    Carrega um template e substitui os placeholders pelos dados fornecidos.
    
    Exemplo:
        html = preencher_template("MEMO_GENERICO", {
            "NOME_DESTINATARIO": "Jo�o Silva",
            "POSTO_GRAD_DESTINATARIO": "MAJ QOBMEC",
            ...
        })
    """
    conteudo = carregar_template(template_id)
    
    for campo, valor in dados.items():
        placeholder = "{" + campo + "}"
        conteudo = conteudo.replace(placeholder, str(valor))
    
    return conteudo


def get_campos_obrigatorios(template_id: str) -> list:
    """Retorna lista de campos obrigat�rios de um template"""
    meta = get_template_info(template_id)
    if meta:
        return meta.get("campos", [])
    return []


def validar_dados_template(template_id: str, dados: dict) -> tuple:
    """
    Valida se todos os campos obrigat�rios foram fornecidos.
    Retorna (True, []) se v�lido, ou (False, [campos_faltantes]) se inv�lido.
    """
    campos_obrigatorios = get_campos_obrigatorios(template_id)
    campos_faltantes = [c for c in campos_obrigatorios if c not in dados]
    
    return (len(campos_faltantes) == 0, campos_faltantes)


# =============================================================================
# RESUMO DOS TEMPLATES DISPON�VEIS
# =============================================================================
"""
MEMORANDOS (4):
- MEMO_GENERICO: Memorando para qualquer finalidade
- MEMO_ENCAMINHAMENTO: Memorando de encaminhamento de documentos
- MEMO_TAF_DEI: Memorando sobre TAF para DEI
- MEMO_DIARIAS: Memorando sobre di�rias para DPLAN

OF�CIOS (2):
- OFICIO_EXTERNO: Of�cio para �rg�os externos
- OFICIO_CONVOCACAO_FERIAS: Of�cio de convoca��o para f�rias pendentes

REQUERIMENTOS (7):
- REQ_GENERICO: Requerimento gen�rico
- REQ_LICENCA_NUPCIAS: Requerimento de licen�a por n�pcias
- REQ_DISPENSA_LUTO: Requerimento de dispensa por luto
- REQ_LICENCA_PATERNIDADE: Requerimento de licen�a paternidade
- REQ_LICENCA_MATERNIDADE: Requerimento de licen�a maternidade
- REQ_ADICIONAL_TITULACAO: Requerimento de adicional de titula��o
- REQ_INCLUSAO_DEPENDENTE: Requerimento de inclus�o de dependente

DESPACHOS (5):
- DESPACHO_SIMPLES: Despacho com texto livre
- DESPACHO_ENCAMINHAMENTO: Despacho de encaminhamento
- DESPACHO_CIENCIA_ARQUIVAMENTO: Despacho de ci�ncia e arquivamento
- DESPACHO_DEFERIMENTO: Despacho de deferimento
- DESPACHO_INDEFERIMENTO: Despacho de indeferimento

NOTAS PARA BG (2):
- NOTA_BG_VIAGEM: Nota sobre viagem a servi�o
- NOTA_BG_GENERICA: Nota gen�rica para BG

TERMOS (1):
- TERMO_ENCERRAMENTO: Termo de encerramento de processo

PORTARIAS (2):
- PORTARIA_COMISSAO: Portaria de nomea��o de comiss�o
- PORTARIA_GENERICA: Portaria gen�rica

TOTAL: 23 templates
"""