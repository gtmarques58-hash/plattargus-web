#!/usr/bin/env python3
"""
laravel_integration.py v3.1 - COM ANíLISE IA + JSON COMPLETO
Fluxo: detalhar_processo (--full) -> Agente IA -> JSON estruturado com documentos
"""
import os, sys, json, re
from typing import Optional, Dict, List
from pathlib import Path
from pydantic import BaseModel
import httpx
from detalhar_client import get_detalhar_client
from typing import List

sys.path.insert(0, '/app/scripts')
SEI_RUNNER_URL = os.getenv("SEI_RUNNER_URL", "http://runner:8001")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
PROMPTS_DIR = Path("/app/prompts")

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
    """Chama o serviço plattargus-detalhar para extrair dados do processo."""
    try:
        client = get_detalhar_client()
        
        if await client.is_online():
            print(f"   ?? Usando detalhar-service para {nup}", file=sys.stderr)
            
            result = await client.detalhar_sync(
                nup=nup,
                credenciais={
                    "sigla": credencial.usuario,
                    "usuario": credencial.usuario,
                    "senha": credencial.senha,
                    "orgao_id": credencial.orgao_id
                },
                user_id=credencial.usuario,
                timeout=720
            )
            
            if result.sucesso:
                resultado = result.resultado or {}
                resumo = resultado.get("resumo_processo") or resultado.get("resumo") or ""
                if isinstance(resumo, dict):
                    resumo = resumo.get("texto") or json.dumps(resumo)
                
                cache_info = " (CACHE)" if result.from_cache else ""
                print(f"   ? Detalhar OK{cache_info}: {len(str(resumo))} chars", file=sys.stderr)
                
                return {
                    "sucesso": True,
                    "nup": nup,
                    "resumo_processo": resumo,
                    "documentos": resultado.get("documentos", []),
                    "from_cache": result.from_cache,
                    "duracao_segundos": result.duracao_segundos,
                    "modo": resultado.get("modo", "detalhar"),
                    "pastas_total": resultado.get("pastas_total", 0),
                    "documentos_total": resultado.get("documentos_total", 0),
                    "extraidos_ok": resultado.get("extraidos_ok", 0),
                    "docs_escaneados": resultado.get("docs_escaneados", 0),
                    "ressalvas": resultado.get("ressalvas", []),
                    "mensagem": resultado.get("mensagem", "Processo extraído com sucesso")
                }
            else:
                print(f"   ?? Detalhar erro: {result.erro}", file=sys.stderr)
                return await chamar_sei_reader_fallback(nup, credencial)
        else:
            print(f"   ?? Detalhar-service offline, usando runner...", file=sys.stderr)
            return await chamar_sei_reader_fallback(nup, credencial)
            
    except Exception as e:
        print(f"   ? Erro detalhar-client: {e}, tentando fallback...", file=sys.stderr)
        return await chamar_sei_reader_fallback(nup, credencial)


