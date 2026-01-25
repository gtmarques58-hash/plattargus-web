#!/usr/bin/env python3
"""
laravel_integration.py v3.1 - COM ANíLISE IA + JSON COMPLETO
Fluxo: detalhar_processo (--full) -> Agente IA -> JSON estruturado com documentos
"""
import os, sys, json, re, time
from typing import Optional, Dict, List
from pathlib import Path
from pydantic import BaseModel
import httpx
from typing import List

sys.path.insert(0, '/app/scripts')
sys.path.insert(0, '/app')

# Pipeline v2 integrado
try:
    from pipeline_v2.orquestrador import processar_pipeline_v2, formatar_analise_para_contexto
    PIPELINE_V2_DISPONIVEL = True
    print("[INIT] Pipeline v2 carregado com sucesso", file=sys.stderr)
except ImportError as e:
    PIPELINE_V2_DISPONIVEL = False
    print(f"[INIT] Pipeline v2 nao disponivel: {e}", file=sys.stderr)

SEI_RUNNER_URL = os.getenv("SEI_RUNNER_URL", "http://runner:8001")
DETALHAR_WORKER_URL = os.getenv("DETALHAR_WORKER_URL", "http://plattargus-detalhar-worker:8102")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
PROMPTS_DIR = Path("/app/prompts")
USAR_PIPELINE_V2 = os.getenv("USAR_PIPELINE_V2", "true").lower() == "true"
USAR_DETALHAR_WORKER = os.getenv("USAR_DETALHAR_WORKER", "true").lower() == "true"

# API de Efetivo
EFETIVO_API_URL = os.getenv("EFETIVO_API_URL", "https://efetivo.gt2m58.cloud")
EFETIVO_API_KEY = os.getenv("EFETIVO_API_KEY", "gw_PlattArgusWeb2025_CBMAC")

# ============================================================
# MODELOS
# ============================================================

class CredencialSEI(BaseModel):
    usuario: str
    senha: str
    orgao_id: str = "31"
    nome: Optional[str] = None
    cargo: Optional[str] = None

class AnalisarProcessoRequest(BaseModel):
    nup: str
    credencial: CredencialSEI

class DestinatarioData(BaseModel):
    sigla: str
    nome: Optional[str] = None
    posto_grad: Optional[str] = None
    cargo: Optional[str] = None
    unidade: Optional[str] = None
    sigla_sei: Optional[str] = None

class RemetenteData(BaseModel):
    nome: Optional[str] = None
    posto_grad: Optional[str] = None
    cargo: Optional[str] = None
    unidade: Optional[str] = None
    portaria: Optional[str] = None

class GerarDocumentoRequest(BaseModel):
    job_id: Optional[str] = None
    user_id: Optional[int] = None
    nup: str
    modo: str = "gerar"
    tipo_documento: str
    template_id: Optional[str] = None
    analise: Optional[dict] = None
    destinatario: Optional[str] = None  # Mantém compatibilidade
    destinatarios: Optional[List[DestinatarioData]] = None  # Novo: lista de destinatários
    remetente: Optional[RemetenteData] = None  # Novo: dados do remetente
    usuario_sei: Optional[str] = None
    instrucao_voz: Optional[str] = None  # Instrução do usuário via comando de voz/texto

class InserirSEIRequest(BaseModel):
    nup: str
    tipo_documento: str
    html: str
    destinatario: Optional[str] = None
    credencial: CredencialSEI

class AssinarSEIRequest(BaseModel):
    sei_numero: str
    credencial: CredencialSEI
    job_id: Optional[str] = None
    user_id: Optional[int] = None
    modo: Optional[str] = "assinar"

# ============================================================
# FUNííES AUXILIARES
# ============================================================


def limpar_html_para_sei(html: str) -> str:
    """
    Remove o bloco de NUP e Tipo de Documento do corpo HTML antes de enviar ao SEI.
    O SEI já possui esses dados como metadados, então não devem aparecer no corpo.
    """
    # Padrão 1: Bloco completo com NUP e Tipo em um <p>
    padrao_bloco = re.compile(
        r'<p[^>]*>\s*[•\-]?\s*NUP\s*:\s*[\d\.\-/]+.*?</p>\s*',
        re.IGNORECASE | re.DOTALL
    )
    html = padrao_bloco.sub('', html)

    # Padrão 2: Linha separada só com NUP
    padrao_nup = re.compile(
        r'<p[^>]*>\s*[•\-]?\s*NUP\s*:\s*[\d\.\-/]+\s*</p>\s*',
        re.IGNORECASE
    )
    html = padrao_nup.sub('', html)

    # Padrão 3: Linha separada só com Tipo de documento
    padrao_tipo = re.compile(
        r'<p[^>]*>\s*[•\-]?\s*Tipo\s*(de\s*)?documento\s*:\s*[^<]+</p>\s*',
        re.IGNORECASE
    )
    html = padrao_tipo.sub('', html)

    # Padrão 4: Dentro de um <p> com <br>, remove só as linhas de NUP/Tipo
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

def carregar_prompt(nome: str) -> str:
    """Carrega prompt do arquivo"""
    path = PROMPTS_DIR / f"{nome}.txt"
    if path.exists():
        return path.read_text(encoding='utf-8')
    return ""

async def chamar_sei_reader_com_credencial(nup: str, credencial: CredencialSEI) -> Dict:
    """
    Extrai e analisa processo do SEI.

    Fluxo:
    1. Tenta usar o Worker /process-now (Pipeline v2 integrado)
    2. Se falhar, usa SEI Runner + Pipeline v2 local (fallback)
    """
    t0 = time.time()

    # Tenta usar o Worker com /process-now (já tem Pipeline v2 integrado)
    if USAR_DETALHAR_WORKER:
        try:
            print(f"   📖 Usando Detalhar Worker /process-now...", file=sys.stderr)
            async with httpx.AsyncClient(timeout=600.0) as client:
                response = await client.post(
                    f"{DETALHAR_WORKER_URL}/process-now",
                    json={
                        "nup": nup,
                        "usuario": credencial.usuario,
                        "senha": credencial.senha,
                        "orgao_id": credencial.orgao_id
                    }
                )
                data = response.json()

            if data.get("status") == "ok":
                duracao = time.time() - t0
                from_cache = data.get("from_cache", False)
                cache_info = " (CACHE)" if from_cache else ""
                print(f"   ✓ Worker OK{cache_info} em {duracao:.1f}s", file=sys.stderr)

                # Montar resultado no formato esperado
                return {
                    "sucesso": True,
                    "nup": nup,
                    "pipeline_v2": True,
                    "from_cache": from_cache,
                    "fonte": "detalhar-worker-cache" if from_cache else "detalhar-worker",
                    "job_id": data.get("job_id"),
                    "resumo_processo": data.get("resumo_texto", ""),
                    "resumo_executivo": data.get("resumo_texto", ""),
                    "interessado": data.get("interessado") or {},
                    "pedido": data.get("pedido") or {},
                    "situacao": data.get("situacao") or {},
                    "analise": {
                        "interessado": data.get("interessado") or {},
                        "pedido": data.get("pedido") or {},
                        "situacao": data.get("situacao") or {},
                        "confianca": data.get("confianca", 0),
                        "resumo_executivo": data.get("resumo_texto", "")
                    },
                    "metricas_pipeline": data.get("metricas") or {},
                    "duracao_total": duracao
                }
            else:
                print(f"   ⚠ Worker erro: {data.get('erro')}, tentando fallback...", file=sys.stderr)

        except Exception as e:
            print(f"   ⚠ Worker indisponivel: {e}, tentando fallback...", file=sys.stderr)

    # Fallback: SEI Runner + Pipeline v2 local
    return await chamar_sei_reader_fallback(nup, credencial)


