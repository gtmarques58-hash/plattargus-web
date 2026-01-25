#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
nota_bg_modulo.py - Módulo de Notas para Boletim Geral
PlattArgus WEB - CBMAC
Versão: 1.0

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

# =============================================================================
# CONFIGURAÇÃO
# =============================================================================

EFETIVO_API_URL = os.getenv("EFETIVO_API_URL", "http://efetivo-api:3001")
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
    
    print("✅ Módulo Nota BG registrado: /api/nota-bg/*")
