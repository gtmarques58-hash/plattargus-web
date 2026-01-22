"""
Detector de Tags Técnicas

Analisa texto de documentos usando regex para detectar
padrões importantes de forma DETERMINÍSTICA (sem LLM).

CORREÇÃO v1.1: Adicionadas tags para:
- TEM_ENCERRAMENTO: Termo de Encerramento
- TEM_DECRETO: Decreto do Governador  
- TEM_AGREGACAO: Agregação de militar
- TEM_CESSAO: Cessão/Disposição
- TEM_FAVORAVEL: Manifestação favorável
- TEM_APRESENTACAO: Apresentação de militar
- TEM_LOTACAO: Lotação/Movimentação
- ORGAO_EXTERNO: Documento de órgão externo
"""

import re
from typing import List, Set, Dict, Tuple
from ..schemas.doc_v1 import TagTecnica


# =============================================================================
# PADRÕES REGEX
# =============================================================================

PATTERNS: Dict[TagTecnica, List[str]] = {
    TagTecnica.TEM_COMANDO: [
        r'\bDETERMINO\b',
        r'\bDETERMINA\b',
        r'\bENCAmINHE-SE\b',
        r'\bRETORNE-SE\b',
        r'\bCUMPRA-SE\b',
        r'\bMANIFESTE-SE\b',
        r'\bPROVIDENCIE-SE\b',
        r'\bAPURE-SE\b',
        r'\bINFORME-SE\b',
        r'\bNOTIFIQUE-SE\b',
        r'\bINTIME-SE\b',
        r'\bCIENTIFIQUE-SE\b',
        r'\bPUBLIQUE-SE\b',
        r'\bREGISTRE-SE\b',
        r'\bANOTE-SE\b',
        r'\bENCAmINHO\s+(PARA|AO|À)\b',
        r'\bREMETO\s+(PARA|AO|À)\b',
        r'\bENVIO\s+(PARA|AO|À)\b',
    ],
    
    TagTecnica.TEM_DECISAO: [
        r'\bAUTORIZO\b',
        r'\bDEFIRO\b',
        r'\bINDEFIRO\b',
        r'\bARQUIVE-SE\b',
        r'\bCONCLUO\b',
        r'\bCONCEDO\b',
        r'\bPublicar em BG\b',
        r'\bHOMOLOGO\b',
        r'\bAPROVO\b',
        r'\bREPROVO\b',
        r'\bACOLHO\b',
        r'\bREJEITO\b',
        r'\bACEITO\b',
        r'\bDECIDO\b',
        r'\bRESOLVE\b',  # Comum em Decretos
    ],
    
    TagTecnica.TEM_PRAZO: [
        r'\bno\s+prazo\s+de\b',
        r'\bem\s+(\d+)\s*(dias?|horas?)\b',
        r'\batÉ\s+(\d{1,2})[/.-](\d{1,2})\b',
        r'\bprazo\s+de\s+(\d+)\b',
        r'\b(\d+)\s*(dias?|horas?)\s*(úteis|corridos)?\b',
        r'\bno\s+prazo\b',
        r'\bcom\s+prazo\b',
        r'\bdata\s+limite\b',
        r'\bvencimento\b',
    ],
    
    TagTecnica.TEM_RECURSO: [
        r'\brecurso\b',
        r'\breconsideraÇÃo\b',
        r'\bretificaÇÃo\b',
        r'\brevisÃo\b',
        r'\bimpugnaÇÃo\b',
        r'\bcontestaÇÃo\b',
        r'\bapelaÇÃo\b',
        r'\bagravo\b',
        r'\bembargo\b',
    ],
    
    TagTecnica.MUDA_DESTINO: [
        r'\bencaminho\s+(para|ao|à)\s+(\w+)\b',
        r'\bremeto\s+(para|ao|à)\s+(\w+)\b',
        r'\benvio\s+(para|ao|à)\s+(\w+)\b',
        r'\bencaminhe-se\s+(para|ao|à)\s+(\w+)\b',
        r'\brestituam-se\s+os\s+autos\b',
        r'\bretornem\s+os\s+autos\b',
    ],
    
    TagTecnica.TEM_DEFERIMENTO: [
        r'\bDEFERIDO\b',
        r'\bAUTORIZADO\b',
        r'\bAPROVADO\b',
        r'\bHOMOLOGADO\b',
        r'\bACOLHIDO\b',
        r'\bACEITO\b',
        r'\bCONCEDIDO\b',
    ],
    
    TagTecnica.TEM_INDEFERIMENTO: [
        r'\bINDEFERIDO\b',
        r'\bNEGADO\b',
        r'\bREPROVADO\b',
        r'\bREJEITADO\b',
        r'\bDENEGADO\b',
        r'\bIMPROCEDENTE\b',
    ],
    
    TagTecnica.TEM_ARQUIVAMENTO: [
        r'\bARQUIVE-SE\b',
        r'\bARQUIVAMENTO\b',
        r'\bARQUIVAR\b',
        r'\bARQUIVADO\b',
        r'\bCONCLUÍDO\b',
    ],
    
    TagTecnica.TEM_PUBLICACAO: [
        r'\bPUBLICAR\b',
        r'\bPUBLICAÇÃO\b',
        r'\bPUBLIQUE-SE\b',
        r'\bBOLETIM\s+GERAL\b',
        r'\b(BG|B\.G\.)\b',
        r'\bDIÁRIO\s+OFICIAL\b',
        r'\b(DOE|D\.O\.E\.)\b',
    ],
    
    # =========================================================================
    # NOVAS TAGS - Correção v1.1
    # =========================================================================
    
    TagTecnica.TEM_ENCERRAMENTO: [
        r'\bTERMO\s+DE\s+ENCERRAMENTO\b',
        r'\bPROCEDO\s+AO\s+ENCERRAMENTO\b',
        r'\bENCERRAMENTO\s+DO\s+PROCESSO\b',
        r'\bENCERRAMENTO\s+DE\s+PROCESSO\b',
        r'\bPROCESSO\s+ENCERRADO\b',
    ],
    
    TagTecnica.TEM_DECRETO: [
        r'\bDECRETO\s*(?:Nº|N°|N\.º)\s*[\d\.\-]+',
        r'\bDECRETO\s+ESTADUAL\b',
        r'\bGOVERNADOR\s+DO\s+ESTADO\b',
        r'\bO\s+GOVERNADOR\b.*\bRESOLVE\b',
    ],
    
    TagTecnica.TEM_AGREGACAO: [
        r'\bAGREGAR\b',
        r'\bAGREGAÇÃO\b',
        r'\bAGREGADO\b',
        r'\bART\.\s*81\b',  # Lei Complementar 164/2006 - Agregação
    ],
    
    TagTecnica.TEM_CESSAO: [
        r'\bCESSÃO\b',
        r'\bCEDIDO\b',
        r'\bCEDER\b',
        r'\bDISPOSIÇÃO\b',
        r'\bDISPOSTO\b',
        r'\bÀ\s+DISPOSIÇÃO\b',
        r'\bPRORROGAÇÃO\s+DE\s+CESSÃO\b',
        r'\bPRORROGAR.*CESSÃO\b',
    ],
    
    TagTecnica.TEM_FAVORAVEL: [
        r'\bFAVORÁVEL\s+AO\s+PLEITO\b',
        r'\bÉ\s+FAVORÁVEL\b',
        r'\bMANIFESTAÇÃO\s+FAVORÁVEL\b',
        r'\bSOMS\s+FAVORÁVEIS\b',
        r'\bOPINA.*FAVORÁVEL\b',
        r'\bCOMANDO\s+É\s+FAVORÁVEL\b',
    ],
    
    TagTecnica.TEM_APRESENTACAO: [
        r'\bAPRESENTAÇÃO\s+DE\s+MILITAR\b',
        r'\bAPRESENTO.*MILITAR\b',
        r'\bMILITAR\s+APRESENT\b',
        r'\bREINCORPORAÇÃO\b',
        r'\bREINCORPORADO\b',
        r'\bFORMALIZA\s+A\s+APRESENTAÇÃO\b',
    ],
    
    TagTecnica.TEM_LOTACAO: [
        r'\bLOTAÇÃO\b',
        r'\bLOTAR\b',
        r'\bLOTADO\b',
        r'\bMOVIMENTAÇÃO\b',
        r'\bTRANSFERÊNCIA\b',
        r'\bREMOÇÃO\b',
        r'\bRELOTAÇÃO\b',
    ],
    
    TagTecnica.ORGAO_EXTERNO: [
        r'\bTRIBUNAL\s+DE\s+JUSTIÇA\b',
        r'\bTJAC\b',
        r'\bPODER\s+JUDICIÁRIO\b',
        r'\bCASA\s+CIVIL\b',
        r'\bCASACIVIL\b',
        r'\bSEAD\b',
        r'\bSECRETARIA\s+DE\s+(?:ESTADO\s+)?(?:DE\s+)?ADMINISTRAÇÃO\b',
        r'\bGOVERNADOR\b',
        r'\bGOVERNO\s+DO\s+ESTADO\b',
        r'\bMINISTÉRIO\s+PÚBLICO\b',
        r'\bMPAC\b',
        r'\bDEFENSORIA\b',
        r'\bPROCURADORIA\b',
        r'\bASSEMBLEIA\s+LEGISLATIVA\b',
        r'\bALEAC\b',
    ],
}


