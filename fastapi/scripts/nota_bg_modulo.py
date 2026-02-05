#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
nota_bg_modulo.py - Módulo de Notas para Boletim Geral
PlattArgus WEB - CBMAC
Versão: 2.0 (com Memorando Inteligente)

INTEGRAÇÃO:
    No final do api.py, antes do `if __name__ == "__main__":`, adicione:

    # Módulo Nota BG
    from nota_bg_modulo import registrar_endpoints_nota_bg
    registrar_endpoints_nota_bg(app)

Endpoints criados:
    GET  /api/nota-bg/tipos              - Lista tipos de ato
    GET  /api/nota-bg/militar/buscar     - Busca militar (autocomplete)
    GET  /api/nota-bg/militar/{mat}      - Busca por matrícula
    POST /api/nota-bg/gerar              - Gera HTML da nota
    POST /api/nota-bg/inserir            - Insere no SEI
    GET  /api/nota-bg/autoridades        - Lista autoridades disponíveis
    POST /api/nota-bg/gerar-memorando    - Gera memorando inteligente com LLM

Formato padrão:
    [POSTO/GRAD] Mat. [MATRÍCULA] [NOME COMPLETO]
    Exemplo: MAJ QOBMEC Mat. 9268863-3 Gilmar Torres Marques Moura
