"""
HEURÍSTICA LEVE - Pipeline v2.0
================================
Extrai sigla FIEL ao documento (exatamente como aparece no número do doc)
"""

import hashlib
import re
from typing import List, Dict, Any, Optional, Tuple

# ============================================================================
# CONFIGURAÇÃO
# ============================================================================

SIGLAS_COMANDO = {"CMDGER", "SUBCMD", "COMGER", "SUBCOMGER"}
TIPOS_EVIDENCIA = {"CERTIFICADO", "LAUDO", "ANEXO", "ATESTADO", "E-MAIL", "EMAIL", "COMPROVANTE", "DECLARAÇÃO"}
TIPOS_CONCLUSAO = {"PORTARIA", "DECRETO"}
TIPOS_DEMANDA_EXTERNA = {"OFÍCIO", "OFICIO", "OFÍCIO-CIRCULAR", "OFICIO-CIRCULAR"}


# ============================================================================
# FUNÇÕES AUXILIARES
# ============================================================================

def get_campo(doc: Dict, *campos) -> Any:
    """Busca valor em múltiplos nomes de campo possíveis."""
    for campo in campos:
        if campo in doc and doc[campo]:
            return doc[campo]
    return None


def extrair_sigla_do_numero_doc(texto: str) -> Optional[str]:
    """
    Extrai sigla FIEL do número do documento.
    
    Padrões:
    - "Ofício nº 1659/2025/CBMAC" → CBMAC
    - "Ofício nº 23748/2025/PMAC" → PMAC
    - "Memorando nº 248/2025/CBMAC - 1BEPCIF" → CBMAC - 1BEPCIF
    - "Despacho nº 2111/2025/PMAC - COMGER - GABIN" → PMAC - COMGER - GABIN
    - "Ofício nº 241/2026/SEAD" → SEAD
    """
    if not texto:
        return None
    
    # Padrão: "nº XXXX/YYYY/SIGLA" ou "nº XXXX/YYYY/ORGAO - SIGLA - SUBSIGLA"
    # Pega tudo após /YYYY/ até nova linha ou fim
    match = re.search(r'[Nn][ºo°]\s*\d+/\d{4}/([A-Z0-9]+(?:\s*-\s*[A-Z0-9]+)*)', texto.upper())
    if match:
        sigla_completa = match.group(1).strip()
        # Normalizar espaços ao redor dos hífens
        sigla_completa = re.sub(r'\s*-\s*', ' - ', sigla_completa)
        return sigla_completa
    
    return None


def extrair_sigla_origem(doc: Dict) -> str:
    """
    Extrai sigla FIEL ao documento.
    Prioriza o número do documento no conteúdo.
    """
    
    # 1. Buscar no conteúdo (número do documento)
    conteudo = get_campo(doc, 'conteudo', 'texto_limpo')
    if conteudo:
        sigla = extrair_sigla_do_numero_doc(conteudo[:1500])
        if sigla:
            return sigla
    
    # 2. Buscar no título
    titulo = get_campo(doc, 'titulo', 'titulo_arvore')
    if titulo:
        sigla = extrair_sigla_do_numero_doc(titulo)
        if sigla:
            return sigla
    
    return "DESCONHECIDO"