# Padrões para detecção de repetitivo
PATTERNS_REPETITIVO = [
    r'^encaminho\s+(para|ao)\s+\w+\.?\s*$',
    r'^remeto\s+(para|ao)\s+\w+\.?\s*$',
    r'^verificar\s*\.?\s*$',
    r'^para\s+conhecimento\s*\.?\s*$',
    r'^ciência\s*\.?\s*$',
    r'^à\s+\w+\s+para\s+(providências|conhecimento|análise)\s*\.?\s*$',
]


# =============================================================================
# FUNÇÕES DE DETECÇÃO
# =============================================================================

def detectar_tags(texto: str) -> List[TagTecnica]:
    """
    Detecta tags técnicas em um texto.
    
    Args:
        texto: Texto do documento
        
    Returns:
        Lista de tags detectadas
    """
    if not texto:
        return []
    
    texto_upper = texto.upper()
    tags_encontradas: Set[TagTecnica] = set()
    
    for tag, patterns in PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, texto_upper, re.IGNORECASE):
                tags_encontradas.add(tag)
                break  # Uma vez encontrada, não precisa testar outros patterns
    
    # Verificar se é repetitivo
    texto_limpo = texto.strip().lower()
    for pattern in PATTERNS_REPETITIVO:
        if re.match(pattern, texto_limpo, re.IGNORECASE):
            tags_encontradas.add(TagTecnica.REPETITIVO)
            break
    
    return list(tags_encontradas)