async def chamar_sei_reader_fallback(nup: str, credencial: CredencialSEI) -> Dict:
    """
    Fallback: SEI Runner + Pipeline v2 local.

    Usado quando o Worker /process-now não está disponível.
    """
    t0 = time.time()

    try:
        # 1. EXTRACAO via SEI Runner
        print(f"   [1/2] Extraindo via SEI Runner (fallback)...", file=sys.stderr)
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.post(
                f"{SEI_RUNNER_URL}/run",
                json={
                    "mode": "detalhar",
                    "nup": nup,
                    "credentials": {
                        "usuario": credencial.usuario,
                        "senha": credencial.senha,
                        "orgao_id": credencial.orgao_id
                    },
                    "full": True
                }
            )
            data = response.json()

        if not data.get("ok"):
            return {"sucesso": False, "erro": data.get("error", "Erro desconhecido"), "nup": nup}

        # Extrair resultado do runner
        resultado = None
        if data.get("json_data"):
            resultado = data["json_data"]
        else:
            output = data.get("output", "")
            json_match = re.search(r'\{[\s\S]*"sucesso"[\s\S]*\}', output)
            if json_match:
                try:
                    resultado = json.loads(json_match.group())
                except:
                    pass

        if not resultado:
            return {"sucesso": True, "nup": nup, "resumo_processo": data.get("output", "")[:8000]}

        resultado["nup"] = nup
        resultado["fonte"] = "sei-runner"
        documentos = resultado.get("documentos", [])

        duracao_extracao = time.time() - t0
        print(f"   ✓ SEI extraido: {len(str(resultado))} chars, {len(documentos)} docs ({duracao_extracao:.1f}s)", file=sys.stderr)

        # 2. PIPELINE v2 (se disponivel e ativado)
        if PIPELINE_V2_DISPONIVEL and USAR_PIPELINE_V2 and documentos:
            print(f"   [2/2] Analisando com Pipeline v2 local...", file=sys.stderr)
            try:
                analise = processar_pipeline_v2(nup, documentos, usar_llm=True)

                if analise.get("sucesso"):
                    resultado["pipeline_v2"] = True
                    resultado["analise"] = analise.get("analise", {})
                    resultado["interessado"] = analise.get("interessado", {})
                    resultado["pedido"] = analise.get("pedido", {})
                    resultado["situacao"] = analise.get("situacao", {})
                    resultado["fluxo"] = analise.get("fluxo", {})
                    resultado["alertas"] = analise.get("alertas", [])
                    resultado["sugestao"] = analise.get("sugestao", "")
                    resultado["resumo_executivo"] = analise.get("resumo_executivo", "")
                    resultado["metricas_pipeline"] = analise.get("metricas", {})
                    resultado["resumo_processo"] = formatar_analise_para_contexto(analise)

                    custo = analise.get("metricas", {}).get("custo_total_usd", 0)
                    print(f"   ✓ Pipeline v2 OK! Custo: ${custo:.4f}", file=sys.stderr)
                else:
                    print(f"   ⚠ Pipeline v2 falhou: {analise.get('erro')}", file=sys.stderr)
                    resultado["pipeline_v2"] = False
                    resultado["pipeline_erro"] = analise.get("erro")
            except Exception as e:
                print(f"   ⚠ Erro no Pipeline v2: {e}", file=sys.stderr)
                resultado["pipeline_v2"] = False
                resultado["pipeline_erro"] = str(e)
        else:
            resultado["pipeline_v2"] = False

        resultado["duracao_total"] = time.time() - t0
        print(f"   ✓ Fallback completo em {resultado['duracao_total']:.1f}s", file=sys.stderr)

        return resultado

    except Exception as e:
        print(f"   ✗ Erro fallback: {e}", file=sys.stderr)
        return {"sucesso": False, "erro": str(e), "nup": nup}



# SISTEMA INTELIGENTE DE CONSULTA DE LEGISLAííO
# Adaptado do n8n para FastAPI
# ============================================================

def detectar_intent_e_topic(pergunta: str) -> dict:
    """
    Detecta a intenção (ANUAL, ININTERRUPTO, LIMITE, GERAL) 
    e o tí³pico (FERIAS, DISPENSA_RECOMPENSA, LICENCA, etc.)
    """
    s = pergunta.lower()
    
    # --- TOPIC (assunto) ---
    has_dispensa = "dispensa" in s
    has_recompensa = "recompensa" in s
    has_ferias = "férias" in s or "ferias" in s
    has_promocao = "promoção" in s or "promocao" in s
    has_licenca = "licença" in s or "licenca" in s
    has_disciplinar = "disciplinar" in s or "punição" in s or "punicao" in s or "transgress" in s
    
    topic = "GERAL"
    if has_dispensa and has_recompensa:
        topic = "DISPENSA_RECOMPENSA"
    elif has_dispensa:
        topic = "DISPENSA_RECOMPENSA"
    elif has_ferias:
        topic = "FERIAS"
    elif has_promocao:
        topic = "PROMOCAO"
    elif has_licenca:
        topic = "LICENCA"
    elif has_disciplinar:
        topic = "DISCIPLINAR"
    
    # --- INTENT (tipo de pergunta) ---
    import re
    is_anual = bool(re.search(r'\b(ano|anual|anuais|por ano|no ano|ao ano)\b', s))
    is_inint = bool(re.search(r'\b(ininterrupt|consecutiv|seguid|cont[ií]nu)\b', s))
    is_limite = bool(re.search(r'\b(quantos?\s+dias|limite|teto|m[aá]ximo|n[aã]o\s+exceder|ultrapass)\b', s))
    
    intent = "GERAL"
    if is_anual:
        intent = "ANUAL"
    elif is_inint:
        intent = "ININTERRUPTO"
    elif is_limite:
        intent = "LIMITE"
    
    return {"topic": topic, "intent": intent}


def reescrever_query(pergunta: str, topic: str, intent: str) -> tuple:
    """
    Reescreve a query para melhorar a busca no RAG
    Retorna (query_expandida, n_results)
    """
    if topic == "DISPENSA_RECOMPENSA":
        if intent == "ANUAL":
            return (f"dispensa recompensa CBMAC limite anual por ano teto máximo não exceder {pergunta}", 18)
        elif intent == "ININTERRUPTO":
            return (f"dispensa recompensa CBMAC dias ininterruptos consecutivos seguidos contínuos não poderá ser concedido mais de {pergunta}", 14)
        elif intent == "LIMITE":
            return (f"dispensa recompensa CBMAC limite máximo não exceder dias {pergunta}", 12)
        else:
            return (f"dispensa recompensa CBMAC {pergunta}", 10)
    
    elif topic == "FERIAS":
        if intent == "ANUAL" or intent == "LIMITE":
            return (f"férias CBMAC regra anual período gozo 30 dias alteração fruição {pergunta}", 16)
        else:
            return (f"férias CBMAC {pergunta}", 12)
    
    elif topic == "LICENCA":
        return (f"licença CBMAC afastamento {pergunta}", 10)
    
    elif topic == "PROMOCAO":
        return (f"promoção militar CBMAC requisitos {pergunta}", 10)
    
    elif topic == "DISCIPLINAR":
        return (f"disciplinar CBMAC regulamento punição {pergunta}", 10)
    
    else:
        # GERAL
        if intent == "ANUAL":
            return (f"CBMAC limite anual por ano teto máximo não exceder {pergunta}", 14)
        elif intent == "ININTERRUPTO":
            return (f"CBMAC consecutivos seguidos contínuos ininterruptos limite máximo {pergunta}", 12)
        elif intent == "LIMITE":
            return (f"CBMAC limite máximo teto não exceder {pergunta}", 12)
        else:
            return (f"CBMAC {pergunta}", 8)


def calcular_score(resultado: dict, topic: str, intent: str) -> int:
    """
    Calcula pontuação de releví¢ncia para um resultado
    """
    meta = resultado.get("metadata", {})
    lei = (meta.get("lei", "") or "").lower()
    text = (resultado.get("text", "") or "").lower()
    
    score = 0
    
    # --- íncoras por tí³pico ---
    if topic == "DISPENSA_RECOMPENSA":
        if "dispensa recompensa" in lei:
            score += 22
        if "portaria" in lei and ("078" in lei or "78" in lei):
            score += 8
        if "dispensa" in text:
            score += 8
        if "recompensa" in text:
            score += 8
    
    elif topic == "FERIAS":
        if "férias" in lei or "ferias" in lei:
            score += 18
        if "férias" in text or "ferias" in text:
            score += 8
        if "gozo" in text or "período" in text or "periodo" in text:
            score += 5
    
    elif topic == "DISCIPLINAR":
        if "disciplinar" in lei or "regulamento disciplinar" in lei:
            score += 14
        if "transgress" in text or "puni" in text or "penal" in text:
            score += 6
    
    else:
        if "cbmac" in text:
            score += 2
    
    # --- Sinais gerais úteis ---
    if "dias" in text:
        score += 4
    
    # --- Intenção ---
    if intent == "ANUAL":
        if "ano" in text or "anual" in text or "por ano" in text:
            score += 10
        if any(x in text for x in ["limite", "máximo", "teto", "não poderá", "não exceder", "ultrapass"]):
            score += 10
    
    elif intent == "ININTERRUPTO":
        if any(x in text for x in ["ininterrupt", "consecut", "seguid", "contínuo", "continuo"]):
            score += 12
    
    elif intent == "LIMITE":
        if any(x in text for x in ["limite", "máximo", "teto", "não exceder"]):
            score += 8
    
    # --- Números (dias/limites) ---
    import re
    if re.search(r'\b\d{1,2}\b', text):
        score += 3
    
    # --- Penalizações ---
    if topic != "GERAL":
        # Constituição/orçamento costuma ser ruído
        if "constitui" in lei and "dispensa" not in text and "férias" not in text and "ferias" not in text:
            score -= 15
        if "orçament" in lei or "ministério público" in text:
            score -= 12
        
        # Sí³ penaliza férias se não for o tí³pico
        if topic != "FERIAS" and ("férias" in lei or "ferias" in lei) and "dispensa" not in text:
            score -= 10
    
    # Textos curtos demais
    if len(text) < 60:
        score -= 3
    
    return score


def filtrar_titulo_estrutural(meta: dict, text: str) -> bool:
    """
    Retorna True se for apenas um título estrutural (sem conteúdo útil)
    """
    artigo = (meta.get("artigo", "") or "").upper()
    texto_upper = (text or "").upper()
    
    is_cap_sec_tit = any([
        artigo.startswith("CAPíTULO"),
        artigo.startswith("CAPITULO"),
        artigo.startswith("SEííO"),
        artigo.startswith("SECAO"),
        artigo.startswith("TíTULO"),
        artigo.startswith("TITULO")
    ])
    
    return is_cap_sec_tit and len(texto_upper) < 180 and "ART." not in texto_upper


