"""
Adaptador

Converte o JSON do detalhar_processo.py atual para o formato DocV1.

CORREÇÃO v1.1: Extrai unidade_origem do CONTEÚDO do documento,
não do campo que vem da extração (que pode estar errado).

O problema original: O SEI retorna unidade_origem como a unidade 
onde está logado, não a unidade que CRIOU o documento.

Estrutura real do JSON do detalhar:
{
    "nup": "...",
    "diretoria": "...",
    "documentos": [
        {
            "indice": 1,
            "pasta": "I" ou "RAIZ",
            "titulo": "Despacho 23 (0018958063)",
            "id_documento": "20673446",
            "conteudo": "texto do documento...",
            "unidade_origem": "CBMAC - DRH",  <- PODE ESTAR ERRADO!
            "sigla_origem": "DRH",            <- PODE ESTAR ERRADO!
            ...
        }
    ]
}
"""

from typing import List, Dict, Any, Optional
from datetime import datetime
import re

from ..schemas import (
    DocV1, TipoDocumento, SituacaoDocumento, MetodoExtracao, TagTecnica,
    Autor, Assinatura, Referencias, InfoExtracao,
    criar_doc_v1
)
from .tags_detector import detectar_tags, extrair_destinos, extrair_docs_mencionados, classificar_documento_semantico


# =============================================================================
# MAPEAMENTO DE TIPOS
# =============================================================================

MAPA_TIPO_DOCUMENTO = {
    "despacho": TipoDocumento.DESPACHO,
    "requerimento": TipoDocumento.REQUERIMENTO,
    "memorando": TipoDocumento.MEMORANDO,
    "ofício": TipoDocumento.OFICIO,
    "oficio": TipoDocumento.OFICIO,
    "informação": TipoDocumento.INFORMACAO,
    "informacao": TipoDocumento.INFORMACAO,
    "parecer": TipoDocumento.PARECER,
    "nota técnica": TipoDocumento.NOTA_TECNICA,
    "nota tecnica": TipoDocumento.NOTA_TECNICA,
    "decisão": TipoDocumento.DECISAO,
    "decisao": TipoDocumento.DECISAO,
    "termo": TipoDocumento.TERMO_ENCERRAMENTO,
    "anexo": TipoDocumento.ANEXO,
    "nota para boletim": TipoDocumento.NOTA_BG,
    "nota bg": TipoDocumento.NOTA_BG,
    "portaria": TipoDocumento.PORTARIA,
    "ata": TipoDocumento.ATA,
    "certidão": TipoDocumento.CERTIDAO,
    "certidao": TipoDocumento.CERTIDAO,
    "ofício-circular": TipoDocumento.OFICIO,
    "calendário": TipoDocumento.ANEXO,
    "calendario": TipoDocumento.ANEXO,
    "decreto": TipoDocumento.DECRETO,
}


def mapear_tipo_documento(tipo_raw: str) -> TipoDocumento:
    """Mapeia tipo do SEI para enum"""
    if not tipo_raw:
        return TipoDocumento.OUTROS
    
    tipo_lower = tipo_raw.lower().strip()
    
    # Busca exata
    if tipo_lower in MAPA_TIPO_DOCUMENTO:
        return MAPA_TIPO_DOCUMENTO[tipo_lower]
    
    # Busca parcial
    for chave, valor in MAPA_TIPO_DOCUMENTO.items():
        if chave in tipo_lower or tipo_lower in chave:
            return valor
    
    return TipoDocumento.OUTROS


# =============================================================================
# MAPEAMENTO DE ÓRGÃOS EXTERNOS
# =============================================================================

