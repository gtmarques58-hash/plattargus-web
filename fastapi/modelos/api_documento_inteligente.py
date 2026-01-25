"""
api_documento_inteligente.py - API de Criação Inteligente de Documentos SEI

Endpoint otimizado que:
1. Classifica a mensagem do usuário (50ms)
2. Se tem template → executa direto no SEI (sem LLM)
3. Se precisa texto livre → retorna para o ARGUS gerar

GANHOS:
- 80% das requisições sem LLM → resposta em <500ms
- 88% redução de custo
- 100% determinístico para templates

Uso:
    uvicorn api_documento_inteligente:app --host 0.0.0.0 --port 8105

Endpoints:
    POST /documento/criar     - Cria documento (auto-detecta template ou texto livre)
    POST /documento/classificar - Apenas classifica (sem criar)
    GET  /templates           - Lista templates disponíveis
    GET  /health              - Health check
"""

import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
from fastapi import FastAPI, HTTPException, BackgroundTasks, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Adiciona o diretório de scripts ao path
SCRIPTS_DIR = os.environ.get("SCRIPTS_DIR", "/app/scripts")
sys.path.insert(0, SCRIPTS_DIR)

# Adiciona o diretório de modelos ao path (para templates_meta.py)
MODELOS_DIR = os.environ.get("MODELOS_DIR", "/app/modelos")
sys.path.insert(0, MODELOS_DIR)

# Configuração da API de Efetivo
EFETIVO_API_URL = os.environ.get("EFETIVO_API_URL", "https://efetivo.gt2m58.cloud")
EFETIVO_API_KEY = os.environ.get("EFETIVO_API_KEY", "gw_PlattArgusWeb2025_CBMAC")

# Importa o classificador
from classificador_documentos import (
    classificar_documento,
    formatar_para_atuar,
    TEMPLATES_CONFIG,
    TEXTO_LIVRE_SEMPRE,
)

# Importa funções do SEI (serão importadas dinamicamente)
# from atuar_no_processo import atuar_no_processo
# from templates_meta import preencher_template, TEMPLATES_META

# =============================================================================
# CONFIGURAÇÃO DE LOGGING
# =============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# =============================================================================
# CONFIGURAÇÃO DA API
# =============================================================================