def detectar_tags_com_detalhes(texto: str) -> Dict[TagTecnica, List[str]]:
    """
    Detecta tags e retorna os matches encontrados.
    
    Args:
        texto: Texto do documento
        
    Returns:
        Dict com tag -> lista de matches
    """
    if not texto:
        return {}
    
    texto_upper = texto.upper()
    resultado: Dict[TagTecnica, List[str]] = {}
    
    for tag, patterns in PATTERNS.items():
        matches = []
        for pattern in patterns:
            encontrados = re.findall(pattern, texto_upper, re.IGNORECASE)
            if encontrados:
                # findall pode retornar grupos, precisamos tratar
                for match in encontrados:
                    if isinstance(match, tuple):
                        matches.append(" ".join(match))
                    else:
                        matches.append(match)
        
        if matches:
            resultado[tag] = list(set(matches))  # Remove duplicados
    
    return resultado


def extrair_prazos(texto: str) -> List[Dict[str, str]]:
    """
    Extrai menções a prazos do texto.
    
    Args:
        texto: Texto do documento
        
    Returns:
        Lista de prazos encontrados
    """
    if not texto:
        return []
    
    prazos = []
    
    # Padrão: "em X dias/horas"
    pattern1 = r'em\s+(\d+)\s*(dias?|horas?)\s*(úteis|corridos)?'
    for match in re.finditer(pattern1, texto, re.IGNORECASE):
        prazos.append({
            "texto": match.group(0),
            "quantidade": match.group(1),
            "unidade": match.group(2),
            "tipo": match.group(3) or "corridos"
        })
    
    # Padrão: "até dd/mm" ou "até dd/mm/aaaa"
    pattern2 = r'até\s+(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{2,4}))?'
    for match in re.finditer(pattern2, texto, re.IGNORECASE):
        prazos.append({
            "texto": match.group(0),
            "dia": match.group(1),
            "mes": match.group(2),
            "ano": match.group(3),
        })
    
    # Padrão: "prazo de X dias"
    pattern3 = r'prazo\s+de\s+(\d+)\s*(dias?|horas?)?'
    for match in re.finditer(pattern3, texto, re.IGNORECASE):
        prazos.append({
            "texto": match.group(0),
            "quantidade": match.group(1),
            "unidade": match.group(2) or "dias",
        })
    
    return prazos