def processar_resultados_rag(resultados: list, topic: str, intent: str) -> list:
    """
    Processa resultados do RAG: pontua, filtra, deduplica e ordena
    """
    # 1. Normaliza e filtra
    processados = []
    for r in resultados:
        meta = r.get("metadata", {})
        text = (r.get("text", "") or "").strip()
        
        # Filtra textos muito curtos
        if len(text) < 40:
            continue
        
        # Filtra títulos estruturais
        if filtrar_titulo_estrutural(meta, text):
            continue
        
        score = calcular_score(r, topic, intent)
        
        processados.append({
            "id": r.get("id", ""),
            "text": text,
            "metadata": meta,
            "lei": meta.get("lei", "Lei"),
            "artigo": meta.get("artigo", ""),
            "score": score
        })
    
    # 2. Ordena por score
    processados.sort(key=lambda x: x["score"], reverse=True)
    
    # 3. Deduplica por lei + artigo
    vistos = set()
    deduplicados = []
    for r in processados:
        chave = f"{r['lei']}||{r['artigo']}"
        if chave not in vistos:
            vistos.add(chave)
            deduplicados.append(r)
    
    # 4. Seleciona top K
    final_k = 8 if intent in ["ANUAL", "ININTERRUPTO", "LIMITE"] else 6
    return deduplicados[:final_k]


async def consultar_legislacao_via_n8n(pergunta: str) -> dict:
    """
    Consulta legislacao via webhook do n8n (processamento inteligente com RAG)
    """
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "http://secretario-sei-n8n-1:5678/webhook/consultar-leis",
                json={"pergunta": pergunta}
            )
            data = response.json()
            if data.get("sucesso"):
                return {
                    "sucesso": True,
                    "contexto": data.get("contexto_leis", ""),
                    "resultados": data.get("resultados", []),
                    "total": data.get("total", 0),
                    "topic": data.get("topic", ""),
                    "intent": data.get("intent", "")
                }
            return {"sucesso": False, "erro": "Sem resultados", "resultados": []}
    except Exception as e:
        print(f"Erro ao consultar n8n: {e}", file=sys.stderr)
        return {"sucesso": False, "erro": str(e), "resultados": []}


async def consultar_legislacao_rag_inteligente(tema: str, n_results: int = 5) -> list:
    """
    Consulta a base de legislação com Intent Detection + Query Rewrite + Scoring
    """
    try:
        # 1. Detecta intent e topic
        detection = detectar_intent_e_topic(tema)
        topic = detection["topic"]
        intent = detection["intent"]
        
        # 2. Reescreve a query
        query_expandida, n_results_ajustado = reescrever_query(tema, topic, intent)
        
        print(f"ð Consulta legislação: topic={topic}, intent={intent}", file=sys.stderr)
        print(f"   Query expandida: {query_expandida[:80]}...", file=sys.stderr)
        
        # 3. Consulta o RAG
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                "http://secretario-sei-leis-runner:8100/query",
                json={
                    "collection": "leis_cbmac",
                    "query_text": query_expandida,
                    "n_results": n_results_ajustado
                }
            )
            data = response.json()
        
        if not data.get("ok") or not data.get("results"):
            return []
        
        # 4. Processa resultados com scoring inteligente
        resultados_processados = processar_resultados_rag(data["results"], topic, intent)
        
        # 5. Formata saída
        leis = []
        for r in resultados_processados:
            leis.append({
                "lei": r["lei"],
                "artigo": r["artigo"],
                "texto": r["text"][:500],
                "referencia": f"{r['lei']} - {r['artigo']}" if r["artigo"] else r["lei"],
                "score": r["score"]
            })
        
        print(f"   â Encontrados: {len(leis)} resultados relevantes", file=sys.stderr)
        return leis
        
    except Exception as e:
        print(f"â ï¸ Erro ao consultar legislação: {e}", file=sys.stderr)
        return []


async def analisar_com_ia(nup: str, conteudo_processo: str, documentos: list = None) -> Dict:
    """
    Chama a IA para analisar o processo e retornar JSON estruturado.
    Esta é a etapa que faltava!
    """
    if not conteudo_processo or len(conteudo_processo.strip()) < 50:
        return {
            "tipo_demanda": "Processo sem conteúdo extraído",
            "resumo_executivo": "Não foi possível extrair conteúdo do processo para análise.",
            "interessado": {"nome": "-", "matricula": "-", "cargo": "-"},
            "pedido_original": {"descricao": "-"},
            "alertas": ["Conteúdo do processo não disponível para análise"],
            "tipo_documento_sugerido": "Despacho",
            "destinatario_sugerido": "",
            "legislacao_aplicavel": []
        }
    
    try:
        import openai
        
        # Carrega o prompt de análise
        prompt_template = carregar_prompt("analise_processo")
        
        if not prompt_template:
            # Prompt fallback se não encontrar o arquivo
            prompt_template = """Analise este processo administrativo e retorne APENAS JSON válido.

PROCESSO (NUP: {nup}):
{conteudo}

RETORNE EXATAMENTE ESTE JSON (sem texto adicional):
{{
  "tipo_demanda": "descrição clara do tipo de demanda",
  "resumo_executivo": "resumo em 2-3 linhas do processo",
  "interessado": {{
    "nome": "nome do interessado",
    "matricula": "matrícula ou -",
    "cargo": "cargo/posto"
  }},
  "pedido_original": {{
    "descricao": "o que foi solicitado",
    "periodo": "período se houver"
  }},
  "unidades": {{
    "demandante": "unidade de origem",
    "resposta": "unidade que deve responder"
  }},
  "alertas": ["pontos de atenção"],
  "tipo_documento_sugerido": "Memorando ou Despacho",
  "destinatario_sugerido": "sigla da unidade destino",
  "legislacao_aplicavel": ["leis/artigos relevantes"]
}}"""
        
        # Monta o prompt final
        prompt = prompt_template.replace("{nup}", nup).replace("{conteudo}", conteudo_processo[:6000])
        # Consulta legislação relevante no RAG
        tipo_demanda_hint = ""
        if "férias" in conteudo_processo.lower() or "ferias" in conteudo_processo.lower():
            tipo_demanda_hint = "férias gozo concessão período"
        elif "licença" in conteudo_processo.lower() or "licenca" in conteudo_processo.lower():
            tipo_demanda_hint = "licença afastamento"
        elif "dispensa" in conteudo_processo.lower():
            tipo_demanda_hint = "dispensa recompensa"
        elif "promoção" in conteudo_processo.lower() or "promocao" in conteudo_processo.lower():
            tipo_demanda_hint = "promoção militar"
        else:
            # Extrai palavras-chave do conteúdo
            tipo_demanda_hint = conteudo_processo[:500]
        
        leis_encontradas = await consultar_legislacao_via_n8n(tipo_demanda_hint)
        
        legislacao_texto = ""
        if leis_encontradas.get("sucesso") and leis_encontradas.get("contexto"):
            legislacao_texto = "\n\nLEGISLAííO APLICíVEL ENCONTRADA:\n" + leis_encontradas["contexto"]
        
        prompt = prompt.replace("{legislacao}", legislacao_texto)
        
        client = openai.OpenAI(api_key=OPENAI_API_KEY)
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {
                    "role": "system", 
                    "content": "Você é um assistente jurídico-administrativo do CBMAC. Analise processos e retorne APENAS JSON válido, sem texto adicional."
                },
                {"role": "user", "content": prompt}
            ],
            max_tokens=2000,
            temperature=0.3
        )
        
        resposta_texto = response.choices[0].message.content.strip()
        
        # Limpa markdown se houver
        resposta_texto = re.sub(r'```json\s*', '', resposta_texto)
        resposta_texto = re.sub(r'```\s*', '', resposta_texto)
        
        # Tenta parsear JSON
        try:
            analise = json.loads(resposta_texto)
            return analise
        except json.JSONDecodeError:
            # Tenta extrair JSON do meio do texto
            json_match = re.search(r'\{[\s\S]*\}', resposta_texto)
            if json_match:
                try:
                    return json.loads(json_match.group())
                except:
                    pass
            
            # Se não conseguir, retorna estrutura básica com o resumo
            return {
                "tipo_demanda": "Análise do processo",
                "resumo_executivo": resposta_texto[:500],
                "interessado": {"nome": "-", "matricula": "-", "cargo": "-"},
                "pedido_original": {"descricao": "-"},
                "alertas": [],
                "tipo_documento_sugerido": "Despacho",
                "destinatario_sugerido": "",
                "legislacao_aplicavel": []
            }
            
    except Exception as e:
        print(f"â Erro na análise IA: {e}", file=sys.stderr)
        return {
            "tipo_demanda": "Erro na análise",
            "resumo_executivo": f"Erro ao processar com IA: {str(e)}",
            "interessado": {"nome": "-", "matricula": "-", "cargo": "-"},
            "pedido_original": {"descricao": "-"},
            "alertas": [f"Erro IA: {str(e)}"],
            "tipo_documento_sugerido": "Despacho",
            "destinatario_sugerido": "",
            "legislacao_aplicavel": []
        }


# ============================================================
# SISTEMA DE TEMPLATES
# ============================================================

