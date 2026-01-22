"""
Resumidor

Gera o resumo executivo (resumo.v1) a partir do case.v1.
Este e o OUTPUT FINAL do pipeline que sera enviado ao ARGUS.

CORREÇÃO v1.1:
- Detecta FASES do processo (encerramento + nova fase)
- Identifica corretamente processos com múltiplas fases
- Usa unidade_origem_real (corrigida)
- Mostra status correto (ENCERRADO vs EM ANDAMENTO)
"""

from typing import List, Optional, Dict
from datetime import datetime, timedelta

from ..schemas import (
    CaseV1, ResumoV1, DocV1, TagTecnica,
    ContextoParaIA, PrazoDestaque, TrechoRelevante,
    criar_resumo_v1
)


# =============================================================================
# DETECÇÃO DE FASES DO PROCESSO
# =============================================================================

def identificar_fases(docs: List[DocV1]) -> List[Dict]:
    """
    Identifica fases do processo baseado em termos de encerramento.
    
    Um processo pode ter múltiplas fases:
    - Fase 1: Pedido inicial -> Decisão -> Encerramento
    - Fase 2: Nova demanda -> Em andamento
    
    Returns:
        Lista de fases com:
        - numero: int
        - inicio_doc: doc_id
        - fim_doc: doc_id ou None
        - status: "CONCLUIDA" ou "EM_ANDAMENTO"
        - docs: lista de doc_ids
        - resumo: texto descritivo
    """
    if not docs:
        return []
    
    # Ordenar por data (mais antigo primeiro)
    docs_ordenados = sorted(
        docs,
        key=lambda d: d.data_ref_doc or datetime.min
    )
    
    fases = []
    fase_atual = {
        "numero": 1,
        "inicio_doc": None,
        "fim_doc": None,
        "status": "EM_ANDAMENTO",
        "docs": [],
        "tem_decreto": False,
        "tem_encerramento": False,
    }
    
    for doc in docs_ordenados:
        # Adicionar doc à fase atual
        fase_atual["docs"].append(doc.doc_id)
        
        if fase_atual["inicio_doc"] is None:
            fase_atual["inicio_doc"] = doc.doc_id
        
        # Verificar se tem decreto
        if doc.is_decreto or TagTecnica.TEM_DECRETO in doc.tags_tecnicas:
            fase_atual["tem_decreto"] = True
        
        # Verificar se é termo de encerramento
        if doc.is_encerramento or TagTecnica.TEM_ENCERRAMENTO in doc.tags_tecnicas:
            fase_atual["tem_encerramento"] = True
            fase_atual["fim_doc"] = doc.doc_id
            fase_atual["status"] = "CONCLUIDA"
            
            # Salvar fase e iniciar nova
            fases.append(fase_atual.copy())
            
            fase_atual = {
                "numero": len(fases) + 1,
                "inicio_doc": None,
                "fim_doc": None,
                "status": "EM_ANDAMENTO",
                "docs": [],
                "tem_decreto": False,
                "tem_encerramento": False,
            }
    
    # Adicionar última fase se não estiver vazia
    if fase_atual["docs"]:
        fases.append(fase_atual)
    
    return fases


def gerar_resumo_fases(fases: List[Dict], docs: List[DocV1]) -> str:
    """
    Gera texto descritivo das fases.
    """
    if not fases:
        return ""
    
    if len(fases) == 1:
        fase = fases[0]
        if fase["status"] == "CONCLUIDA":
            return "Processo CONCLUÍDO (fase única encerrada)."
        else:
            return "Processo em andamento."
    
    # Múltiplas fases
    partes = [f"Processo com {len(fases)} FASES identificadas:"]
    
    for fase in fases:
        status = "✅ CONCLUÍDA" if fase["status"] == "CONCLUIDA" else "🔄 EM ANDAMENTO"
        partes.append(f"  Fase {fase['numero']}: {status} ({len(fase['docs'])} docs)")
    
    return " ".join(partes)


# =============================================================================
# GERAÇÃO DE RESUMO EXECUTIVO
# =============================================================================

