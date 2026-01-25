"""
ORQUESTRADOR Pipeline v2.0 - Standalone para FastAPI
=====================================================
Une: Heuristica -> Curador (se necessario) -> Analista
"""

import time
import sys
from typing import Dict, Any, List

from .config import USAR_LLM, LIMITE_DOCS_DIRETO, LIMITE_CHARS_DIRETO
from .heuristica_leve import processar_heuristica_leve
from .curador_llm import curar_processo
from .analista_llm import analisar_processo


def processar_pipeline_v2(
    nup: str,
    documentos: List[Dict[str, Any]],
    usar_llm: bool = True
) -> Dict[str, Any]:
    """
    Pipeline completo v2.0

    Fluxo:
    1. Heuristica Leve (classificacao + dedup)
    2. Se docs > 10 ou chars > 120k -> Curador (seleciona 8-12)
    3. Analista (gera JSON rico)

    Args:
        nup: Numero do processo
        documentos: Lista de documentos extraidos
        usar_llm: Se False, so faz heuristica

    Returns:
        Dict com analise completa + metricas
    """
    inicio = time.time()

    resultado = {
        "nup": nup,
        "sucesso": False,
        "pipeline_v2": True,
        "etapas": {},
        "erro": None
    }

    try:
        # ================================================================
        # ETAPA 1: HEURISTICA LEVE
        # ================================================================
        t1 = time.time()

        if not documentos:
            resultado["erro"] = "Nenhum documento encontrado"
            return resultado

        print(f"   [PIPELINE] Heuristica: {len(documentos)} docs...", file=sys.stderr)
        heur = processar_heuristica_leve(documentos, nup)

        resultado["etapas"]["heuristica"] = {
            "tempo_ms": int((time.time() - t1) * 1000),
            "total_docs": len(heur.get('documentos', [])),
            "total_chars": heur.get('metricas', {}).get('total_chars', 0),
            "contagem_prioridade": heur.get('metricas', {}).get('contagem_prioridade', {}),
            "precisa_curador": heur.get('metricas', {}).get('precisa_curador', False)
        }

        if not usar_llm or not USAR_LLM:
            resultado["heuristica"] = heur
            resultado["sucesso"] = True
            resultado["modo"] = "APENAS_HEURISTICA"
            return resultado

        # ================================================================
        # ETAPA 2: CURADOR (se necessario)
        # ================================================================
        total_docs = len(heur.get('documentos', []))
        total_chars = heur.get('metricas', {}).get('total_chars', 0)
        precisa_curador = total_docs > LIMITE_DOCS_DIRETO or total_chars > LIMITE_CHARS_DIRETO

        heur_para_analista = heur

        if precisa_curador:
            t2 = time.time()
            print(f"   [PIPELINE] Curador: reduzindo {total_docs} docs...", file=sys.stderr)

            curado = curar_processo(heur)

            if not curado.get('sucesso'):
                resultado["erro"] = f"Curador falhou: {curado.get('erro')}"
                resultado["heuristica"] = heur
                return resultado

            heur_para_analista = curado.get('heuristica_filtrada', heur)

            resultado["etapas"]["curador"] = {
                "tempo_ms": int((time.time() - t2) * 1000),
                "docs_original": total_docs,
                "docs_selecionados": curado.get('total_selecionado', 0),
                "reducao_percent": curado.get('reducao_percent', 0),
                "docs_ids": curado.get('docs_selecionados', []),
                "custo": curado.get('_meta', {}).get('custo', 0)
            }
        else:
            resultado["etapas"]["curador"] = {"pulado": True, "motivo": "docs <= 10 e chars <= 120k"}

        # ================================================================
        # ETAPA 3: ANALISTA
        # ================================================================
        t3 = time.time()
        print(f"   [PIPELINE] Analista: gerando analise...", file=sys.stderr)

        analise = analisar_processo(heur_para_analista)

        if not analise.get('sucesso'):
            resultado["erro"] = f"Analista falhou: {analise.get('erro')}"
            resultado["heuristica"] = heur
            return resultado

        resultado["etapas"]["analista"] = {
            "tempo_ms": int((time.time() - t3) * 1000),
            "docs_analisados": analise.get('total_docs_analisados', 0),
            "custo": analise.get('_meta', {}).get('custo', 0),
            "confianca": analise.get('confianca', 0)
        }

        # ================================================================
        # RESULTADO FINAL
        # ================================================================
        resultado["sucesso"] = True
        resultado["modo"] = "CURADOR+ANALISTA" if precisa_curador else "ANALISTA_DIRETO"
        resultado["analise"] = analise
        resultado["resumo_executivo"] = analise.get('resumo_executivo', '')
        resultado["situacao"] = analise.get('situacao', {})
        resultado["interessado"] = analise.get('interessado', {})
        resultado["pedido"] = analise.get('pedido', {})
        resultado["fluxo"] = analise.get('fluxo', {})
        resultado["alertas"] = analise.get('alertas', [])
        resultado["sugestao"] = analise.get('sugestao', '')

        # Metricas consolidadas
        custo_total = (
            resultado["etapas"].get("curador", {}).get("custo", 0) +
            resultado["etapas"].get("analista", {}).get("custo", 0)
        )

        resultado["metricas"] = {
            "tempo_total_ms": int((time.time() - inicio) * 1000),
            "custo_total_usd": custo_total,
            "docs_original": len(documentos),
            "docs_analisados": analise.get('total_docs_analisados', 0),
            "confianca": analise.get('confianca', 0)
        }

        print(f"   [PIPELINE] OK! Modo: {resultado['modo']} | Custo: ${custo_total:.4f}", file=sys.stderr)

    except Exception as e:
        resultado["erro"] = str(e)
        resultado["sucesso"] = False
        print(f"   [PIPELINE] Erro: {e}", file=sys.stderr)

    return resultado