def carregar_template(template_id: str) -> tuple:
    """
    Carrega um template do sistema de modelos.
    Retorna (conteudo_html, metadados) ou (None, None) se não encontrar.
    """
    try:
        # Importa os metadados dos templates
        from modelos.templates_meta import TEMPLATES_META, MODELOS_DIR

        if template_id not in TEMPLATES_META:
            print(f"[TEMPLATE] Template não encontrado: {template_id}", file=sys.stderr)
            return None, None

        meta = TEMPLATES_META[template_id]
        caminho = meta.get("arquivo_path")

        if caminho is None or not caminho.exists():
            print(f"[TEMPLATE] Arquivo não encontrado: {caminho}", file=sys.stderr)
            return None, None

        conteudo = caminho.read_text(encoding="utf-8")
        return conteudo, meta
    except Exception as e:
        print(f"[TEMPLATE] Erro ao carregar template {template_id}: {e}", file=sys.stderr)
        return None, None


def preencher_template(
    template_id: str,
    conteudo: str,
    analise: dict,
    destinatarios: list = None,
    destinatario: str = None,
    remetente: dict = None,
    instrucao_voz: str = None
) -> str:
    """
    Preenche um template com os dados fornecidos.
    Mapeia os campos da análise/destinatário/remetente para os placeholders do template.
    """
    # Extrai dados da análise
    interessado = analise.get("interessado", {})
    pedido = analise.get("pedido_original", {}) or analise.get("pedido", {})
    sugestao = analise.get("sugestao", {})

    # Monta dados do(s) destinatário(s) - suporta múltiplos
    nome_dest = ""
    posto_dest = ""
    cargo_dest = ""
    sigla_dest = ""
    vocativo = "Senhor(a)"
    bloco_destinatario_completo = ""

    if destinatarios and len(destinatarios) > 0:
        if len(destinatarios) == 1:
            # Um destinatário
            d = destinatarios[0]
            nome_dest = d.get('nome', '')
            posto_dest = d.get('posto_grad', '')
            cargo_dest = d.get('cargo', '')
            sigla_dest = d.get('sigla_sei', '') or d.get('sigla', '')

            # Define vocativo
            if 'Comandante' in cargo_dest:
                vocativo = "Senhor Comandante"
            elif 'Diretor' in cargo_dest:
                vocativo = "Senhor Diretor"
            elif 'Chefe' in cargo_dest:
                vocativo = "Senhor Chefe"
        else:
            # Múltiplos destinatários
            linhas = []
            siglas = []
            for d in destinatarios:
                nome = d.get('nome', '')
                posto = d.get('posto_grad', '')
                cargo = d.get('cargo', '')
                sigla = d.get('sigla_sei', '') or d.get('sigla', '')
                linhas.append(f"{posto} {nome} - {cargo}".strip())
                siglas.append(sigla)

            # Formata como lista
            nome_dest = "\\n".join([f"- {l}" for l in linhas])
            sigla_dest = ", ".join(siglas)
            vocativo = "Senhores"
            # Marca para usar formato especial
            bloco_destinatario_completo = f"Aos Senhores:\\n" + "\\n".join([f"- {l}" for l in linhas]) + f"\\n{sigla_dest}"

    elif destinatario:
        nome_dest = destinatario
    elif interessado:
        nome_dest = interessado.get('nome', '')
        posto_dest = interessado.get('posto_grad', '')
        cargo_dest = interessado.get('cargo', '')

        if 'Comandante' in cargo_dest:
            vocativo = "Senhor Comandante"
        elif 'Diretor' in cargo_dest:
            vocativo = "Senhor Diretor"
        elif 'Chefe' in cargo_dest:
            vocativo = "Senhor Chefe"

    # Monta dados do remetente
    nome_rem = remetente.get('nome', '') if remetente else ''
    posto_rem = remetente.get('posto_grad', '') if remetente else ''
    cargo_rem = remetente.get('cargo', '') if remetente else ''
    sigla_rem = remetente.get('unidade', '') if remetente else ''
    portaria_rem = remetente.get('portaria', '') if remetente else ''

    # Extrai assunto
    assunto = analise.get('assunto', '') or pedido.get('descricao', '') or analise.get('tipo_demanda', '')

    # Gera texto do corpo baseado na sugestão/instrução
    texto_corpo = ""
    if instrucao_voz:
        texto_corpo = f"<p style=\"text-align: justify; text-indent: 1.5cm;\">{instrucao_voz}</p>"
    elif sugestao:
        acao = sugestao.get('acao', '') if isinstance(sugestao, dict) else ''
        fund = sugestao.get('fundamentacao', '') if isinstance(sugestao, dict) else ''
        if acao and fund:
            texto_corpo = f"<p style=\"text-align: justify; text-indent: 1.5cm;\">{acao}. {fund}</p>"
        elif acao:
            texto_corpo = f"<p style=\"text-align: justify; text-indent: 1.5cm;\">{acao}</p>"

    # Dicionário de substituição (todos os campos possíveis)
    dados = {
        # Destinatário
        "NOME_COMPLETO": f"{posto_dest} {nome_dest}".strip() if posto_dest else nome_dest,
        "NOME_DESTINATARIO": nome_dest,
        "POSTO_GRAD_DESTINATARIO": posto_dest,
        "CARGO_DESTINO": cargo_dest,
        "CARGO_DESTINATARIO": cargo_dest,
        "SIGLA_UNIDADE": sigla_dest or "CBMAC",
        "VOCATIVO": f"{vocativo},",

        # Remetente
        "NOME_REMETENTE": f"{posto_rem} {nome_rem}".strip() if posto_rem else nome_rem,
        "POSTO_GRAD_REMETENTE": posto_rem,
        "CARGO_REMETENTE": cargo_rem,
        "SIGLA_REMETENTE": sigla_rem or "CBMAC",
        "NUMERO_PORTARIA": portaria_rem,

        # Conteúdo
        "ASSUNTO": assunto,
        "ASSUNTO_RESUMIDO": assunto[:100] if assunto else "",
        "TEXTO_CORPO": texto_corpo,

        # Campos extras que alguns templates podem usar
        "MOTIVO_ENCAMINHAMENTO": pedido.get('descricao', ''),
        "DIA": "",
        "MES": "",
        "ANO": "",
    }

    # Substitui os placeholders
    try:
        html = conteudo.format(**dados)
    except KeyError as e:
        # Se faltar algum campo, tenta substituir os que existem
        print(f"[TEMPLATE] Campo ausente {e}, usando substituição parcial", file=sys.stderr)
        for chave, valor in dados.items():
            conteudo = conteudo.replace(f"{{{chave}}}", str(valor))
        html = conteudo

    return html


