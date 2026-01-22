"""
Estagiario B - Consolidação
Usa GPT-4.1-mini para consolidar triagens
"""

import json
import asyncio
import os
from typing import List, Dict, Any
from datetime import datetime
import httpx

from ..schemas import (
    TriageV1, HeurV1, CaseV1,
    SituacaoAtual, PedidoVigente, UltimoComando, Pendencia,
    EventoTimeline, CitacaoBase, FluxoTramitacao,
    criar_case_v1
)

# =============================================================================
# CONFIGURACAO
# =============================================================================

class ConfigEstagiarioB:
    modelo: str = "gpt-4.1-mini"
    api_url: str = "https://api.openai.com/v1/chat/completions"
    max_tokens: int = 2048
    temperature: float = 0.1
    timeout: int = 60

config = ConfigEstagiarioB()

# =============================================================================
# PROMPT - CONSOLIDAÇÃO
# =============================================================================

PROMPT_SISTEMA_B = """Você é um analista de processos administrativos do SEI do Corpo de Bombeiros do Acre (CBMAC).
Sua tarefa é identificar a SITUAÇÃO ATUAL do processo e o FLUXO DE TRAMITAÇÃO.
Retorne APENAS JSON válido, sem explicações."""

PROMPT_CONSOLIDACAO = """Consolide estes documentos do processo {nup}:

DOCUMENTOS (mais recente primeiro):
{documentos}

---
Retorne EXATAMENTE este JSON:
{{
  "situacao_atual": "<ESCOLHA UMA DAS OPÇÕES ABAIXO - OBRIGATÓRIO>",
  "situacao_descricao": "1-2 frases explicando a situação",
  "pedido_vigente": {{
    "descricao": "o que está sendo pedido/aguardado AGORA",
    "doc_id_origem": "ID do documento",
    "urgente": false
  }},
  "ultimo_comando": {{
    "descricao": "última determinação dada",
    "doc_id": "ID do documento",
    "destino": "sigla da unidade que deve executar"
  }},
  "fluxo_tramitacao": {{
    "demandante": "sigla ESPECÍFICA de quem iniciou (COI, 2BEPCIF, 3BEPCIF, DRH - NUNCA use CBMAC)",
    "executora": "sigla de quem deve agir AGORA",
    "resposta": "sigla de quem recebe o resultado",
    "caminho": ["SIGLA1", "SIGLA2", "SIGLA3"]
  }},
  "pendencias_abertas": [],
  "timeline": [
    {{"doc_id": "ID", "unidade": "SIGLA", "evento": "descrição curta", "tipo": "PEDIDO|DECISAO|COMANDO|ENCAMINHAMENTO"}}
  ],
  "docs_relevantes": ["ID1", "ID2"]
}}

=== OPÇÕES PARA situacao_atual (ESCOLHA A MAIS ADEQUADA) ===

"PENDENTE PUBLICACAO" - PRIORIDADE ALTA, use quando:
  - Existe despacho com "Publicar em BG" ou "Publicar no BG"
  - Existe NBG com "Concedo", "Autorizo", "Defiro"
  - O pedido JÁ FOI DEFERIDO, falta DRH publicar no Boletim Geral
  - Último comando direciona para DRH para publicação

"DEFERIDO" - use quando:
  - Pedido aprovado E já publicado, ou não precisa de publicação
  - Decreto do Governador concedendo algo

"INDEFERIDO" - use quando:
  - Pedido negado explicitamente com "Indefiro", "Nego", "Não autorizo"

"AGUARDANDO ANALISE" - use quando:
  - Processo novo, sem manifestação de mérito ainda
  - Apenas encaminhamentos sem decisão

"EM TRAMITACAO" - use quando:
  - Passando entre unidades
  - Aguardando parecer ou manifestação
  - Sem decisão final ainda

"RECURSO EM ANALISE" - use quando:
  - Há recurso ou reconsideração interposta

"ARQUIVADO" - use quando:
  - Processo encerrado com Termo de Encerramento

"CONCLUIDO" - use quando:
  - Todas as pendências resolvidas, sem necessidade de mais ações

=== REGRAS CRÍTICAS ===

1. "Publicar em BG" no despacho = SEMPRE "PENDENTE PUBLICACAO"
2. NBG com "Concedo" + despacho "Publicar em BG" = "PENDENTE PUBLICACAO"
3. Extrair demandante de "CBMAC - COI" → use "COI" (NUNCA "CBMAC" genérico)
4. "AO SENHOR... DIRETOR DE RECURSOS HUMANOS" = executora "DRH"
5. "AO SENHOR... COMANDANTE GERAL" = executora "CMDGER"
6. Caminho deve mostrar sequência real do fluxo

=== IMPORTANTE ===
NÃO existe opção "OUTRO". Escolha a situação mais próxima da realidade.
Se não tiver certeza, use "EM TRAMITACAO".

JSON:"""

