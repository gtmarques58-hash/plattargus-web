"""
classificador_documentos.py - Classificador Inteligente de Documentos SEI

Este módulo detecta o tipo de documento, extrai informações da mensagem
do usuário e preenche templates automaticamente.

FLUXO:
1. Usuário envia: "Termo de Encerramento BG 08/2026"
2. Classificador detecta: template_id = TERMO_ENCERRAMENTO
3. Classificador extrai: MOTIVO = "a publicação no BG nº 08/2026"
4. Retorna dados prontos para o backend

Uso:
    from classificador_documentos import classificar_documento
    
    resultado = classificar_documento(
        mensagem="Termo de Encerramento BG 08/2026",
        contexto={
            "sigla": "DRH",
            "nup": "0609.012097.00016/2026-69",
            "remetente": {
                "nome": "GILMAR TORRES MARQUES MOURA",
                "posto": "MAJ QOBMEC",
                "cargo": "Diretor de Recursos Humanos",
                "matricula": "9215394"
            }
        }
    )
    
    # resultado:
    # {
    #     "usar_template": True,
    #     "template_id": "TERMO_ENCERRAMENTO",
    #     "tipo_sei": "Termo de Encerramento de Processo Eletrônico",
    #     "campos": {...},
    #     "texto_livre": False
    # }
"""

import re
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple

# =============================================================================
# MESES POR EXTENSO
# =============================================================================

MESES = {
    1: "janeiro", 2: "fevereiro", 3: "março", 4: "abril",
    5: "maio", 6: "junho", 7: "julho", 8: "agosto",
    9: "setembro", 10: "outubro", 11: "novembro", 12: "dezembro"
}

# =============================================================================
# CONFIGURAÇÃO DOS TEMPLATES
# =============================================================================

