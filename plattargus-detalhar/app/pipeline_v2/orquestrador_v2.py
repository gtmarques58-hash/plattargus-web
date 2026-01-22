"""
ORQUESTRADOR v2.0 - Pipeline Completo
======================================
Une: Heurística → Curador (se necessário) → Analista
"""

import json
import sys
import time
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime

# path no container

from config import USAR_LLM, ANALISE_DIR
from heuristica_leve import processar_heuristica_leve
from curador_llm import curar_processo
from analista_llm import analisar_processo

# ============================================================================
# CONFIGURAÇÃO
# ============================================================================

LIMITE_DOCS_DIRETO = 10
LIMITE_CHARS_DIRETO = 120000

# ============================================================================
# ORQUESTRADOR
# ============================================================================

def processar_pipeline_v2(
    json_raw: Dict[str, Any],
    usar_llm: bool = True,
    salvar_intermediarios: bool = True
) -> Dict[str, Any]:
    """
    Pipeline completo v2.0
    
    Fluxo:
    1. Heurística Leve (classificação + dedup)
    2. Se docs > 10 ou chars > 120k → Curador (seleciona 8-12)
    3. Analista (gera JSON rico)
    
    Args:
        json_raw: JSON do detalhar_processo.py (com documentos)
        usar_llm: Se False, só faz heurística
        salvar_intermediarios: Salvar JSONs de cada etapa
        
    Returns:
        Dict com análise completa + métricas
    """
    inicio = time.time()
    nup = json_raw.get('nup', 'DESCONHECIDO')
    
    resultado = {
        "nup": nup,
        "sucesso": False,
        "pipeline_v2": True,
        "etapas": {},
        "erro": None
    }
    
    try:
        # ================================================================
        # ETAPA 1: HEURÍSTICA LEVE
        # ================================================================
        t1 = time.time()
        
        documentos = json_raw.get('documentos', [])
        if not documentos:
            resultado["erro"] = "Nenhum documento encontrado"
            return resultado
        
        heur = processar_heuristica_leve(documentos, nup)
        
        resultado["etapas"]["heuristica"] = {
            "tempo_ms": int((time.time() - t1) * 1000),
            "total_docs": len(heur.get('documentos', [])),
            "total_chars": heur.get('metricas', {}).get('total_chars', 0),
            "contagem_prioridade": heur.get('metricas', {}).get('contagem_prioridade', {}),
            "precisa_curador": heur.get('metricas', {}).get('precisa_curador', False)
        }
        
        if salvar_intermediarios:
            _salvar_json(heur, nup, "heur")
        
        if not usar_llm:
            resultado["heuristica"] = heur
            resultado["sucesso"] = True
            resultado["modo"] = "APENAS_HEURISTICA"
            return resultado
        
        # ================================================================
        # ETAPA 2: CURADOR (se necessário)
        # ================================================================
        total_docs = len(heur.get('documentos', []))
        total_chars = heur.get('metricas', {}).get('total_chars', 0)
        precisa_curador = total_docs > LIMITE_DOCS_DIRETO or total_chars > LIMITE_CHARS_DIRETO
        
        heur_para_analista = heur
        
        if precisa_curador:
            t2 = time.time()
            
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
            
            if salvar_intermediarios:
                _salvar_json(curado, nup, "curado")
        else:
            resultado["etapas"]["curador"] = {"pulado": True, "motivo": "docs <= 10 e chars <= 120k"}
        
        # ================================================================
        # ETAPA 3: ANALISTA
        # ================================================================
        t3 = time.time()
        
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
        
        if salvar_intermediarios:
            _salvar_json(analise, nup, "analise")
        
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
        
        # Métricas consolidadas
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
        
    except Exception as e:
        resultado["erro"] = str(e)
        resultado["sucesso"] = False
    
    return resultado


def _salvar_json(data: Dict, nup: str, sufixo: str) -> Optional[Path]:
    """Salva JSON intermediário."""
    try:
        nup_safe = nup.replace("/", "-").replace(" ", "_")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        arquivo = ANALISE_DIR / f"{nup_safe}_{sufixo}.json"
        arquivo.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
        return arquivo
    except:
        return None


def formatar_resumo_para_argus(resultado: Dict) -> str:
    """Formata resultado para o prompt do ARGUS."""
    if not resultado.get('sucesso'):
        return f"❌ Erro no pipeline: {resultado.get('erro')}"
    
    analise = resultado.get('analise', {})
    situacao = analise.get('situacao', {})
    interessado = analise.get('interessado', {})
    pedido = analise.get('pedido', {})
    fluxo = analise.get('fluxo', {})
    
    texto = f"""
============================================================
📋 CONTEXTO PRÉ-PROCESSADO DO PROCESSO
============================================================
NUP: {resultado.get('nup')}

👤 INTERESSADO:
   Nome: {interessado.get('nome', 'N/A')}
   Posto/Cargo: {interessado.get('posto_grad', 'N/A')}
   Unidade: {interessado.get('unidade', 'N/A')}

📋 PEDIDO:
   Tipo: {pedido.get('tipo', 'N/A')}
   Descrição: {pedido.get('descricao', 'N/A')}
   Motivo: {pedido.get('motivo', 'N/A')}

🚦 SITUAÇÃO:
   Status: {situacao.get('status', 'N/A')}
   Etapa: {situacao.get('etapa_atual', 'N/A')}
   Próximo: {situacao.get('proximo_passo', 'N/A')}

🔀 FLUXO:
   Origem: {fluxo.get('origem', 'N/A')}
   Destino: {fluxo.get('destino_final', 'N/A')}
   Caminho: {' → '.join(fluxo.get('caminho', []))}
   Atual: {fluxo.get('unidade_atual', 'N/A')}

📝 RESUMO:
{analise.get('resumo_executivo', 'N/A')}

⚠️ ALERTAS:
{chr(10).join('• ' + a for a in analise.get('alertas', [])) or '• Nenhum'}

============================================================
📊 Pipeline v2.0 | Custo: ${resultado.get('metricas', {}).get('custo_total_usd', 0):.4f}
============================================================
"""
    return texto.strip()


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python orquestrador_v2.py <arquivo_raw.json>")
        sys.exit(1)
    
    with open(sys.argv[1]) as f:
        json_raw = json.load(f)
    
    print(f"🚀 Pipeline v2.0: {json_raw.get('nup')}")
    print(f"📄 Docs: {len(json_raw.get('documentos', []))}")
    print()
    
    resultado = processar_pipeline_v2(json_raw)
    
    if resultado.get('sucesso'):
        print(f"✅ Pipeline OK! Modo: {resultado.get('modo')}")
        print(f"⏱️  Tempo: {resultado['metricas']['tempo_total_ms']}ms")
        print(f"💰 Custo: ${resultado['metricas']['custo_total_usd']:.6f}")
        print()
        print(formatar_resumo_para_argus(resultado))
    else:
        print(f"❌ Erro: {resultado.get('erro')}")