"""

import os
import re
import json
import unicodedata
from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from openai import OpenAI

# Módulo centralizado de formatação
try:
    from formato_documentos import (
        formatar_destinatario,
        formatar_destinatario_simples,
        formatar_remetente,
        determinar_genero,
        formatar_nome,
        formatar_posto_grad,
        _determinar_vocativo
    )
    FORMATO_CENTRALIZADO = True
    print("[NOTA_BG] Módulo formato_documentos carregado", file=__import__('sys').stderr)
except ImportError as e:
    FORMATO_CENTRALIZADO = False
    print(f"[NOTA_BG] Módulo formato_documentos não disponível: {e}", file=__import__('sys').stderr)

# =============================================================================
# CONFIGURAÇÃO
# =============================================================================

EFETIVO_API_URL = os.getenv("EFETIVO_API_URL", "http://efetivo-api:3001")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
EFETIVO_API_KEY = os.getenv("EFETIVO_API_KEY", "gw_PlattArgusWeb2025_CBMAC")
SEI_RUNNER_URL = os.getenv("SEI_RUNNER_URL", "http://runner:8001")

# Tipo de documento no SEI (exato)
TIPO_DOCUMENTO_NOTA_BG = "Nota para Boletim Geral - BG - CBMAC"

# =============================================================================
# ENUMS
# =============================================================================

class TipoAto(str, Enum):
    # Férias
    FERIAS_CONCESSAO = "FÉRIAS - CONCESSÃO"
    FERIAS_APRESENTACAO = "FÉRIAS - APRESENTAÇÃO"
    FERIAS_SUSTACAO = "FÉRIAS - SUSTAÇÃO"
    FERIAS_INTERRUPCAO = "FÉRIAS - INTERRUPÇÃO"
    
    # Dispensa como recompensa
    DISPENSA_RECOMPENSA_CONCESSAO = "DISPENSA COMO RECOMPENSA - CONCESSÃO"
    DISPENSA_RECOMPENSA_APRESENTACAO = "DISPENSA COMO RECOMPENSA - APRESENTAÇÃO"
    
    # Dispensa geral
    DISPENSA_CONCESSAO = "DISPENSA - CONCESSÃO"
    DISPENSA_APRESENTACAO = "DISPENSA - APRESENTAÇÃO"
    
    # Licenças
    LICENCA_ESPECIAL_CONCESSAO = "LICENÇA ESPECIAL - CONCESSÃO"
    LICENCA_ESPECIAL_APRESENTACAO = "LICENÇA ESPECIAL - APRESENTAÇÃO"
    LICENCA_PATERNIDADE_CONCESSAO = "LICENÇA PATERNIDADE - CONCESSÃO"
    LICENCA_PATERNIDADE_APRESENTACAO = "LICENÇA PATERNIDADE - APRESENTAÇÃO"
    
    # Luto e Núpcias
    LUTO_CONCESSAO = "LUTO - CONCESSÃO"
    LUTO_APRESENTACAO = "LUTO - APRESENTAÇÃO"
    NUPCAS_CONCESSAO = "NÚPCIAS - CONCESSÃO"
    NUPCAS_APRESENTACAO = "NÚPCIAS - APRESENTAÇÃO"
    
    # Viagem
    VIAGEM_SERVICO = "VIAGEM A SERVIÇO DA CORPORAÇÃO - COM ÔNUS"
    
    # Outros
    ELOGIO = "ELOGIO"


class CategoriaAto(str, Enum):
    OFICIAIS = "OFICIAIS"
    PRACAS_ST_SGT = "PRACAS_ST_SGT"
    PRACAS_CB_SD = "PRACAS_CB_SD"
    CIVIS = "CIVIS"


# =============================================================================
# MODELOS PYDANTIC
# =============================================================================

class MilitarBusca(BaseModel):
    """Resultado de busca de militar"""
    matricula: str
    matricula_completa: str
    nome: str
    posto_grad: str
    lotacao: Optional[str] = None
    formatado: str


class NotaBGGerarRequest(BaseModel):
    """Request para gerar nota BG"""
    tipo_ato: str  # TipoAto enum value
    data_ato: str  # DD/MM/YYYY
    militar_nome: str
    militar_matricula: Optional[str] = None
    usuario_sei: str
    
    # Campos opcionais por tipo
    dias: Optional[int] = None
    periodo_aquisitivo: Optional[str] = None
    data_apresentacao: Optional[str] = None
    motivo: Optional[str] = None
    destino: Optional[str] = None
    origem: Optional[str] = None
    sei_processo: Optional[str] = None


class NotaBGInserirRequest(BaseModel):
    """Request para inserir nota no SEI"""
    nup: str
    html: str
    usuario_sei: str


class MemorandoInteligenteRequest(BaseModel):
    """Request para gerar memorando inteligente com LLM"""
    mensagem: str  # Ex: "ao COC informando que seguem as alterações de férias"
    publicacoes: List[Dict]  # Lista de publicações da nota BG
    remetente: Optional[Dict] = None  # Dados do remetente (nome, posto, cargo, matricula)
    ano: Optional[int] = None


# =============================================================================
# ALIASES DE AUTORIDADES (sinônimos para busca natural)
# =============================================================================

AUTORIDADES_ALIASES = {
    # COMANDO GERAL
    "CMDGER": ["CMDGER", "COMANDO GERAL", "COMANDANTE GERAL", "COMANDANTE-GERAL", "CG", "COMANDANTE", "CMD GERAL"],
    "SUBCMD": ["SUBCMD", "SUBCOMANDO", "SUBCOMANDANTE", "SUBCOMANDO GERAL", "SUB COMANDO", "SUB CMD"],

    # COMANDOS OPERACIONAIS
    "COC": ["COC", "COMANDO OPERACIONAL DA CAPITAL", "OPERACIONAL CAPITAL", "CMD OPERACIONAL CAPITAL"],
    "COI": ["COI", "COMANDO OPERACIONAL DO INTERIOR", "OPERACIONAL INTERIOR", "CMD OPERACIONAL INTERIOR"],
    "COA": ["COA", "COMANDO DE OPERACOES AEREAS", "OPERACOES AEREAS", "CMD AEREO"],
    "GOA": ["GOA", "GRUPAMENTO DE OPERACOES AEREAS", "1 GRUPAMENTO AEREO", "GRUPAMENTO AEREO"],

    # BATALHOES
    "1BEPCIF": ["1BEPCIF", "PRIMEIRO BATALHAO", "1 BATALHAO", "1 BEPCIF", "1BEP", "1º BATALHÃO", "1º BEP"],
    "2BEPCIF": ["2BEPCIF", "SEGUNDO BATALHAO", "2 BATALHAO", "2 BEPCIF", "2BEP", "2º BATALHÃO", "2º BEP"],
    "3BEPCIF": ["3BEPCIF", "TERCEIRO BATALHAO", "3 BATALHAO", "3 BEPCIF", "3BEP", "3º BATALHÃO", "3º BEP"],
    "4BEPCIF": ["4BEPCIF", "QUARTO BATALHAO", "4 BATALHAO", "4 BEPCIF", "4BEP", "4º BATALHÃO", "4º BEP"],
    "5BEPCIF": ["5BEPCIF", "QUINTO BATALHAO", "5 BATALHAO", "5 BEPCIF", "5BEP", "5º BATALHÃO", "5º BEP"],
    "6BEPCIF": ["6BEPCIF", "SEXTO BATALHAO", "6 BATALHAO", "6 BEPCIF", "6BEP", "6º BATALHÃO", "6º BEP"],
    "7BEPCIF": ["7BEPCIF", "SETIMO BATALHAO", "7 BATALHAO", "7 BEPCIF", "7BEP", "7º BATALHÃO", "7º BEP"],
    "8BEPCIF": ["8BEPCIF", "OITAVO BATALHAO", "8 BATALHAO", "8 BEPCIF", "8BEP", "8º BATALHÃO", "8º BEP"],
    "9BEPCIF": ["9BEPCIF", "NONO BATALHAO", "9 BATALHAO", "9 BEPCIF", "9BEP", "9º BATALHÃO", "9º BEP"],

    # DIRETORIAS
    "DRH": ["DRH", "RECURSOS HUMANOS", "DIRETORIA DE RH", "DIRETORIA DE RECURSOS HUMANOS", "DIRETOR DE RH"],
    "DEI": ["DEI", "DIRETORIA DE ENSINO", "ENSINO E INSTRUCAO", "DIRETORIA DE ENSINO E INSTRUCAO", "ENSINO"],
    "DLPF": ["DLPF", "DIRETORIA DE LOGISTICA", "LOGISTICA PATRIMONIO E FINANCAS", "LOGISTICA", "DAL"],
    "DSAU": ["DSAU", "DS", "DIRETORIA DE SAUDE", "SAUDE"],
    "DATOP": ["DATOP", "DIRETORIA DE ATIVIDADES TECNICAS", "ATIVIDADES TECNICAS E OPERACIONAIS"],
    "DPLAN": ["DPLAN", "DIRETORIA DE PLANEJAMENTO", "PLANEJAMENTO"],

    # ASSESSORIAS
    "AJGER": ["AJGER", "AJUDANCIA GERAL", "AJUDANCIA"],
    "ASSJUR": ["ASSJUR", "ASSESSORIA JURIDICA", "JURIDICO"],
    "ASCOM": ["ASCOM", "ASSESSORIA DE COMUNICACAO", "COMUNICACAO"],
    "ASSINT": ["ASSINT", "ASSESSORIA DE INTELIGENCIA", "INTELIGENCIA"],

    # OUTROS
    "CORGER": ["CORGER", "CORREGEDORIA", "CORREGEDOR"],
    "CNTINT": ["CNTINT", "CONTROLADORIA INTERNA", "CONTROLADORIA"],
    "DEPTIC": ["DEPTIC", "TECNOLOGIA DA INFORMACAO", "TI", "TIC", "INFORMATICA"],
    "CEMAN": ["CEMAN", "CENTRO DE MANUTENCAO", "MANUTENCAO"],
}


def identificar_autoridade_por_texto(texto: str) -> Optional[str]:
    """
    Identifica a chave de autoridade a partir de texto natural.
    Ex: "ao COC" -> "COC", "para o Comandante Geral" -> "CMDGER"
    """
    texto_upper = normalize_text(texto)

    # Remove preposições comuns
    texto_limpo = re.sub(r'\b(AO|A|PARA|PARA O|PARA A|DO|DA|AOS|AS)\b', '', texto_upper).strip()

    for chave, aliases in AUTORIDADES_ALIASES.items():
        for alias in aliases:
            alias_norm = normalize_text(alias)
            if alias_norm in texto_limpo or texto_limpo in alias_norm:
                return chave

    return None


# =============================================================================
# UTILITÁRIOS
# =============================================================================

def normalize_text(text: str) -> str:
    """Remove acentos para busca"""
    if not text:
        return ""
    nfkd = unicodedata.normalize('NFKD', text)
    return ''.join(c for c in nfkd if not unicodedata.combining(c)).upper()


def numero_por_extenso(n: int) -> str:
    """Converte número para extenso"""
    extensos = {
        1: "um", 2: "dois", 3: "três", 4: "quatro", 5: "cinco",
        6: "seis", 7: "sete", 8: "oito", 9: "nove", 10: "dez",
        11: "onze", 12: "doze", 13: "treze", 14: "quatorze", 15: "quinze",
        16: "dezesseis", 17: "dezessete", 18: "dezoito", 19: "dezenove",
        20: "vinte", 21: "vinte e um", 22: "vinte e dois", 23: "vinte e três",
        24: "vinte e quatro", 25: "vinte e cinco", 26: "vinte e seis",
        27: "vinte e sete", 28: "vinte e oito", 29: "vinte e nove",
        30: "trinta", 60: "sessenta", 90: "noventa"
    }
    return extensos.get(n, str(n))


def formatar_data_extenso(data_str: str) -> str:
    """Converte DD/MM/YYYY para 'DD de mês de YYYY'"""
    meses = [
        "janeiro", "fevereiro", "março", "abril", "maio", "junho",
        "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"
    ]
    try:
        dt = datetime.strptime(data_str, "%d/%m/%Y")
        return f"{dt.day:02d} de {meses[dt.month - 1]} de {dt.year}"
    except:
        return data_str


def classificar_categoria(posto_grad: str) -> CategoriaAto:
    """Classifica militar por categoria"""
    posto_upper = posto_grad.upper() if posto_grad else ""
    
    oficiais = ["CEL", "TEN CEL", "TC", "MAJ", "CAP", "1º TEN", "2º TEN", "1° TEN", "2° TEN", "TEN"]
    st_sgt = ["ST", "SUB TEN", "1º SGT", "2º SGT", "3º SGT", "1° SGT", "2° SGT", "3° SGT", "SGT"]
    cb_sd = ["CB", "SD"]
    
    for posto in oficiais:
        if posto in posto_upper:
            return CategoriaAto.OFICIAIS
    
    for posto in st_sgt:
        if posto in posto_upper:
            return CategoriaAto.PRACAS_ST_SGT
    
    for posto in cb_sd:
        if posto in posto_upper:
            return CategoriaAto.PRACAS_CB_SD
    
    return CategoriaAto.CIVIS


# =============================================================================
# CLIENTE API DE EFETIVO
# =============================================================================

async def buscar_militar_api(query: str, limit: int = 10) -> List[Dict]:
    """Busca militar na API de efetivo"""
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(
                f"{EFETIVO_API_URL}/efetivo/search",
                params={"q": query, "limit": limit},
                headers={"X-API-Key": EFETIVO_API_KEY}
            )
            response.raise_for_status()
            data = response.json()
            return data.get("records", [])
        except Exception as e:
            print(f"Erro ao buscar militar: {e}")
            return []


async def buscar_militar_por_matricula(matricula: str) -> Optional[Dict]:
    """Busca militar por matrícula exata"""
    # A API de Efetivo aceita matricula completa (com hifen) ou apenas numeros
    # Primeiro tenta com a matricula como veio
    mat_busca = matricula.strip()

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(
                f"{EFETIVO_API_URL}/efetivo/{mat_busca}",
                headers={"X-API-Key": EFETIVO_API_KEY}
            )
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"Erro ao buscar matrícula: {e}")
            return None


def formatar_militar(record: Dict) -> MilitarBusca:
    """Formata registro da API no padrão"""
    matricula = record.get("matricula", "")
    nome = record.get("nome", "")
    posto_grad = record.get("posto_grad", "")
    lotacao = record.get("lotacao", "")
    
    # Formato padrão: "MAJ QOBMEC Mat. 9268863-3 Gilmar Torres Marques Moura"
    formatado = f"{posto_grad} Mat. {matricula} {nome}".strip()
    
    mat_base = matricula.split("-")[0] if "-" in matricula else matricula
    
    return MilitarBusca(
        matricula=mat_base,
        matricula_completa=matricula,
        nome=nome,
        posto_grad=posto_grad,
        lotacao=lotacao,
        formatado=formatado
    )


# =============================================================================
# TEMPLATES DE NOTAS
# =============================================================================

TEMPLATES = {
    "FÉRIAS - CONCESSÃO": "Concedo, a contar da data acima, {dias} ({dias_extenso}) dias de férias ao {militar}, referente ao período aquisitivo de {periodo}. Devendo apresentar-se em {data_apresentacao}.",
    
    "FÉRIAS - APRESENTAÇÃO": "Apresentou-se na data acima, por término de {dias} ({dias_extenso}) dias de férias, o {militar}, referente ao período aquisitivo de {periodo}.",
    
    "FÉRIAS - SUSTAÇÃO": "Autorizo sustar na data acima, {dias} ({dias_extenso}) dias de férias, do {militar}, referente ao período aquisitivo de {periodo}, por necessidade do serviço, devendo ser usufruídas a partir de {data_apresentacao}.",
    
    "FÉRIAS - INTERRUPÇÃO": "Autorizo interromper na data acima, as férias do {militar}, referente ao período aquisitivo de {periodo}, por necessidade do serviço, restando {dias} ({dias_extenso}) dias a serem usufruídos oportunamente.",
    
    "DISPENSA COMO RECOMPENSA - CONCESSÃO": "Concedo, a contar da data acima, {dias} ({dias_extenso}) dias de dispensa como recompensa, ao {militar}, {motivo}. Devendo apresentar-se em {data_apresentacao}.",
    
    "DISPENSA COMO RECOMPENSA - APRESENTAÇÃO": "Apresentou-se na data acima, por término de {dias} ({dias_extenso}) dias de dispensa como recompensa, o {militar}.",
    
    "DISPENSA - CONCESSÃO": "Concedo, a contar da data acima, {dias} ({dias_extenso}) dias de dispensa, ao {militar}, {motivo}. Devendo apresentar-se em {data_apresentacao}.",
    
    "DISPENSA - APRESENTAÇÃO": "Apresentou-se na data acima, por término de {dias} ({dias_extenso}) dias de dispensa, o {militar}.",
    
    "LICENÇA ESPECIAL - CONCESSÃO": "Concedo, a contar da data acima, {dias} ({dias_extenso}) dias de Licença Especial, ao {militar}, referente ao período aquisitivo de {periodo}. Devendo apresentar-se em {data_apresentacao}.",
    
    "LICENÇA ESPECIAL - APRESENTAÇÃO": "Apresentou-se na data acima, por término de {dias} ({dias_extenso}) dias de Licença Especial, o {militar}, referente ao período aquisitivo de {periodo}.",
    
    "LICENÇA PATERNIDADE - CONCESSÃO": "Concedo, a contar da data acima, {dias} ({dias_extenso}) dias de Licença Paternidade, ao {militar}. Devendo apresentar-se em {data_apresentacao}.",
    
    "LICENÇA PATERNIDADE - APRESENTAÇÃO": "Apresentou-se na data acima, por término de {dias} ({dias_extenso}) dias de Licença Paternidade, o {militar}.",
    
    "LUTO - CONCESSÃO": "Concedo, a contar da data acima, {dias} ({dias_extenso}) dias de dispensa por motivo de luto, ao {militar}, em virtude do falecimento de {motivo}. Devendo apresentar-se em {data_apresentacao}.",
    
    "LUTO - APRESENTAÇÃO": "Apresentou-se na data acima, por término de {dias} ({dias_extenso}) dias de dispensa por motivo de luto, o {militar}.",
    
    "NÚPCIAS - CONCESSÃO": "Concedo, a contar da data acima, {dias} ({dias_extenso}) dias de dispensa por motivo de núpcias, ao {militar}. Devendo apresentar-se em {data_apresentacao}.",
    
    "NÚPCIAS - APRESENTAÇÃO": "Apresentou-se na data acima, por término de {dias} ({dias_extenso}) dias de dispensa por motivo de núpcias, o {militar}.",
    
    "VIAGEM A SERVIÇO DA CORPORAÇÃO - COM ÔNUS": "Viajou na data acima, o {militar}, autorizado pelo Comandante Geral do CBMAC, de {origem} com destino a {destino}, para {motivo}. O retorno está previsto para {data_apresentacao}.",
    
    "ELOGIO": "Elogio o {militar}, {motivo}.",
}


def gerar_texto_nota(
    tipo_ato: str,
    militar: MilitarBusca,
    dias: Optional[int] = None,
    periodo: Optional[str] = None,
    data_apresentacao: Optional[str] = None,
    motivo: Optional[str] = None,
    origem: Optional[str] = None,
    destino: Optional[str] = None,
    sei_processo: Optional[str] = None,
) -> str:
    """Gera o texto da nota baseado no template"""
    
    template = TEMPLATES.get(tipo_ato, "")
    if not template:
        return f"[Template não encontrado para: {tipo_ato}]"
    
    vars_nota = {
        "militar": militar.formatado,
        "dias": str(dias) if dias else "",
        "dias_extenso": numero_por_extenso(dias) if dias else "",
        "periodo": periodo or "",
        "data_apresentacao": formatar_data_extenso(data_apresentacao) if data_apresentacao else "",
        "motivo": motivo or "",
        "origem": origem or "",
        "destino": destino or "",
    }
    
    texto = template.format(**vars_nota)
    
    if sei_processo:
        texto += f" (SEI nº {sei_processo})"
    
    return texto


def gerar_html_nota(tipo_ato: str, data_ato: str, texto_corpo: str) -> str:
    """Gera HTML completo da nota no formato SEI"""

    html = f"""<p style="text-align: left;"><strong>{tipo_ato}</strong></p>