ORGAOS_CONHECIDOS = {
    # Poder Judiciário
    "TJAC": {"nome": "Tribunal de Justiça do Estado do Acre", "tipo": "JUDICIARIO", "externo": True},
    "ASMIL": {"nome": "Assessoria Militar - TJAC", "tipo": "JUDICIARIO", "externo": True},
    "SEC-GSI": {"nome": "Secretaria do Gabinete de Segurança Institucional - TJAC", "tipo": "JUDICIARIO", "externo": True},
    
    # Governo do Estado
    "GOVERNADOR": {"nome": "Governador do Estado do Acre", "tipo": "EXECUTIVO", "externo": True},
    "CASACIVIL": {"nome": "Casa Civil", "tipo": "EXECUTIVO", "externo": True},
    "SEAD": {"nome": "Secretaria de Estado de Administração", "tipo": "EXECUTIVO", "externo": True},
    "SEAPE": {"nome": "Secretaria Adjunta de Pessoal - SEAD", "tipo": "EXECUTIVO", "externo": True},
    "DEVIDA": {"nome": "Departamento de Vida Funcional - SEAD", "tipo": "EXECUTIVO", "externo": True},
    "DIRGEP": {"nome": "Diretoria de Gestão de Pessoas - SEAD", "tipo": "EXECUTIVO", "externo": True},
    "DEGAB": {"nome": "Departamento de Gabinete - SEAD", "tipo": "EXECUTIVO", "externo": True},
    
    # CBMAC (não são externos)
    "CBMAC": {"nome": "Corpo de Bombeiros Militar do Estado do Acre", "tipo": "MILITAR", "externo": False},
    "CMDGER": {"nome": "Comando Geral - CBMAC", "tipo": "MILITAR", "externo": False},
    "DRH": {"nome": "Diretoria de Recursos Humanos - CBMAC", "tipo": "MILITAR", "externo": False},
    "COI": {"nome": "Comando Operacional do Interior - CBMAC", "tipo": "MILITAR", "externo": False},
    "COC": {"nome": "Comando Operacional da Capital - CBMAC", "tipo": "MILITAR", "externo": False},
    "DAL": {"nome": "Diretoria de Apoio Logístico - CBMAC", "tipo": "MILITAR", "externo": False},
    
    # Unidades Operacionais
    "1BEPCIF": {"nome": "1º Batalhão de Emergências e Proteção Civil", "tipo": "MILITAR", "externo": False},
    "2BEPCIF": {"nome": "2º Batalhão de Emergências e Proteção Civil", "tipo": "MILITAR", "externo": False},
    "3BEPCIF": {"nome": "3º Batalhão de Emergências e Proteção Civil", "tipo": "MILITAR", "externo": False},
    "4BEPCIF": {"nome": "4º Batalhão de Emergências e Proteção Civil", "tipo": "MILITAR", "externo": False},
    "2CIACIAER": {"nome": "2ª Companhia de Aviação", "tipo": "MILITAR", "externo": False},
}


# =============================================================================
# EXTRAÇÃO DE UNIDADE_ORIGEM DO CONTEÚDO (CORREÇÃO PRINCIPAL)
# =============================================================================

# Padrão 1: Número do documento com sigla
# Ex: "Despacho nº 3805/2024/CASACIVIL - GABIN"
PATTERN_NUM_DOC = re.compile(
    r'(?:Despacho|Ofício|Memorando|Termo|Parecer|Informação|Nota)\s*(?:nº|n°|n\.º)?\s*'
    r'[\d\.]+/\d{4}/([A-Z][A-Z0-9\-]+)(?:\s*[-–]\s*([A-Z][A-Z0-9]+))?',
    re.IGNORECASE
)

# Padrão 2: OF. Nº com sigla (formato TJAC)
# Ex: "OF. Nº 7338/ASMIL"
PATTERN_OF_SIGLA = re.compile(
    r'OF\.\s*(?:Nº|N°|N\.º)\s*[\d]+/([A-Z][A-Z0-9\-]+)',
    re.IGNORECASE
)

# Padrão 3: Cabeçalho institucional
CABECALHOS = {
    "PODER JUDICIÁRIO DO ESTADO DO ACRE": "TJAC",
    "TRIBUNAL DE JUSTIÇA DO ESTADO DO ACRE": "TJAC",
    "ESTADO DO ACRE\nCASA CIVIL": "CASACIVIL",
    "CASA CIVIL": "CASACIVIL",
    "SECRETARIA DE ESTADO DE ADMINISTRAÇÃO": "SEAD",
    "SECRETARIA DE ESTADO DA ADMINISTRAÇÃO": "SEAD",
    "CORPO DE BOMBEIROS MILITAR": "CBMAC",
    "ESTADO DO ACRE\nCORPO DE BOMBEIROS MILITAR": "CBMAC",
}

# Padrão 4: Decreto do Governador
PATTERN_DECRETO = re.compile(
    r'DECRETO\s*(?:Nº|N°|N\.º)\s*[\d\.\-]+\-?P?,?\s*DE',
    re.IGNORECASE
)