app = FastAPI(
    title="API de Documentos Inteligente",
    description="Criação otimizada de documentos SEI com classificação automática",
    version="1.0.0",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =============================================================================
# MODELOS PYDANTIC
# =============================================================================

class Remetente(BaseModel):
    """Dados do remetente do documento."""
    nome: str = Field(..., description="Nome completo")
    posto: str = Field(..., description="Posto/Graduação")
    cargo: str = Field(..., description="Cargo")
    matricula: str = Field(..., description="Matrícula")


class CriarDocumentoRequest(BaseModel):
    """Request para criar documento."""
    mensagem: str = Field(..., description="Mensagem do usuário (ex: 'Termo de Encerramento BG 08/2026')")
    nup: str = Field(..., description="NUP do processo")
    sigla: str = Field(..., description="Sigla da unidade do usuário")
    remetente: Remetente = Field(..., description="Dados do remetente")
    
    # Campos opcionais para complementar
    destinatario: Optional[Dict[str, str]] = Field(None, description="Dados do destinatário (se aplicável)")
    campos_extras: Optional[Dict[str, str]] = Field(None, description="Campos extras para o template")
    
    # Configurações
    executar_sei: bool = Field(True, description="Se True, cria no SEI. Se False, apenas retorna prévia")
    chat_id: Optional[str] = Field(None, description="ID do chat (para callbacks)")

    class Config:
        json_schema_extra = {
            "example": {
                "mensagem": "Termo de Encerramento BG 08/2026",
                "nup": "0609.012097.00016/2026-69",
                "sigla": "DRH",
                "remetente": {
                    "nome": "GILMAR TORRES MARQUES MOURA",
                    "posto": "MAJ QOBMEC",
                    "cargo": "Diretor de Recursos Humanos",
                    "matricula": "9215394"
                },
                "executar_sei": True
            }
        }


class ClassificarRequest(BaseModel):
    """Request para apenas classificar (sem criar)."""
    mensagem: str = Field(..., description="Mensagem do usuário")
    sigla: str = Field(..., description="Sigla da unidade")
    remetente: Optional[Remetente] = Field(None, description="Dados do remetente")


class DocumentoResponse(BaseModel):
    """Response da criação de documento."""
    sucesso: bool
    usou_template: bool
    template_id: Optional[str] = None
    tipo_sei: Optional[str] = None
    
    # Se usou template e executou
    sei_numero: Optional[str] = None
    sei_numero_editor: Optional[str] = None
    documento_criado: bool = False
    
    # Se precisa texto livre
    requer_argus: bool = False
    mensagem_argus: Optional[str] = None
    
    # Campos extraídos/preenchidos
    campos: Optional[Dict[str, Any]] = None
    campos_faltantes: Optional[List[str]] = None
    
    # Preview do documento (se não executou)
    preview_html: Optional[str] = None
    
    # Métricas
    tempo_ms: int
    confianca: float = 0.0
    
    # Erros
    erro: Optional[str] = None


# =============================================================================
# FUNÇÕES AUXILIARES
# =============================================================================

def limpar_html_para_sei(html: str) -> str:
    """
    Remove o bloco de NUP e Tipo de Documento do corpo HTML antes de enviar ao SEI.

    O SEI já possui esses dados como metadados, então não devem aparecer no corpo.

    Remove padrões como:
    - <p>• NUP: 0609.012097.00016/2026-69<br>- Tipo de documento: Despacho</p>
    - <p>NUP: ...<br>Tipo: ...</p>
    - Variações com bullet points, traços, etc.
    """
    import re

    # Padrão 1: Bloco completo com NUP e Tipo em um <p>
    # Ex: <p>• NUP: 0609.012097.00016/2026-69<br>- Tipo de documento: Despacho</p>
    padrao_bloco = re.compile(
        r'<p[^>]*>\s*[•\-]?\s*NUP\s*:\s*[\d\.\-/]+.*?</p>\s*',
        re.IGNORECASE | re.DOTALL
    )
    html = padrao_bloco.sub('', html)

    # Padrão 2: Linha separada só com NUP
    # Ex: <p>NUP: 0609.012097.00016/2026-69</p>
    padrao_nup = re.compile(
        r'<p[^>]*>\s*[•\-]?\s*NUP\s*:\s*[\d\.\-/]+\s*</p>\s*',
        re.IGNORECASE
    )
    html = padrao_nup.sub('', html)

    # Padrão 3: Linha separada só com Tipo de documento
    # Ex: <p>- Tipo de documento: Despacho</p>
    padrao_tipo = re.compile(
        r'<p[^>]*>\s*[•\-]?\s*Tipo\s*(de\s*)?documento\s*:\s*[^<]+</p>\s*',
        re.IGNORECASE
    )
    html = padrao_tipo.sub('', html)

    # Padrão 4: Dentro de um <p> com <br>, remove só as linhas de NUP/Tipo
    # Ex: "• NUP: ...<br>" ou "- Tipo de documento: ...<br>"
    padrao_linha_nup = re.compile(
        r'[•\-]?\s*NUP\s*:\s*[\d\.\-/]+\s*<br\s*/?>',
        re.IGNORECASE
    )
    html = padrao_linha_nup.sub('', html)

    padrao_linha_tipo = re.compile(
        r'[•\-]?\s*Tipo\s*(de\s*)?documento\s*:\s*[^<]+<br\s*/?>',
        re.IGNORECASE
    )
    html = padrao_linha_tipo.sub('', html)

    # Remove <hr> separador que fica após o bloco NUP/Tipo
    html = re.sub(r'<hr[^>]*>\s*', '', html)

    # Remove parágrafos vazios que sobraram
    html = re.sub(r'<p[^>]*>\s*</p>', '', html)

    # Remove espaços em branco extras no início
    html = html.lstrip()

    return html


async def carregar_template_conteudo(template_id: str) -> Optional[str]:
    """Carrega o conteúdo de um template."""
    try:
        from templates_meta import carregar_template
        return carregar_template(template_id)
    except Exception as e:
        logger.error(f"Erro ao carregar template {template_id}: {e}")
        return None


async def preencher_template_campos(template_id: str, campos: Dict[str, str]) -> Optional[str]:
    """Preenche um template com os campos fornecidos."""
    try:
        from templates_meta import preencher_template
        return preencher_template(template_id, campos)
    except Exception as e:
        logger.error(f"Erro ao preencher template {template_id}: {e}")
        return None


async def executar_no_sei(
    nup: str,
    tipo_documento: str,
    corpo_html: str,
    destinatario: str = "",
    sigla: str = "",
    chat_id: Optional[str] = None
) -> Dict[str, Any]:
    """Executa a criação do documento no SEI."""
    try:
        from atuar_no_processo import atuar_no_processo
        
        resultado = await atuar_no_processo(
            nup=nup,
            tipo_documento=tipo_documento,
            destinatario=destinatario,
            corpo_html=corpo_html,
            chat_id=chat_id,
            sigla=sigla
        )
        
        return resultado
        
    except Exception as e:
        logger.error(f"Erro ao executar no SEI: {e}")
        return {
            "sucesso": False,
            "erro": str(e),
            "documento_criado": False
        }


def consultar_lista_contatos(sigla: str) -> Optional[Dict[str, str]]:
    """Consulta a lista de contatos para obter dados do chefe da unidade."""
    try:
        from diretorias_db import get_diretoria_info
        info = get_diretoria_info(sigla)
        if info:
            return {
                "nome": info.get("chefe_nome", ""),
                "posto": info.get("chefe_posto", ""),
                "cargo": info.get("chefe_cargo", ""),
                "matricula": info.get("chefe_matricula", ""),
            }
    except Exception as e:
        logger.warning(f"Erro ao consultar contatos para {sigla}: {e}")
    return None


# =============================================================================
# CLIENTE API DE EFETIVO
# =============================================================================

class MilitarResponse(BaseModel):
    """Dados de um militar retornado pela API de Efetivo."""
    matricula: str
    matricula_completa: str
    nome: str
    posto_grad: str
    lotacao: Optional[str] = None
    cargo: Optional[str] = None
    formatado: str  # Ex: "MAJ QOBMEC Mat. 9268863-3 GILMAR TORRES MARQUES MOURA"


async def buscar_militar_efetivo(query: str, limit: int = 10) -> List[Dict]:
    """
    Busca militar na API de Efetivo por nome ou matricula.
    Retorna lista de registros encontrados.
    """
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
        except httpx.TimeoutException:
            logger.warning(f"Timeout ao buscar militar: {query}")
            return []
        except Exception as e:
            logger.warning(f"Erro ao buscar militar '{query}': {e}")
            return []


async def buscar_militar_por_matricula(matricula: str) -> Optional[Dict]:
    """
    Busca militar por matricula exata na API de Efetivo.
    Retorna dados completos do militar ou None se nao encontrado.
    """
    # A API de Efetivo aceita matricula completa (com hifen) ou busca por aproximacao
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
        except httpx.TimeoutException:
            logger.warning(f"Timeout ao buscar matricula: {matricula}")
            return None
        except Exception as e:
            logger.warning(f"Erro ao buscar matricula '{matricula}': {e}")
            return None


def formatar_militar(record: Dict) -> MilitarResponse:
    """Formata registro da API de Efetivo no padrao do sistema."""
    matricula = record.get("matricula", "")
    nome = record.get("nome", "")
    posto_grad = record.get("posto_grad", "")
    lotacao = record.get("lotacao", "")
    cargo = record.get("funcao", "") or ""

    # Formato padrao: "MAJ QOBMEC Mat. 9268863-3 GILMAR TORRES MARQUES MOURA"
    formatado = f"{posto_grad} Mat. {matricula} {nome}".strip()

    # Extrai matricula base (sem digito verificador)
    mat_base = matricula.split("-")[0] if "-" in matricula else matricula

    return MilitarResponse(
        matricula=mat_base,
        matricula_completa=matricula,
        nome=nome,
        posto_grad=posto_grad,
        lotacao=lotacao,
        cargo=cargo,
        formatado=formatado
    )


async def completar_dados_remetente(remetente: Dict) -> Dict:
    """
    Completa dados do remetente buscando na API de Efetivo.
    Se tiver matricula, busca dados atualizados.
    """
    matricula = remetente.get("matricula", "")

    if not matricula:
        return remetente

    # Busca na API de Efetivo
    dados_efetivo = await buscar_militar_por_matricula(matricula)

    if dados_efetivo:
        # Atualiza dados do remetente com dados do Efetivo
        # Mantem dados informados pelo usuario se existirem
        return {
            "nome": remetente.get("nome") or dados_efetivo.get("nome", ""),
            "posto": remetente.get("posto") or dados_efetivo.get("posto_grad", ""),
            "cargo": remetente.get("cargo") or dados_efetivo.get("funcao", ""),
            "matricula": dados_efetivo.get("matricula", matricula),
            "lotacao": dados_efetivo.get("lotacao", ""),
        }

    return remetente


# =============================================================================
# ENDPOINTS
# =============================================================================

@app.get("/health")
async def health_check():
    """Health check do serviço."""
    return {
        "status": "healthy",
        "service": "api-documento-inteligente",
        "timestamp": datetime.now().isoformat(),
        "templates_disponiveis": len(TEMPLATES_CONFIG),
    }


@app.get("/templates")
async def listar_templates():
    """Lista todos os templates disponíveis."""
    templates = []
    
    for template_id, config in TEMPLATES_CONFIG.items():
        templates.append({
            "template_id": template_id,
            "tipo_sei": config["tipo_sei"],
            "gatilhos": config["gatilhos"],
            "campos_obrigatorios": config.get("campos_obrigatorios", []),
            "texto_livre": config.get("texto_livre", False),
        })
    
    return {
        "templates": templates,
        "total": len(templates),
        "texto_livre_sempre": TEXTO_LIVRE_SEMPRE,
    }


# =============================================================================
# ENDPOINTS DE BUSCA DE MILITAR (API EFETIVO)
# =============================================================================

@app.get("/militar/buscar")
async def buscar_militar(
    q: str = Query(..., min_length=2, description="Termo de busca (nome ou matricula)"),
    limit: int = Query(10, ge=1, le=50, description="Limite de resultados")
):
    """
    Busca militares na API de Efetivo.
    Usado para autocomplete no frontend.

    Exemplo de uso:
        GET /militar/buscar?q=gilmar&limit=5

    Retorna lista de militares formatados:
        - matricula: "9268863"
        - matricula_completa: "9268863-3"
        - nome: "GILMAR TORRES MARQUES MOURA"
        - posto_grad: "MAJ QOBMEC"
        - lotacao: "COMANDO GERAL"
        - formatado: "MAJ QOBMEC Mat. 9268863-3 GILMAR TORRES MARQUES MOURA"
    """
    inicio = time.time()

    # Busca na API de Efetivo
    records = await buscar_militar_efetivo(q, limit)

    # Formata resultados
    militares = [formatar_militar(r).dict() for r in records]

    tempo_ms = int((time.time() - inicio) * 1000)

    return {
        "query": q,
        "total": len(militares),
        "militares": militares,
        "tempo_ms": tempo_ms,
        "fonte": "efetivo-api"
    }


@app.get("/militar/{matricula}")
async def obter_militar(matricula: str):
    """
    Obtem dados completos de um militar por matricula.

    Exemplo de uso:
        GET /militar/9268863
        GET /militar/9268863-3

    Retorna dados completos do militar ou 404 se nao encontrado.
    """
    dados = await buscar_militar_por_matricula(matricula)

    if not dados:
        raise HTTPException(
            status_code=404,
            detail=f"Militar com matricula '{matricula}' nao encontrado"
        )

    militar = formatar_militar(dados)

    return {
        "sucesso": True,
        "militar": militar.dict(),
        "fonte": "efetivo-api"
    }


# =============================================================================
# ENDPOINTS DE DOCUMENTO
# =============================================================================

@app.post("/documento/classificar", response_model=Dict[str, Any])
async def classificar_apenas(request: ClassificarRequest):
    """
    Apenas classifica a mensagem (sem criar documento).
    Útil para preview antes de criar.
    """
    inicio = time.time()
    
    # Monta contexto
    contexto = {
        "sigla": request.sigla,
    }
    
    if request.remetente:
        contexto["remetente"] = {
            "nome": request.remetente.nome,
            "posto": request.remetente.posto,
            "cargo": request.remetente.cargo,
            "matricula": request.remetente.matricula,
        }
    
    # Classifica
    resultado = classificar_documento(request.mensagem, contexto)
    
    tempo_ms = int((time.time() - inicio) * 1000)
    
    return {
        **resultado,
        "tempo_ms": tempo_ms,
    }


@app.post("/documento/criar", response_model=DocumentoResponse)
async def criar_documento(request: CriarDocumentoRequest):
    """
    Cria documento inteligente.
    
    FLUXO:
    1. Classifica a mensagem
    2. Se tem template → preenche e executa no SEI
    3. Se precisa texto livre → retorna para ARGUS gerar
    
    RESPOSTA RÁPIDA:
    - Com template: ~200-500ms
    - Sem template: ~50ms (retorna para ARGUS)
    """
    inicio = time.time()
    
    logger.info(f"[CRIAR] NUP={request.nup} | Mensagem='{request.mensagem}' | Sigla={request.sigla}")

    # =========================================================================
    # 1. MONTA CONTEXTO (com dados do Efetivo se disponivel)
    # =========================================================================
    remetente_dados = {
        "nome": request.remetente.nome,
        "posto": request.remetente.posto,
        "cargo": request.remetente.cargo,
        "matricula": request.remetente.matricula,
    }

    # Tenta completar dados do remetente via API de Efetivo
    if request.remetente.matricula:
        try:
            remetente_dados = await completar_dados_remetente(remetente_dados)
            logger.info(f"[EFETIVO] Dados do remetente completados: {remetente_dados.get('nome')}")
        except Exception as e:
            logger.warning(f"[EFETIVO] Erro ao completar dados: {e}")

    contexto = {
        "sigla": request.sigla,
        "nup": request.nup,
        "remetente": remetente_dados
    }

    # =========================================================================
    # 2. CLASSIFICA
    # =========================================================================
    classificacao = classificar_documento(request.mensagem, contexto)
    
    tempo_classificacao = int((time.time() - inicio) * 1000)
    logger.info(f"[CLASSIFICADO] Template={classificacao.get('template_id')} | "
                f"Confiança={classificacao.get('confianca', 0):.0%} | "
                f"Tempo={tempo_classificacao}ms")
    
    # =========================================================================
    # 3. SE PRECISA TEXTO LIVRE → RETORNA PARA ARGUS
    # =========================================================================
    if not classificacao["usar_template"] or classificacao.get("texto_livre"):
        tempo_total = int((time.time() - inicio) * 1000)
        
        return DocumentoResponse(
            sucesso=True,
            usou_template=False,
            template_id=classificacao.get("template_id"),
            tipo_sei=classificacao.get("tipo_sei"),
            requer_argus=True,
            mensagem_argus=f"Documento '{classificacao.get('tipo_sei', 'solicitado')}' requer texto livre. "
                          f"ARGUS deve gerar o corpo do documento.",
            campos=classificacao.get("campos"),
            campos_faltantes=classificacao.get("campos_faltantes"),
            tempo_ms=tempo_total,
            confianca=classificacao.get("confianca", 0),
        )
    
    # =========================================================================
    # 4. ADICIONA CAMPOS EXTRAS (se fornecidos)
    # =========================================================================
    campos = classificacao["campos"].copy()
    
    if request.campos_extras:
        campos.update(request.campos_extras)
    
    # =========================================================================
    # 5. VERIFICA CAMPOS FALTANTES
    # =========================================================================
    campos_faltantes = classificacao.get("campos_faltantes", [])
    
    # Remove campos que agora estão preenchidos
    campos_faltantes = [c for c in campos_faltantes if not campos.get(c)]
    
    if campos_faltantes and request.executar_sei:
        tempo_total = int((time.time() - inicio) * 1000)
        
        return DocumentoResponse(
            sucesso=False,
            usou_template=True,
            template_id=classificacao["template_id"],
            tipo_sei=classificacao["tipo_sei"],
            campos=campos,
            campos_faltantes=campos_faltantes,
            tempo_ms=tempo_total,
            confianca=classificacao.get("confianca", 0),
            erro=f"Campos obrigatórios faltantes: {', '.join(campos_faltantes)}",
        )
    
    # =========================================================================
    # 6. PREENCHE O TEMPLATE
    # =========================================================================
    try:
        corpo_html = await preencher_template_campos(
            classificacao["template_id"],
            campos
        )
        
        if not corpo_html:
            raise ValueError("Template retornou vazio")
            
    except Exception as e:
        tempo_total = int((time.time() - inicio) * 1000)
        logger.error(f"[ERRO] Falha ao preencher template: {e}")
        
        return DocumentoResponse(
            sucesso=False,
            usou_template=True,
            template_id=classificacao["template_id"],
            tipo_sei=classificacao["tipo_sei"],
            campos=campos,
            tempo_ms=tempo_total,
            confianca=classificacao.get("confianca", 0),
            erro=f"Erro ao preencher template: {str(e)}",
        )
    
    # =========================================================================
    # 7. SE NÃO EXECUTAR → RETORNA PREVIEW
    # =========================================================================
    if not request.executar_sei:
        tempo_total = int((time.time() - inicio) * 1000)
        
        return DocumentoResponse(
            sucesso=True,
            usou_template=True,
            template_id=classificacao["template_id"],
            tipo_sei=classificacao["tipo_sei"],
            documento_criado=False,
            campos=campos,
            preview_html=corpo_html,
            tempo_ms=tempo_total,
            confianca=classificacao.get("confianca", 0),
        )
    
    # =========================================================================
    # 8. EXECUTA NO SEI
    # =========================================================================
    logger.info(f"[SEI] Executando no SEI...")
    
    resultado_sei = await executar_no_sei(
        nup=request.nup,
        tipo_documento=classificacao["tipo_sei"],
        corpo_html=corpo_html,
        destinatario=request.destinatario.get("nome", "") if request.destinatario else "",
        sigla=request.sigla,
        chat_id=request.chat_id,
    )
    
    tempo_total = int((time.time() - inicio) * 1000)
    
    # =========================================================================
    # 9. RETORNA RESULTADO
    # =========================================================================
    if resultado_sei.get("sucesso") or resultado_sei.get("documento_criado"):
        logger.info(f"[SUCESSO] SEI nº {resultado_sei.get('sei_numero_editor')} | "
                   f"Tempo total={tempo_total}ms")
        
        return DocumentoResponse(
            sucesso=True,
            usou_template=True,
            template_id=classificacao["template_id"],
            tipo_sei=classificacao["tipo_sei"],
            sei_numero=resultado_sei.get("sei_numero_arvore") or resultado_sei.get("numero_doc"),
            sei_numero_editor=resultado_sei.get("sei_numero_editor"),
            documento_criado=True,
            campos=campos,
            tempo_ms=tempo_total,
            confianca=classificacao.get("confianca", 0),
        )
    else:
        logger.error(f"[ERRO] Falha no SEI: {resultado_sei.get('erro')}")
        
        return DocumentoResponse(
            sucesso=False,
            usou_template=True,
            template_id=classificacao["template_id"],
            tipo_sei=classificacao["tipo_sei"],
            documento_criado=False,
            campos=campos,
            preview_html=corpo_html,
            tempo_ms=tempo_total,
            confianca=classificacao.get("confianca", 0),
            erro=resultado_sei.get("erro", "Erro desconhecido ao criar documento no SEI"),
        )


# =============================================================================
# ENDPOINT SIMPLIFICADO (COMPATÍVEL COM N8N)
# =============================================================================

class CriarSimplificadoRequest(BaseModel):
    """Request simplificado para integração com n8n."""
    mensagem: str
    nup: str
    sigla: str
    executar: bool = True
    
    class Config:
        json_schema_extra = {
            "example": {
                "mensagem": "Termo de Encerramento BG 08/2026",
                "nup": "0609.012097.00016/2026-69",
                "sigla": "DRH",
                "executar": True
            }
        }


@app.post("/documento/criar-simples")
async def criar_documento_simplificado(request: CriarSimplificadoRequest):
    """
    Endpoint simplificado que busca dados do remetente automaticamente.
    Ideal para integração com n8n.
    """
    inicio = time.time()
    
    # Busca dados do remetente pela sigla
    remetente_data = consultar_lista_contatos(request.sigla)
    
    if not remetente_data:
        return {
            "sucesso": False,
            "erro": f"Sigla '{request.sigla}' não encontrada na lista de contatos",
            "requer_argus": True,
        }
    
    # Monta contexto
    contexto = {
        "sigla": request.sigla,
        "nup": request.nup,
        "remetente": remetente_data,
    }
    
    # Classifica
    classificacao = classificar_documento(request.mensagem, contexto)
    
    # Se precisa texto livre
    if not classificacao["usar_template"] or classificacao.get("texto_livre"):
        tempo_total = int((time.time() - inicio) * 1000)
        return {
            "sucesso": True,
            "usou_template": False,
            "requer_argus": True,
            "tipo_sei": classificacao.get("tipo_sei"),
            "mensagem": "ARGUS deve gerar texto livre",
            "tempo_ms": tempo_total,
        }
    
    # Preenche template
    try:
        corpo_html = await preencher_template_campos(
            classificacao["template_id"],
            classificacao["campos"]
        )
    except Exception as e:
        return {
            "sucesso": False,
            "erro": str(e),
            "requer_argus": True,
        }
    
    # Se não executar, retorna preview
    if not request.executar:
        tempo_total = int((time.time() - inicio) * 1000)
        return {
            "sucesso": True,
            "usou_template": True,
            "template_id": classificacao["template_id"],
            "tipo_sei": classificacao["tipo_sei"],
            "preview_html": corpo_html,
            "campos": classificacao["campos"],
            "tempo_ms": tempo_total,
        }
    
    # Executa no SEI
    resultado_sei = await executar_no_sei(
        nup=request.nup,
        tipo_documento=classificacao["tipo_sei"],
        corpo_html=corpo_html,
        sigla=request.sigla,
    )
    
    tempo_total = int((time.time() - inicio) * 1000)
    
    return {
        "sucesso": resultado_sei.get("sucesso", False),
        "usou_template": True,
        "template_id": classificacao["template_id"],
        "tipo_sei": classificacao["tipo_sei"],
        "sei_numero_editor": resultado_sei.get("sei_numero_editor"),
        "documento_criado": resultado_sei.get("documento_criado", False),
        "erro": resultado_sei.get("erro"),
        "tempo_ms": tempo_total,
    }


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    
    port = int(os.environ.get("PORT", 8105))
    
    print("=" * 60)
    print("API DE DOCUMENTOS INTELIGENTE")
    print("=" * 60)
    print(f"Templates disponíveis: {len(TEMPLATES_CONFIG)}")
    print(f"Texto livre: {TEXTO_LIVRE_SEMPRE}")
    print(f"Porta: {port}")
    print("=" * 60)
    
    uvicorn.run(
        "api_documento_inteligente:app",
        host="0.0.0.0",
        port=port,
        reload=False,
        log_level="info",
    )