TEMPLATES_CONFIG = {
    # =========================================================================
    # TERMO DE ENCERRAMENTO
    # =========================================================================
    "TERMO_ENCERRAMENTO": {
        "gatilhos": [
            r"termo\s*de\s*encerramento",
            r"encerrar\s*processo",
            r"encerramento\s*do\s*processo",
            r"encerrar\s*tramita[çc][aã]o",
        ],
        "tipo_sei": "Termo de Encerramento de Processo Eletrônico",
        "campos_obrigatorios": [
            "DIA", "MES", "ANO", "MOTIVO_ENCERRAMENTO",
            "NOME_RESPONSAVEL", "POSTO_GRAD_RESPONSAVEL",
            "CARGO_RESPONSAVEL", "MATRICULA"
        ],
        "extratores": {
            # Extrai número do BG
            "bg": r"BG\s*n?[º°]?\s*(\d+[/-]\d{4}|\d+)",
            # Extrai se foi deferido
            "deferido": r"\b(deferid[oa]|deferimento)\b",
            # Extrai se foi indeferido
            "indeferido": r"\b(indeferid[oa]|indeferimento)\b",
            # Extrai se é arquivamento
            "arquivamento": r"\b(arquiv|arquivamento)\b",
            # Extrai se é publicação
            "publicacao": r"\b(publica[çc][aã]o|publicad[oa])\b",
            # Extrai se é conclusão
            "conclusao": r"\b(conclu[ií]d[oa]|conclus[aã]o)\b",
            # Extrai se não há pendências
            "sem_pendencias": r"\b(sem\s*pend[êe]ncias?|inexist[êe]ncia)\b",
        },
    },
    
    # =========================================================================
    # DESPACHOS
    # =========================================================================
    "DESPACHO_SIMPLES": {
        "gatilhos": [
            r"despacho\s*simples",
            r"despacho\s*livre",
        ],
        "tipo_sei": "Despacho",
        "campos_obrigatorios": [
            "CARGO_DESTINATARIO", "SIGLA_UNIDADE_DESTINATARIO", "VOCATIVO",
            "TEXTO_DESPACHO", "NOME_REMETENTE", "POSTO_GRAD_REMETENTE",
            "CARGO_REMETENTE", "SIGLA_UNIDADE"
        ],
        "texto_livre": True,  # Precisa de texto do usuário
    },
    
    "DESPACHO_ENCAMINHAMENTO": {
        "gatilhos": [
            r"despacho\s*(de\s*)?encaminha",
            r"encaminhar\s*para",
            r"encaminho\s*(ao|à|para)",
        ],
        "tipo_sei": "Despacho",
        "campos_obrigatorios": [
            "CARGO_DESTINATARIO", "SIGLA_UNIDADE_DESTINATARIO", "VOCATIVO",
            "NOME_REMETENTE", "POSTO_GRAD_REMETENTE", "CARGO_REMETENTE",
            "SIGLA_UNIDADE"
        ],
        "extratores": {
            "destino": r"(?:para|ao|à)\s*([A-Z]{2,10}|[A-Za-zÀ-ú\s]+?)(?:\s*[,.]|\s*$)",
        },
    },
    
    "DESPACHO_CIENCIA_ARQUIVAMENTO": {
        "gatilhos": [
            r"despacho\s*(de\s*)?ci[êe]ncia",
            r"ci[êe]ncia\s*e\s*arquiv",
            r"ciente\s*e?\s*arquiv",
        ],
        "tipo_sei": "Despacho",
        "campos_obrigatorios": [
            "NOME_REMETENTE", "POSTO_GRAD_REMETENTE",
            "CARGO_REMETENTE", "SIGLA_UNIDADE"
        ],
    },
    
    "DESPACHO_DEFERIMENTO": {
        "gatilhos": [
            r"despacho\s*(de\s*)?deferimento",
            r"deferir\s*pedido",
            r"defiro\s*o\s*pedido",
        ],
        "tipo_sei": "Despacho",
        "campos_obrigatorios": [
            "TEXTO_DEFERIMENTO", "NOME_REMETENTE", "POSTO_GRAD_REMETENTE",
            "CARGO_REMETENTE", "SIGLA_UNIDADE"
        ],
        "extratores": {
            "motivo": r"(?:deferi[rd]o?|aprova[rd]o?)\s*(.+?)(?:\.|$)",
        },
    },
    
    "DESPACHO_INDEFERIMENTO": {
        "gatilhos": [
            r"despacho\s*(de\s*)?indeferimento",
            r"indeferir\s*pedido",
            r"indefiro\s*o\s*pedido",
        ],
        "tipo_sei": "Despacho",
        "campos_obrigatorios": [
            "MOTIVOS_INDEFERIMENTO", "NOME_REMETENTE", "POSTO_GRAD_REMETENTE",
            "CARGO_REMETENTE", "SIGLA_UNIDADE"
        ],
        "extratores": {
            "motivo": r"(?:indeferi[rd]o?|negad[oa])\s*(.+?)(?:\.|$)",
        },
    },
    
    # =========================================================================
    # REQUERIMENTOS
    # =========================================================================
    "REQ_GENERICO": {
        "gatilhos": [
            r"requerimento\s*gen[ée]rico",
            r"requerimento\s*simples",
        ],
        "tipo_sei": "Requerimento",
        "campos_obrigatorios": [
            "NOME_COMANDANTE", "CARGO_COMANDANTE", "ASSUNTO", "NOME_REQUERENTE",
            "POSTO_GRAD_REQUERENTE", "MATRICULA", "UNIDADE_LOTACAO",
            "TEXTO_SOLICITACAO", "TEXTO_COMPLEMENTAR"
        ],
        "texto_livre": True,
    },
    
    "REQ_LICENCA_NUPCIAS": {
        "gatilhos": [
            r"licen[çc]a\s*(por\s*)?(motivo\s*de\s*)?n[úu]pcias",
            r"licen[çc]a\s*casamento",
            r"licen[çc]a\s*gala",
        ],
        "tipo_sei": "Requerimento",
        "campos_obrigatorios": [
            "NOME_COMANDANTE", "CARGO_COMANDANTE", "NOME_REQUERENTE",
            "POSTO_GRAD_REQUERENTE", "MATRICULA", "MATRICULA_CERTIDAO",
            "DATA_RETORNO"
        ],
        "extratores": {
            "data_retorno": r"retor(?:no|nar)\s*(?:em|dia)?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
        },
    },
    
    "REQ_DISPENSA_LUTO": {
        "gatilhos": [
            r"dispensa\s*(por\s*)?(motivo\s*de\s*)?luto",
            r"licen[çc]a\s*luto",
            r"dispensa\s*falecimento",
            r"luto",
        ],
        "tipo_sei": "Requerimento",
        "campos_obrigatorios": [
            "NOME_COMANDANTE", "CARGO_COMANDANTE", "NOME_REQUERENTE",
            "POSTO_GRAD_REQUERENTE", "MATRICULA", "UNIDADE_LOTACAO",
            "GRAU_PARENTESCO", "NOME_FALECIDO", "DATA_FALECIMENTO",
            "LOCAL_FALECIMENTO"
        ],
        "extratores": {
            "parentesco": r"(pai|m[ãa]e|filho|filha|irm[ãa]o|irm[ãa]|av[ôó]|av[óo]|c[ôo]njuge|esposa?o?)",
            "nome_falecido": r"falecimento\s*(?:de|do|da)\s*([A-ZÀ-Ú][a-zà-ú]+(?:\s+[A-ZÀ-Ú][a-zà-ú]+)*)",
            "data_falecimento": r"(?:falec\w+|[óo]bito)\s*(?:em|dia)?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
        },
    },
    
    "REQ_LICENCA_PATERNIDADE": {
        "gatilhos": [
            r"licen[çc]a\s*paternidade",
            r"paternidade",
        ],
        "tipo_sei": "Requerimento",
        "campos_obrigatorios": [
            "NOME_COMANDANTE", "CARGO_COMANDANTE", "NOME_REQUERENTE",
            "POSTO_GRAD_REQUERENTE", "MATRICULA", "UNIDADE_LOTACAO",
            "DATA_NASCIMENTO", "DATA_RETORNO"
        ],
        "extratores": {
            "data_nascimento": r"nasc\w*\s*(?:em|dia)?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
        },
    },
    
    "REQ_LICENCA_MATERNIDADE": {
        "gatilhos": [
            r"licen[çc]a\s*maternidade",
            r"maternidade",
        ],
        "tipo_sei": "Requerimento",
        "campos_obrigatorios": [
            "NOME_COMANDANTE", "CARGO_COMANDANTE", "NOME_REQUERENTE",
            "POSTO_GRAD_REQUERENTE", "MATRICULA", "UNIDADE_LOTACAO",
            "DATA_NASCIMENTO"
        ],
        "extratores": {
            "data_nascimento": r"nasc\w*\s*(?:em|dia)?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
        },
    },
    
    "REQ_ADICIONAL_TITULACAO": {
        "gatilhos": [
            r"adicional\s*(de\s*)?titula[çc][aã]o",
            r"titula[çc][aã]o",
        ],
        "tipo_sei": "Requerimento",
        "campos_obrigatorios": [
            "NOME_COMANDANTE", "CARGO_COMANDANTE", "NOME_REQUERENTE",
            "POSTO_GRAD_REQUERENTE", "MATRICULA", "UNIDADE_LOTACAO",
            "NOME_CURSO", "NIVEL_CURSO", "NOME_INSTITUICAO", "DATA_CONCLUSAO"
        ],
        "extratores": {
            "curso": r"curso\s*(?:de\s*)?([A-Za-zÀ-ú\s]+?)(?:\s*[,.]|\s*$)",
            "nivel": r"(gradua[çc][aã]o|p[óo]s[- ]?gradua[çc][aã]o|mestrado|doutorado|especializa[çc][aã]o)",
        },
    },
    
    "REQ_INCLUSAO_DEPENDENTE": {
        "gatilhos": [
            r"inclus[aã]o\s*(de\s*)?dependente",
            r"incluir\s*dependente",
            r"rol\s*de\s*dependentes",
        ],
        "tipo_sei": "Requerimento",
        "campos_obrigatorios": [
            "NOME_COMANDANTE", "CARGO_COMANDANTE", "NOME_REQUERENTE",
            "POSTO_GRAD_REQUERENTE", "MATRICULA", "UNIDADE_LOTACAO",
            "NOME_DEPENDENTE", "GRAU_PARENTESCO", "DATA_NASCIMENTO_DEPENDENTE",
            "CPF_DEPENDENTE"
        ],
        "extratores": {
            "nome_dependente": r"dependente\s*([A-ZÀ-Ú][a-zà-ú]+(?:\s+[A-ZÀ-Ú][a-zà-ú]+)*)",
            "parentesco": r"(filho|filha|c[ôo]njuge|esposa?o?|companheira?o?)",
        },
    },
    
    # =========================================================================
    # NOTAS PARA BOLETIM GERAL
    # =========================================================================
    "NOTA_BG_VIAGEM": {
        "gatilhos": [
            r"nota\s*(para\s*)?(bg|boletim)\s*(sobre\s*)?viagem",
            r"nota\s*viagem",
            r"bg\s*viagem",
        ],
        "tipo_sei": "Nota para Boletim Geral - BG - CBMAC",
        "campos_obrigatorios": [
            "TIPO_ONUS", "DATA_VIAGEM", "HORA_SAIDA", "POSTO_GRAD", "MATRICULA",
            "NOME_MILITAR", "CIDADE_DESTINO", "UF_DESTINO", "MOTIVO_VIAGEM",
            "TIPO_TRANSPORTE", "DATA_RETORNO", "HORA_RETORNO", "NUP_PROCESSO",
            "NOME_REMETENTE", "POSTO_GRAD_REMETENTE", "CARGO_REMETENTE",
            "NUMERO_PORTARIA"
        ],
        "extratores": {
            "destino": r"(?:para|destino)\s*([A-Za-zÀ-ú\s]+?)(?:[/-]([A-Z]{2}))?(?:\s*[,.]|\s*$)",
            "data_viagem": r"(?:dia|em|saida)\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
        },
    },
    
    "NOTA_BG_GENERICA": {
        "gatilhos": [
            r"nota\s*(para\s*)?(bg|boletim)\s*gen[ée]rica",
            r"nota\s*(para\s*)?(bg|boletim)$",
        ],
        "tipo_sei": "Nota para Boletim Geral - BG - CBMAC",
        "campos_obrigatorios": [
            "ALTERACAO_ESCALA", "ALTERACAO_INSTRUCAO", "ALTERACAO_ASSUNTOS_GERAIS",
            "ALTERACAO_JUSTICA", "NOME_REMETENTE", "POSTO_GRAD_REMETENTE",
            "CARGO_REMETENTE", "NUMERO_PORTARIA"
        ],
        "texto_livre": True,
    },
    
    # =========================================================================
    # PORTARIAS
    # =========================================================================
    "PORTARIA_COMISSAO": {
        "gatilhos": [
            r"portaria\s*(de\s*)?comiss[aã]o",
            r"portaria\s*nomea[çc][aã]o\s*comiss[aã]o",
            r"nomear\s*comiss[aã]o",
        ],
        "tipo_sei": "Portaria",
        "campos_obrigatorios": [
            "DECRETO_NOMEACAO", "CONSIDERANDOS", "FINALIDADE_COMISSAO",
            "LISTA_MEMBROS", "ATRIBUICOES_COMISSAO", "DATA_VIGENCIA",
            "NOME_COMANDANTE", "POSTO_COMANDANTE"
        ],
        "texto_livre": True,
    },
    
    "PORTARIA_GENERICA": {
        "gatilhos": [
            r"portaria\s*gen[ée]rica",
            r"portaria\s*simples",
        ],
        "tipo_sei": "Portaria",
        "campos_obrigatorios": [
            "DECRETO_NOMEACAO", "CONSIDERANDOS", "TEXTO_RESOLUCAO",
            "NOME_COMANDANTE", "POSTO_COMANDANTE"
        ],
        "texto_livre": True,
    },
}

