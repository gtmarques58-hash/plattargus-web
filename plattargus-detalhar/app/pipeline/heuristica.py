"""
Motor de Heurística

VERSÃO v1.2: Usa EstagioProcessual para classificar documentos no ciclo de vida

Ciclo de vida:
  ÂNCORA → FUNDAMENTO → DECISÃO → FORMALIZAÇÃO → ENCERRAMENTO
     ↑                                              |
     └──────────── (recurso = novo ciclo) ──────────┘

Processa documentos enriquecidos (doc.v1) e gera:
- Estágio processual de cada documento
- Score de relevância
- Compressão de cadeias repetitivas
- Seleção de top_docs com cobertura de todos os estágios
- Identificação de ciclos processuais

Tudo DETERMINÍSTICO - sem LLM.
"""

from typing import List, Dict, Optional, Tuple
from datetime import datetime
from collections import defaultdict

from ..schemas import (
    DocV1, TagTecnica,
    HeurV1, ParametrosHeuristica, DocScore, TopDoc,
    TipoAto, Sinal, GrupoCompressao, Compressao, CoberturaObrigatoria,
    EstagioProcessual, CicloProcessual,
    criar_heur_v1, classificar_estagio, identificar_ciclos
)
from .tags_detector import classificar_ato


# =============================================================================
# CÁLCULO DE SCORE
# =============================================================================

def calcular_score(
    doc: DocV1,
    params: ParametrosHeuristica,
    posicao_recencia: int,
    total_docs: int
) -> Tuple[int, List[str], str, List[Sinal], EstagioProcessual]:
    """
    Calcula score de um documento.
    
    VERSÃO v1.2: Inclui estágio processual no cálculo
    
    Returns:
        Tuple (score, motivos, tipo_ato, sinais, estagio)
    """
    score = 0
    motivos = []
    sinais: List[Sinal] = []
    
    # Obter tags como strings para classificar_estagio
    tags_str = [t.value if hasattr(t, 'value') else str(t) for t in doc.tags_tecnicas]
    
    # 1) Classificar estágio processual (NOVO v1.2)
    estagio = classificar_estagio(
        tipo_documento=doc.tipo_documento.value if doc.tipo_documento else "",
        tags_tecnicas=tags_str,
        is_decreto=getattr(doc, 'is_decreto', False),
        is_encerramento=getattr(doc, 'is_encerramento', False),
        is_decisorio=getattr(doc, 'is_decisorio', False),
        is_pedido=getattr(doc, 'is_pedido', False)
    )
    
    # 2) Score base por estágio (NOVO v1.2)
    score_estagio = params.pesos_estagio.get(estagio.value, 10)
    score += score_estagio
    motivos.append(f"ESTAGIO_{estagio.value}")
    
    # 3) Classificar ato (legado)
    tipo_ato = classificar_ato(doc.tags_tecnicas, doc.tipo_documento.value if doc.tipo_documento else "")
    
    # 4) Score adicional por tipo de ato (para compatibilidade)
    if tipo_ato in params.pesos:
        score += params.pesos[tipo_ato] // 2  # Metade do peso (para não duplicar)
        motivos.append(tipo_ato)
    
    # 5) Sinais adicionais
    if TagTecnica.TEM_PRAZO in doc.tags_tecnicas:
        score += params.pesos.get("TEM_PRAZO", 20)
        motivos.append("TEM_PRAZO")
        sinais.append(Sinal.TEM_PRAZO)
    
    if TagTecnica.TEM_RECURSO in doc.tags_tecnicas:
        score += params.pesos.get("TEM_RECURSO", 25)
        motivos.append("TEM_RECURSO")
        sinais.append(Sinal.TEM_RECURSO)
    
    if TagTecnica.MUDA_DESTINO in doc.tags_tecnicas:
        score += params.pesos.get("MUDA_DESTINO", 15)
        motivos.append("MUDA_DESTINO")
        sinais.append(Sinal.MUDA_DESTINO)
    
    if TagTecnica.TEM_ARQUIVAMENTO in doc.tags_tecnicas:
        score += params.pesos.get("ARQUIVAMENTO", 10)
        motivos.append("ARQUIVAMENTO")
        sinais.append(Sinal.ARQUIVAMENTO)
    
    if TagTecnica.TEM_DEFERIMENTO in doc.tags_tecnicas or TagTecnica.TEM_INDEFERIMENTO in doc.tags_tecnicas:
        score += params.pesos.get("DECISAO_FINAL", 30)
        motivos.append("DECISAO_FINAL")
        sinais.append(Sinal.DECISAO_FINAL)
    
    # Novas tags v1.1
    if TagTecnica.TEM_DECRETO in doc.tags_tecnicas or getattr(doc, 'is_decreto', False):
        score += params.pesos.get("TEM_DECRETO", 100)
        motivos.append("TEM_DECRETO")
        sinais.append(Sinal.DECISAO_FINAL)
    
    if TagTecnica.TEM_ENCERRAMENTO in doc.tags_tecnicas or getattr(doc, 'is_encerramento', False):
        score += params.pesos.get("TEM_ENCERRAMENTO", 90)
        motivos.append("TEM_ENCERRAMENTO")
    
    if TagTecnica.TEM_FAVORAVEL in doc.tags_tecnicas or getattr(doc, 'is_favoravel', False):
        score += params.pesos.get("TEM_FAVORAVEL", 70)
        motivos.append("TEM_FAVORAVEL")
    
    if TagTecnica.TEM_APRESENTACAO in doc.tags_tecnicas:
        score += params.pesos.get("TEM_APRESENTACAO", 60)
        motivos.append("TEM_APRESENTACAO")
    
    if TagTecnica.TEM_AGREGACAO in doc.tags_tecnicas:
        score += params.pesos.get("TEM_AGREGACAO", 50)
        motivos.append("TEM_AGREGACAO")
    
    if TagTecnica.TEM_CESSAO in doc.tags_tecnicas:
        score += params.pesos.get("TEM_CESSAO", 50)
        motivos.append("TEM_CESSAO")
    
    if TagTecnica.TEM_LOTACAO in doc.tags_tecnicas:
        score += params.pesos.get("TEM_LOTACAO", 40)
        motivos.append("TEM_LOTACAO")
    
    if TagTecnica.ORGAO_EXTERNO in doc.tags_tecnicas or getattr(doc, 'is_orgao_externo', False):
        score += params.pesos.get("ORGAO_EXTERNO", 30)
        motivos.append("ORGAO_EXTERNO")
    
    # 6) Bônus de recência
    if posicao_recencia < 3:
        score += params.bonus_recencia_top3
        motivos.append("RECENTE_TOP3")
    elif posicao_recencia < 10:
        score += params.bonus_recencia_top10
        motivos.append("RECENTE_TOP10")
    
    # 7) Penalização para TRÂMITE sem novidade
    if estagio == EstagioProcessual.TRAMITE:
        # Não penalizar se tem tags importantes
        tags_importantes = [
            TagTecnica.TEM_DECRETO, TagTecnica.TEM_ENCERRAMENTO,
            TagTecnica.TEM_DECISAO, TagTecnica.TEM_PRAZO,
            TagTecnica.TEM_DEFERIMENTO, TagTecnica.TEM_INDEFERIMENTO,
            TagTecnica.TEM_FAVORAVEL, TagTecnica.TEM_RECURSO
        ]
        tem_novidade = any(tag in doc.tags_tecnicas for tag in tags_importantes)
        
        if not tem_novidade and TagTecnica.REPETITIVO in doc.tags_tecnicas:
            score = max(5, score - 30)
            motivos.append("REPETITIVO")
            sinais.append(Sinal.REPETITIVO)
    
    return score, motivos, tipo_ato, sinais, estagio