# Padrão 5: Termo de Encerramento com sigla
PATTERN_TERMO = re.compile(
    r'TERMO\s+DE\s+ENCERRAMENTO.*?(?:Nº|N°)\s*[\d]+/\d{4}/([A-Z][A-Z0-9\-]+)(?:\s*[-–]\s*([A-Z][A-Z0-9]+))?',
    re.IGNORECASE | re.DOTALL
)


def extrair_unidade_do_conteudo(conteudo: str) -> Dict[str, Optional[str]]:
    """
    Extrai a unidade de origem REAL do conteúdo do documento.
    
    Args:
        conteudo: Texto do documento
    
    Returns:
        Dict com:
        - unidade_origem_real: Sigla principal (ex: "CASACIVIL", "TJAC")
        - unidade_origem_detalhe: Detalhe/subdivisão (ex: "GABIN", "DEVIDA")
        - unidade_origem_completa: Formato completo (ex: "CASACIVIL - GABIN")
        - metodo_extracao_unidade: Como foi identificada
        - is_orgao_externo: Se é órgão externo ao CBMAC
    """
    resultado = {
        "unidade_origem_real": None,
        "unidade_origem_detalhe": None,
        "unidade_origem_completa": None,
        "metodo_extracao_unidade": None,
        "is_orgao_externo": False
    }
    
    if not conteudo:
        return resultado
    
    # 1. Tentar extrair do número do documento (mais confiável)
    match = PATTERN_NUM_DOC.search(conteudo)
    if match:
        sigla = match.group(1).upper()
        subsigla = match.group(2).upper() if match.group(2) else None
        resultado["unidade_origem_real"] = sigla
        resultado["unidade_origem_detalhe"] = subsigla
        resultado["unidade_origem_completa"] = f"{sigla} - {subsigla}" if subsigla else sigla
        resultado["metodo_extracao_unidade"] = "numero_documento"
        # Verificar se é externo
        info_orgao = ORGAOS_CONHECIDOS.get(sigla, {})
        resultado["is_orgao_externo"] = info_orgao.get("externo", sigla not in ["CBMAC", "DRH", "COI", "COC", "DAL", "CMDGER"])
        return resultado
    
    # 2. Tentar padrão OF. Nº (TJAC)
    match = PATTERN_OF_SIGLA.search(conteudo)
    if match:
        sigla = match.group(1).upper()
        resultado["unidade_origem_real"] = sigla
        resultado["unidade_origem_completa"] = sigla
        resultado["metodo_extracao_unidade"] = "oficio_sigla"
        info_orgao = ORGAOS_CONHECIDOS.get(sigla, {})
        resultado["is_orgao_externo"] = info_orgao.get("externo", True)
        return resultado
    
    # 3. Tentar padrão de Termo de Encerramento
    match = PATTERN_TERMO.search(conteudo)
    if match:
        sigla = match.group(1).upper()
        subsigla = match.group(2).upper() if match.group(2) else None
        resultado["unidade_origem_real"] = sigla
        resultado["unidade_origem_detalhe"] = subsigla
        resultado["unidade_origem_completa"] = f"{sigla} - {subsigla}" if subsigla else sigla
        resultado["metodo_extracao_unidade"] = "termo_encerramento"
        info_orgao = ORGAOS_CONHECIDOS.get(sigla, {})
        resultado["is_orgao_externo"] = info_orgao.get("externo", False)
        return resultado
    
    # 4. Verificar se é Decreto do Governador
    if PATTERN_DECRETO.search(conteudo):
        if re.search(r'Governador\s+do\s+Estado', conteudo, re.IGNORECASE):
            resultado["unidade_origem_real"] = "GOVERNADOR"
            resultado["unidade_origem_completa"] = "GOVERNADOR"
            resultado["metodo_extracao_unidade"] = "decreto_governador"
            resultado["is_orgao_externo"] = True
            return resultado
    
    # 5. Tentar extrair do cabeçalho institucional
    conteudo_upper = conteudo.upper()
    for cabecalho, sigla in sorted(CABECALHOS.items(), key=lambda x: -len(x[0])):
        if cabecalho.upper() in conteudo_upper:
            resultado["unidade_origem_real"] = sigla
            resultado["unidade_origem_completa"] = sigla
            resultado["metodo_extracao_unidade"] = "cabecalho_institucional"
            info_orgao = ORGAOS_CONHECIDOS.get(sigla, {})
            resultado["is_orgao_externo"] = info_orgao.get("externo", False)
            return resultado
    
    return resultado