# =============================================================================
# CHAMADA OPENAI
# =============================================================================

async def chamar_llm_consolidacao(
    nup: str,
    docs_str: str,
    api_key: str
) -> Dict[str, Any]:
    """Chama GPT-4.1-mini para consolidar."""
    
    prompt = PROMPT_CONSOLIDACAO.format(nup=nup, documentos=docs_str)
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": config.modelo,
        "max_tokens": config.max_tokens,
        "temperature": config.temperature,
        "messages": [
            {"role": "system", "content": PROMPT_SISTEMA_B},
            {"role": "user", "content": prompt}
        ]
    }
    
    async with httpx.AsyncClient(timeout=config.timeout) as client:
        try:
            response = await client.post(config.api_url, json=payload, headers=headers)
            response.raise_for_status()
            
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            
            # Limpar JSON
            content = content.strip()
            if "```" in content:
                parts = content.split("```")
                for part in parts:
                    part = part.strip()
                    if part.startswith("json"):
                        part = part[4:].strip()
                    if part.startswith("{"):
                        content = part
                        break
            
            resultado = json.loads(content)
            
            # Pós-processamento: forçar PENDENTE PUBLICACAO se detectar padrão
            situacao = resultado.get("situacao_atual", "")
            docs_lower = docs_str.lower()
            
            if "publicar em bg" in docs_lower or "publicar no bg" in docs_lower:
                resultado["situacao_atual"] = "PENDENTE PUBLICACAO"
            elif situacao == "OUTRO" or not situacao:
                resultado["situacao_atual"] = "EM TRAMITACAO"
            
            return resultado
            
        except Exception as e:
            return {"_erro": str(e), "situacao_atual": "EM TRAMITACAO"}

# =============================================================================
# FORMATAR DOCS PARA PROMPT
# =============================================================================

def formatar_docs_para_consolidacao(itens: list, cobertura: dict = None) -> str:
    """Formata triagens para o prompt."""
    docs_str = ""
    for item in itens:
        unidade = getattr(item, 'unidade_origem', 'N/A')
        destino = getattr(item, 'unidade_destino', 'N/A')
        resultado = item.resultado.value if item.resultado else 'N/A'
        assunto = item.assunto_curto or 'N/A'
        
        docs_str += f"""
DOC_ID: {item.doc_id}
ORIGEM: {unidade}
DESTINO: {destino}
ATO: {item.ato_semantico.value}
ASSUNTO: {assunto}
RESULTADO: {resultado}
STATUS: {item.status}
---"""
    return docs_str

# =============================================================================
# FALLBACK
# =============================================================================

def consolidacao_fallback(triage: TriageV1, heur: HeurV1) -> Dict[str, Any]:
    """Consolidação básica sem LLM."""
    
    itens = sorted(triage.itens, key=lambda x: x.doc_id, reverse=True)
    
    # Coletar unidades (excluir CBMAC genérico)
    unidades = []
    for item in itens:
        u = getattr(item, 'unidade_origem', None)
        if u and u not in unidades and u != "CBMAC":
            unidades.append(u)
    
    # Detectar situação
    situacao = "EM TRAMITACAO"  # Default ao invés de OUTRO
    ultimo_destino = None
    tem_publicar_bg = False
    tem_deferido = False
    
    for item in itens:
        destino = getattr(item, 'unidade_destino', None)
        assunto = (item.assunto_curto or "").upper()
        
        # Detectar "Publicar em BG"
        if "PUBLICAR EM BG" in assunto or "PUBLICAR NO BG" in assunto:
            tem_publicar_bg = True
            ultimo_destino = destino or "DRH"
            
        if item.ato_semantico.value == "COMANDO" and destino:
            ultimo_destino = destino
            
        if item.resultado:
            if item.resultado.value == "DEFERIDO":
                tem_deferido = True
            elif item.resultado.value == "INDEFERIDO":
                situacao = "INDEFERIDO"
                break
    
    # Determinar situação final
    if tem_publicar_bg:
        situacao = "PENDENTE PUBLICACAO"
    elif tem_deferido and ultimo_destino == "DRH":
        situacao = "PENDENTE PUBLICACAO"
    elif tem_deferido:
        situacao = "DEFERIDO"
    
    return {
        "situacao_atual": situacao,
        "situacao_descricao": "",
        "fluxo_tramitacao": {
            "demandante": unidades[-1] if unidades else None,
            "executora": ultimo_destino or (unidades[0] if unidades else None),
            "resposta": unidades[-1] if unidades else None,
            "caminho": list(reversed(unidades)) + ([ultimo_destino] if ultimo_destino and ultimo_destino not in unidades else [])
        },
        "pedido_vigente": None,
        "ultimo_comando": {
            "destino": ultimo_destino
        } if ultimo_destino else None,
        "pendencias_abertas": [],
        "timeline": [
            {"doc_id": item.doc_id, "unidade": getattr(item, 'unidade_origem', None), 
             "evento": item.assunto_curto, "tipo": item.ato_semantico.value}
            for item in itens[:5]
        ],
        "docs_relevantes": [item.doc_id for item in itens[:7]]
    }