<p style="text-align: left;"><strong>Em {data_ato},</strong></p>
<p style="text-align: justify;">{texto_corpo}</p>"""

    return html


# =============================================================================
# MEMORANDO INTELIGENTE (LLM)
# =============================================================================

async def buscar_autoridade_db(chave: str) -> Optional[Dict]:
    """Busca autoridade no banco SQLite."""
    try:
        from autoridades_db import AutoridadesDB
        db = AutoridadesDB()
        return db.buscar(chave)
    except Exception as e:
        print(f"Erro ao buscar autoridade {chave}: {e}")
        return None


async def listar_autoridades_db() -> List[Dict]:
    """Lista todas as autoridades ativas."""
    try:
        from autoridades_db import AutoridadesDB
        db = AutoridadesDB()
        return db.listar_todas(apenas_ativas=True)
    except Exception as e:
        print(f"Erro ao listar autoridades: {e}")
        return []


def gerar_resumo_publicacoes(publicacoes: List[Dict]) -> str:
    """Gera resumo das publicações para o memorando."""
    if not publicacoes:
        return "alterações diversas"

    contagem = {}
    for pub in publicacoes:
        tipo = pub.get('tipo_ato', '') or pub.get('tipo_ato_texto', '')
        tipo_upper = tipo.upper()

        # Categoriza por tipo de ato
        if 'FERIAS' in tipo_upper or 'FÉRIAS' in tipo_upper:
            if 'SUSTACAO' in tipo_upper or 'SUSTAÇÃO' in tipo_upper or 'INTERRUP' in tipo_upper:
                contagem['sustação de férias'] = contagem.get('sustação de férias', 0) + 1
            elif 'CANCEL' in tipo_upper:
                contagem['cancelamento de férias'] = contagem.get('cancelamento de férias', 0) + 1
            elif 'ALTER' in tipo_upper or 'REMANEJ' in tipo_upper:
                contagem['alteração de férias'] = contagem.get('alteração de férias', 0) + 1
            else:
                contagem['férias'] = contagem.get('férias', 0) + 1
        elif 'VIAGEM' in tipo_upper:
            contagem['viagem a serviço'] = contagem.get('viagem a serviço', 0) + 1
        elif 'TRANSFERENCIA' in tipo_upper or 'TRANSFERÊNCIA' in tipo_upper:
            contagem['transferência'] = contagem.get('transferência', 0) + 1
        elif 'DISPENSA' in tipo_upper:
            contagem['dispensa médica'] = contagem.get('dispensa médica', 0) + 1
        elif 'LICENCA' in tipo_upper or 'LICENÇA' in tipo_upper:
            contagem['licença'] = contagem.get('licença', 0) + 1
        elif 'ELOGIO' in tipo_upper:
            contagem['elogio'] = contagem.get('elogio', 0) + 1
        elif 'APRESENT' in tipo_upper:
            contagem['apresentação'] = contagem.get('apresentação', 0) + 1
        elif 'MOVIMENT' in tipo_upper:
            contagem['movimentação'] = contagem.get('movimentação', 0) + 1
        else:
            contagem['outras alterações'] = contagem.get('outras alterações', 0) + 1

    partes = []
    for tipo, qtd in contagem.items():
        if qtd == 1:
            partes.append(f"1 (uma) {tipo}")
        else:
            # Pluraliza corretamente
            tipo_plural = tipo
            if tipo.endswith('ão'):
                tipo_plural = tipo[:-2] + 'ões'
            elif not tipo.endswith('s'):
                tipo_plural = tipo + 's'
            partes.append(f"{qtd} ({numero_por_extenso(qtd)}) {tipo_plural}")

    return ', '.join(partes)


async def gerar_memorando_llm(
    mensagem: str,
    publicacoes: List[Dict],
    autoridade: Optional[Dict],
    remetente: Optional[Dict],
    ano: int
) -> Dict:
    """
    Usa LLM para gerar texto formal do memorando.

    Args:
        mensagem: Descrição natural do usuário
        publicacoes: Lista de publicações da nota BG
        autoridade: Dados da autoridade destinatária
        remetente: Dados do remetente
        ano: Ano do memorando

    Returns:
        Dict com html, texto_plano, destinatario
    """
    if not OPENAI_API_KEY:
        # Fallback sem LLM
        return gerar_memorando_template(publicacoes, autoridade, remetente, ano)

    try:
        client = OpenAI(api_key=OPENAI_API_KEY)

        resumo = gerar_resumo_publicacoes(publicacoes)
        qtd_pubs = len(publicacoes)

        # Monta contexto do destinatário (formato: Nome - POSTO)
        dest_nome_raw = ""
        dest_posto = ""
        dest_cargo = ""
        if autoridade:
            dest_nome_raw = autoridade.get('nome_atual', '')
            dest_posto = autoridade.get('posto_grad', '')
            dest_cargo = autoridade.get('unidade_destino', '')

        # Formata nome do destinatário (mantém separado do posto para gerar_html_memorando)
        if FORMATO_CENTRALIZADO:
            dest_nome = formatar_nome(dest_nome_raw)
            # Versão para prompt com posto incluído
            dest_display = f"{dest_nome} - {formatar_posto_grad(dest_posto)}" if dest_posto else dest_nome
        else:
            dest_nome = dest_nome_raw.title() if dest_nome_raw else ''
            dest_display = f"{dest_nome} - {dest_posto.upper()}" if dest_posto else dest_nome

        # Monta contexto do remetente (formato: Nome - POSTO)
        rem_nome_raw = ""
        rem_posto = ""
        rem_cargo = ""
        rem_matricula = ""
        if remetente:
            rem_nome_raw = remetente.get('nome', '')
            rem_posto = remetente.get('posto', '') or remetente.get('posto_grad', '')
            rem_cargo = remetente.get('cargo', '')
            rem_matricula = remetente.get('matricula', '')

        # Formata nome do remetente (sem posto - será adicionado por gerar_html_memorando)
        if FORMATO_CENTRALIZADO:
            rem_nome = formatar_nome(rem_nome_raw)
        else:
            rem_nome = rem_nome_raw.title() if rem_nome_raw else ''

        # Determina vocativo baseado no cargo e gênero
        if FORMATO_CENTRALIZADO:
            genero = determinar_genero(dest_nome_raw, dest_cargo)
            vocativo_sugerido = _determinar_vocativo(dest_cargo, genero)
        else:
            if dest_cargo:
                cargo_lower = dest_cargo.lower()
                if 'comandante' in cargo_lower:
                    vocativo_sugerido = "Senhor Comandante"
                elif 'diretor' in cargo_lower:
                    vocativo_sugerido = "Senhor Diretor"
                elif 'subcomandante' in cargo_lower:
                    vocativo_sugerido = "Senhor Subcomandante-Geral"
                elif 'chefe' in cargo_lower:
                    vocativo_sugerido = "Senhor Chefe"
                else:
                    vocativo_sugerido = "Senhor"
            else:
                vocativo_sugerido = "Senhor"

        # Detecta se tem instrução do usuário
        tem_instrucao = mensagem and mensagem.strip() and len(mensagem.strip()) > 5

        # Monta bloco de instrução para o prompt
        if tem_instrucao:
            instrucao_bloco = f"""
