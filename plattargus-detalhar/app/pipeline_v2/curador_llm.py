"""
CURADOR LLM - Pipeline v2.0
============================
GPT-4o-mini para selecionar os 8-12 docs essenciais.
"""

import json
import sys
import httpx
from typing import Dict, Any
from datetime import datetime

# path no container
from .config import get_openai_key, MODELO_CURADOR

API_URL = "https://api.openai.com/v1/chat/completions"

PROMPT_CURADOR = """Você é um curador de processos administrativos. Selecione os 8-12 documentos ESSENCIAIS.

## PROCESSO: {nup}
## TOTAL: {total_docs} documentos | {total_chars:,} caracteres

## DOCUMENTOS:
{lista_documentos}

## CRITÉRIOS:
1. SEMPRE INCLUIR: Demandante (1º doc), Despachos CMDGER/SUBCMD, Memorandos, Portarias
2. INCLUIR SE RELEVANTE: Pareceres, Ofícios externos (PMAC, SEAD)
3. EXCLUIR: Encaminhamentos repetitivos, Anexos sem mérito

RETORNE JSON:
{{"docs_selecionados": [1, 2, 5, 9], "resumo_rapido": "...", "confianca": 0.9}}"""


def chamar_curador(nup: str, total_docs: int, total_chars: int, lista_documentos: str) -> Dict[str, Any]:
    try:
        api_key = get_openai_key()
    except ValueError as e:
        return {"erro": str(e), "sucesso": False}
    
    prompt = PROMPT_CURADOR.format(nup=nup, total_docs=total_docs, total_chars=total_chars, lista_documentos=lista_documentos)
    
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": MODELO_CURADOR,
        "max_tokens": 1500,
        "temperature": 0.1,
        "messages": [
            {"role": "system", "content": "Responda APENAS JSON válido."},
            {"role": "user", "content": prompt}
        ]
    }
    
    try:
        inicio = datetime.now()
        response = httpx.post(API_URL, json=payload, headers=headers, timeout=60)
        response.raise_for_status()
        duracao = (datetime.now() - inicio).total_seconds()
        
        data = response.json()
        conteudo = data["choices"][0]["message"]["content"].strip()
        if "```" in conteudo:
            conteudo = conteudo.split("```")[1].replace("json", "").strip()
        
        resultado = json.loads(conteudo)
        resultado["_meta"] = {
            "modelo": MODELO_CURADOR,
            "tokens": data["usage"]["total_tokens"],
            "duracao_s": duracao,
            "custo": (data["usage"]["prompt_tokens"] * 0.15 + data["usage"]["completion_tokens"] * 0.6) / 1_000_000
        }
        resultado["sucesso"] = True
        return resultado
    except Exception as e:
        return {"erro": str(e), "sucesso": False}


def formatar_lista(heur: Dict) -> str:
    linhas = []
    for doc in heur.get('documentos', []):
        pos = doc.get('posicao_processada', doc.get('indice', 0))
        tipo = doc.get('_tipo_normalizado', 'DOC')
        sigla = doc.get('_sigla_normalizada', '?')
        chars = len(doc.get('conteudo', ''))
        prio = doc.get('classificacao', {}).get('prioridade', 'MEDIA')
        emoji = "🔴" if prio == "ALTA" else "🟡" if prio == "MEDIA" else "🟢"
        linhas.append(f"{emoji}[{pos:2d}] {tipo:12}|{sigla:18}|{chars:5}ch")
    return "\n".join(linhas)


def curar_processo(heur: Dict) -> Dict:
    nup = heur.get('nup', '?')
    total_docs = len(heur.get('documentos', []))
    total_chars = heur.get('metricas', {}).get('total_chars', 0)
    
    resultado = chamar_curador(nup, total_docs, total_chars, formatar_lista(heur))
    if not resultado.get('sucesso'):
        return resultado
    
    docs_sel = resultado.get('docs_selecionados', [])
    docs_filt = [d for d in heur['documentos'] if d.get('posicao_processada', d.get('indice')) in docs_sel]
    chars_filt = sum(len(d.get('conteudo', '')) for d in docs_filt)
    
    resultado["nup"] = nup
    resultado["total_original"] = total_docs
    resultado["total_selecionado"] = len(docs_filt)
    resultado["reducao_percent"] = round((1 - chars_filt / total_chars) * 100, 1) if total_chars else 0
    resultado["heuristica_filtrada"] = {"nup": nup, "documentos": docs_filt, "metricas": {"chars": chars_filt}}
    return resultado


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python curador_llm.py <heur.json>")
        sys.exit(1)
    
    with open(sys.argv[1]) as f:
        heur = json.load(f)
    
    print(f"📊 Curando: {heur.get('nup')}")
    print(f"📄 Docs: {len(heur.get('documentos', []))}")
    
    res = curar_processo(heur)
    
    if res.get('sucesso'):
        print(f"✅ OK! {res['total_original']}→{res['total_selecionado']} docs ({res['reducao_percent']}%)")
        print(f"📄 Selecionados: {res['docs_selecionados']}")
        print(f"💰 ${res['_meta']['custo']:.6f}")
        
        out = sys.argv[1].replace('_heur.json', '_curado.json')
        with open(out, 'w') as f:
            json.dump(res, f, indent=2, ensure_ascii=False)
        print(f"💾 {out}")
    else:
        print(f"❌ {res.get('erro')}")