def extrair_destinos(texto: str) -> List[str]:
    """
    Extrai unidades/destinos mencionados para encaminhamento.
    
    Args:
        texto: Texto do documento
        
    Returns:
        Lista de siglas de destino
    """
    if not texto:
        return []
    
    destinos = set()
    
    # Padrões de encaminhamento
    patterns = [
        r'encaminho\s+(?:para|ao|à)\s+(\w+)',
        r'remeto\s+(?:para|ao|à)\s+(\w+)',
        r'envio\s+(?:para|ao|à)\s+(\w+)',
        r'encaminhe-se\s+(?:para|ao|à)\s+(\w+)',
        r'à\s+(\w+)\s+para\s+(?:providências|conhecimento|análise|manifestação)',
        r'ao\s+(?:senhor\s+)?(?:diretor\s+)?(?:da\s+|do\s+)?(\w+)',
    ]
    
    for pattern in patterns:
        for match in re.finditer(pattern, texto, re.IGNORECASE):
            sigla = match.group(1).upper()
            # Filtrar palavras comuns que não são siglas
            palavras_ignorar = ['PARA', 'QUE', 'COM', 'POR', 'DOS', 'DAS', 'SENHOR', 'SENHORA', 
                               'PRESENTE', 'PROCESSO', 'CONHECIMENTO', 'PROVIDÊNCIAS', 'ANÁLISE']
            if len(sigla) >= 2 and sigla not in palavras_ignorar:
                destinos.add(sigla)
    
    return list(destinos)


def extrair_docs_mencionados(texto: str) -> List[str]:
    """
    Extrai IDs de documentos SEI mencionados no texto.
    
    Args:
        texto: Texto do documento
        
    Returns:
        Lista de doc_ids mencionados
    """
    if not texto:
        return []
    
    # Padrão: números SEI (normalmente 10 dígitos)
    pattern = r'\b(\d{10})\b'
    matches = re.findall(pattern, texto)
    
    # Padrão: "documento nº XXXX" ou "SEI nº XXXX"
    pattern2 = r'(?:documento|SEI|doc\.?)\s*n[ºº°]?\s*(\d+)'
    matches2 = re.findall(pattern2, texto, re.IGNORECASE)
    
    return list(set(matches + matches2))


# =============================================================================
# CLASSIFICAÇÃO DE ATO
# =============================================================================