INSTRUÇÃO DO USUÁRIO (interpretar e incorporar):
"{mensagem}"

IMPORTANTE: O usuário pode ter:
- Ditado por voz (pode ter erros de transcrição - interprete o sentido)
- Digitado abreviado (ex: "urgente", "p/ publicação imediata")
- Dado contexto específico (ex: "são alterações de janeiro", "referente ao mês anterior")

Incorpore o SENTIDO da instrução no corpo do memorando de forma FORMAL e CONCISA."""
        else:
            instrucao_bloco = """
SEM INSTRUÇÃO ESPECÍFICA DO USUÁRIO.

Gere um memorando PADRÃO de encaminhamento, mencionando:
- Que segue anexa a Nota para Boletim Geral
- O tipo de alterações contidas
- Solicitação de apreciação e publicação"""

        prompt = f"""Você é um redator oficial do Corpo de Bombeiros Militar do Acre (CBMAC).
Gere o CORPO de um memorando formal de encaminhamento de Nota para Boletim Geral.

CONTEXTO DO DOCUMENTO:
- Destinatário: {dest_display or '[a ser definido]'} - {dest_cargo or '[cargo]'}
- Remetente: {rem_nome or '[remetente]'} - {rem_cargo or '[cargo]'}
- A nota contém {qtd_pubs} alteração(ões): {resumo}
{instrucao_bloco}