def extrair_tipo_documento(doc: Dict) -> str:
    """Extrai tipo do documento."""
    tipo = get_campo(doc, 'tipo_documento', 'tipo')
    if tipo:
        return normalizar_tipo_documento(tipo)
    
    titulo = get_campo(doc, 'titulo_arvore', 'titulo')
    if titulo:
        titulo_upper = titulo.upper()
        
        tipos_map = [
            ("MEMORANDO-CIRCULAR", ["MEMORANDO", "CIRCULAR"]),
            ("MEMORANDO", ["MEMORANDO"]),
            ("OFÍCIO-CIRCULAR", ["OFÍCIO", "CIRCULAR"]),
            ("OFÍCIO-CIRCULAR", ["OFICIO", "CIRCULAR"]),
            ("OFÍCIO", ["OFÍCIO"]),
            ("OFÍCIO", ["OFICIO"]),
            ("DESPACHO", ["DESPACHO"]),
            ("REQUERIMENTO", ["REQUERIMENTO"]),
            ("PORTARIA", ["PORTARIA"]),
            ("DECRETO", ["DECRETO"]),
            ("PARECER", ["PARECER"]),
            ("NOTA-BG", ["NOTA", "BG"]),
            ("NOTA-BG", ["NOTA", "BOLETIM"]),
            ("CERTIFICADO", ["CERTIFICADO"]),
            ("LAUDO", ["LAUDO"]),
            ("TERMO", ["TERMO"]),
            ("ANEXO", ["ANEXO"]),
            ("E-MAIL", ["E-MAIL"]),
            ("E-MAIL", ["EMAIL"]),
            ("MENSAGEM", ["MENSAGEM"]),
        ]
        
        for tipo_result, keywords in tipos_map:
            if all(kw in titulo_upper for kw in keywords):
                return tipo_result
    
    return "DESCONHECIDO"


def normalizar_tipo_documento(tipo: str) -> str:
    """Normaliza tipo de documento."""
    if not tipo:
        return "DESCONHECIDO"
    
    tipo_upper = tipo.upper().strip()
    
    normalizacao = {
        "OFÍCIO": ["OFÍCIO", "OFICIO"],
        "OFÍCIO-CIRCULAR": ["OFÍCIO-CIRCULAR", "OFICIO-CIRCULAR", "OFÍCIO CIRCULAR"],
        "MEMORANDO": ["MEMORANDO"],
        "MEMORANDO-CIRCULAR": ["MEMORANDO-CIRCULAR", "MEMORANDO CIRCULAR"],
        "DESPACHO": ["DESPACHO"],
        "REQUERIMENTO": ["REQUERIMENTO"],
        "PORTARIA": ["PORTARIA"],
        "DECRETO": ["DECRETO"],
        "NOTA-BG": ["NOTA PARA BG", "NOTA BG", "NOTA PARA BOLETIM"],
        "CERTIFICADO": ["CERTIFICADO"],
        "LAUDO": ["LAUDO"],
        "PARECER": ["PARECER"],
        "TERMO": ["TERMO"],
        "E-MAIL": ["E-MAIL", "EMAIL"],
        "ANEXO": ["ANEXO"],
        "MENSAGEM": ["MENSAGEM"],
    }
    
    for tipo_norm, variantes in normalizacao.items():
        for var in variantes:
            if var in tipo_upper:
                return tipo_norm
    
    return tipo_upper


def calcular_hash(texto: str) -> str:
    """Calcula hash MD5 do texto."""
    if not texto:
        return ""
    return hashlib.md5(texto.encode('utf-8', errors='ignore')).hexdigest()


def eh_sigla_externa(sigla: str) -> bool:
    """Verifica se a sigla é de órgão externo ao CBMAC."""
    if not sigla or sigla == "DESCONHECIDO":
        return False
    sigla_upper = sigla.upper().strip()
    # Se começa com PMAC, SEAD, TCE, etc
    externos = ["PMAC", "SEAD", "SEJUSP", "TCE", "MP", "MPE", "CASACIVIL", "PGE", "SEPA"]
    for ext in externos:
        if sigla_upper.startswith(ext):
            return True
    return False


def eh_sigla_comando(sigla: str) -> bool:
    """Verifica se é sigla do comando."""
    if not sigla:
        return False
    sigla_upper = sigla.upper().strip()
    for cmd in SIGLAS_COMANDO:
        if cmd in sigla_upper:
            return True
    return False


def get_formato(doc: Dict) -> str:
    """Extrai formato do documento."""
    formato = get_campo(doc, 'formato', 'tipo_detectado')
    if isinstance(formato, dict):
        formato = formato.get('detector', 'html')
    if formato:
        formato_lower = str(formato).lower()
        if 'html' in formato_lower:
            return 'html'
        if 'pdf' in formato_lower:
            return 'pdf'
        if 'image' in formato_lower or 'imagem' in formato_lower:
            return 'imagem'
    return 'html'