# =============================================================================
# EXTRAÇÃO DE TIPO DO TÍTULO
# =============================================================================

def extrair_tipo_do_titulo(titulo: str) -> str:
    """
    Extrai o tipo do documento do título.
    Exemplo: "Despacho 23 (0018958063)" -> "Despacho"
    """
    if not titulo:
        return ""
    
    # Verificar se é Decreto
    if re.match(r'^Decreto', titulo, re.IGNORECASE):
        return "Decreto"
    
    # Verificar se é Termo de Encerramento
    if re.match(r'^Termo\s+de\s+Encerramento', titulo, re.IGNORECASE):
        return "Termo de Encerramento"
    
    # Pegar primeira palavra antes de número ou parênteses
    match = re.match(r'^([A-Za-zÀ-ú\s\-]+?)(?:\s+(?:Nº|nº|n°|N°|\d))', titulo)
    if match:
        return match.group(1).strip()
    
    match = re.match(r'^([A-Za-zÀ-ú\-]+)', titulo)
    if match:
        return match.group(1).strip()
    
    return ""


def extrair_numero_sei_do_titulo(titulo: str) -> str:
    """
    Extrai o número SEI do título.
    Exemplo: "Despacho 23 (0018958063)" -> "0018958063"
    """
    if not titulo:
        return ""
    
    match = re.search(r'\((\d{10})\)', titulo)
    if match:
        return match.group(1)
    return ""


# =============================================================================
# EXTRAÇÃO DE METADADOS DO TEXTO
# =============================================================================

def extrair_autor_do_texto(texto: str) -> Optional[Autor]:
    """
    Tenta extrair autor do rodapé do documento.
    """
    if not texto:
        return None
    
    # Padrão: "Documento assinado eletronicamente por ..."
    pattern1 = r'Documento assinado eletronicamente por\s+([^,\n]+)'
    match1 = re.search(pattern1, texto, re.IGNORECASE)
    if match1:
        nome = match1.group(1).strip()
        return Autor(nome=nome)
    
    # Padrão: procurar no final do documento
    linhas = texto.strip().split('\n')
    ultimas_linhas = linhas[-10:] if len(linhas) > 10 else linhas
    
    for linha in ultimas_linhas:
        # Detectar padrão de patente + nome
        pattern_patente = r'^(CEL|TEN CEL|MAJ|CAP|1º TEN|2º TEN|SUBTEN|1º SGT|2º SGT|3º SGT|CB|SD)\s+(.+)'
        match = re.match(pattern_patente, linha.strip(), re.IGNORECASE)
        if match:
            return Autor(
                nome=f"{match.group(1)} {match.group(2)}".strip(),
                cargo=match.group(1)
            )
    
    return None


def extrair_assinaturas_do_texto(texto: str) -> List[Assinatura]:
    """
    Extrai assinaturas do rodapé do documento SEI.
    """
    assinaturas = []
    
    if not texto:
        return assinaturas
    
    # Padrão completo com hora
    pattern_completo = r'Documento assinado eletronicamente por\s+([^,]+)\s*,\s*([^,]+)\s*,\s*em\s+(\d{2}/\d{2}/\d{4})\s*,\s*às\s+(\d{2}:\d{2})'
    
    for match in re.finditer(pattern_completo, texto, re.IGNORECASE):
        nome = match.group(1).strip()
        cargo = match.group(2).strip()
        data_str = match.group(3)
        hora_str = match.group(4)
        
        datahora = None
        datahora_raw = f"{data_str} {hora_str}"
        try:
            datahora = datetime.strptime(datahora_raw, "%d/%m/%Y %H:%M")
        except:
            try:
                datahora = datetime.strptime(data_str, "%d/%m/%Y")
            except:
                pass
        
        assinaturas.append(Assinatura(
            nome=nome,
            cargo=cargo,
            datahora=datahora,
            datahora_raw=datahora_raw
        ))
    
    # Se não encontrou com hora, tentar sem hora
    if not assinaturas:
        pattern_simples = r'Documento assinado eletronicamente por\s+([^,]+)\s*,?\s*([^,]*)\s*,?\s*em\s+(\d{2}/\d{2}/\d{4})'
        
        for match in re.finditer(pattern_simples, texto, re.IGNORECASE):
            nome = match.group(1).strip()
            cargo = match.group(2).strip() if match.group(2) else None
            data_str = match.group(3)
            
            datahora = None
            try:
                datahora = datetime.strptime(data_str, "%d/%m/%Y")
            except:
                pass
            
            assinaturas.append(Assinatura(
                nome=nome,
                cargo=cargo,
                datahora=datahora,
                datahora_raw=data_str
            ))
    
    return assinaturas