REGRAS DO CBMAC (OBRIGATÓRIAS):
1. Texto FORMAL, CONCISO, OBJETIVO - estilo militar/institucional
2. Máximo 2 parágrafos CURTOS (2-3 linhas cada)
3. Inicie com "Com os cumprimentos de estilo, encaminho a Vossa Senhoria..."
4. Mencione "Nota para Boletim Geral" (não abrevie como "Nota BG")
5. Finalize solicitando apreciação e publicação
6. NUNCA seja prolixo - vá DIRETO ao ponto
7. Use "Vossa Senhoria" (não "V.Sa." nem "Senhor")

VOCATIVO CORRETO: {vocativo_sugerido}

FORMATO DE SAÍDA (JSON válido):
{{
    "vocativo": "{vocativo_sugerido}",
    "corpo": "Com os cumprimentos de estilo, encaminho a Vossa Senhoria...",
    "fechamento": "Atenciosamente"
}}

Responda SOMENTE com o JSON, sem explicações ou texto adicional."""

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=500
        )

        texto_resposta = response.choices[0].message.content.strip()

        # Tenta parsear JSON
        try:
            # Remove markdown code blocks se houver
            if texto_resposta.startswith("```"):
                texto_resposta = re.sub(r'^```json?\n?', '', texto_resposta)
                texto_resposta = re.sub(r'\n?```$', '', texto_resposta)

            dados = json.loads(texto_resposta)
            vocativo = dados.get('vocativo', 'Senhor Comandante')
            corpo = dados.get('corpo', '')
            fechamento = dados.get('fechamento', 'Atenciosamente')
        except json.JSONDecodeError:
            # Fallback: usa texto direto
            vocativo = "Senhor Comandante"
            corpo = texto_resposta
            fechamento = "Atenciosamente"

        # Gera HTML do memorando
        html = gerar_html_memorando(
            destinatario_nome=dest_nome,
            destinatario_cargo=dest_cargo,
            vocativo=vocativo,
            corpo=corpo,
            fechamento=fechamento,
            remetente_nome=rem_nome,
            remetente_cargo=rem_cargo,
            remetente_matricula=rem_matricula,
            ano=ano,
            remetente_posto=rem_posto,
            destinatario_posto=dest_posto
        )

        # Formata nome para retorno
        dest_nome_retorno = dest_nome
        if dest_posto:
            if FORMATO_CENTRALIZADO:
                dest_nome_retorno = f"{dest_nome} - {formatar_posto_grad(dest_posto)}"
            else:
                dest_nome_retorno = f"{dest_nome} - {dest_posto.upper()}"

        return {
            "sucesso": True,
            "html": html,
            "vocativo": vocativo,
            "corpo": corpo,
            "fechamento": fechamento,
            "destinatario": {
                "nome": dest_nome_retorno,
                "cargo": dest_cargo,
                "chave": autoridade.get('chave_busca') if autoridade else None
            },
            "remetente": remetente,
            "usou_llm": True
        }

    except Exception as e:
        print(f"Erro ao gerar memorando com LLM: {e}")
        return gerar_memorando_template(publicacoes, autoridade, remetente, ano)


def gerar_memorando_template(
    publicacoes: List[Dict],
    autoridade: Optional[Dict],
    remetente: Optional[Dict],
    ano: int
) -> Dict:
    """Gera memorando usando template (fallback sem LLM)."""
    resumo = gerar_resumo_publicacoes(publicacoes)
    qtd_pubs = len(publicacoes)

    # Extrai dados do destinatário
    dest_nome_raw = ""
    dest_posto = ""
    dest_cargo = ""
    if autoridade:
        dest_nome_raw = autoridade.get('nome_atual', '')
        dest_posto = autoridade.get('posto_grad', '')
        dest_cargo = autoridade.get('unidade_destino', '')

    # Formata nome do destinatário (sem posto - será adicionado por gerar_html_memorando)
    if FORMATO_CENTRALIZADO:
        dest_nome = formatar_nome(dest_nome_raw)
    else:
        dest_nome = dest_nome_raw.title() if dest_nome_raw else ''

    # Extrai dados do remetente
    rem_nome_raw = ""
    rem_posto = ""
    rem_cargo = ""
    rem_matricula = ""
    if remetente:
        rem_nome_raw = remetente.get('nome', '')
        rem_posto = remetente.get('posto', '') or remetente.get('posto_grad', '')
        rem_cargo = remetente.get('cargo', '')
        rem_matricula = remetente.get('matricula', '')

    # Formata nome do remetente (sem posto - será adicionado por gerar_html_memorando)
    if FORMATO_CENTRALIZADO:
        rem_nome = formatar_nome(rem_nome_raw)
    else:
        rem_nome = rem_nome_raw.title() if rem_nome_raw else ''

    # Vocativo baseado no cargo e gênero
    if FORMATO_CENTRALIZADO:
        genero = determinar_genero(dest_nome_raw, dest_cargo)
        vocativo = _determinar_vocativo(dest_cargo, genero)
    else:
        if dest_cargo:
            cargo_lower = dest_cargo.lower()
            if 'comandante' in cargo_lower:
                vocativo = "Senhor Comandante"
            elif 'diretor' in cargo_lower:
                vocativo = "Senhor Diretor"
            elif 'subcomandante' in cargo_lower:
                vocativo = "Senhor Subcomandante-Geral"
            elif 'chefe' in cargo_lower:
                vocativo = "Senhor Chefe"
            else:
                vocativo = "Senhor"
        else:
            vocativo = "Senhor Comandante"

    corpo = f"""Com os cumprimentos de estilo, encaminho a Vossa Senhoria a Nota para Boletim Geral anexa, contendo {qtd_pubs} ({numero_por_extenso(qtd_pubs)}) alteração(ões) referente(s) a {resumo}, para apreciação e posterior publicação."""

    fechamento = "Atenciosamente"

    html = gerar_html_memorando(
        destinatario_nome=dest_nome,
        destinatario_cargo=dest_cargo,
        vocativo=vocativo,
        corpo=corpo,
        fechamento=fechamento,
        remetente_nome=rem_nome,
        remetente_cargo=rem_cargo,
        remetente_matricula=rem_matricula,
        ano=ano,
        remetente_posto=rem_posto,
        destinatario_posto=dest_posto
    )

    # Formata nome para retorno
    dest_nome_retorno = dest_nome
    if dest_posto:
        if FORMATO_CENTRALIZADO:
            dest_nome_retorno = f"{dest_nome} - {formatar_posto_grad(dest_posto)}"
        else:
            dest_nome_retorno = f"{dest_nome} - {dest_posto.upper()}"

    return {
        "sucesso": True,
        "html": html,
        "vocativo": vocativo,
        "corpo": corpo,
        "fechamento": fechamento,
        "destinatario": {
            "nome": dest_nome_retorno,
            "cargo": dest_cargo,
            "chave": autoridade.get('chave_busca') if autoridade else None
        },
        "remetente": remetente,
        "usou_llm": False
    }


def gerar_html_memorando(
    destinatario_nome: str,
    destinatario_cargo: str,
    vocativo: str,
    corpo: str,
    fechamento: str,
    remetente_nome: str,
    remetente_cargo: str,
    remetente_matricula: str,
    ano: int,
    sigla_remetente: str = "",
    portaria: str = "",
    remetente_posto: str = "",
    destinatario_posto: str = ""
) -> str:
    """
    Gera HTML formatado do memorando no padrão SEI.

    IMPORTANTE: O SEI já adiciona o cabeçalho (Estado/CBMAC) e numeração,
    então o HTML deve conter apenas o corpo do documento.

    Formato:
        Destinatário: Ao Sr./À Sra. Nome - POSTO
                      Cargo
        Remetente:    Nome - POSTO
                      Cargo
                      Portaria/Matrícula
    """
    if FORMATO_CENTRALIZADO:
        # Usa módulo centralizado para formatação consistente

        # Formata destinatário
        genero_dest = determinar_genero(destinatario_nome, destinatario_cargo)
        pronome = "À Sra." if genero_dest == 'F' else "Ao Sr."
        nome_dest_formatado = formatar_nome(destinatario_nome) if destinatario_nome else '[Nome do Destinatário]'

        # Monta linha do destinatário: Nome - POSTO
        if destinatario_posto:
            dest_linha = f"{nome_dest_formatado} - {formatar_posto_grad(destinatario_posto)}"
        else:
            dest_linha = nome_dest_formatado

        if destinatario_cargo:
            dest_linha += f"<br>{destinatario_cargo}"

        html_dest = f'<p style="text-align: left;">{pronome} {dest_linha}</p>'

        # Formata remetente usando módulo centralizado
        html_rem = formatar_remetente(
            nome=remetente_nome,
            posto_grad=remetente_posto,
            cargo=remetente_cargo,
            portaria=portaria,
            matricula=remetente_matricula,
            sigla=sigla_remetente
        )

        html = f"""{html_dest}