def classificar_ato(tags: List[TagTecnica], tipo_documento: str) -> str:
    """
    Classifica o tipo de ato baseado nas tags e tipo do documento.
    
    Returns:
        String com o tipo de ato (ATO_DECISAO, ATO_COMANDO, etc.)
    """
    # Prioridade: ENCERRAMENTO > DECRETO > DECISAO > COMANDO > PEDIDO > FUNDAMENTACAO > TRAMITE
    
    # NOVO: Encerramento tem prioridade máxima
    if TagTecnica.TEM_ENCERRAMENTO in tags:
        return "ATO_ENCERRAMENTO"
    
    # NOVO: Decreto é decisão de alto nível
    if TagTecnica.TEM_DECRETO in tags:
        return "ATO_DECISAO"
    
    if TagTecnica.TEM_DECISAO in tags or TagTecnica.TEM_DEFERIMENTO in tags or TagTecnica.TEM_INDEFERIMENTO in tags:
        return "ATO_DECISAO"
    
    # NOVO: Manifestação favorável é tipo de decisão
    if TagTecnica.TEM_FAVORAVEL in tags:
        return "ATO_DECISAO"
    
    if TagTecnica.TEM_RECURSO in tags:
        return "ATO_RECURSO"
    
    if TagTecnica.TEM_COMANDO in tags:
        return "ATO_COMANDO"
    
    # Por tipo de documento
    tipo_upper = tipo_documento.upper() if tipo_documento else ""
    
    if "REQUERIMENTO" in tipo_upper or "SOLICITAÇÃO" in tipo_upper:
        return "ATO_PEDIDO"
    
    if "PARECER" in tipo_upper or "INFORMAÇÃO" in tipo_upper or "NOTA" in tipo_upper:
        return "ATO_FUNDAMENTACAO"
    
    if "DECRETO" in tipo_upper:
        return "ATO_DECISAO"
    
    if "TERMO" in tipo_upper and "ENCERRAMENTO" in tipo_upper:
        return "ATO_ENCERRAMENTO"
    
    if TagTecnica.MUDA_DESTINO in tags:
        return "ATO_TRAMITE"
    
    if TagTecnica.REPETITIVO in tags:
        return "ATO_TRAMITE"
    
    return "ATO_INFORMATIVO"


# =============================================================================
# FUNÇÕES AUXILIARES PARA CLASSIFICAÇÃO SEMÂNTICA
# =============================================================================

def classificar_documento_semantico(texto: str, titulo: str = "") -> Dict[str, any]:
    """
    Classifica semanticamente um documento.
    
    Returns:
        Dict com:
        - tipo_semantico: PEDIDO, DECISAO, ENCAMINHAMENTO, ENCERRAMENTO, INFORMATIVO
        - is_decisorio: bool
        - is_encerramento: bool
        - is_decreto: bool
        - is_pedido: bool
        - is_favoravel: True/False/None
        - is_orgao_externo: bool
    """
    tags = detectar_tags(texto)
    titulo_upper = titulo.upper() if titulo else ""
    
    resultado = {
        "tipo_semantico": "INFORMATIVO",
        "is_decisorio": False,
        "is_encerramento": False,
        "is_decreto": False,
        "is_pedido": False,
        "is_favoravel": None,
        "is_orgao_externo": False,
    }
    
    # Detectar órgão externo
    if TagTecnica.ORGAO_EXTERNO in tags:
        resultado["is_orgao_externo"] = True
    
    # Detectar Decreto
    if TagTecnica.TEM_DECRETO in tags or "DECRETO" in titulo_upper:
        resultado["tipo_semantico"] = "DECISAO"
        resultado["is_decisorio"] = True
        resultado["is_decreto"] = True
        return resultado
    
    # Detectar Termo de Encerramento
    if TagTecnica.TEM_ENCERRAMENTO in tags or "TERMO DE ENCERRAMENTO" in titulo_upper:
        resultado["tipo_semantico"] = "ENCERRAMENTO"
        resultado["is_encerramento"] = True
        return resultado
    
    # Detectar manifestação favorável
    if TagTecnica.TEM_FAVORAVEL in tags:
        resultado["is_favoravel"] = True
        resultado["tipo_semantico"] = "DECISAO"
        resultado["is_decisorio"] = True
        return resultado
    
    # Detectar decisão
    if TagTecnica.TEM_DECISAO in tags or TagTecnica.TEM_DEFERIMENTO in tags or TagTecnica.TEM_INDEFERIMENTO in tags:
        resultado["tipo_semantico"] = "DECISAO"
        resultado["is_decisorio"] = True
        return resultado
    
    # Detectar pedido/solicitação
    if re.search(r'PEDIMOS\s+PROVIDÊNCIAS|SOLICITO\s+MANIFESTAÇÃO|REQUER|SOLICIT', texto.upper()):
        resultado["tipo_semantico"] = "PEDIDO"
        resultado["is_pedido"] = True
        return resultado
    
    # Detectar determinação/comando
    if TagTecnica.TEM_COMANDO in tags or TagTecnica.MUDA_DESTINO in tags:
        resultado["tipo_semantico"] = "ENCAMINHAMENTO"
        return resultado
    
    return resultado