def formatar_analise_para_contexto(resultado: Dict) -> str:
    """Formata resultado do pipeline para uso como contexto."""
    if not resultado.get('sucesso'):
        return f"Erro no pipeline: {resultado.get('erro')}"

    analise = resultado.get('analise', {})
    situacao = analise.get('situacao', {})
    interessado = analise.get('interessado', {})
    pedido = analise.get('pedido', {})
    fluxo = analise.get('fluxo', {})

    partes = [
        f"NUP: {resultado.get('nup')}",
        "",
        "INTERESSADO:",
        f"  Nome: {interessado.get('nome', 'N/A')}",
        f"  Posto/Cargo: {interessado.get('posto_grad', 'N/A')}",
        f"  Unidade: {interessado.get('unidade', 'N/A')}",
        "",
        "PEDIDO:",
        f"  Tipo: {pedido.get('tipo', 'N/A')}",
        f"  Descricao: {pedido.get('descricao', 'N/A')}",
        f"  Motivo: {pedido.get('motivo', 'N/A')}",
        "",
        "SITUACAO:",
        f"  Status: {situacao.get('status', 'N/A')}",
        f"  Etapa: {situacao.get('etapa_atual', 'N/A')}",
        f"  Proximo: {situacao.get('proximo_passo', 'N/A')}",
        "",
        "FLUXO:",
        f"  Origem: {fluxo.get('origem', 'N/A')}",
        f"  Destino: {fluxo.get('destino_final', 'N/A')}",
        f"  Caminho: {' -> '.join(fluxo.get('caminho', []))}",
        f"  Atual: {fluxo.get('unidade_atual', 'N/A')}",
        "",
        "RESUMO:",
        analise.get('resumo_executivo', 'N/A'),
        "",
        "ALERTAS:",
        '\n'.join('  - ' + a for a in analise.get('alertas', [])) or '  Nenhum',
    ]

    if analise.get('sugestao'):
        partes.extend(["", "SUGESTAO:", f"  {analise.get('sugestao')}"])

    return '\n'.join(partes)
