"""
Estagiario A - Triagem por Documento
Usa GPT-4o-mini para analisar cada documento
"""

import json
import asyncio
import os
from typing import List, Dict, Any
from datetime import datetime
import httpx

from ..schemas import (
    DocV1, TriageV1, ItemTriagem, AtoSemantico, ResultadoAto, Prazo, Citacao,
    criar_triage_v1, criar_item_triagem
)

# =============================================================================
# CONFIGURACAO
# =============================================================================

class ConfigEstagiarioA:
    modelo: str = "gpt-4o-mini"
    api_url: str = "https://api.openai.com/v1/chat/completions"
    max_tokens: int = 1024
    temperature: float = 0.1
    timeout: int = 30
    max_concurrent: int = 5

config = ConfigEstagiarioA()

# =============================================================================
# PROMPT SIMPLIFICADO - TRIAGEM
# =============================================================================

PROMPT_SISTEMA_A = """Você analisa documentos do SEI (Sistema Eletrônico de Informações) do Corpo de Bombeiros do Acre.
Retorne APENAS JSON válido, sem explicações."""

PROMPT_TRIAGEM = """Analise este documento e retorne JSON:

DOCUMENTO:
- ID: {doc_id}
- Tipo: {tipo_documento}
- Origem: {unidade_origem}
- Título: {titulo}

TEXTO:
{texto}

---
Retorne EXATAMENTE este JSON:
{{
  "doc_id": "{doc_id}",
  "ato_semantico": "PEDIDO|COMANDO|DECISAO|PARECER|ENCAMINHAMENTO|OUTRO",
  "assunto_curto": "1 frase curta",
  "resultado": "DEFERIDO|INDEFERIDO|null",
  "unidade_origem": "{unidade_origem}",
  "unidade_destino": "sigla ou null",
  "status": "pendente|resolvido",
  "confianca": 0.8
}}

REGRAS:
1. NBG com "Concedo" ou "Autorizo" = DECISAO + DEFERIDO
2. Despacho com "Publicar em BG" = COMANDO (destino = DRH)
3. "AO SENHOR... DIRETOR DE RECURSOS HUMANOS" = destino DRH
4. unidade_origem = extrair de "CBMAC - SIGLA" (use {unidade_origem})
5. Nunca use "CBMAC" genérico, sempre a sigla específica (COI, DRH, 2BEPCIF)

JSON:"""

# =============================================================================
# CHAMADA OPENAI
# =============================================================================