def gerar_resumo_executivo_texto(case: CaseV1, fases: List[Dict] = None) -> str:
    """
    Gera texto do resumo executivo a partir do case.
    
    CORREÇÃO v1.1: Inclui informação sobre fases do processo.
    """
    partes = []
    
    # Info sobre fases
    if fases and len(fases) > 1:
        fases_concluidas = sum(1 for f in fases if f["status"] == "CONCLUIDA")
        fases_abertas = len(fases) - fases_concluidas
        partes.append(f"Processo com {len(fases)} fases ({fases_concluidas} concluídas, {fases_abertas} em andamento).")
    
    # Situação
    partes.append(f"Situação atual: {case.situacao_atual.value}.")
    
    if case.situacao_descricao:
        partes.append(case.situacao_descricao)
    
    # Pedido vigente
    if case.pedido_vigente:
        partes.append(f"Pedido vigente: {case.pedido_vigente.descricao} (doc {case.pedido_vigente.doc_id_origem}).")
    
    # Último comando
    if case.ultimo_comando:
        cmd = case.ultimo_comando.descricao
        if case.ultimo_comando.prazo:
            cmd += f" (prazo: {case.ultimo_comando.prazo})"
        partes.append(f"Última determinação: {cmd}.")
    
    # Pendências
    if case.pendencias_abertas:
        pend = ", ".join([p.descricao for p in case.pendencias_abertas[:3]])
        partes.append(f"Pendências: {pend}.")
    
    # Alertas
    for alerta in case.alertas[:2]:
        partes.append(f"Atenção: {alerta}")
    
    return " ".join(partes)


def extrair_prazos_destaque(case: CaseV1) -> List[PrazoDestaque]:
    """
    Extrai prazos que merecem destaque.
    """
    prazos = []
    
    if case.ultimo_comando and case.ultimo_comando.prazo:
        prazos.append(PrazoDestaque(
            descricao=case.ultimo_comando.descricao,
            doc_origem=case.ultimo_comando.doc_id,
            urgente=True
        ))
    
    for pend in case.pendencias_abertas:
        if pend.prazo:
            prazos.append(PrazoDestaque(
                descricao=pend.descricao,
                doc_origem=pend.doc_id,
                urgente=False
            ))
    
    return prazos


def extrair_trechos_relevantes(
    case: CaseV1,
    docs: Optional[List[DocV1]] = None
) -> List[TrechoRelevante]:
    """
    Extrai trechos relevantes para citação.
    """
    trechos = []
    
    for bc in case.base_citada[:5]:
        trechos.append(TrechoRelevante(
            doc_id=bc.doc_id,
            tipo_doc="",
            trecho=bc.trecho,
            motivo_relevancia="Base para conclusão"
        ))
    
    return trechos


def montar_contexto_ia(case: CaseV1, fases: List[Dict] = None) -> ContextoParaIA:
    """
    Monta instruções de contexto para a IA.
    
    CORREÇÃO v1.1: Inclui informações sobre fases.
    """
    contexto = ContextoParaIA()
    
    # Foco
    if case.pedido_vigente:
        contexto.foco = f"O pedido ATUAL é: {case.pedido_vigente.descricao}"
    
    # Se tem múltiplas fases
    if fases and len(fases) > 1:
        fases_concluidas = [f for f in fases if f["status"] == "CONCLUIDA"]
        if fases_concluidas:
            contexto.ignorar = f"Fases já encerradas: {len(fases_concluidas)} fase(s) concluída(s)"
            contexto.observacoes.append("Processo com múltiplas fases - focar na fase atual")
    
    # Ignorar
    if case.pendencias_encerradas:
        encerrados = [p.descricao for p in case.pendencias_encerradas[:3]]
        if contexto.ignorar:
            contexto.ignorar += f". Pedidos resolvidos: {', '.join(encerrados)}"
        else:
            contexto.ignorar = f"Pedidos já resolvidos: {', '.join(encerrados)}"
    
    # Docs essenciais
    contexto.docs_essenciais = case.docs_relevantes[:5]
    
    # Observações
    contexto.observacoes.extend(case.alertas[:3])
    
    return contexto


def identificar_unidades(case: CaseV1, docs: Optional[List[DocV1]] = None) -> Dict[str, str]:
    """
    Identifica unidades envolvidas usando o fluxo de tramitação.
    
    CORREÇÃO v1.1: Usa unidade_origem_real (corrigida).
    """
    unidades = {}
    
    # Usar fluxo de tramitação se disponível
    fluxo = case.fluxo_tramitacao
    if fluxo:
        if fluxo.demandante:
            unidades["demandante"] = fluxo.demandante
        if fluxo.executora:
            unidades["executora"] = fluxo.executora
        if fluxo.resposta:
            unidades["resposta"] = fluxo.resposta
        if fluxo.caminho:
            unidades["caminho"] = " -> ".join(fluxo.caminho)
    
    # Extrair dos docs se disponível - CORREÇÃO v1.1: usar unidade_origem_real
    if not unidades and docs:
        unidades_lista = []
        for doc in docs:
            # Priorizar unidade_origem_real (corrigida)
            sigla = doc.get_sigla_efetiva() if hasattr(doc, 'get_sigla_efetiva') else (
                getattr(doc, 'unidade_origem_real', None) or getattr(doc, 'sigla_origem', None)
            )
            if sigla and sigla not in unidades_lista:
                unidades_lista.append(sigla)
        
        if unidades_lista:
            unidades["demandante"] = unidades_lista[0]  # Primeiro doc
            unidades["executora"] = unidades_lista[-1]  # Último doc
            unidades["resposta"] = unidades_lista[0]
            unidades["caminho"] = " -> ".join(unidades_lista[:10])  # Max 10
    
    # Fallback: do último comando
    if not unidades.get("executora") and case.ultimo_comando and case.ultimo_comando.destino:
        unidades["executora"] = case.ultimo_comando.destino
    
    return unidades