<p style="text-align: left;">Assunto: <b>Encaminhamento de Nota para Boletim Geral</b></p>

<p style="text-align: left; text-indent: 1.5cm;">{vocativo},</p>

<p style="text-align: justify; text-indent: 1.5cm;">{corpo}</p>

<p style="text-align: left; text-indent: 1.5cm;">{fechamento},</p>

{html_rem}"""

        return html

    # Fallback: formato anterior (caso módulo não disponível)
    dest_linha = destinatario_nome or '[Nome do Destinatário]'
    if destinatario_cargo:
        dest_linha = f"{dest_linha}<br>\n{destinatario_cargo}"

    rem_nome = remetente_nome or '[Nome do Remetente]'
    rem_cargo = remetente_cargo or '[Cargo/Função]'

    if sigla_remetente:
        rem_linha_final = f"{sigla_remetente}/CBMAC"
    elif remetente_matricula:
        rem_linha_final = f"Matrícula {remetente_matricula}"
    else:
        rem_linha_final = ""

    if portaria:
        rem_linha_final = f"Port. nº {portaria}"

    # Determina gênero para pronome
    genero = 'M'
    if destinatario_nome:
        primeiro_nome = destinatario_nome.split()[0].upper() if destinatario_nome.split() else ''
        nomes_femininos = ['MARIA', 'ANA', 'FRANCISCA', 'ANTONIA', 'ADRIANA', 'JULIANA']
        if primeiro_nome in nomes_femininos or primeiro_nome.endswith('A'):
            genero = 'F'

    pronome = "À Sra." if genero == 'F' else "Ao Sr."

    html = f"""<p style="text-align: left;">{pronome} {dest_linha}</p>

<p style="text-align: left;">Assunto: <b>Encaminhamento de Nota para Boletim Geral</b></p>

<p style="text-align: left; text-indent: 1.5cm;">{vocativo},</p>

<p style="text-align: justify; text-indent: 1.5cm;">{corpo}</p>

<p style="text-align: left; text-indent: 1.5cm;">{fechamento},</p>