# =============================================================================
# CONVERSÃO
# =============================================================================

def converter_para_case_v1(resposta: Dict[str, Any], nup: str) -> CaseV1:
    case = criar_case_v1(nup)
    
    situacao_str = resposta.get("situacao_atual", "EM TRAMITACAO")
    
    # Converter OUTRO para EM TRAMITACAO
    if situacao_str == "OUTRO" or not situacao_str:
        situacao_str = "EM TRAMITACAO"
    
    try:
        case.situacao_atual = SituacaoAtual(situacao_str)
    except ValueError:
        case.situacao_atual = SituacaoAtual.EM_TRAMITACAO
    
    case.situacao_descricao = resposta.get("situacao_descricao", "")
    
    pv = resposta.get("pedido_vigente")
    if pv and isinstance(pv, dict):
        case.pedido_vigente = PedidoVigente(
            descricao=pv.get("descricao", ""),
            doc_id_origem=pv.get("doc_id_origem", ""),
            urgente=pv.get("urgente", False)
        )
    
    uc = resposta.get("ultimo_comando")
    if uc and isinstance(uc, dict):
        case.ultimo_comando = UltimoComando(
            descricao=uc.get("descricao", ""),
            doc_id=uc.get("doc_id", ""),
            prazo=uc.get("prazo"),
            destino=uc.get("destino")
        )
    
    ft = resposta.get("fluxo_tramitacao", {})
    if ft:
        case.fluxo_tramitacao = FluxoTramitacao(
            demandante=ft.get("demandante"),
            executora=ft.get("executora"),
            resposta=ft.get("resposta"),
            caminho=ft.get("caminho", [])
        )
    
    for ev in resposta.get("timeline", []):
        if isinstance(ev, dict):
            evento = EventoTimeline(
                doc_id=ev.get("doc_id", ""),
                evento=ev.get("evento", ""),
                tipo=ev.get("tipo")
            )
            evento.unidade = ev.get("unidade")
            case.timeline.append(evento)
    
    case.docs_relevantes = resposta.get("docs_relevantes", [])
    case.processado_em = datetime.now()
    
    return case

# =============================================================================
# PROCESSAMENTO
# =============================================================================

async def processar_consolidacao_async(
    triage: TriageV1,
    heur: HeurV1,
    api_key: str = None,
    usar_llm: bool = True
) -> CaseV1:
    
    nup = triage.nup
    api_key = api_key or os.environ.get("OPENAI_API_KEY")
    
    if usar_llm and api_key:
        docs_str = formatar_docs_para_consolidacao(triage.itens)
        resposta = await chamar_llm_consolidacao(nup, docs_str, api_key)
        case = converter_para_case_v1(resposta, nup)
        case.modelo_usado = config.modelo
    else:
        resposta = consolidacao_fallback(triage, heur)
        case = converter_para_case_v1(resposta, nup)
        case.modelo_usado = "fallback"
    
    return case

def processar_consolidacao(
    triage: TriageV1,
    heur: HeurV1,
    api_key: str = None,
    usar_llm: bool = True
) -> CaseV1:
    return asyncio.run(processar_consolidacao_async(triage, heur, api_key, usar_llm))