def calcular_flags(case: CaseV1, fases: List[Dict] = None) -> Dict[str, bool]:
    """
    Calcula flags importantes.
    
    CORREÇÃO v1.1: Inclui flag para múltiplas fases.
    """
    flags = {
        "tem_prazo_pendente": bool(case.ultimo_comando and case.ultimo_comando.prazo) or \
                              any(p.prazo for p in case.pendencias_abertas),
        "tem_recurso": "RECURSO" in case.situacao_atual.value,
        "tem_decisao_final": case.situacao_atual.value in ["DEFERIDO", "INDEFERIDO", "ARQUIVADO", "CONCLUÍDO"],
        "fluxo_regular": len(case.alertas) == 0,
        "requer_urgencia": case.pedido_vigente.urgente if case.pedido_vigente else False,
    }
    
    # CORREÇÃO v1.1: Flags para fases
    if fases:
        flags["tem_multiplas_fases"] = len(fases) > 1
        flags["todas_fases_concluidas"] = all(f["status"] == "CONCLUIDA" for f in fases)
        flags["tem_fase_em_andamento"] = any(f["status"] == "EM_ANDAMENTO" for f in fases)
    
    return flags


# =============================================================================
# FUNÇÃO PRINCIPAL
# =============================================================================

def gerar_resumo(
    case: CaseV1,
    docs: Optional[List[DocV1]] = None,
    pipeline_info: Optional[Dict] = None
) -> ResumoV1:
    """
    Gera resumo executivo completo.
    
    CORREÇÃO v1.1: Detecta e inclui informações sobre fases do processo.
    """
    resumo = criar_resumo_v1(case.nup)
    
    # Identificar fases do processo
    fases = identificar_fases(docs) if docs else []
    
    # Resumo executivo em texto
    resumo.resumo_executivo = gerar_resumo_executivo_texto(case, fases)
    
    # Campos estruturados
    resumo.situacao_atual = case.situacao_atual.value
    
    # CORREÇÃO v1.1: Ajustar situação baseada em fases
    if fases:
        todas_concluidas = all(f["status"] == "CONCLUIDA" for f in fases)
        if todas_concluidas and "ANDAMENTO" in resumo.situacao_atual.upper():
            resumo.situacao_atual = "CONCLUÍDO"
    
    resumo.pedido_vigente = case.pedido_vigente.descricao if case.pedido_vigente else ""
    resumo.ultimo_comando = case.ultimo_comando.descricao if case.ultimo_comando else ""
    
    # Prazos
    resumo.prazos_pendentes = extrair_prazos_destaque(case)
    if resumo.prazos_pendentes:
        resumo.prazo_mais_urgente = resumo.prazos_pendentes[0].descricao
    
    # Contexto para IA
    resumo.contexto_para_ia = montar_contexto_ia(case, fases)
    
    # Trechos relevantes
    resumo.trechos_relevantes = extrair_trechos_relevantes(case, docs)
    
    # Unidades
    resumo.unidades = identificar_unidades(case, docs)
    
    # Flags
    resumo.flags = calcular_flags(case, fases)
    
    # Pipeline info
    if pipeline_info:
        resumo.pipeline = pipeline_info
    
    # CORREÇÃO v1.1: Adicionar info sobre fases
    if fases:
        resumo.pipeline["fases"] = len(fases)
        resumo.pipeline["fases_concluidas"] = sum(1 for f in fases if f["status"] == "CONCLUIDA")
    
    resumo.processado_em = datetime.now()
    
    return resumo


# =============================================================================
# FORMATAÇÃO PARA ARGUS
# =============================================================================