async def chamar_sei_reader_fallback(nup: str, credencial: CredencialSEI) -> Dict:
    """Fallback: chama o SEI Runner diretamente (modo antigo)."""
    try:
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
        
        if data.get("json_data"):
            resultado = data["json_data"]
            resultado["nup"] = nup
            return resultado
        
        output = data.get("output", "")
        json_match = re.search(r'\{[\s\S]*"sucesso"[\s\S]*\}', output)
        if json_match:
            try:
                resultado = json.loads(json_match.group())
                resultado["nup"] = nup
                return resultado
            except:
                pass
        
        return {"sucesso": True, "nup": nup, "resumo_processo": output[:8000]}
        
    except Exception as e:
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
    """Gera documento usando OpenAI GPT-4"""
    try:
        import openai
        
        # Monta contexto da análise
        resumo = analise.get("resumo_executivo", "") or analise.get("resumo_processo", "") or ""
        interessado = analise.get("interessado", {})
        pedido = analise.get("pedido_original", {}) or analise.get("pedido", {})
        sugestao = analise.get("sugestao", {})
        
        # Monta bloco de destinatário(s)
        bloco_destinatario = ""
        vocativo = "Senhor(a)"
        
        if destinatarios and len(destinatarios) > 0:
            if len(destinatarios) == 1:
                # Um destinatário
                d = destinatarios[0]
                nome_dest = d.get('nome', '')
                posto_dest = d.get('posto_grad', '')
                cargo_dest = d.get('cargo', '')
                sigla_dest = d.get('sigla', '')
                sigla_sei = d.get('sigla_sei', f'CBMAC-{sigla_dest}')
                
                bloco_destinatario = f"Ao(à) Sr(a). {posto_dest} {nome_dest}\n{cargo_dest} - {sigla_sei}"
                
                # Define vocativo baseado no cargo
                if 'Comandante' in cargo_dest:
                    vocativo = "Senhor Comandante"
                elif 'Diretor' in cargo_dest:
                    vocativo = "Senhor Diretor"
                elif 'Chefe' in cargo_dest:
                    vocativo = "Senhor Chefe"
                else:
                    vocativo = "Senhor(a)"
            else:
                # Múltiplos destinatários (circular)
                nomes = []
                siglas = []
                for d in destinatarios:
                    posto = d.get('posto_grad', '')
                    nome = d.get('nome', '')
                    sigla = d.get('sigla', '')
                    nomes.append(f"{posto} {nome}".strip())
                    siglas.append(d.get('sigla_sei', f'CBMAC-{sigla}'))
                
                # Determina vocativo para circular
                cargos = [d.get('cargo', '') for d in destinatarios]
                if all('Comandante' in c for c in cargos):
                    vocativo = "Senhores Comandantes"
                elif all('Diretor' in c for c in cargos):
                    vocativo = "Senhores Diretores"
                else:
                    vocativo = "Senhores"
                
                bloco_destinatario = f"Aos Senhores:\n" + "\n".join([f"- {n}" for n in nomes])
                bloco_destinatario += f"\n\n{', '.join(siglas)}"
        elif destinatario:
            # Fallback: destinatário como string simples
            bloco_destinatario = f"Ao(à) Sr(a). {destinatario}"
        elif interessado and interessado.get('nome'):
            # Fallback: usa dados do interessado da análise
            nome_int = interessado.get('nome', '')
            cargo_int = interessado.get('cargo', '')
            posto_int = interessado.get('posto_grad', '')

            if posto_int:
                bloco_destinatario = f"Ao(à) Sr(a). {posto_int} {nome_int}"
            else:
                bloco_destinatario = f"Ao(à) Sr(a). {nome_int}"
            if cargo_int:
                bloco_destinatario += f"\n{cargo_int}"

            # Define vocativo baseado no cargo do interessado
            if cargo_int and 'Comandante' in cargo_int:
                vocativo = "Senhor Comandante"
            elif cargo_int and 'Diretor' in cargo_int:
                vocativo = "Senhor Diretor"
            elif cargo_int and 'Chefe' in cargo_int:
                vocativo = "Senhor Chefe"
            else:
                vocativo = "Senhor(a)"
        else:
            bloco_destinatario = ""
        
        # Monta bloco do remetente
        bloco_remetente = ""
        if remetente:
            nome_rem = remetente.get('nome', '')
            posto_rem = remetente.get('posto_grad', '')
            cargo_rem = remetente.get('cargo', '')
            portaria = remetente.get('portaria', '')
            
            bloco_remetente = f"{posto_rem} {nome_rem}\n{cargo_rem}"
            if portaria:
                bloco_remetente += f"\n{portaria}"
        
        # Extrai assunto da análise
        assunto = analise.get('assunto', '') or pedido.get('descricao', '') or analise.get('tipo_demanda', '')

        # Monta bloco de instrução do usuário (comando de voz)
        bloco_instrucao = ""
        if instrucao_voz and instrucao_voz.strip():
            bloco_instrucao = f"INSTRUÇÃO DO USUÁRIO: {instrucao_voz.strip()}"

        contexto = f"""
NUP: {nup}
TIPO DE DOCUMENTO: {tipo}
TIPO DE DEMANDA: {analise.get('tipo_demanda', '-')}
RESUMO: {resumo}

INTERESSADO: {interessado.get('nome', '-')} - {interessado.get('cargo', '-')}
PEDIDO: {pedido.get('descricao', '-')}

SUGESTíO DE AííO: {sugestao.get('acao', '-') if isinstance(sugestao, dict) else '-'}
FUNDAMENTAííO: {sugestao.get('fundamentacao', '-') if isinstance(sugestao, dict) else '-'}
{bloco_instrucao}
"""
        
        # Carrega prompt de geração
        prompt_template = carregar_prompt("gerar_documento")
        
        if prompt_template:
            prompt = prompt_template.replace("{tipo_documento}", tipo)
            prompt = prompt.replace("{nup}", nup)
            prompt = prompt.replace("{analise}", contexto)
            prompt = prompt.replace("{dados_destinatario}", bloco_destinatario)
            prompt = prompt.replace("{dados_remetente}", bloco_remetente)
            prompt = prompt.replace("{vocativo}", vocativo)
            prompt = prompt.replace("{assunto}", assunto)
            prompt = prompt.replace("{legislacao}", "")
            prompt = prompt.replace("{instrucao_voz}", instrucao_voz.strip() if instrucao_voz else "")
        else:
            prompt = f"""Gere um {tipo} formal para o processo {nup}.

{contexto}

=== ESTRUTURA DO DOCUMENTO ===

{bloco_destinatario}

Assunto: {assunto}

{vocativo},

[GERE O CORPO DO DOCUMENTO AQUI - Use parágrafos numerados se apropriado]

Atenciosamente,

{bloco_remetente}

=== INSTRUííES ===
- Use linguagem formal e objetiva
- Siga o padrão de documentos oficiais do CBMAC
- O cabeçalho acima (destinatário, assunto, vocativo) já está definido - use exatamente como está
- Gere apenas o corpo do documento (texto principal)
- Finalize com "Atenciosamente," e os dados do remetente
- Baseie-se apenas no contexto fornecido

Gere o documento em HTML simples (use <p>, <br>, <strong>).
Use style inline para formatação:
- Parágrafos: text-align: justify; text-indent: 1.5cm
- Assinatura: text-align: center
"""
        
        client = openai.OpenAI(api_key=OPENAI_API_KEY)
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": "Você gera documentos oficiais do CBMAC em HTML. Mantenha o formato estruturado com destinatário, assunto, vocativo, corpo e assinatura."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=2000,
            temperature=0.3
        )
        
        html = response.choices[0].message.content
        # Limpa markdown se houver
        html = re.sub(r'```html\s*', '', html)
        html = re.sub(r'```\s*', '', html)

        # Remove NUP/Tipo que o LLM possa ter gerado (evita duplicação)
        html = re.sub(r'<p[^>]*>\s*[•\-]?\s*NUP\s*:\s*[\d\.\-/]+.*?</p>\s*', '', html, flags=re.IGNORECASE | re.DOTALL)
        html = re.sub(r'[•\-]?\s*NUP\s*:\s*[\d\.\-/]+\s*<br\s*/?>', '', html, flags=re.IGNORECASE)
        html = re.sub(r'[•\-]?\s*Tipo\s*(de\s*)?documento\s*:\s*[^<]+<br\s*/?>', '', html, flags=re.IGNORECASE)
        html = re.sub(r'<p[^>]*>\s*</p>', '', html)  # Remove parágrafos vazios
        html = html.strip()

        # Adiciona cabeçalho padronizado com NUP e Tipo no início do documento
        cabecalho_nup_tipo = f'<p style="text-align: left; font-size: 10pt; color: #555;">• NUP: {nup}<br>• Tipo de documento: {tipo}</p><hr style="margin: 10px 0;">'
        html = cabecalho_nup_tipo + html

        return {"sucesso": True, "documento": html, "tipo": tipo, "nup": nup}
    except Exception as e:
        return {"sucesso": False, "erro": str(e)}

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
        print(f"ð¥ /v1/inserir-sei - NUP: {req.nup}, Tipo: {req.tipo_documento}", file=sys.stderr)
        
        try:
            async with httpx.AsyncClient(timeout=180.0) as client:
                response = await client.post(
                    f"{SEI_RUNNER_URL}/run",
                    json={
                        "mode": "atuar",
                        "nup": req.nup,
                        "tipo_documento": req.tipo_documento,
                        "destinatario": req.destinatario or "",
                        "texto_despacho": limpar_html_para_sei(req.html) if req.html else "",
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