<p style="text-align: center;">{rem_nome}<br>
{rem_cargo}"""

    if rem_linha_final:
        html += f"<br>\n{rem_linha_final}"

    html += "</p>"

    return html


# =============================================================================
# FUNÇÃO PARA REGISTRAR ENDPOINTS
# =============================================================================

def registrar_endpoints_nota_bg(app: FastAPI):
    """
    Registra todos os endpoints de Nota BG na aplicação FastAPI.
    
    Uso no api.py:
        from nota_bg_modulo import registrar_endpoints_nota_bg
        registrar_endpoints_nota_bg(app)
    """
    
    # Importa a função de auditoria do módulo principal
    try:
        from __main__ import registrar_auditoria
    except ImportError:
        def registrar_auditoria(usuario, acao, detalhes=None, ip=None):
            print(f"[AUDIT] {usuario}: {acao} - {detalhes}")
    
    # -----------------------------------------------------------------
    # GET /api/nota-bg/tipos - Lista tipos de ato
    # -----------------------------------------------------------------
    @app.get("/api/nota-bg/tipos")
    async def listar_tipos_ato():
        """Lista todos os tipos de ato disponíveis"""
        tipos = []
        for tipo in TipoAto:
            if "FÉRIAS" in tipo.value:
                grupo = "Férias"
            elif "DISPENSA COMO RECOMPENSA" in tipo.value:
                grupo = "Dispensa como Recompensa"
            elif "DISPENSA" in tipo.value:
                grupo = "Dispensa"
            elif "LICENÇA ESPECIAL" in tipo.value:
                grupo = "Licença Especial"
            elif "LICENÇA PATERNIDADE" in tipo.value:
                grupo = "Licença Paternidade"
            elif "LUTO" in tipo.value:
                grupo = "Luto"
            elif "NÚPCIAS" in tipo.value:
                grupo = "Núpcias"
            elif "VIAGEM" in tipo.value:
                grupo = "Viagem"
            else:
                grupo = "Outros"
            
            tipos.append({
                "id": tipo.name,
                "nome": tipo.value,
                "grupo": grupo,
            })
        
        return {"tipos": tipos, "tipo_documento_sei": TIPO_DOCUMENTO_NOTA_BG}
    
    # -----------------------------------------------------------------
    # GET /api/nota-bg/militar/buscar - Autocomplete
    # -----------------------------------------------------------------
    @app.get("/api/nota-bg/militar/buscar")
    async def buscar_militar_endpoint(
        q: str = Query(..., min_length=2, description="Nome ou matrícula"),
        limit: int = Query(10, ge=1, le=50)
    ):
        """Busca militar por nome ou matrícula (autocomplete)"""
        records = await buscar_militar_api(q, limit)
        resultados = [formatar_militar(r) for r in records]
        
        return {
            "query": q,
            "total": len(resultados),
            "resultados": [r.dict() for r in resultados]
        }
    
    # -----------------------------------------------------------------
    # GET /api/nota-bg/militar/{matricula} - Por matrícula
    # -----------------------------------------------------------------
    @app.get("/api/nota-bg/militar/{matricula}")
    async def get_militar_endpoint(matricula: str):
        """Busca militar por matrícula exata"""
        record = await buscar_militar_por_matricula(matricula)
        
        if not record:
            raise HTTPException(status_code=404, detail="Militar não encontrado")
        
        return formatar_militar(record).dict()
    
    # -----------------------------------------------------------------
    # POST /api/nota-bg/gerar - Gera HTML da nota
    # -----------------------------------------------------------------
    @app.post("/api/nota-bg/gerar")
    async def gerar_nota_endpoint(req: NotaBGGerarRequest, request: Request):
        """Gera HTML da nota completa com validação de militar"""
        
        ip = request.client.host if request.client else "unknown"
        alertas = []
        erros = []
        
        # 1. Busca o militar
        militar = None
        
        if req.militar_matricula:
            record = await buscar_militar_por_matricula(req.militar_matricula)
            if record:
                militar = formatar_militar(record)
            else:
                erros.append(f"Matrícula não encontrada: {req.militar_matricula}")
        
        if not militar and req.militar_nome:
            records = await buscar_militar_api(req.militar_nome, limit=5)
            
            if len(records) == 0:
                erros.append(f"Militar não encontrado: {req.militar_nome}")
            elif len(records) == 1:
                militar = formatar_militar(records[0])
            else:
                # Múltiplos resultados - retorna lista para seleção
                return JSONResponse({
                    "sucesso": False,
                    "homonimos": True,
                    "opcoes": [formatar_militar(r).dict() for r in records],
                    "mensagem": f"Encontrados {len(records)} militares. Selecione o correto."
                })
        
        if not militar:
            return JSONResponse({
                "sucesso": False,
                "erros": erros,
                "alertas": alertas
            })
        
        # 2. Gera texto
        texto_corpo = gerar_texto_nota(
            tipo_ato=req.tipo_ato,
            militar=militar,
            dias=req.dias,
            periodo=req.periodo_aquisitivo,
            data_apresentacao=req.data_apresentacao,
            motivo=req.motivo,
            origem=req.origem,
            destino=req.destino,
            sei_processo=req.sei_processo,
        )
        
        # 3. Gera HTML
        html = gerar_html_nota(
            tipo_ato=req.tipo_ato,
            data_ato=req.data_ato,
            texto_corpo=texto_corpo,
        )
        
        # 4. Auditoria
        registrar_auditoria(
            req.usuario_sei, 
            "NOTA_BG_GERAR", 
            f"Tipo: {req.tipo_ato}, Militar: {militar.matricula_completa}", 
            ip
        )
        
        return JSONResponse({
            "sucesso": True,
            "html": html,
            "texto_plano": texto_corpo,
            "militar_validado": militar.dict(),
            "tipo_ato": req.tipo_ato,
            "alertas": alertas,
            "erros": erros,
        })
    
    # -----------------------------------------------------------------
    # POST /api/nota-bg/inserir - Insere no SEI
    # -----------------------------------------------------------------
    @app.post("/api/nota-bg/inserir")
    async def inserir_nota_sei_endpoint(req: NotaBGInserirRequest, request: Request):
        """Insere nota BG no SEI via Runner"""
        
        ip = request.client.host if request.client else "unknown"
        
        try:
            # Busca sigla do usuário
            from diretorias_db import DiretoriasDB
            db = DiretoriasDB()
            diretoria = db.buscar_por_usuario(req.usuario_sei)
            
            if not diretoria:
                return JSONResponse({
                    "sucesso": False, 
                    "erro": f"Usuário '{req.usuario_sei}' não encontrado"
                })
            
            sigla = diretoria.get("sigla")
            
            # Chama Runner
            async with httpx.AsyncClient(timeout=180.0) as http_client:
                response = await http_client.post(
                    f"{SEI_RUNNER_URL}/run",
                    json={
                        "mode": "atuar",
                        "nup": req.nup,
                        "sigla": sigla,
                        "tipo_documento": TIPO_DOCUMENTO_NOTA_BG,
                        "destinatario": "",
                        "texto_despacho": req.html
                    }
                )
                data = response.json()
            
            if data.get("ok") == False:
                return JSONResponse({
                    "sucesso": False, 
                    "erro": data.get("error", "Erro desconhecido no Runner")
                })
            
            # Auditoria
            registrar_auditoria(
                req.usuario_sei, 
                "NOTA_BG_INSERIR_SEI", 
                f"NUP: {req.nup}", 
                ip
            )
            
            return JSONResponse({
                "sucesso": True,
                "nup": req.nup,
                "tipo_documento": TIPO_DOCUMENTO_NOTA_BG,
                "mensagem": "Nota BG inserida com sucesso!"
            })
            
        except httpx.TimeoutException:
            return JSONResponse({
                "sucesso": False, 
                "erro": "Timeout ao comunicar com o Runner (3 min)"
            })
        except Exception as e:
            return JSONResponse({
                "sucesso": False, 
                "erro": str(e)
            })
    
    # -----------------------------------------------------------------
    # GET /api/nota-bg/config - Configuração
    # -----------------------------------------------------------------
    @app.get("/api/nota-bg/config")
    async def get_config_nota_bg():
        """Retorna configurações do módulo"""
        return {
            "tipo_documento_sei": TIPO_DOCUMENTO_NOTA_BG,
            "formato_militar": "[POSTO/GRAD] Mat. [MATRÍCULA] [NOME COMPLETO]",
            "exemplo": "MAJ QOBMEC Mat. 9268863-3 Gilmar Torres Marques Moura",
            "efetivo_api": EFETIVO_API_URL,
        }

    # -----------------------------------------------------------------
    # GET /api/nota-bg/autoridades - Lista autoridades
    # -----------------------------------------------------------------
    @app.get("/api/nota-bg/autoridades")
    async def listar_autoridades_endpoint():
        """Lista todas as autoridades disponíveis para destinatário do memorando."""
        autoridades = await listar_autoridades_db()

        # Agrupa por categoria
        categorias = {
            "Comando Geral": [],
            "Comandos Operacionais": [],
            "Diretorias": [],
            "Assessorias": [],
            "Batalhões": [],
            "Outros": []
        }

        for a in autoridades:
            chave = a.get('chave_busca', '')
            item = {
                "chave": chave,
                "nome": a.get('nome_atual', ''),
                "posto": a.get('posto_grad', ''),
                "unidade": a.get('unidade_destino', ''),
                "sigla": a.get('sigla_unidade', ''),
                "formatado": f"{a.get('posto_grad', '')} {a.get('nome_atual', '')}".strip()
            }

            if chave in ['CMDGER', 'SUBCMD']:
                categorias["Comando Geral"].append(item)
            elif chave in ['COC', 'COI', 'COA', 'GOA']:
                categorias["Comandos Operacionais"].append(item)
            elif chave.startswith('D') or chave in ['DRH', 'DEI', 'DLPF', 'DSAU', 'DATOP', 'DPLAN']:
                categorias["Diretorias"].append(item)
            elif chave.startswith('ASS') or chave == 'AJGER':
                categorias["Assessorias"].append(item)
            elif 'BEP' in chave or 'BATALHAO' in chave.upper():
                categorias["Batalhões"].append(item)
            else:
                categorias["Outros"].append(item)

        return {
            "autoridades": autoridades,
            "categorias": categorias,
            "total": len(autoridades)
        }

    # -----------------------------------------------------------------
    # POST /api/nota-bg/gerar-memorando - Memorando Inteligente
    # -----------------------------------------------------------------
    @app.post("/api/nota-bg/gerar-memorando")
    async def gerar_memorando_inteligente_endpoint(req: MemorandoInteligenteRequest, request: Request):
        """
        Gera memorando inteligente usando LLM.

        O usuário pode digitar algo como:
        - "ao COC informando que seguem as alterações de férias"
        - "para o Subcomandante com urgência"
        - "Memorando ao DRH sobre férias do mês"

        O sistema:
        1. Identifica a autoridade pelo texto natural
        2. Busca dados da autoridade no banco
        3. Usa LLM para gerar texto formal
        4. Retorna HTML pronto para o SEI
        """
        ip = request.client.host if request.client else "unknown"
        ano = req.ano or datetime.now().year

        # 1. Identifica autoridade pelo texto
        chave_autoridade = identificar_autoridade_por_texto(req.mensagem)

        autoridade = None
        if chave_autoridade:
            autoridade = await buscar_autoridade_db(chave_autoridade)

        # 2. Gera memorando com LLM
        resultado = await gerar_memorando_llm(
            mensagem=req.mensagem,
            publicacoes=req.publicacoes,
            autoridade=autoridade,
            remetente=req.remetente,
            ano=ano
        )

        # 3. Adiciona info de autoridade detectada
        resultado["autoridade_detectada"] = chave_autoridade
        resultado["autoridade_encontrada"] = autoridade is not None

        # Se não encontrou autoridade, sugere opções
        if not autoridade:
            autoridades_disponiveis = await listar_autoridades_db()
            resultado["sugestoes"] = [
                {
                    "chave": a.get('chave_busca'),
                    "nome": f"{a.get('posto_grad', '')} {a.get('nome_atual', '')}".strip(),
                    "unidade": a.get('unidade_destino', '')
                }
                for a in autoridades_disponiveis[:10]
            ]
            resultado["mensagem"] = "Autoridade não identificada. Selecione uma das sugestões ou digite novamente."

        # 4. Auditoria
        registrar_auditoria(
            req.remetente.get('matricula', 'desconhecido') if req.remetente else 'desconhecido',
            "NOTA_BG_MEMO_INTELIGENTE",
            f"Autoridade: {chave_autoridade or 'não detectada'}, Pubs: {len(req.publicacoes)}",
            ip
        )

        return JSONResponse(resultado)

    # -----------------------------------------------------------------
    # POST /api/nota-bg/gerar-memorando-simples - Sem LLM
    # -----------------------------------------------------------------
    @app.post("/api/nota-bg/gerar-memorando-simples")
    async def gerar_memorando_simples_endpoint(req: MemorandoInteligenteRequest):
        """
        Gera memorando usando template (sem LLM).
        Útil quando LLM não está disponível ou para respostas mais rápidas.
        """
        ano = req.ano or datetime.now().year

        # Identifica autoridade
        chave_autoridade = identificar_autoridade_por_texto(req.mensagem)

        autoridade = None
        if chave_autoridade:
            autoridade = await buscar_autoridade_db(chave_autoridade)

        # Gera memorando com template
        resultado = gerar_memorando_template(
            publicacoes=req.publicacoes,
            autoridade=autoridade,
            remetente=req.remetente,
            ano=ano
        )

        resultado["autoridade_detectada"] = chave_autoridade
        resultado["autoridade_encontrada"] = autoridade is not None

        return JSONResponse(resultado)

    print("✅ Módulo Nota BG v2.0 registrado: /api/nota-bg/* (com Memorando Inteligente)")
