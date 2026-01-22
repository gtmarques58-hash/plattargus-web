#!/usr/bin/env python3
"""
Teste da Heurística Leve com dados reais do detalhar-service.

Uso:
    python3 teste_heuristica_leve.py /path/para/raw/job_id.json
    
Ou para testar com o último job:
    python3 teste_heuristica_leve.py --ultimo
"""

import sys
import json
import os
from pathlib import Path

# Adicionar o diretório do pipeline ao path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from heuristica_leve import (
    processar_heuristica_leve, 
    gerar_resumo_para_curador,
    get_titulo,
    get_doc_id,
)

# Caminhos padrão
RAW_PATH = "/root/secretario-sei/data/detalhar/raw"
HEUR_PATH = "/root/secretario-sei/data/detalhar/heur_v2"


def carregar_dados_raw(caminho: str) -> dict:
    """Carrega JSON do arquivo raw extraído pelo Playwright."""
    with open(caminho, 'r', encoding='utf-8') as f:
        return json.load(f)


def encontrar_ultimo_job(base_path: str = RAW_PATH) -> str:
    """Encontra o arquivo raw mais recente."""
    raw_dir = Path(base_path)
    if not raw_dir.exists():
        raise FileNotFoundError(f"Diretório {base_path} não existe")
    
    arquivos = list(raw_dir.glob("*.json"))
    if not arquivos:
        raise FileNotFoundError(f"Nenhum arquivo JSON em {base_path}")
    
    arquivos.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    return str(arquivos[0])


def imprimir_resultado(resultado: dict):
    """Imprime resultado formatado."""
    print("\n" + "=" * 60)
    print("RESULTADO HEURÍSTICA LEVE v2.0")
    print("=" * 60)
    
    print(f"\n📋 NUP: {resultado['nup']}")
    print(f"✅ Sucesso: {resultado['sucesso']}")
    
    if resultado.get('erro'):
        print(f"❌ Erro: {resultado['erro']}")
        return
    
    metricas = resultado['metricas']
    print(f"\n📊 MÉTRICAS:")
    print(f"   • Docs originais: {metricas['total_original']}")
    print(f"   • Após dedup: {metricas['total_apos_dedup']}")
    print(f"   • Após agrupamento: {metricas['total_apos_agrupamento']}")
    print(f"   • Duplicados removidos: {metricas['duplicados_removidos']}")
    print(f"   • Total caracteres: {metricas['total_chars']:,}")
    print(f"   • Total anexos agrupados: {metricas['total_anexos']}")
    
    print(f"\n🎯 PRIORIDADES:")
    for prio, qtd in metricas['contagem_prioridade'].items():
        emoji = {"ALTA": "🔴", "MEDIA": "🟡", "BAIXA": "🟢"}.get(prio, "⚪")
        print(f"   {emoji} {prio}: {qtd}")
    
    print(f"\n📁 TIPOS IDENTIFICADOS:")
    for tipo, qtd in metricas['contagem_tipo'].items():
        print(f"   • {tipo}: {qtd}")
    
    decisao = resultado['decisao']
    print(f"\n🔀 DECISÃO DE FLUXO:")
    print(f"   • Fluxo escolhido: {decisao['fluxo']}")
    print(f"   • Precisa Curador: {metricas['precisa_curador']}")
    if metricas.get('motivo_curador'):
        print(f"   • Motivo: {metricas['motivo_curador']}")
    
    print(f"\n📄 DOCUMENTOS CLASSIFICADOS:")
    print("-" * 60)
    for doc in resultado['documentos']:
        c = doc['classificacao']
        emoji = {"ALTA": "🔴", "MEDIA": "🟡", "BAIXA": "🟢"}.get(c['prioridade'], "⚪")
        
        titulo = get_titulo(doc)[:50]
        tipo = doc.get('_tipo_normalizado', 'N/A')
        sigla = doc.get('_sigla_normalizada', 'N/A')
        
        anexos = len(doc.get('anexos', []))
        anexos_str = f" +{anexos} anexos" if anexos > 0 else ""
        
        print(f"{emoji} [{c['prioridade']:5}] {tipo:15} | {sigla:15} | {c['tipo']}")
        print(f"   └─ {titulo}...{anexos_str}")
        print(f"   └─ Motivo: {c['motivo']}")
        print()


def imprimir_resumo_curador(resumo: dict):
    """Imprime resumo formatado para o Curador."""
    print("\n" + "=" * 60)
    print("RESUMO PARA CURADOR (sem conteúdo)")
    print("=" * 60)
    
    print(f"\nNUP: {resumo['nup']}")
    print(f"Total docs: {resumo['total_docs']}")
    print(f"Total chars: {resumo['total_chars']:,}")
    
    print(f"\nEstrutura: {resumo['resumo_estrutural']}")
    
    print(f"\nDOCUMENTOS:")
    for d in resumo['documentos']:
        emoji = {"ALTA": "🔴", "MEDIA": "🟡", "BAIXA": "🟢"}.get(d['prioridade'], "⚪")
        print(f"{emoji} {d['posicao']:2}. {d['tipo']:15} | {d['sigla']:15} | {d['chars']:,} chars")


def main():
    if len(sys.argv) < 2:
        print("Uso: python3 teste_heuristica_leve.py <arquivo.json>")
        print("  ou: python3 teste_heuristica_leve.py --ultimo")
        sys.exit(1)
    
    arg = sys.argv[1]
    
    if arg == "--ultimo":
        try:
            caminho = encontrar_ultimo_job()
            print(f"📂 Usando último arquivo: {caminho}")
        except FileNotFoundError as e:
            print(f"❌ Erro: {e}")
            sys.exit(1)
    else:
        caminho = arg
    
    if not os.path.exists(caminho):
        print(f"❌ Arquivo não encontrado: {caminho}")
        sys.exit(1)
    
    print(f"📂 Carregando: {caminho}")
    dados = carregar_dados_raw(caminho)
    
    # Extrair documentos
    documentos = dados.get('documentos', [])
    nup = dados.get('nup', 'N/A')
    
    print(f"📋 NUP: {nup}")
    print(f"📄 Documentos encontrados: {len(documentos)}")
    
    # Processar
    resultado = processar_heuristica_leve(documentos, nup)
    
    # Imprimir resultado
    imprimir_resultado(resultado)
    
    # Se precisar de curador, mostrar resumo
    if resultado['metricas']['precisa_curador']:
        resumo = gerar_resumo_para_curador(resultado)
        imprimir_resumo_curador(resumo)
    
    # Salvar resultado
    job_id = os.path.basename(caminho).replace('.json', '')
    output_path = os.path.join(HEUR_PATH, f"{job_id}_heur.json")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(resultado, f, ensure_ascii=False, indent=2)
    
    print(f"\n💾 Resultado salvo em: {output_path}")


if __name__ == "__main__":
    main()