async def gerar_documento_com_ia(
    tipo: str,
    nup: str,
    analise: dict,
    destinatario: str = None,
    destinatarios: list = None,
    remetente: dict = None,
    template_id: str = None,
    instrucao_voz: str = None
) -> Dict:
    """
    Gera documento usando template (se disponível) ou OpenAI GPT-4 (fallback).

    Fluxo:
    1. Se template_id fornecido, tenta carregar e preencher o template
    2. Se template não existir ou falhar, usa LLM como fallback
    """

    # =========================================================
    # TENTATIVA 1: Usar template SOMENTE se houver instrução explícita
    # Se não houver instrução, usar LLM para gerar conteúdo contextualizado
    # =========================================================
    tem_instrucao = instrucao_voz and instrucao_voz.strip() and len(instrucao_voz.strip()) > 2

    if template_id and tem_instrucao:
        print(f"[TEMPLATE] Tentando usar template: {template_id} (instrução: {instrucao_voz[:50]}...)", file=sys.stderr)
        conteudo, meta = carregar_template(template_id)

        if conteudo:
            try:
                html = preencher_template(
                    template_id=template_id,
                    conteudo=conteudo,
                    analise=analise,
                    destinatarios=destinatarios,
                    destinatario=destinatario,
                    remetente=remetente,
                    instrucao_voz=instrucao_voz
                )

                # Adiciona cabeçalho com NUP e Tipo
                cabecalho = f'<p style="text-align: left; font-size: 10pt; color: #555;">• NUP: {nup}<br>• Tipo de documento: {tipo}</p><hr style="margin: 10px 0;">'
                html = cabecalho + html

                print(f"[TEMPLATE] Documento gerado com sucesso via template {template_id}", file=sys.stderr)
                return {
                    "sucesso": True,
                    "documento": html,
                    "tipo": tipo,
                    "nup": nup,
                    "fonte": "template",
                    "template_id": template_id
                }
            except Exception as e:
                print(f"[TEMPLATE] Erro ao preencher template {template_id}: {e}, usando LLM como fallback", file=sys.stderr)
        else:
            print(f"[TEMPLATE] Template {template_id} não encontrado, usando LLM como fallback", file=sys.stderr)
    elif template_id and not tem_instrucao:
        print(f"[LLM] Sem instrução explícita, usando LLM para gerar conteúdo contextualizado", file=sys.stderr)

    # =========================================================
    # TENTATIVA 2: Usar LLM (OpenAI) para gerar APENAS O CORPO
    # O código monta a estrutura completa (destinatário, vocativo, fecho, assinatura)
    # =========================================================
    try:
        import openai

        # Monta contexto da análise
        resumo = analise.get("resumo_executivo", "") or analise.get("resumo_processo", "") or ""
        interessado = analise.get("interessado", {})
        pedido = analise.get("pedido_original", {}) or analise.get("pedido", {})
        sugestao = analise.get("sugestao", {})

        # =========================================================
        # FUNÇÃO AUXILIAR: DETERMINAR GÊNERO
        # =========================================================
        def determinar_genero(nome: str, cargo: str) -> str:
            """
            Determina gênero baseado no cargo e nome.
            Retorna 'F' para feminino, 'M' para masculino.
            """
            # 1. Verifica pelo cargo (mais confiável)
            cargos_femininos = ['Diretora', 'Comandante Geral', 'Subcomandante', 'Chefa', 'Assessora', 'Coordenadora']
            cargos_masculinos = ['Diretor', 'Comandante', 'Chefe', 'Assessor', 'Coordenador']

            cargo_lower = cargo.lower() if cargo else ''

            # Cargos explicitamente femininos
            if 'diretora' in cargo_lower or 'chefa' in cargo_lower or 'assessora' in cargo_lower or 'coordenadora' in cargo_lower:
                return 'F'

            # 2. Verifica pelo nome (heurística)
            if nome:
                primeiro_nome = nome.split()[0].upper() if nome.split() else ''

                # Nomes femininos comuns (lista não exaustiva)
                nomes_femininos = [
                    'MARIA', 'ANA', 'FRANCISCA', 'ANTONIA', 'ADRIANA', 'JULIANA', 'MARCIA',
                    'FERNANDA', 'PATRICIA', 'ALINE', 'SANDRA', 'CAMILA', 'AMANDA', 'BRUNA',
                    'JESSICA', 'LETICIA', 'JULIA', 'LUCIANA', 'VANESSA', 'CARLA', 'SIMONE',
                    'DANIELA', 'RENATA', 'CAROLINA', 'RAFAELA', 'CRISTIANE', 'FABIANA',
                    'CLAUDIA', 'HELENA', 'BEATRIZ', 'LARISSA', 'PRISCILA', 'TATIANA',
                    'GABRIELA', 'NATALIA', 'MONICA', 'PAULA', 'RAQUEL', 'VIVIANE', 'ELIANE',
                    'ROSANGELA', 'ROSA', 'LUCIA', 'ELIZABETH', 'TEREZA', 'EDILENE', 'EDNA'
                ]

                if primeiro_nome in nomes_femininos:
                    return 'F'

                # Heurística: nomes terminados em 'A' geralmente são femininos
                # (mas há exceções como ÉDEN, que não termina em A)
                # Nomes que terminam em 'A' e não são exceções conhecidas
                excecoes_masculinas = ['JOSEFA', 'COSTA', 'SOUZA', 'SILVA', 'MOURA', 'VIEIRA', 'OLIVEIRA', 'PEREIRA']
                if primeiro_nome.endswith('A') and primeiro_nome not in excecoes_masculinas and len(primeiro_nome) > 2:
                    return 'F'

            # Default: masculino (mais comum no CBMAC)
            return 'M'

        # =========================================================
        # 1. MONTA HTML DO DESTINATÁRIO
        # =========================================================
        html_destinatario = ""
        vocativo = "Senhor,"

        if destinatarios and len(destinatarios) > 0:
            if len(destinatarios) == 1:
                # Um destinatário
                d = destinatarios[0]
                nome_dest = d.get('nome', '')
                posto_dest = d.get('posto_grad', '')
                cargo_dest = d.get('cargo', '')
                sigla_dest = d.get('sigla', '')
                sigla_sei = d.get('sigla_sei', f'CBMAC-{sigla_dest}')

                # Determina gênero
                genero = determinar_genero(nome_dest, cargo_dest)

                # Monta destinatário com pronome correto
                if genero == 'F':
                    pronome_dest = "À Sra."
                else:
                    pronome_dest = "Ao Sr."

                html_destinatario = f'<p style="text-align: left;">{pronome_dest} <b>{posto_dest} {nome_dest}</b><br>{cargo_dest} - {sigla_sei}</p>'

                # Define vocativo baseado no cargo e gênero
                if 'Comandante' in cargo_dest:
                    vocativo = "Senhora Comandante," if genero == 'F' else "Senhor Comandante,"
                elif 'Diretor' in cargo_dest:
                    vocativo = "Senhora Diretora," if genero == 'F' else "Senhor Diretor,"
                elif 'Chefe' in cargo_dest:
                    vocativo = "Senhora Chefe," if genero == 'F' else "Senhor Chefe,"
                elif 'Subcomandante' in cargo_dest:
                    vocativo = "Senhora Subcomandante," if genero == 'F' else "Senhor Subcomandante,"
                else:
                    vocativo = "Senhora," if genero == 'F' else "Senhor,"
            else:
                # Múltiplos destinatários (circular)
                partes_dest = []
                generos = []
                for d in destinatarios:
                    nome = d.get('nome', '')
                    posto = d.get('posto_grad', '')
                    cargo = d.get('cargo', '')
                    sigla = d.get('sigla', '')
                    sigla_sei = d.get('sigla_sei', f'CBMAC-{sigla}')

                    genero = determinar_genero(nome, cargo)
                    generos.append(genero)
                    pronome = "À Sra." if genero == 'F' else "Ao Sr."

                    partes_dest.append(f'<p style="text-align: left;">{pronome} <b>{posto} {nome}</b><br>{cargo} - {sigla_sei}</p>')

                html_destinatario = '\n'.join(partes_dest)

                # Determina vocativo para circular (usa masculino plural se misto)
                cargos = [d.get('cargo', '') for d in destinatarios]
                todos_femininos = all(g == 'F' for g in generos)

                if all('Comandante' in c for c in cargos):
                    vocativo = "Senhoras Comandantes," if todos_femininos else "Senhores Comandantes,"
                elif all('Diretor' in c for c in cargos):
                    vocativo = "Senhoras Diretoras," if todos_femininos else "Senhores Diretores,"
                else:
                    vocativo = "Senhoras," if todos_femininos else "Senhores,"
        elif destinatario:
            # Fallback: destinatário como string simples
            genero = determinar_genero(destinatario, '')
            pronome = "À Sra." if genero == 'F' else "Ao Sr."
            html_destinatario = f'<p style="text-align: left;">{pronome} <b>{destinatario}</b></p>'
            vocativo = "Senhora," if genero == 'F' else "Senhor,"
        elif interessado and interessado.get('nome'):
            # Fallback: usa dados do interessado da análise
            nome_int = interessado.get('nome', '')
            cargo_int = interessado.get('cargo', '')
            posto_int = interessado.get('posto_grad', '')

            genero = determinar_genero(nome_int, cargo_int)
            pronome = "À Sra." if genero == 'F' else "Ao Sr."

            if posto_int:
                html_destinatario = f'<p style="text-align: left;">{pronome} <b>{posto_int} {nome_int}</b>'
            else:
                html_destinatario = f'<p style="text-align: left;">{pronome} <b>{nome_int}</b>'
            if cargo_int:
                html_destinatario += f'<br>{cargo_int}'
            html_destinatario += '</p>'

            # Define vocativo baseado no cargo e gênero do interessado
            if cargo_int and 'Comandante' in cargo_int:
                vocativo = "Senhora Comandante," if genero == 'F' else "Senhor Comandante,"
            elif cargo_int and 'Diretor' in cargo_int:
                vocativo = "Senhora Diretora," if genero == 'F' else "Senhor Diretor,"
            elif cargo_int and 'Chefe' in cargo_int:
                vocativo = "Senhora Chefe," if genero == 'F' else "Senhor Chefe,"
            else:
                vocativo = "Senhora," if genero == 'F' else "Senhor,"

        # =========================================================
        # 2. MONTA HTML DO VOCATIVO
        # =========================================================
        html_vocativo = f'<p style="text-align: left; text-indent: 1.5cm;">{vocativo}</p>'

        # =========================================================
        # 2.1 MONTA HTML DO ASSUNTO
        # =========================================================
        # Extrai assunto da análise
        assunto = analise.get('assunto', '') or pedido.get('descricao', '') or analise.get('tipo_demanda', '') or ''
        assunto = assunto.strip()

        html_assunto = ""
        if assunto:
            # Formato SEI: Assunto: <strong>TEXTO EM NEGRITO</strong>
            html_assunto = f'<p class="Texto_Justificado">Assunto: <strong>{assunto}</strong></p>'

        # =========================================================
        # 3. MONTA HTML DO FECHO
        # =========================================================
        html_fecho = '<p style="text-align: left; text-indent: 1.5cm;">Atenciosamente,</p>'

        # =========================================================
        # 4. MONTA HTML DA ASSINATURA
        # =========================================================
        html_assinatura = ""
        if remetente:
            nome_rem = remetente.get('nome', '')
            posto_rem = remetente.get('posto_grad', '')
            cargo_rem = remetente.get('cargo', '')
            unidade_rem = remetente.get('unidade', '')
            portaria = remetente.get('portaria', '')

            html_assinatura = f'<p style="text-align: center;"><b>{nome_rem} - {posto_rem}</b><br>{cargo_rem}'
            if unidade_rem and unidade_rem not in cargo_rem:
                html_assinatura += f' - {unidade_rem}'
            if portaria:
                html_assinatura += f'<br>{portaria}'
            html_assinatura += '</p>'

        # =========================================================
        # 5. MONTA CONTEXTO PARA A IA GERAR APENAS O CORPO
        # =========================================================
        assunto = analise.get('assunto', '') or pedido.get('descricao', '') or analise.get('tipo_demanda', '')

        contexto = f"""TIPO DE DOCUMENTO: {tipo}
NUP: {nup}
TIPO DE DEMANDA: {analise.get('tipo_demanda', '-')}

RESUMO DO PROCESSO:
{resumo}

INTERESSADO: {interessado.get('nome', '-')} - {interessado.get('posto_grad', '-')} - {interessado.get('cargo', '-')}
PEDIDO: {pedido.get('descricao', '-')}
ASSUNTO: {assunto}

SUGESTÃO DE AÇÃO: {sugestao.get('acao', '-') if isinstance(sugestao, dict) else '-'}
FUNDAMENTAÇÃO: {sugestao.get('fundamentacao', '-') if isinstance(sugestao, dict) else '-'}
"""

        # Adiciona instrução do usuário se houver
        if instrucao_voz and instrucao_voz.strip():
            contexto += f"\nINSTRUÇÃO DO USUÁRIO (PRIORIDADE MÁXIMA): {instrucao_voz.strip()}"

        # =========================================================
        # 6. PROMPT PARA A IA GERAR APENAS O CORPO
        # =========================================================
        prompt = f"""Gere APENAS o CORPO de um {tipo} formal do CBMAC.

{contexto}

IMPORTANTE:
- Gere APENAS os parágrafos do corpo do documento (1 a 3 parágrafos)
- NÃO inclua destinatário, vocativo, fecho ou assinatura (já serão adicionados automaticamente)
- NÃO inclua NUP ou tipo de documento no texto
- Use linguagem DIRETA, CLARA e OBJETIVA
- Vá direto ao ponto - sem enrolação
- Se houver INSTRUÇÃO DO USUÁRIO, siga EXATAMENTE o que foi solicitado

FORMATO HTML OBRIGATÓRIO para cada parágrafo:
<p style="text-align: justify; text-indent: 1.5cm;">Texto do parágrafo aqui.</p>

Gere apenas os parágrafos do corpo, nada mais."""

        print(f"[LLM] Gerando corpo do documento...", file=sys.stderr)

        client = openai.OpenAI(api_key=OPENAI_API_KEY)
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": "Você é um redator oficial do CBMAC. Gere apenas o corpo do documento (parágrafos), sem destinatário, vocativo, fecho ou assinatura. Use HTML com style inline."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=1500,
            temperature=0.3
        )

        html_corpo = response.choices[0].message.content

        # Limpa markdown se houver
        html_corpo = re.sub(r'```html\s*', '', html_corpo)
        html_corpo = re.sub(r'```\s*', '', html_corpo)
        html_corpo = html_corpo.strip()

        # Remove qualquer NUP/Tipo que o LLM possa ter gerado
        html_corpo = re.sub(r'<p[^>]*>\s*[•\-]?\s*NUP\s*:\s*[\d\.\-/]+.*?</p>\s*', '', html_corpo, flags=re.IGNORECASE | re.DOTALL)
        html_corpo = re.sub(r'[•\-]?\s*NUP\s*:\s*[\d\.\-/]+\s*<br\s*/?>', '', html_corpo, flags=re.IGNORECASE)
        html_corpo = re.sub(r'<p[^>]*>\s*</p>', '', html_corpo)  # Remove parágrafos vazios
        html_corpo = html_corpo.strip()

        print(f"[LLM] Corpo gerado: {len(html_corpo)} chars", file=sys.stderr)

        # =========================================================
        # 7. MONTA O DOCUMENTO COMPLETO
        # =========================================================
        # Cabeçalho com NUP e Tipo (será removido antes de enviar ao SEI)
        cabecalho = f'<p style="text-align: left; font-size: 10pt; color: #555;">• NUP: {nup}<br>• Tipo de documento: {tipo}</p><hr style="margin: 10px 0;">'

        # Monta documento completo
        partes = [cabecalho]

        # Inclui destinatário no HTML para extração posterior
        # O endpoint /v1/inserir-sei vai extrair e remover antes de enviar ao SEI
        if html_destinatario:
            partes.append(html_destinatario)

        # Inclui assunto ANTES do vocativo (ordem correta em docs oficiais)
        if html_assunto:
            partes.append(html_assunto)

        partes.append(html_vocativo)
        partes.append(html_corpo)
        partes.append(html_fecho)

        if html_assinatura:
            partes.append(html_assinatura)

        html_completo = '\n'.join(partes)

        print(f"[LLM] Documento completo: {len(html_completo)} chars", file=sys.stderr)

        return {"sucesso": True, "documento": html_completo, "tipo": tipo, "nup": nup, "fonte": "llm"}
    except Exception as e:
        print(f"[LLM] Erro: {e}", file=sys.stderr)
        return {"sucesso": False, "erro": str(e), "fonte": "llm"}