def extrair_info_criacao(texto: str) -> Dict[str, Any]:
    """
    Extrai informações de criação do documento.
    """
    info = {
        "criado_por": None,
        "versao": None,
        "modificado_por": None,
        "data_criacao": None,
        "data_criacao_raw": None,
    }
    
    if not texto:
        return info
    
    pattern = r'Criado por\s+([^,]+)\s*,\s*versão\s+(\d+)\s+por\s+([^\s]+)\s+em\s+(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2}:\d{2})'
    
    match = re.search(pattern, texto, re.IGNORECASE)
    if match:
        info["criado_por"] = match.group(1).strip()
        info["versao"] = int(match.group(2))
        info["modificado_por"] = match.group(3).strip()
        data_str = match.group(4)
        hora_str = match.group(5)
        info["data_criacao_raw"] = f"{data_str} {hora_str}"
        
        try:
            info["data_criacao"] = datetime.strptime(info["data_criacao_raw"], "%d/%m/%Y %H:%M:%S")
        except:
            pass
    
    return info


# =============================================================================
# CONVERSÃO PRINCIPAL
# =============================================================================

def converter_documento_para_doc_v1(
    doc_json: Dict[str, Any],
    nup: str,
    ordem: int = 0
) -> DocV1:
    """
    Converte um documento do JSON atual para DocV1.
    
    CORREÇÃO v1.1: Extrai unidade_origem do CONTEÚDO do documento,
    não apenas do campo que vem da extração.
    """
    # Extrair título e número SEI
    titulo = doc_json.get("titulo", "")
    
    # Número SEI
    numero_sei = extrair_numero_sei_do_titulo(titulo)
    if not numero_sei:
        numero_sei = str(doc_json.get("id_documento", ""))
    
    doc_id = str(doc_json.get("id_documento", numero_sei))
    
    # Texto
    texto_raw = doc_json.get("conteudo", "")
    texto_limpo = texto_raw.strip() if texto_raw else ""
    texto_limpo = re.sub(r'&nbsp;', ' ', texto_limpo)
    texto_limpo = re.sub(r'\s+', ' ', texto_limpo)
    
    # Tipo: extrair do título
    tipo_raw = extrair_tipo_do_titulo(titulo)
    tipo_documento = mapear_tipo_documento(tipo_raw)
    
    # Ordem e pasta
    ordem_doc = doc_json.get("indice", ordem)
    pasta = doc_json.get("pasta", "RAIZ")
    tree_path = [pasta] if pasta else []
    
    # Método de extração
    metodo_raw = doc_json.get("metodo_extracao", doc_json.get("origem_conteudo", ""))
    metodo = MetodoExtracao.VIEWER_HTML
    if "ocr" in str(metodo_raw).lower():
        metodo = MetodoExtracao.OCR
    elif "pdf" in str(metodo_raw).lower():
        metodo = MetodoExtracao.PDF_TEXT
    
    # Autor e assinaturas
    autor = extrair_autor_do_texto(texto_limpo)
    assinaturas = extrair_assinaturas_do_texto(texto_limpo)
    info_criacao = extrair_info_criacao(texto_limpo)
    
    # Data
    data_inclusao = None
    data_inclusao_raw = None
    
    if assinaturas and assinaturas[0].datahora:
        data_inclusao = assinaturas[0].datahora
        data_inclusao_raw = assinaturas[0].datahora_raw
    elif info_criacao.get("data_criacao"):
        data_inclusao = info_criacao["data_criacao"]
        data_inclusao_raw = info_criacao["data_criacao_raw"]
    else:
        match_data = re.search(r'em (\d{2}/\d{2}/\d{4})', texto_limpo)
        if match_data:
            try:
                data_inclusao = datetime.strptime(match_data.group(1), "%d/%m/%Y")
                data_inclusao_raw = match_data.group(1)
            except:
                pass
    
    if not autor and assinaturas:
        autor = Autor(
            nome=assinaturas[0].nome,
            cargo=assinaturas[0].cargo
        )
    
    # Situação
    situacao = SituacaoDocumento.ASSINADO
    if "minuta" in texto_limpo.lower():
        situacao = SituacaoDocumento.MINUTA
    
    # Páginas e tamanho
    paginas = doc_json.get("paginas", 0) or 0
    tamanho = doc_json.get("tamanho_bytes", 0) or len(texto_raw)
    
    # =========================================================================
    # CORREÇÃO v1.1: Extrair unidade_origem REAL do conteúdo
    # =========================================================================
    
    # Valores originais (podem estar errados)
    unidade_origem_original = doc_json.get("unidade_origem")
    sigla_origem_original = doc_json.get("sigla_origem")
    
    # Extrair unidade do conteúdo
    info_unidade = extrair_unidade_do_conteudo(texto_raw)
    
    # Se não conseguiu extrair do conteúdo, usar o original como fallback
    if not info_unidade["unidade_origem_real"]:
        info_unidade["unidade_origem_real"] = sigla_origem_original
        info_unidade["unidade_origem_completa"] = unidade_origem_original
        info_unidade["metodo_extracao_unidade"] = "fallback_original"
    
    # Classificação semântica
    info_semantica = classificar_documento_semantico(texto_raw, titulo)
    
    # =========================================================================
    # Criar DocV1
    # =========================================================================
    
    doc = DocV1(
        nup=nup,
        doc_id=doc_id,
        numero_sei=numero_sei,
        tipo_documento=tipo_documento,
        tipo_documento_raw=tipo_raw,
        titulo_arvore=titulo,
        ordem_arvore=ordem_doc,
        tree_path=tree_path,
        
        # Unidade original (pode estar errada)
        unidade_origem=unidade_origem_original,
        sigla_origem=sigla_origem_original,
        
        # Unidade corrigida (extraída do conteúdo)
        unidade_origem_real=info_unidade["unidade_origem_real"],
        unidade_origem_detalhe=info_unidade["unidade_origem_detalhe"],
        unidade_origem_completa=info_unidade["unidade_origem_completa"],
        metodo_extracao_unidade=info_unidade["metodo_extracao_unidade"],
        
        # Classificação semântica
        tipo_semantico=info_semantica["tipo_semantico"],
        is_decisorio=info_semantica["is_decisorio"],
        is_encerramento=info_semantica["is_encerramento"],
        is_decreto=info_semantica["is_decreto"],
        is_pedido=info_semantica["is_pedido"],
        is_favoravel=info_semantica["is_favoravel"],
        is_orgao_externo=info_unidade.get("is_orgao_externo", False) or info_semantica["is_orgao_externo"],
        
        # Autor e status
        autor=autor,
        situacao_documento=situacao,
        assinaturas=assinaturas,
        
        # Datas
        data_inclusao=data_inclusao,
        data_inclusao_raw=data_inclusao_raw,
        
        # Texto
        texto_raw=texto_raw,
        texto_limpo=texto_limpo,
        
        # Extração
        extracao=InfoExtracao(metodo=metodo),
        
        # Extras
        paginas=paginas,
        tamanho_bytes=tamanho,
    )
    
    # Detectar tags técnicas
    doc.tags_tecnicas = detectar_tags(texto_limpo)
    
    # Adicionar tag de órgão externo se aplicável
    if doc.is_orgao_externo and TagTecnica.ORGAO_EXTERNO not in doc.tags_tecnicas:
        doc.tags_tecnicas.append(TagTecnica.ORGAO_EXTERNO)
    
    # Referências
    destinos = extrair_destinos(texto_limpo)
    docs_mencionados = extrair_docs_mencionados(texto_limpo)
    doc.referencias = Referencias(
        menciona_docs=docs_mencionados,
        encaminha_para=destinos
    )
    
    # Calcular hash e data_ref
    doc.atualizar_hash()
    doc.definir_data_ref()
    
    return doc


def converter_json_para_docs_v1(json_detalhar: Dict[str, Any]) -> List[DocV1]:
    """
    Converte JSON completo do detalhar para lista de DocV1.
    """
    nup = json_detalhar.get("nup", "")
    documentos = json_detalhar.get("documentos", [])
    
    docs = []
    for idx, doc_json in enumerate(documentos):
        try:
            doc = converter_documento_para_doc_v1(doc_json, nup, idx)
            docs.append(doc)
        except Exception as e:
            print(f"Erro ao converter doc {idx}: {e}")
            continue
    
    return docs
