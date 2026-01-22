"""
ANALISTA LLM - Pipeline v2.0
=============================
GPT-4.1-mini para gerar JSON rico com análise completa.
"""

import json
import sys
import httpx
from typing import Dict, Any
from datetime import datetime

# path no container
from .config import get_openai_key, MODELO_ANALISTA

API_URL = "https://api.openai.com/v1/chat/completions"

PROMPT_ANALISTA = """Analise os documentos do processo {nup} e extraia informações estruturadas.

## DOCUMENTOS:
{documentos_texto}

## RETORNE JSON:
{{
  "interessado": {{
    "nome": "Nome completo",
    "posto_grad": "Posto/Graduação",
    "unidade": "Unidade de lotação",
    "vinculo": "Militar|Servidor|Civil|Órgão externo"
  }},
  "pedido": {{
    "tipo": "TRANSFERÊNCIA|LICENÇA|DOAÇÃO|CESSÃO|etc",
    "descricao": "Descrição curta do pedido",
    "motivo": "Motivação"
  }},
  "situacao": {{
    "status": "EM_ANALISE|DEFERIDO|INDEFERIDO|PENDENTE_PUBLICACAO|ARQUIVADO",
    "etapa_atual": "Onde está agora",
    "proximo_passo": "O que precisa acontecer"
  }},
  "fluxo": {{
    "origem": "Sigla origem",
    "destino_final": "Sigla decisória",
    "caminho": ["SIGLA1", "SIGLA2"],
    "unidade_atual": "Onde está"
  }},
  "prazos": [{{"descricao": "...", "data_limite": "DD/MM/AAAA", "status": "PENDENTE|CUMPRIDO"}}],
  "legislacao": [{{"tipo": "Lei|Decreto", "numero": "...", "artigo": "..."}}],
  "resumo_executivo": "2-3 frases resumindo o processo",
  "alertas": ["Pontos de atenção"],
  "confianca": 0.85
}}

REGRAS:
- Se não encontrar, use null
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
        emoji = "🔴" if prio == "ALTA" else "🟡" if prio == "MEDIA" else "🟢"
        partes.append(f"---\n{emoji}[{pos}] {tipo} | {sigla}\n{conteudo}\n---")
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
            {"role": "system", "content": "Você é um analista de processos. Responda APENAS JSON válido."},
            {"role": "user", "content": prompt}
        ]
    }
    
    try:
        inicio = datetime.now()
        response = httpx.post(API_URL, json=payload, headers=headers, timeout=90)
        response.raise_for_status()
        duracao = (datetime.now() - inicio).total_seconds()
        
        data = response.json()
        conteudo = data["choices"][0]["message"]["content"].strip()
        if "```" in conteudo:
            conteudo = conteudo.split("```")[1].replace("json", "").strip()
        
        resultado = json.loads(conteudo)
        resultado["_meta"] = {
            "modelo": MODELO_ANALISTA,
            "tokens": data["usage"]["total_tokens"],
            "duracao_s": duracao,
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


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python analista_llm.py <heur_filtrado.json ou curado.json>")
        sys.exit(1)
    
    with open(sys.argv[1]) as f:
        data = json.load(f)
    
    # Se vier do curador, pegar heuristica_filtrada
    if 'heuristica_filtrada' in data:
        heur = data['heuristica_filtrada']
    else:
        heur = data
    
    print(f"📊 Analisando: {heur.get('nup')}")
    print(f"📄 Docs: {len(heur.get('documentos', []))}")
    
    res = analisar_processo(heur)
    
    if res.get('sucesso'):
        print(f"✅ Análise OK!")
        print(f"👤 Interessado: {res.get('interessado', {}).get('nome', 'N/A')}")
        print(f"📋 Pedido: {res.get('pedido', {}).get('tipo', 'N/A')}")
        print(f"🚦 Status: {res.get('situacao', {}).get('status', 'N/A')}")
        print(f"📝 Resumo: {res.get('resumo_executivo', 'N/A')[:100]}...")
        print(f"💰 ${res['_meta']['custo']:.6f}")
        
        out = sys.argv[1].replace('.json', '_analise.json').replace('_curado', '').replace('_heur', '')
        with open(out, 'w') as f:
            json.dump(res, f, indent=2, ensure_ascii=False)
        print(f"💾 {out}")
    else:
        print(f"❌ {res.get('erro')}")