def get_conteudo(doc: Dict) -> str:
    """Extrai conteúdo do documento."""
    return get_campo(doc, 'conteudo', 'texto_limpo', 'texto_raw', 'texto') or ""


def get_titulo(doc: Dict) -> str:
    """Extrai título do documento."""
    return get_campo(doc, 'titulo_arvore', 'titulo') or ""


def get_doc_id(doc: Dict) -> str:
    """Extrai ID do documento."""
    return str(get_campo(doc, 'doc_id', 'id_documento', 'numero_sei') or "")


# ============================================================================
# CLASSIFICAÇÃO DE PRIORIDADE
# ============================================================================

def classificar_prioridade(doc: Dict[str, Any], posicao: int) -> Dict[str, Any]:
    """Classifica documento por prioridade."""
    tipo = extrair_tipo_documento(doc)
    sigla = extrair_sigla_origem(doc)
    formato = get_formato(doc)
    
    classificacao = {
        "prioridade": "MEDIA",
        "tipo": "TRAMITACAO",
        "eh_demandante": posicao == 1,
        "eh_externo": False,
        "eh_decisorio": False,
        "eh_conclusao": False,
        "motivo": ""
    }
    
    # ALTA - Primeiro documento
    if posicao == 1:
        classificacao["prioridade"] = "ALTA"
        classificacao["tipo"] = "DEMANDANTE"
        classificacao["eh_demandante"] = True
        if tipo in TIPOS_DEMANDA_EXTERNA and formato == "pdf" and eh_sigla_externa(sigla):
            classificacao["tipo"] = "DEMANDA_EXTERNA"
            classificacao["eh_externo"] = True
            classificacao["motivo"] = f"Demanda externa de {sigla}"
        else:
            classificacao["motivo"] = f"Primeiro documento ({tipo} de {sigla})"
        return classificacao
    
    # ALTA - Ofício PDF externo
    if tipo in TIPOS_DEMANDA_EXTERNA and formato == "pdf" and eh_sigla_externa(sigla):
        classificacao["prioridade"] = "ALTA"
        classificacao["tipo"] = "DEMANDA_EXTERNA"
        classificacao["eh_externo"] = True
        classificacao["motivo"] = f"Demanda externa de {sigla}"
        return classificacao
    
    # ALTA - Portaria/Decreto
    if tipo in TIPOS_CONCLUSAO:
        classificacao["prioridade"] = "ALTA"
        classificacao["tipo"] = "CONCLUSAO"
        classificacao["eh_conclusao"] = True
        classificacao["motivo"] = f"{tipo} de {sigla} = conclusão formal"
        return classificacao
    
    # ALTA - Despacho do comando
    if tipo == "DESPACHO" and eh_sigla_comando(sigla):
        classificacao["prioridade"] = "ALTA"
        classificacao["tipo"] = "ORDEM_COMANDO"
        classificacao["eh_decisorio"] = True
        classificacao["motivo"] = f"Despacho do {sigla} = ordem decisória"
        return classificacao
    
    # ALTA - Memorando
    if "MEMORANDO" in tipo:
        classificacao["prioridade"] = "ALTA"
        classificacao["tipo"] = "MEMORANDO"
        classificacao["motivo"] = f"Memorando de {sigla} = possível aprovação"
        return classificacao
    
    # ALTA - Requerimento
    if tipo == "REQUERIMENTO":
        classificacao["prioridade"] = "ALTA"
        classificacao["tipo"] = "ADITAMENTO"
        classificacao["motivo"] = f"Requerimento de {sigla} = nova demanda ou aditamento"
        return classificacao
    
    # ALTA - Nota BG
    if tipo == "NOTA-BG":
        classificacao["prioridade"] = "ALTA"
        classificacao["tipo"] = "PUBLICACAO"
        classificacao["motivo"] = f"Nota BG de {sigla} = aguarda publicação"
        return classificacao
    
    # MÉDIA - Despacho outras unidades
    if tipo == "DESPACHO":
        classificacao["prioridade"] = "MEDIA"
        classificacao["tipo"] = "TRAMITACAO"
        classificacao["motivo"] = f"Despacho de tramitação ({sigla})"
        return classificacao
    
    # MÉDIA - Parecer
    if tipo == "PARECER":
        classificacao["prioridade"] = "MEDIA"
        classificacao["tipo"] = "FUNDAMENTACAO"
        classificacao["motivo"] = f"Parecer de {sigla} = fundamentação"
        return classificacao
    
    # BAIXA - Evidências
    if tipo in TIPOS_EVIDENCIA:
        classificacao["prioridade"] = "BAIXA"
        classificacao["tipo"] = "EVIDENCIA"
        classificacao["motivo"] = f"{tipo} = documento de suporte"
        return classificacao
    
    # BAIXA - PDF não-ofício
    if formato == "pdf" and tipo not in TIPOS_DEMANDA_EXTERNA:
        classificacao["prioridade"] = "BAIXA"
        classificacao["tipo"] = "EVIDENCIA"
        classificacao["motivo"] = f"PDF interno ({tipo}) = evidência/anexo"
        return classificacao
    
    # MÉDIA - Padrão
    classificacao["motivo"] = f"Documento de tramitação ({tipo} de {sigla})"
    return classificacao