# ============================================================
# CLIENTE API DE EFETIVO
# ============================================================

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
            print(f"[EFETIVO] Timeout ao buscar: {query}", file=sys.stderr)
            return []
        except Exception as e:
            print(f"[EFETIVO] Erro ao buscar '{query}': {e}", file=sys.stderr)
            return []


async def buscar_militar_por_matricula(matricula: str) -> Optional[Dict]:
    """
    Busca militar por matricula exata na API de Efetivo.
    """
    # A API de Efetivo aceita matricula completa (com hifen)
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
            print(f"[EFETIVO] Erro ao buscar matricula '{matricula}': {e}", file=sys.stderr)
            return None


def formatar_militar(record: Dict) -> Dict:
    """Formata registro da API de Efetivo no padrao do sistema."""
    matricula = record.get("matricula", "")
    nome = record.get("nome", "")
    posto_grad = record.get("posto_grad", "")
    lotacao = record.get("lotacao", "")
    cargo = record.get("funcao", "") or ""

    # Formato padrao: "MAJ QOBMEC Mat. 9268863-3 GILMAR TORRES MARQUES MOURA"
    formatado = f"{posto_grad} Mat. {matricula} {nome}".strip()
    mat_base = matricula.split("-")[0] if "-" in matricula else matricula

    return {
        "matricula": mat_base,
        "matricula_completa": matricula,
        "nome": nome,
        "posto_grad": posto_grad,
        "lotacao": lotacao,
        "cargo": cargo,
        "formatado": formatado
    }


# ============================================================
# REGISTRO DOS ENDPOINTS
# ============================================================