# =============================================================================
# COMPRESSÃO DE CADEIAS
# =============================================================================

def detectar_cadeias_repetitivas(docs_scores: List[DocScore]) -> Dict[str, List[str]]:
    """
    Detecta cadeias de documentos repetitivos (TRÂMITE consecutivos).
    """
    grupos: Dict[str, List[str]] = defaultdict(list)
    tramites_consecutivos = []
    
    for ds in docs_scores:
        # Usar estágio ao invés de ato
        if ds.estagio == EstagioProcessual.TRAMITE:
            tramites_consecutivos.append(ds.doc_id)
        else:
            if len(tramites_consecutivos) >= 2:
                grupo_id = f"thread:tramite_{tramites_consecutivos[0]}"
                grupos[grupo_id] = tramites_consecutivos.copy()
            tramites_consecutivos = []
    
    if len(tramites_consecutivos) >= 2:
        grupo_id = f"thread:tramite_{tramites_consecutivos[0]}"
        grupos[grupo_id] = tramites_consecutivos.copy()
    
    return grupos


def comprimir_cadeias(
    docs_scores: List[DocScore],
    grupos: Dict[str, List[str]]
) -> Tuple[List[DocScore], Compressao]:
    """
    Aplica compressão mantendo primeiro e último de cada cadeia.
    """
    compressao = Compressao()
    
    for grupo_id, doc_ids in grupos.items():
        if len(doc_ids) < 2:
            continue
        
        mantidos = [doc_ids[0], doc_ids[-1]]
        descartados = doc_ids[1:-1] if len(doc_ids) > 2 else []
        
        grupo = GrupoCompressao(
            grupo_id=grupo_id,
            regra="mantem_primeiro_e_ultimo_de_tramites_consecutivos",
            docs_descartados=descartados,
            docs_mantidos=mantidos,
            justificativa="Trâmites intermediários sem novidade foram comprimidos."
        )
        compressao.grupos.append(grupo)
        compressao.total_descartados += len(descartados)
        compressao.total_mantidos += len(mantidos)
        
        for ds in docs_scores:
            if ds.doc_id in doc_ids:
                ds.grupo_compressao = grupo_id
                if ds.doc_id in descartados:
                    ds.compressao = {"descartado": True, "motivo": "tramite_intermediario"}
    
    return docs_scores, compressao