def formatar_para_argus(resumo: ResumoV1, docs: Optional[List[DocV1]] = None) -> str:
    """
    Formata o resumo para enviar ao ARGUS como contexto.
    
    CORREÇÃO v1.1: Inclui informações sobre fases.
    CORREÇÃO v1.2: Inclui textos dos documentos essenciais e instrução de minuta.
    """
    linhas = [
        "=" * 60,
        "📋 CONTEXTO PRÉ-PROCESSADO DO PROCESSO",
        "=" * 60,
        f"NUP: {resumo.nup}",
        "",
    ]
    
    # Info sobre fases (se houver múltiplas)
    if resumo.pipeline.get("fases", 0) > 1:
        total_fases = resumo.pipeline["fases"]
        fases_ok = resumo.pipeline.get("fases_concluidas", 0)
        linhas.append(f"📊 FASES: {total_fases} ({fases_ok} concluídas, {total_fases - fases_ok} em andamento)")
        linhas.append("")
    
    linhas.append(f"🚦 SITUAÇÃO: {resumo.situacao_atual}")
    linhas.append("")
    
    if resumo.pedido_vigente:
        linhas.append(f"📌 PEDIDO VIGENTE: {resumo.pedido_vigente}")
        linhas.append("")
    
    if resumo.ultimo_comando:
        linhas.append(f"⚡ ÚLTIMA DETERMINAÇÃO: {resumo.ultimo_comando}")
        linhas.append("")
    
    if resumo.prazos_pendentes:
        linhas.append("⏰ PRAZOS PENDENTES:")
        for prazo in resumo.prazos_pendentes[:3]:
            urgente = "🔴 URGENTE" if prazo.urgente else "🟡"
            linhas.append(f"  {urgente} {prazo.descricao}")
        linhas.append("")
    
    # Fluxo de tramitação
    if resumo.unidades:
        linhas.append("🏢 UNIDADES ENVOLVIDAS:")
        if resumo.unidades.get("demandante"):
            linhas.append(f"  Demandante: {resumo.unidades['demandante']}")
        if resumo.unidades.get("executora"):
            linhas.append(f"  Executora: {resumo.unidades['executora']}")
        if resumo.unidades.get("resposta"):
            linhas.append(f"  Resposta: {resumo.unidades['resposta']}")
        if resumo.unidades.get("caminho"):
            linhas.append(f"  Fluxo: {resumo.unidades['caminho']}")
        linhas.append("")
    
    if resumo.contexto_para_ia.foco:
        linhas.append(f"🎯 FOCO: {resumo.contexto_para_ia.foco}")
    
    if resumo.contexto_para_ia.ignorar:
        linhas.append(f"⛔ IGNORAR: {resumo.contexto_para_ia.ignorar}")
    
    linhas.append("")
    linhas.append("📝 RESUMO EXECUTIVO:")
    linhas.append(resumo.resumo_executivo)
    linhas.append("")
    
    # CORREÇÃO v1.2: Incluir textos dos documentos essenciais
    if docs:
        docs_essenciais_ids = resumo.contexto_para_ia.docs_essenciais[:5]
        docs_map = {str(d.doc_id): d for d in docs}
        
        docs_com_texto = []
        for doc_id in docs_essenciais_ids:
            if str(doc_id) in docs_map:
                docs_com_texto.append(docs_map[str(doc_id)])
        
        if docs_com_texto:
            linhas.append("=" * 60)
            linhas.append("📄 DOCUMENTOS ESSENCIAIS (TEXTO COMPLETO)")
            linhas.append("=" * 60)
            
            for doc in docs_com_texto:
                linhas.append("")
                titulo = doc.titulo_arvore or (doc.tipo_documento.value if hasattr(doc.tipo_documento, 'value') else str(doc.tipo_documento))
                linhas.append(f"--- {titulo} ({doc.doc_id}) ---")
                sigla = doc.get_sigla_efetiva() if hasattr(doc, 'get_sigla_efetiva') else getattr(doc, 'sigla_origem', None)
                if sigla:
                    linhas.append(f"Origem: {sigla}")
                if doc.data_ref_doc:
                    linhas.append(f"Data: {doc.data_ref_doc.strftime('%d/%m/%Y')}")
                linhas.append("")
                # Limitar texto a 2000 chars por doc
                texto = doc.texto_limpo or doc.texto_raw or ""
                if len(texto) > 2000:
                    texto = texto[:2000] + "... [TRUNCADO]"
                linhas.append(texto)
                linhas.append("")
            
            linhas.append("=" * 60)
    
    # CORREÇÃO v1.2: Instrução para oferecer minuta
    linhas.append("")
    linhas.append("💡 INSTRUÇÃO: Ao final da análise, SEMPRE ofereça ao usuário ajuda para elaborar a minuta do próximo documento necessário (despacho, memorando, ofício, etc).")
    linhas.append("")
    linhas.append("=" * 60)
    
    return "\n".join(linhas)