def registrar_endpoints_laravel(app):
    from fastapi import Request, Query

    # ==========================================================
    # ENDPOINTS DE BUSCA DE MILITAR (API EFETIVO)
    # ==========================================================

    @app.get("/api/militar/buscar")
    async def api_buscar_militar(
        q: str = Query(..., min_length=2, description="Termo de busca"),
        limit: int = Query(10, ge=1, le=50, description="Limite de resultados")
    ):
        """
        Busca militares na API de Efetivo.
        Usado para autocomplete no frontend.

        Exemplo: GET /api/militar/buscar?q=gilmar&limit=5
        """
        import time
        inicio = time.time()

        records = await buscar_militar_efetivo(q, limit)
        militares = [formatar_militar(r) for r in records]
        tempo_ms = int((time.time() - inicio) * 1000)

        return {
            "sucesso": True,
            "query": q,
            "total": len(militares),
            "militares": militares,
            "tempo_ms": tempo_ms,
            "fonte": "efetivo-api"
        }

    @app.get("/api/militar/{matricula}")
    async def api_obter_militar(matricula: str):
        """
        Obtem dados completos de um militar por matricula.

        Exemplo: GET /api/militar/9268863
        """
        dados = await buscar_militar_por_matricula(matricula)

        if not dados:
            return {
                "sucesso": False,
                "erro": f"Militar com matricula '{matricula}' nao encontrado"
            }

        militar = formatar_militar(dados)
        return {
            "sucesso": True,
            "militar": militar,
            "fonte": "efetivo-api"
        }

    # ==========================================================
    # ENDPOINTS EXISTENTES
    # ==========================================================

    @app.post("/api/v2/analisar-processo")
    async def analisar_processo_v2(req: AnalisarProcessoRequest, request: Request):
        """
        Endpoint principal de análise - AGORA COM IA!
        
        Fluxo:
        1. Chama SEI Runner (detalhar_processo.py) para extrair texto
        2. Chama IA (GPT) para analisar e estruturar
        3. Retorna JSON completo para o frontend
        """
        print(f"ð¥ /api/v2/analisar-processo - NUP: {req.nup}, Usuario: {req.credencial.usuario}", file=sys.stderr)
        
        # ETAPA 1: Extrai dados do SEI
        print(f"   â³ Extraindo dados do SEI...", file=sys.stderr)
        dados_sei = await chamar_sei_reader_com_credencial(req.nup, req.credencial)
        
        if not dados_sei.get("sucesso"):
            return {
                "sucesso": False, 
                "erro": dados_sei.get("erro", "Erro ao ler processo"), 
                "nup": req.nup
            }
        
        # Extrai o conteúdo para análise
        conteudo_bruto = dados_sei.get("resumo_processo", "") or dados_sei.get("output_bruto", "")
        documentos = dados_sei.get("documentos", [])
        
        print(f"   â SEI extraído: {len(conteudo_bruto)} chars, {len(documentos)} docs", file=sys.stderr)
        
        # ETAPA 2: Chama IA para analisar
        print(f"   â³ Analisando com IA...", file=sys.stderr)
        analise_ia = await analisar_com_ia(req.nup, conteudo_bruto, documentos)
        print(f"   â Análise IA concluída", file=sys.stderr)
        
        # ETAPA 3: Monta resposta completa
        # Documentos vêm com conteúdo completo quando full=True
        documentos_completos = dados_sei.get("documentos", [])
        
        return {
            "sucesso": True,
            "nup": req.nup,
            "analise": analise_ia,
            "resumo_processo": conteudo_bruto[:3000],
            "documentos": documentos_completos,  # Com conteúdo completo!
            "conteudo_bruto": conteudo_bruto[:5000],
            # Campos extras do detalhar
            "modo": dados_sei.get("modo", ""),
            "pastas_total": dados_sei.get("pastas_total", 0),
            "documentos_total": dados_sei.get("documentos_total", len(documentos_completos)),
            "docs_extraidos": dados_sei.get("extraidos_ok", len(documentos_completos)),
            "docs_escaneados": dados_sei.get("docs_escaneados", 0),
            "ressalvas": dados_sei.get("ressalvas", []),
            "duracao_segundos": dados_sei.get("duracao_segundos", 0),
            "mensagem": dados_sei.get("mensagem", "Processo analisado com sucesso!")
        }
    
    @app.post("/v1/gerar-documento")
    async def gerar_documento_v1(req: GerarDocumentoRequest, request: Request):
        """Endpoint para Laravel gerar documento com IA"""
        print(f"ð¥ /v1/gerar-documento - NUP: {req.nup}, Tipo: {req.tipo_documento}", file=sys.stderr)
        print(f"   ð¦ destinatarios: {req.destinatarios}", file=sys.stderr)
        print(f"   ð¦ remetente: {req.remetente}", file=sys.stderr)
        print(f"   🎤 instrucao_voz: {req.instrucao_voz}", file=sys.stderr)
        
        # Converte destinatarios de Pydantic para dict
        destinatarios_dict = None
        if req.destinatarios:
            destinatarios_dict = [d.dict() for d in req.destinatarios]
        
        remetente_dict = None
        if req.remetente:
            remetente_dict = req.remetente.dict()
        
        resultado = await gerar_documento_com_ia(
            tipo=req.tipo_documento,
            nup=req.nup,
            analise=req.analise or {},
            destinatario=req.destinatario,
            destinatarios=destinatarios_dict,
            remetente=remetente_dict,
            template_id=req.template_id,
            instrucao_voz=req.instrucao_voz
        )
        
        return resultado
    
    @app.post("/api/v2/gerar-documento")
    async def gerar_documento_v2(req: GerarDocumentoRequest, request: Request):
        """Alias para /v1/gerar-documento"""
        return await gerar_documento_v1(req, request)
    
    @app.post("/v1/inserir-sei")
    async def inserir_sei_v1(req: InserirSEIRequest, request: Request):
        """Endpoint para inserir documento no SEI"""
        print(f"🔥 /v1/inserir-sei - NUP: {req.nup}, Tipo: {req.tipo_documento}", file=sys.stderr)

        # Extrai destinatário do HTML para preencher o iframe de Endereçamento do SEI
        # Formatos aceitos:
        # - Novo: <p>Ao Sr. <b>NOME</b><br>CARGO</p> ou <p>À Sra. <b>NOME</b><br>CARGO</p>
        # - Antigo: <p>Ao(À) Sr(a). <b>NOME</b><br>CARGO</p>
        destinatario = req.destinatario or ""
        html_para_sei = req.html or ""

        if not destinatario and html_para_sei:
            # Regex que aceita: "Ao Sr.", "À Sra.", "Ao(À) Sr(a)."
            match = re.search(
                r'(Ao\s+Sr\.|À\s+Sra\.|Ao\(À\)\s*Sr\(a\)\.)\s*<b>([^<]+)</b><br>([^<]+)',
                html_para_sei,
                re.IGNORECASE
            )
            if match:
                pronome = match.group(1).strip()
                nome = match.group(2).strip()
                cargo = match.group(3).strip()
                # Formato para o iframe mantém o pronome original
                destinatario = f"{pronome} {nome}\n{cargo}"
                print(f"   📬 destinatario extraído: '{pronome}' '{nome}' / '{cargo}'", file=sys.stderr)

                # Remove o bloco de destinatário do HTML (SEI tem campo próprio)
                html_para_sei = re.sub(
                    r'<p[^>]*>\s*(Ao\s+Sr\.|À\s+Sra\.|Ao\(À\)\s*Sr\(a\)\.)\s*<b>[^<]+</b><br>[^<]+</p>\s*',
                    '',
                    html_para_sei,
                    flags=re.IGNORECASE
                )
            else:
                print(f"   📬 destinatario: não encontrado no HTML", file=sys.stderr)
        else:
            print(f"   📬 destinatario: '{destinatario[:50] if destinatario else 'vazio'}'", file=sys.stderr)

        print(f"   📄 html length: {len(html_para_sei)} chars", file=sys.stderr)

        try:
            async with httpx.AsyncClient(timeout=180.0) as client:
                response = await client.post(
                    f"{SEI_RUNNER_URL}/run",
                    json={
                        "mode": "atuar",
                        "nup": req.nup,
                        "tipo_documento": req.tipo_documento,
                        "destinatario": destinatario,
                        "texto_despacho": limpar_html_para_sei(html_para_sei) if html_para_sei else "",
                        "credentials": {
                            "usuario": req.credencial.usuario,
                            "senha": req.credencial.senha,
                            "orgao_id": req.credencial.orgao_id
                        }
                    }
                )
                data = response.json()
            
            if not data.get("ok"):
                return {"sucesso": False, "erro": data.get("error", "Erro ao inserir")}

            # Usa json_data parseado pelo Runner (stdout do script)
            json_data = data.get("json_data")
            if json_data and isinstance(json_data, dict):
                return json_data

            # Fallback: retorna erro com output para diagnóstico
            output = data.get("output", "")
            return {"sucesso": False, "erro": "Não foi possível extrair resultado do script", "output": output[:1000]}
        except Exception as e:
            return {"sucesso": False, "erro": str(e)}

    @app.post("/v1/assinar")
    async def assinar_sei_v1(req: AssinarSEIRequest, request: Request):
        """Endpoint para assinar documento no SEI (step-up flow)"""
        print(f"\U0001f525 /v1/assinar - SEI: {req.sei_numero}", file=sys.stderr)

        try:
            creds = {
                "usuario": req.credencial.usuario,
                "senha": req.credencial.senha,
                "orgao_id": req.credencial.orgao_id,
            }
            if req.credencial.nome:
                creds["nome"] = req.credencial.nome
            if req.credencial.cargo:
                creds["cargo"] = req.credencial.cargo

            async with httpx.AsyncClient(timeout=180.0) as client:
                response = await client.post(
                    f"{SEI_RUNNER_URL}/run",
                    json={
                        "mode": "assinar",
                        "sei_numero": req.sei_numero,
                        "credentials": creds,
                    }
                )
                data = response.json()

            if not data.get("ok"):
                return {"sucesso": False, "erro": data.get("error", "Erro ao assinar")}

            json_data = data.get("json_data")
            if json_data and isinstance(json_data, dict):
                return json_data

            output = data.get("output", "")
            return {"sucesso": False, "erro": "Não foi possível extrair resultado do script", "output": output[:1000]}
        except Exception as e:
            return {"sucesso": False, "erro": str(e)}

    @app.post("/api/v2/testar-credencial")
    async def testar_credencial_v2(credencial: CredencialSEI):
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{SEI_RUNNER_URL}/testar-login", 
                    json={
                        "usuario": credencial.usuario, 
                        "senha": credencial.senha, 
                        "orgao_id": credencial.orgao_id
                    }
                )
                data = response.json()
            return {
                "sucesso": data.get("ok", False), 
                "mensagem": data.get("message", ""), 
                "usuario": credencial.usuario
            }
        except Exception as e:
            return {"sucesso": False, "erro": str(e)}
    
    @app.get("/api/v2/health")
    async def health_v2():
        return {
            "status": "ok",
            "laravel_integration": True,
            "supports_direct_credentials": True,
            "ia_analysis": True,
            "version": "3.0"
        }

    @app.post("/api/debug/capturar-editor-sei")
    async def capturar_editor_sei(request: Request):
        """
        DEBUG: Captura a estrutura HTML do editor de documentos do SEI.
        Usado para analisar como o SEI monta os campos (destinatário, corpo, etc).
        """
        try:
            data = await request.json()
            nup = data.get("nup")
            tipo_documento = data.get("tipo_documento", "Memorando")
            credencial = data.get("credencial", {})

            if not nup:
                return {"sucesso": False, "erro": "Campo 'nup' é obrigatório"}
            if not credencial.get("usuario") or not credencial.get("senha"):
                return {"sucesso": False, "erro": "Credenciais (usuario/senha) são obrigatórias"}

            print(f"🔍 DEBUG: Capturando estrutura editor SEI - NUP: {nup}, Tipo: {tipo_documento}", file=sys.stderr)

            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    f"{SEI_RUNNER_URL}/run",
                    json={
                        "mode": "capturar_editor",
                        "nup": nup,
                        "tipo_documento": tipo_documento,
                        "credentials": {
                            "usuario": credencial.get("usuario"),
                            "senha": credencial.get("senha"),
                            "orgao_id": credencial.get("orgao_id", "31")
                        }
                    }
                )
                data = response.json()

            if not data.get("ok"):
                return {"sucesso": False, "erro": data.get("error", "Erro ao capturar"), "output": data.get("output", "")[:2000]}

            json_data = data.get("json_data", {})
            if json_data:
                return {"sucesso": True, "estrutura": json_data}

            return {"sucesso": False, "erro": "Não foi possível extrair estrutura", "output": data.get("output", "")[:2000]}

        except Exception as e:
            import traceback
            return {"sucesso": False, "erro": str(e), "traceback": traceback.format_exc()}

    @app.post("/api/melhorar-texto")
    async def melhorar_texto_endpoint(request: Request):
        """Melhora texto usando OpenAI"""
        try:
            data = await request.json()
            texto = data.get("texto", "")
            
            if not texto:
                return {"sucesso": False, "erro": "Texto não fornecido"}
            
            import openai
            
            prompt = f"""Você é um revisor de documentos oficiais do CBMAC.

Melhore o texto abaixo, corrigindo:
- Erros gramaticais e ortográficos
- Concordí¢ncia verbal e nominal
- Clareza e objetividade
- Formalidade adequada

Texto original:
{texto}

Retorne APENAS o texto melhorado em HTML (use <p>, <br>, <strong>), sem explicações."""

            client = openai.OpenAI(api_key=OPENAI_API_KEY)
            response = client.chat.completions.create(
                model="gpt-4.1-mini",
                messages=[
                    {"role": "system", "content": "Você melhora textos oficiais mantendo formalidade."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=2000,
                temperature=0.3
            )
            
            texto_melhorado = response.choices[0].message.content
            texto_melhorado = re.sub(r'```html\s*', '', texto_melhorado)
            texto_melhorado = re.sub(r'```\s*', '', texto_melhorado)
            
            return {
                "sucesso": True,
                "texto_melhorado": texto_melhorado,
                "modelo_usado": "gpt-4.1-mini"
            }
        except Exception as e:
            return {"sucesso": False, "erro": str(e)}
    

    @app.post("/api/consultar-lei")
    async def consultar_lei_endpoint(request: Request):
        """Endpoint para consultar legislação via RAG"""
        try:
            data = await request.json()
            consulta = data.get("consulta", "")
            n_results = data.get("n_results", 5)
            
            if not consulta:
                return {"sucesso": False, "erro": "Consulta não informada", "resultados": []}
            
            # Consulta o RAG via webhook n8n
            resultado_n8n = await consultar_legislacao_via_n8n(consulta)
            
            # Usa resultados do n8n
            if resultado_n8n.get("sucesso"):
                return {
                    "sucesso": True,
                    "resultados": resultado_n8n.get("resultados", []),
                    "total": resultado_n8n.get("total", 0),
                    "contexto": resultado_n8n.get("contexto", "")
                }
            
            return {
                "sucesso": True,
                "resultados": [],
                "total": 0
            }
        except Exception as e:
            print(f"â Erro ao consultar legislação: {e}", file=sys.stderr)
            return {"sucesso": False, "erro": str(e), "resultados": []}


    @app.post("/api/chat")
    async def chat_analitico_endpoint(request: Request):
        """Endpoint para chat analítico com contexto do processo"""
        try:
            data = await request.json()
            mensagem = data.get("mensagem", "")
            texto_processo = data.get("texto_canonico", "")
            modelo = data.get("modelo_forcado", "gpt-4.1-mini")
            user_id = data.get("user_id", "")
            
            if not mensagem:
                return {"sucesso": False, "erro": "Mensagem não informada"}
            
            import openai
            
            # Consulta legislação relevante baseada na mensagem
            leis_context = ""
            try:
                resultado_leis = await consultar_legislacao_via_n8n(mensagem)
                if resultado_leis.get("sucesso") and resultado_leis.get("contexto"):
                    leis_context = "\n\nLEGISLAííO RELEVANTE ENCONTRADA:\n" + resultado_leis["contexto"]
            except:
                pass
            
            # Monta o contexto
            contexto = ""
            if texto_processo:
                contexto = f"\n\nCONTEXTO DO PROCESSO:\n{texto_processo[:4000]}"
            
            system_prompt = f"""Você é o ARGUS, assistente inteligente do CBMAC (Corpo de Bombeiros Militar do Acre).

Sua função é auxiliar na análise de processos administrativos, responder dúvidas sobre legislação e ajudar na redação de documentos.

REGRAS:
- Use linguagem formal administrativa
- Cite a legislação quando relevante
- Seja objetivo e claro
- Se não souber, diga que não sabe
- Use HTML para formatação: <b>, <i>, <p>, <br>, <ul>, <li>
{leis_context}
{contexto}"""

            client = openai.OpenAI(api_key=OPENAI_API_KEY)
            response = client.chat.completions.create(
                model=modelo,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": mensagem}
                ],
                max_tokens=2000,
                temperature=0.7
            )
            
            resposta = response.choices[0].message.content
            
            return {
                "sucesso": True,
                "resposta": resposta,
                "modelo": modelo
            }
            
        except Exception as e:
            print(f"â Erro no chat: {e}", file=sys.stderr)
            return {"sucesso": False, "erro": str(e)}

    print("â Endpoints Laravel v3.1 registrados (ANíLISE IA + JSON COMPLETO!)")

    
    # ============================================================
    # ALIASES PARA COMPATIBILIDADE COM FRONTEND
    # ============================================================
    
    
    @app.post("/api/processos/gerar-documento")
    async def gerar_documento_alias(req: GerarDocumentoRequest):
        """Alias para /api/v2/gerar-documento"""
        return await gerar_documento_v2(req)
    
    @app.post("/api/processos/inserir-sei")
    async def inserir_sei_alias(req: InserirSEIRequest):
        """Alias para v1/inserir-sei"""
        return await inserir_documento_sei(req)
    
    @app.post("/api/processos/chat")
    async def chat_alias(request: Request):
        """Alias para /api/chat"""
        return await chat_analitico_endpoint(request)
    
    print("â Aliases de compatibilidade registrados")


    # ============================================================
    # BUSCA CREDENCIAIS DO POSTGRESQL
    # ============================================================
    
    @app.post("/api/processos/analisar")
    async def analisar_com_credenciais_db(request: Request):
        """
        Analisa processo buscando credenciais do PostgreSQL.
        Frontend envia: { nup, usuario_sei }
        """
        import psycopg2
        from decrypt_laravel import decrypt_laravel_aes_gcm
        
        try:
            data = await request.json()
            nup = data.get("nup")
            usuario_sei = data.get("usuario_sei")
            
            if not nup or not usuario_sei:
                return {"sucesso": False, "erro": "NUP e usuario_sei são obrigatí³rios"}
            
            # Conecta no PostgreSQL
            conn = psycopg2.connect(
                host=os.getenv("DB_HOST", "plattargus-db"),
                port=os.getenv("DB_PORT", "5432"),
                database=os.getenv("DB_DATABASE", "plattargus_web"),
                user=os.getenv("DB_USERNAME", "plattargus_web"),
                password=os.getenv("DB_PASSWORD", "")
            )
            cursor = conn.cursor()
            
            # Busca credenciais
            cursor.execute("""
                SELECT sei_senha_cipher, sei_senha_iv, sei_senha_tag, sei_orgao_id, sei_cargo
                FROM users 
                WHERE usuario_sei = %s AND ativo = true AND sei_credencial_ativa = true
            """, (usuario_sei,))
            
            row = cursor.fetchone()
            conn.close()
            
            if not row:
                return {"sucesso": False, "erro": f"Credenciais não encontradas para {usuario_sei}"}
            
            cipher, iv, tag, orgao_id, cargo = row
            
            if not cipher or not iv or not tag:
                return {"sucesso": False, "erro": "Senha SEI não configurada. Vincule suas credenciais."}
            
            # Descriptografa senha
            try:
                senha = decrypt_laravel_aes_gcm(bytes(cipher), bytes(iv), bytes(tag))
            except Exception as e:
                print(f"â Erro ao descriptografar: {e}", file=sys.stderr)
                return {"sucesso": False, "erro": "Erro ao descriptografar credenciais"}
            
            # Chama a análise com credenciais
            credencial = CredencialSEI(
                usuario=usuario_sei,
                senha=senha,
                orgao_id=orgao_id or "31"
            )
            
            req = AnalisarProcessoRequest(nup=nup, credencial=credencial)
            return await analisar_processo_v2(req)
            
        except Exception as e:
            print(f"â Erro em analisar_com_credenciais_db: {e}", file=sys.stderr)
            return {"sucesso": False, "erro": str(e)}

    print("â Endpoint /api/processos/analisar (PostgreSQL) registrado")