async def chamar_llm_triagem(doc: DocV1, api_key: str) -> Dict[str, Any]:
    """Chama GPT-4o-mini para triar documento."""
    
    unidade = doc.get_sigla_efetiva() or getattr(doc, 'sigla_origem', 'N/A')
    
    prompt = PROMPT_TRIAGEM.format(
        doc_id=doc.doc_id,
        tipo_documento=doc.tipo_documento.value if doc.tipo_documento else "OUTROS",
        unidade_origem=unidade,
        titulo=doc.titulo_arvore or "",
        texto=doc.texto_limpo[:3000] if doc.texto_limpo else ""
    )
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": config.modelo,
        "max_tokens": config.max_tokens,
        "temperature": config.temperature,
        "messages": [
            {"role": "system", "content": PROMPT_SISTEMA_A},
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
                content = content.split("```")[1].replace("json", "").strip()
            
            resultado = json.loads(content)
            resultado["unidade_origem"] = resultado.get("unidade_origem") or unidade
            return resultado
            
        except Exception as e:
            return {
                "doc_id": doc.doc_id,
                "ato_semantico": "OUTRO",
                "assunto_curto": doc.titulo_arvore or "",
                "resultado": None,
                "unidade_origem": unidade,
                "unidade_destino": None,
                "status": "pendente",
                "confianca": 0.0,
                "_erro": str(e)
            }

# =============================================================================
# FALLBACK REGEX
# =============================================================================

def triagem_fallback_regex(doc: DocV1) -> Dict[str, Any]:
    """Triagem básica sem LLM."""
    from .tags_detector import classificar_ato
    from ..schemas.doc_v1 import TagTecnica
    import re
    
    unidade = doc.get_sigla_efetiva() or getattr(doc, 'sigla_origem', None)
    texto = doc.texto_limpo.upper() if doc.texto_limpo else ""
    
    # Detectar destino
    destino = None
    if "DIRETOR DE RECURSOS HUMANOS" in texto:
        destino = "DRH"
    elif "COMANDANTE GERAL" in texto or "COMANDANTE-GERAL" in texto:
        destino = "CMDGER"
    elif match := re.search(r'AO\s+(?:SENHOR\s+)?(\w+)', texto):
        destino = match.group(1)
    
    # Classificar ato
    tipo_ato = classificar_ato(doc.tags_tecnicas, doc.tipo_documento.value if doc.tipo_documento else "")
    mapa_ato = {
        "ATO_DECISAO": "DECISAO",
        "ATO_COMANDO": "COMANDO", 
        "ATO_PEDIDO": "PEDIDO",
        "ATO_TRAMITE": "ENCAMINHAMENTO",
    }
    ato = mapa_ato.get(tipo_ato, "OUTRO")
    
    # Detectar resultado
    resultado = None
    status = "pendente"
    if TagTecnica.TEM_DEFERIMENTO in doc.tags_tecnicas or "CONCEDO" in texto or "AUTORIZO" in texto:
        resultado = "DEFERIDO"
        status = "resolvido"
    elif TagTecnica.TEM_INDEFERIMENTO in doc.tags_tecnicas:
        resultado = "INDEFERIDO"
        status = "resolvido"
    
    # Publicar em BG = COMANDO
    if "PUBLICAR EM BG" in texto:
        ato = "COMANDO"
        destino = "DRH"
    
    return {
        "doc_id": doc.doc_id,
        "ato_semantico": ato,
        "assunto_curto": doc.titulo_arvore or "",
        "resultado": resultado,
        "unidade_origem": unidade,
        "unidade_destino": destino,
        "status": status,
        "confianca": 0.6
    }

# =============================================================================
# CONVERSÃO
# =============================================================================

def converter_para_item_triagem(resposta: Dict[str, Any], doc_id: str) -> ItemTriagem:
    try:
        ato = AtoSemantico(resposta.get("ato_semantico", "OUTRO").upper())
    except ValueError:
        ato = AtoSemantico.OUTRO
    
    resultado = None
    if resposta.get("resultado"):
        try:
            resultado = ResultadoAto(resposta["resultado"].upper())
        except ValueError:
            pass
    
    return ItemTriagem(
        doc_id=doc_id,
        ato_semantico=ato,
        assunto_curto=resposta.get("assunto_curto", ""),
        pedido_principal=resposta.get("pedido_principal"),
        providencia_solicitada=resposta.get("providencia_solicitada"),
        prazo=Prazo(existe=False, texto=None),
        resultado=resultado,
        citacoes=[],
        status=resposta.get("status", "pendente"),
        confianca=float(resposta.get("confianca", 0.5)),
        unidade_origem=resposta.get("unidade_origem"),
        unidade_destino=resposta.get("unidade_destino"),
    )

# =============================================================================
# PROCESSAMENTO
# =============================================================================

async def processar_triagem_lote(
    docs: List[DocV1],
    api_key: str = None,
    usar_llm: bool = True,
    max_concurrent: int = None
) -> TriageV1:
    
    nup = docs[0].nup if docs else ""
    api_key = api_key or os.environ.get("OPENAI_API_KEY")
    modelo = config.modelo if usar_llm and api_key else "fallback_regex"
    
    triage = criar_triage_v1(nup, modelo)
    triage.total_docs_analisados = len(docs)
    
    itens: List[ItemTriagem] = []
    
    if usar_llm and api_key:
        semaphore = asyncio.Semaphore(max_concurrent or config.max_concurrent)
        
        async def processar_um(doc: DocV1):
            async with semaphore:
                resposta = await chamar_llm_triagem(doc, api_key)
                return converter_para_item_triagem(resposta, doc.doc_id)
        
        tasks = [processar_um(doc) for doc in docs]
        itens = await asyncio.gather(*tasks)
    else:
        for doc in docs:
            resposta = triagem_fallback_regex(doc)
            itens.append(converter_para_item_triagem(resposta, doc.doc_id))
    
    triage.itens = itens
    triage.processado_em = datetime.now()
    return triage

def processar_triagem(docs: List[DocV1], api_key: str = None, usar_llm: bool = True) -> TriageV1:
    return asyncio.run(processar_triagem_lote(docs, api_key, usar_llm))