# =============================================================================
# DOCUMENTOS QUE SEMPRE USAM TEXTO LIVRE (ARGUS GERA)
# =============================================================================

TEXTO_LIVRE_SEMPRE = [
    "memorando",
    "ofício",
    "oficio",
]


# =============================================================================
# FUNÇÕES AUXILIARES
# =============================================================================

def get_data_atual() -> Dict[str, str]:
    """Retorna data atual formatada."""
    agora = datetime.now()
    return {
        "DIA": str(agora.day),
        "MES": MESES[agora.month],
        "ANO": str(agora.year),
        "DATA_COMPLETA": agora.strftime("%d/%m/%Y"),
    }


def extrair_com_regex(texto: str, padrao: str) -> Optional[str]:
    """Extrai valor usando regex."""
    match = re.search(padrao, texto, re.IGNORECASE)
    if match:
        return match.group(1) if match.groups() else match.group(0)
    return None


def normalizar_texto(texto: str) -> str:
    """Normaliza texto para comparação."""
    return texto.lower().strip()


def montar_motivo_encerramento(extraidos: Dict[str, str]) -> str:
    """Monta o motivo de encerramento baseado no que foi extraído."""
    
    # Prioridade: BG > publicação > deferido > indeferido > arquivamento > conclusão > sem_pendências
    
    if extraidos.get("bg"):
        bg = extraidos["bg"]
        # Normaliza formato do BG
        if "/" not in bg and "-" not in bg:
            # Se não tem ano, adiciona ano atual
            bg = f"{bg}/{datetime.now().year}"
        return f"a publicação no BG nº {bg}"
    
    if extraidos.get("publicacao"):
        return "a publicação em Boletim Geral"
    
    if extraidos.get("deferido"):
        return "o deferimento do pedido"
    
    if extraidos.get("indeferido"):
        return "o indeferimento do pedido"
    
    if extraidos.get("arquivamento"):
        return "o arquivamento administrativo"
    
    if extraidos.get("conclusao"):
        return "a conclusão das providências solicitadas"
    
    if extraidos.get("sem_pendencias"):
        return "a inexistência de pendências"
    
    # Default
    return "a conclusão da tramitação"