# ============================================================================
# AGRUPAMENTO E DEDUP
# ============================================================================

def agrupar_anexos(documentos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Agrupa anexos com documentos pais."""
    if not documentos:
        return []
    
    resultado = []
    doc_atual = None
    
    for doc in documentos:
        titulo = get_titulo(doc).upper()
        tipo = extrair_tipo_documento(doc)
        formato = get_formato(doc)
        sigla_atual = extrair_sigla_origem(doc)
        
        eh_anexo = (
            tipo == "ANEXO" or
            "ANEXO" in titulo or
            (formato in ["pdf", "imagem"] and 
             doc_atual is not None and
             extrair_sigla_origem(doc_atual) == sigla_atual and
             tipo not in TIPOS_DEMANDA_EXTERNA and
             tipo not in TIPOS_CONCLUSAO)
        )
        
        if eh_anexo and doc_atual is not None:
            if "anexos" not in doc_atual:
                doc_atual["anexos"] = []
            doc_atual["anexos"].append({
                "doc_id": get_doc_id(doc),
                "titulo": get_titulo(doc),
                "tipo": tipo,
                "formato": formato,
                "tamanho_chars": len(get_conteudo(doc))
            })
        else:
            if doc_atual is not None:
                resultado.append(doc_atual)
            doc_atual = doc.copy()
            doc_atual["anexos"] = doc_atual.get("anexos", [])
    
    if doc_atual is not None:
        resultado.append(doc_atual)
    
    return resultado


def deduplicar(documentos: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], int]:
    """Remove documentos duplicados."""
    vistos = set()
    resultado = []
    removidos = 0
    
    for doc in documentos:
        conteudo = get_conteudo(doc)
        hash_doc = calcular_hash(conteudo)
        if hash_doc and hash_doc in vistos:
            removidos += 1
            continue
        if hash_doc:
            vistos.add(hash_doc)
        resultado.append(doc)
    
    return resultado, removidos


# ============================================================================
# FUNÇÃO PRINCIPAL
# ============================================================================

def processar_heuristica_leve(documentos: List[Dict[str, Any]], nup: str = "") -> Dict[str, Any]:
    """Processa documentos com heurística leve."""
    if not documentos:
        return {
            "nup": nup,
            "sucesso": False,
            "erro": "Nenhum documento fornecido",
            "documentos": [],
            "metricas": {}
        }
    
    # 1. Ordenar
    docs_ordenados = sorted(
        documentos,
        key=lambda x: x.get("ordem_arvore", x.get("indice", 999))
    )
    
    # 2. Deduplicar
    docs_unicos, qtd_removidos = deduplicar(docs_ordenados)
    
    # 3. Agrupar anexos
    docs_agrupados = agrupar_anexos(docs_unicos)
    
    # 4. Classificar
    docs_classificados = []
    for i, doc in enumerate(docs_agrupados, start=1):
        doc_classificado = doc.copy()
        doc_classificado["classificacao"] = classificar_prioridade(doc, i)
        doc_classificado["posicao_processada"] = i
        doc_classificado["_tipo_normalizado"] = extrair_tipo_documento(doc)
        doc_classificado["_sigla_normalizada"] = extrair_sigla_origem(doc)
        doc_classificado["_formato"] = get_formato(doc)
        docs_classificados.append(doc_classificado)
    
    # 5. Métricas
    total_chars = sum(len(get_conteudo(d)) for d in docs_classificados)
    
    contagem_prioridade = {"ALTA": 0, "MEDIA": 0, "BAIXA": 0}
    contagem_tipo = {}
    
    for doc in docs_classificados:
        prio = doc["classificacao"]["prioridade"]
        tipo = doc["classificacao"]["tipo"]
        contagem_prioridade[prio] = contagem_prioridade.get(prio, 0) + 1
        contagem_tipo[tipo] = contagem_tipo.get(tipo, 0) + 1
    
    precisa_curador = len(docs_classificados) > 10 or total_chars > 120000
    
    return {
        "nup": nup,
        "sucesso": True,
        "erro": None,
        "documentos": docs_classificados,
        "metricas": {
            "total_original": len(documentos),
            "total_apos_dedup": len(docs_unicos),
            "total_apos_agrupamento": len(docs_classificados),
            "duplicados_removidos": qtd_removidos,
            "total_chars": total_chars,
            "total_anexos": sum(len(d.get("anexos", [])) for d in docs_classificados),
            "contagem_prioridade": contagem_prioridade,
            "contagem_tipo": contagem_tipo,
            "precisa_curador": precisa_curador,
            "motivo_curador": (
                f"docs={len(docs_classificados)}>10" if len(docs_classificados) > 10
                else f"chars={total_chars}>120k" if total_chars > 120000
                else None
            )
        },
        "decisao": {
            "fluxo": "CURADOR" if precisa_curador else "DIRETO",
            "docs_alta": contagem_prioridade["ALTA"],
            "docs_media": contagem_prioridade["MEDIA"],
            "docs_baixa": contagem_prioridade["BAIXA"]
        }
    }


def gerar_resumo_para_curador(resultado_heuristica: Dict[str, Any]) -> Dict[str, Any]:
    """Gera resumo para o Curador."""
    docs = resultado_heuristica.get("documentos", [])
    
    docs_resumidos = []
    for doc in docs:
        docs_resumidos.append({
            "doc_id": get_doc_id(doc),
            "posicao": doc.get("posicao_processada", 0),
            "tipo": doc.get("_tipo_normalizado", ""),
            "titulo": get_titulo(doc)[:100],
            "sigla": doc.get("_sigla_normalizada", ""),
            "formato": doc.get("_formato", ""),
            "chars": len(get_conteudo(doc)),
            "prioridade": doc.get("classificacao", {}).get("prioridade", ""),
            "tipo_classificado": doc.get("classificacao", {}).get("tipo", ""),
            "motivo": doc.get("classificacao", {}).get("motivo", ""),
            "qtd_anexos": len(doc.get("anexos", []))
        })
    
    return {
        "nup": resultado_heuristica.get("nup", ""),
        "total_docs": len(docs),
        "total_chars": resultado_heuristica.get("metricas", {}).get("total_chars", 0),
        "resumo_estrutural": resultado_heuristica.get("metricas", {}).get("contagem_tipo", {}),
        "documentos": docs_resumidos
    }
