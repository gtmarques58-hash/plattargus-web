"""
ANALISTA LLM - Pipeline v2.0 (Standalone para FastAPI)
=============================
GPT-4.1-mini para gerar JSON rico com analise completa.
"""

import json
import sys
import httpx
from typing import Dict, Any

from .config import get_openai_key, MODELO_ANALISTA

API_URL = "https://api.openai.com/v1/chat/completions"

PROMPT_ANALISTA = """Analise os documentos do processo {nup} e extraia informacoes estruturadas.

## DOCUMENTOS:
{documentos_texto}

## RETORNE JSON:
{{
  "interessado": {{
    "nome": "Nome completo",
    "posto_grad": "Posto/Graduacao",
    "unidade": "Unidade de lotacao",
    "vinculo": "Militar|Servidor|Civil|Orgao externo"
  }},
  "pedido": {{
    "tipo": "TRANSFERENCIA|LICENCA|DOACAO|CESSAO|etc",
    "descricao": "Descricao curta do pedido",
    "motivo": "Motivacao"
  }},
  "situacao": {{
    "status": "EM_ANALISE|DEFERIDO|INDEFERIDO|PENDENTE_PUBLICACAO|ARQUIVADO",
    "etapa_atual": "Onde esta agora",
    "proximo_passo": "O que precisa acontecer"
  }},
  "fluxo": {{
    "origem": "Sigla origem",
    "destino_final": "Sigla decisoria",
    "caminho": ["SIGLA1", "SIGLA2"],
    "unidade_atual": "Onde esta"
  }},
  "prazos": [{{"descricao": "...", "data_limite": "DD/MM/AAAA", "status": "PENDENTE|CUMPRIDO"}}],
  "legislacao": [{{"tipo": "Lei|Decreto", "numero": "...", "artigo": "..."}}],
  "resumo_executivo": "2-3 frases resumindo o processo",
  "alertas": ["Pontos de atencao"],
  "sugestao": "Sugestao de proximo passo ou minuta de documento",
  "confianca": 0.85
}}

REGRAS:
- Se nao encontrar, use null
- Seja FIEL aos documentos
- Priorize documentos recentes"""


def formatar_docs(heur: Dict) -> str:
    partes = []
    for doc in heur.get('documentos', []):
        pos = doc.get('posicao_processada', doc.get('indice', 0))
        tipo = doc.get('_tipo_normalizado', 'DOC')
        sigla = doc.get('_sigla_normalizada', '?')
        prio = doc.get('classificacao', {}).get('prioridade', 'MEDIA')
        conteudo = doc.get('conteudo', '')[:2500]
        emoji = "A" if prio == "ALTA" else "M" if prio == "MEDIA" else "B"
        partes.append(f"---\n[{emoji}][{pos}] {tipo} | {sigla}\n{conteudo}\n---")
    return "\n".join(partes)


def chamar_analista(nup: str, docs_texto: str) -> Dict:
    try:
        api_key = get_openai_key()
    except ValueError as e:
        return {"erro": str(e), "sucesso": False}

    prompt = PROMPT_ANALISTA.format(nup=nup, documentos_texto=docs_texto)

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": MODELO_ANALISTA,
        "max_tokens": 4000,
        "temperature": 0.1,
        "messages": [
            {"role": "system", "content": "Voce e um analista de processos. Responda APENAS JSON valido."},
            {"role": "user", "content": prompt}
        ]
    }

    try:
        response = httpx.post(API_URL, json=payload, headers=headers, timeout=90)
        response.raise_for_status()

        data = response.json()
        conteudo = data["choices"][0]["message"]["content"].strip()
        if "```" in conteudo:
            conteudo = conteudo.split("```")[1].replace("json", "").strip()

        resultado = json.loads(conteudo)
        resultado["_meta"] = {
            "modelo": MODELO_ANALISTA,
            "tokens": data["usage"]["total_tokens"],
            "custo": (data["usage"]["prompt_tokens"] * 0.4 + data["usage"]["completion_tokens"] * 1.6) / 1_000_000
        }
        resultado["sucesso"] = True
        return resultado
    except Exception as e:
        return {"erro": str(e), "sucesso": False}


def analisar_processo(heur: Dict) -> Dict:
    nup = heur.get('nup', '?')
    docs_texto = formatar_docs(heur)

    resultado = chamar_analista(nup, docs_texto)
    resultado["nup"] = nup
    resultado["total_docs_analisados"] = len(heur.get('documentos', []))
    return resultado