# =============================================================================
# COBERTURA OBRIGATÓRIA
# =============================================================================

def calcular_cobertura_obrigatoria(
    docs: List[DocV1],
    docs_scores: List[DocScore]
) -> CoberturaObrigatoria:
    """
    Determina documentos que DEVEM ser incluídos.
    
    VERSÃO v1.2: Cobertura por estágio processual
    """
    cobertura = CoberturaObrigatoria()
    
    # Ordenar por data_ref_doc (mais recente primeiro)
    docs_ordenados = sorted(
        docs,
        key=lambda d: d.data_ref_doc or datetime.min,
        reverse=True
    )
    
    # Map doc_id -> DocScore para pegar estágio
    score_map = {ds.doc_id: ds for ds in docs_scores}
    
    # Últimos 3 recentes
    cobertura.ultimos_3_recentes = [d.doc_id for d in docs_ordenados[:3]]
    
    for doc in docs_ordenados:
        ds = score_map.get(doc.doc_id)
        estagio = ds.estagio if ds else EstagioProcessual.TRAMITE
        
        # Por estágio (NOVO v1.2)
        if not cobertura.ultimo_ancora and estagio == EstagioProcessual.ANCORA:
            cobertura.ultimo_ancora = doc.doc_id
            cobertura.ultimo_pedido = doc.doc_id  # Compatibilidade
        
        if not cobertura.ultimo_fundamento and estagio == EstagioProcessual.FUNDAMENTO:
            cobertura.ultimo_fundamento = doc.doc_id
            cobertura.ultimo_parecer = doc.doc_id  # Compatibilidade
        
        if not cobertura.ultimo_decisao and estagio == EstagioProcessual.DECISAO:
            cobertura.ultimo_decisao = doc.doc_id
            cobertura.ultimo_decisorio = doc.doc_id  # Compatibilidade
        
        if not cobertura.ultimo_formalizacao and estagio == EstagioProcessual.FORMALIZACAO:
            cobertura.ultimo_formalizacao = doc.doc_id
        
        if not cobertura.ultimo_encerramento and estagio == EstagioProcessual.ENCERRAMENTO:
            cobertura.ultimo_encerramento = doc.doc_id
        
        # Último recurso (legado)
        if not cobertura.ultimo_recurso:
            if TagTecnica.TEM_RECURSO in doc.tags_tecnicas:
                cobertura.ultimo_recurso = doc.doc_id
        
        # Docs com prazo
        if TagTecnica.TEM_PRAZO in doc.tags_tecnicas:
            cobertura.docs_com_prazo.append(doc.doc_id)
        
        # Todos os decretos
        if TagTecnica.TEM_DECRETO in doc.tags_tecnicas or getattr(doc, 'is_decreto', False):
            cobertura.todos_decretos.append(doc.doc_id)
        
        # Todos os encerramentos
        if TagTecnica.TEM_ENCERRAMENTO in doc.tags_tecnicas or getattr(doc, 'is_encerramento', False):
            cobertura.todos_encerramentos.append(doc.doc_id)
    
    return cobertura


# =============================================================================
# SELEÇÃO TOP-K
# =============================================================================