# =============================================================================
# FUNÇÃO PRINCIPAL
# =============================================================================

def classificar_documento(
    mensagem: str,
    contexto: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Classifica a mensagem do usuário e retorna dados para criação do documento.
    
    Args:
        mensagem: Texto do usuário (ex: "Termo de Encerramento BG 08/2026")
        contexto: Dados do contexto (sigla, nup, remetente, etc.)
    
    Returns:
        Dict com:
        - usar_template: bool - Se deve usar template
        - template_id: str - ID do template (se usar_template=True)
        - tipo_sei: str - Tipo do documento no SEI
        - campos: Dict - Campos preenchidos
        - campos_faltantes: List - Campos que precisam ser preenchidos
        - texto_livre: bool - Se precisa de texto livre do ARGUS
        - confianca: float - Confiança na classificação (0-1)
    """
    
    contexto = contexto or {}
    mensagem_normalizada = normalizar_texto(mensagem)
    
    # =========================================================================
    # 1. VERIFICA SE É TEXTO LIVRE OBRIGATÓRIO (Memorando/Ofício)
    # =========================================================================
    for tipo in TEXTO_LIVRE_SEMPRE:
        if tipo in mensagem_normalizada:
            return {
                "usar_template": False,
                "template_id": None,
                "tipo_sei": tipo.capitalize(),
                "campos": {},
                "campos_faltantes": [],
                "texto_livre": True,
                "confianca": 1.0,
                "mensagem": f"Documento '{tipo}' usa texto livre. ARGUS deve gerar."
            }
    
    # =========================================================================
    # 2. TENTA CLASSIFICAR COM TEMPLATES
    # =========================================================================
    melhor_match = None
    melhor_confianca = 0.0
    
    for template_id, config in TEMPLATES_CONFIG.items():
        for gatilho in config["gatilhos"]:
            if re.search(gatilho, mensagem_normalizada):
                # Calcula confiança baseada no tamanho do match
                match = re.search(gatilho, mensagem_normalizada)
                confianca = len(match.group(0)) / len(mensagem_normalizada)
                confianca = min(confianca * 2, 1.0)  # Normaliza
                
                if confianca > melhor_confianca:
                    melhor_confianca = confianca
                    melhor_match = (template_id, config)
    
    # =========================================================================
    # 3. SE NÃO ENCONTROU, RETORNA TEXTO LIVRE
    # =========================================================================
    if not melhor_match:
        return {
            "usar_template": False,
            "template_id": None,
            "tipo_sei": None,
            "campos": {},
            "campos_faltantes": [],
            "texto_livre": True,
            "confianca": 0.0,
            "mensagem": "Tipo de documento não identificado. ARGUS deve interpretar."
        }
    
    template_id, config = melhor_match
    
    # =========================================================================
    # 4. EXTRAI DADOS DA MENSAGEM
    # =========================================================================
    extraidos = {}
    
    if "extratores" in config:
        for campo, padrao in config["extratores"].items():
            valor = extrair_com_regex(mensagem, padrao)
            if valor:
                extraidos[campo] = valor
    
    # =========================================================================
    # 5. MONTA CAMPOS DO TEMPLATE
    # =========================================================================
    campos = {}
    data_atual = get_data_atual()
    
    # Campos de data (sempre preenchidos)
    campos["DIA"] = data_atual["DIA"]
    campos["MES"] = data_atual["MES"]
    campos["ANO"] = data_atual["ANO"]
    
    # Campos do contexto (remetente)
    remetente = contexto.get("remetente", {})
    campos["NOME_RESPONSAVEL"] = remetente.get("nome", "")
    campos["NOME_REMETENTE"] = remetente.get("nome", "")
    campos["POSTO_GRAD_RESPONSAVEL"] = remetente.get("posto", "")
    campos["POSTO_GRAD_REMETENTE"] = remetente.get("posto", "")
    campos["CARGO_RESPONSAVEL"] = remetente.get("cargo", "")
    campos["CARGO_REMETENTE"] = remetente.get("cargo", "")
    campos["MATRICULA"] = remetente.get("matricula", "")
    campos["SIGLA_UNIDADE"] = contexto.get("sigla", "")
    
    # Campos específicos do template
    if template_id == "TERMO_ENCERRAMENTO":
        campos["MOTIVO_ENCERRAMENTO"] = montar_motivo_encerramento(extraidos)
    
    # Copia campos extraídos
    for campo, valor in extraidos.items():
        campo_upper = campo.upper()
        if campo_upper not in campos:
            campos[campo_upper] = valor
    
    # =========================================================================
    # 6. IDENTIFICA CAMPOS FALTANTES
    # =========================================================================
    campos_faltantes = []
    for campo in config.get("campos_obrigatorios", []):
        if campo not in campos or not campos[campo]:
            campos_faltantes.append(campo)
    
    # =========================================================================
    # 7. RETORNA RESULTADO
    # =========================================================================
    return {
        "usar_template": True,
        "template_id": template_id,
        "tipo_sei": config["tipo_sei"],
        "campos": campos,
        "campos_faltantes": campos_faltantes,
        "texto_livre": config.get("texto_livre", False),
        "confianca": melhor_confianca,
        "extraidos": extraidos,  # Para debug
    }


def formatar_para_atuar(classificacao: Dict[str, Any], nup: str) -> Dict[str, Any]:
    """
    Formata a classificação para chamar atuar_processo_sei.
    
    Args:
        classificacao: Resultado de classificar_documento()
        nup: NUP do processo
    
    Returns:
        Dict pronto para passar ao atuar_processo_sei
    """
    
    if not classificacao["usar_template"]:
        return {
            "usar_template": False,
            "mensagem": "Documento requer texto livre. ARGUS deve gerar corpo_html."
        }
    
    return {
        "nup": nup,
        "template_id": classificacao["template_id"],
        "tipo_documento": classificacao["tipo_sei"],
        **classificacao["campos"]
    }


# =============================================================================
# CLI PARA TESTES
# =============================================================================

if __name__ == "__main__":
    import json
    import sys
    
    # Contexto de exemplo
    contexto_exemplo = {
        "sigla": "DRH",
        "nup": "0609.012097.00016/2026-69",
        "remetente": {
            "nome": "GILMAR TORRES MARQUES MOURA",
            "posto": "MAJ QOBMEC",
            "cargo": "Diretor de Recursos Humanos",
            "matricula": "9215394"
        }
    }
    
    # Testes
    testes = [
        "Termo de Encerramento BG 08/2026",
        "Termo de Encerramento deferido",
        "Termo de Encerramento publicação BG nº 15/2026",
        "Termo de Encerramento arquivamento",
        "Despacho de encaminhamento para COC",
        "Despacho ciência e arquivamento",
        "Licença paternidade nascimento dia 20/01/2026",
        "Dispensa por luto - falecimento do pai",
        "Memorando para o COC sobre viaturas",
        "Ofício externo para Secretaria de Segurança",
        "Nota para BG sobre viagem",
        "Adicional de titulação curso de mestrado",
    ]
    
    if len(sys.argv) > 1:
        # Usa argumento da linha de comando
        testes = [" ".join(sys.argv[1:])]
    
    print("=" * 70)
    print("TESTE DO CLASSIFICADOR DE DOCUMENTOS")
    print("=" * 70)
    
    for teste in testes:
        print(f"\n📝 Entrada: \"{teste}\"")
        print("-" * 50)
        
        resultado = classificar_documento(teste, contexto_exemplo)
        
        if resultado["usar_template"]:
            print(f"✅ Template: {resultado['template_id']}")
            print(f"   Tipo SEI: {resultado['tipo_sei']}")
            print(f"   Confiança: {resultado['confianca']:.0%}")
            
            if resultado.get("extraidos"):
                print(f"   Extraído: {resultado['extraidos']}")
            
            if resultado["campos_faltantes"]:
                print(f"   ⚠️  Campos faltantes: {resultado['campos_faltantes']}")
            
            # Mostra campos preenchidos relevantes
            campos_relevantes = {k: v for k, v in resultado["campos"].items() if v}
            if campos_relevantes:
                print(f"   Campos: {json.dumps(campos_relevantes, ensure_ascii=False, indent=4)}")
        else:
            print(f"📄 Texto Livre: {resultado.get('mensagem', 'ARGUS deve gerar')}")
    
    print("\n" + "=" * 70)