def selecionar_top_docs(
    docs_scores: List[DocScore],
    cobertura: CoberturaObrigatoria,
    top_k: int = 12
) -> List[TopDoc]:
    """
    Seleciona os top-k documentos mais relevantes.
    
    VERSÃO v1.2: Garante cobertura de todos os estágios
    """
    # Docs obrigatórios
    obrigatorios = set()
    
    # Por estágio (NOVO)
    if cobertura.ultimo_ancora:
        obrigatorios.add(cobertura.ultimo_ancora)
    if cobertura.ultimo_fundamento:
        obrigatorios.add(cobertura.ultimo_fundamento)
    if cobertura.ultimo_decisao:
        obrigatorios.add(cobertura.ultimo_decisao)
    if cobertura.ultimo_formalizacao:
        obrigatorios.add(cobertura.ultimo_formalizacao)
    if cobertura.ultimo_encerramento:
        obrigatorios.add(cobertura.ultimo_encerramento)
    
    # Legado
    if cobertura.ultimo_decisorio:
        obrigatorios.add(cobertura.ultimo_decisorio)
    if cobertura.ultimo_pedido:
        obrigatorios.add(cobertura.ultimo_pedido)
    if cobertura.ultimo_parecer:
        obrigatorios.add(cobertura.ultimo_parecer)
    if cobertura.ultimo_recurso:
        obrigatorios.add(cobertura.ultimo_recurso)
    
    obrigatorios.update(cobertura.ultimos_3_recentes)
    obrigatorios.update(cobertura.docs_com_prazo)
    obrigatorios.update(cobertura.todos_decretos)
    obrigatorios.update(cobertura.todos_encerramentos)
    
    # Filtrar descartados por compressão
    docs_validos = [ds for ds in docs_scores if not ds.compressao.get("descartado", False)]
    
    # Ordenar por score
    docs_ordenados = sorted(docs_validos, key=lambda d: d.score, reverse=True)
    
    # Selecionar
    selecionados = []
    ids_selecionados = set()
    
    # Primeiro: obrigatórios
    for ds in docs_ordenados:
        if ds.doc_id in obrigatorios and ds.doc_id not in ids_selecionados:
            selecionados.append(TopDoc(
                doc_id=ds.doc_id,
                motivos=ds.motivos + ["COBERTURA_OBRIGATORIA"],
                score=ds.score,
                estagio=ds.estagio
            ))
            ids_selecionados.add(ds.doc_id)
    
    # Depois: completar com top-k
    for ds in docs_ordenados:
        if len(selecionados) >= top_k:
            break
        if ds.doc_id not in ids_selecionados:
            selecionados.append(TopDoc(
                doc_id=ds.doc_id,
                motivos=ds.motivos,
                score=ds.score,
                estagio=ds.estagio
            ))
            ids_selecionados.add(ds.doc_id)
    
    return selecionados


# =============================================================================
# FUNÇÃO PRINCIPAL
# =============================================================================

def processar_heuristica(
    docs: List[DocV1],
    params: Optional[ParametrosHeuristica] = None
) -> HeurV1:
    """
    Processa lista de documentos e gera heurística completa.
    
    VERSÃO v1.2: Inclui estágios processuais e ciclos
    """
    params = params or ParametrosHeuristica()
    nup = docs[0].nup if docs else ""
    
    heur = criar_heur_v1(nup, params)
    heur.total_docs_original = len(docs)
    
    # Ordenar por data_ref_doc (mais recente primeiro)
    docs_ordenados = sorted(
        docs,
        key=lambda d: d.data_ref_doc or datetime.min,
        reverse=True
    )
    
    # 1) Calcular score de cada documento (inclui estágio)
    docs_scores: List[DocScore] = []
    for idx, doc in enumerate(docs_ordenados):
        score, motivos, tipo_ato, sinais, estagio = calcular_score(doc, params, idx, len(docs))
        
        ds = DocScore(
            doc_id=doc.doc_id,
            tipo_documento=doc.tipo_documento.value if doc.tipo_documento else "OUTROS",
            data_ref_doc=doc.data_ref_doc,
            estagio=estagio,  # NOVO v1.2
            ato=TipoAto(tipo_ato) if tipo_ato in [e.value for e in TipoAto] else TipoAto.ATO_INFORMATIVO,
            sinais=sinais,
            score=score,
            motivos=motivos,
        )
        docs_scores.append(ds)
    
    # 2) Detectar cadeias repetitivas
    grupos = detectar_cadeias_repetitivas(docs_scores)
    
    # 3) Comprimir cadeias
    docs_scores, compressao = comprimir_cadeias(docs_scores, grupos)
    
    # 4) Calcular cobertura obrigatória
    cobertura = calcular_cobertura_obrigatoria(docs, docs_scores)
    
    # 5) Selecionar top-k
    top_docs = selecionar_top_docs(docs_scores, cobertura, params.top_k)
    
    # 6) Identificar ciclos processuais (NOVO v1.2)
    ciclos = identificar_ciclos(docs_scores)
    
    # Montar resultado
    heur.docs = docs_scores
    heur.compressao = compressao
    heur.top_docs = top_docs
    heur.cobertura_obrigatoria = cobertura
    heur.ciclos = ciclos
    heur.ciclo_atual = len(ciclos) if ciclos else 1
    heur.total_docs_filtrados = len(top_docs)
    heur.processado_em = datetime.now()
    
    return heur
