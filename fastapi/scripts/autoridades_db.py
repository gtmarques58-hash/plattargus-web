#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
autoridades_db.py - Banco de Autoridades do ARGUS

Substitui o Google Sheets para consulta de autoridades/diretores.

Estrutura:
- Chave_busca: identificador único (ex: "DEI", "DRH", "COMANDANTE")
- Unidade_Destino: nome completo da unidade
- Sigla_Unidade: sigla
- Posto_Grad: posto/graduação (MAJ, TC, CEL, etc)
- Nome_Atual: nome do titular atual
- Matricula: matrícula do servidor (opcional, para consulta rápida)
- Efetivo: número de efetivo do setor (opcional)

Uso:
    from autoridades_db import AutoridadesDB
    
    db = AutoridadesDB()
    
    # Buscar autoridade
    autoridade = db.buscar("DEI")
    # Retorna: {'posto_grad': 'MAJ', 'nome': 'FELIPE CARNEIRO', ...}
    
    # Para usar em minutas
    destinatario = db.formatar_destinatario("DEI")
    # Retorna: "MAJ QOBM FELIPE CARNEIRO - Diretor de Ensino e Instrução"
"""

import os
import sys
import sqlite3
import json
from datetime import datetime
from typing import Optional, List, Dict, Tuple
from pathlib import Path


# =============================================================================
# CONFIGURAÇÃO
# =============================================================================

DB_PATH = os.getenv("ARGUS_AUTORIDADES_DB", "/data/argus_autoridades.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS autoridades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chave_busca TEXT UNIQUE NOT NULL,
    unidade_destino TEXT NOT NULL,
    sigla_unidade TEXT,
    posto_grad TEXT,
    nome_atual TEXT NOT NULL,
    matricula TEXT,
    efetivo INTEGER,
    email TEXT,
    telefone TEXT,
    observacoes TEXT,
    ativo INTEGER DEFAULT 1,
    criado_em TEXT NOT NULL,
    atualizado_em TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chave ON autoridades(chave_busca);
CREATE INDEX IF NOT EXISTS idx_sigla ON autoridades(sigla_unidade);
CREATE INDEX IF NOT EXISTS idx_ativo ON autoridades(ativo);

-- Tabela de histórico (quem ocupou o cargo antes)
CREATE TABLE IF NOT EXISTS autoridades_historico (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chave_busca TEXT NOT NULL,
    posto_grad TEXT,
    nome TEXT NOT NULL,
    matricula TEXT,
    data_inicio TEXT,
    data_fim TEXT,
    criado_em TEXT NOT NULL
);
"""


# =============================================================================
# CLASSE PRINCIPAL
# =============================================================================

class AutoridadesDB:
    """Gerenciador de autoridades com SQLite."""
    
    def __init__(self, db_path: str = None):
        self.db_path = db_path or DB_PATH
        self._ensure_db_exists()
    
    def _ensure_db_exists(self):
        """Cria o banco e tabelas se não existirem."""
        db_dir = os.path.dirname(self.db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
        
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(SCHEMA)
            conn.commit()
    
    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def _row_to_dict(self, row: sqlite3.Row) -> Dict:
        if not row:
            return None
        d = dict(row)
        if 'ativo' in d:
            d['ativo'] = bool(d['ativo'])
        return d
    
    # =========================================================================
    # CRUD
    # =========================================================================
    
    def cadastrar(
        self,
        chave_busca: str,
        unidade_destino: str,
        nome_atual: str,
        sigla_unidade: str = None,
        posto_grad: str = None,
        matricula: str = None,
        efetivo: int = None,
        email: str = None,
        telefone: str = None,
        observacoes: str = None
    ) -> Dict:
        """
        Cadastra uma nova autoridade/unidade.
        
        Args:
            chave_busca: Identificador único (ex: "DEI", "COMANDANTE")
            unidade_destino: Nome completo (ex: "Diretoria de Ensino e Instrução")
            nome_atual: Nome do titular
            sigla_unidade: Sigla (ex: "DEI")
            posto_grad: Posto/graduação (ex: "MAJ QOBM")
            matricula: Matrícula do servidor
            efetivo: Número de efetivo do setor
        """
        agora = datetime.now().isoformat()
        chave = chave_busca.upper().strip()
        
        with self._get_connection() as conn:
            cursor = conn.execute("""
                INSERT INTO autoridades (
                    chave_busca, unidade_destino, sigla_unidade, posto_grad,
                    nome_atual, matricula, efetivo, email, telefone,
                    observacoes, criado_em, atualizado_em
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                chave,
                unidade_destino.strip(),
                (sigla_unidade or "").strip() or None,
                (posto_grad or "").strip() or None,
                nome_atual.strip(),
                (matricula or "").strip() or None,
                efetivo,
                (email or "").strip() or None,
                (telefone or "").strip() or None,
                observacoes,
                agora,
                agora
            ))
            conn.commit()
            return self.buscar(chave)
    
    def atualizar(self, chave_busca: str, **campos) -> bool:
        """
        Atualiza campos de uma autoridade.
        Salva o titular anterior no histórico antes de atualizar.
        """
        chave = chave_busca.upper().strip()
        
        # Campos permitidos
        campos_permitidos = {
            'unidade_destino', 'sigla_unidade', 'posto_grad', 'nome_atual',
            'matricula', 'efetivo', 'email', 'telefone', 'observacoes', 'ativo'
        }
        
        campos_update = {k: v for k, v in campos.items() if k in campos_permitidos}
        if not campos_update:
            return False
        
        # Se está atualizando o titular, salva histórico
        if 'nome_atual' in campos_update:
            atual = self.buscar(chave)
            if atual and atual.get('nome_atual'):
                self._salvar_historico(
                    chave,
                    atual.get('posto_grad'),
                    atual.get('nome_atual'),
                    atual.get('matricula')
                )
        
        campos_update['atualizado_em'] = datetime.now().isoformat()
        
        set_clause = ', '.join(f"{k} = ?" for k in campos_update.keys())
        values = list(campos_update.values()) + [chave]
        
        with self._get_connection() as conn:
            cursor = conn.execute(f"""
                UPDATE autoridades SET {set_clause} WHERE chave_busca = ?
            """, values)
            conn.commit()
            return cursor.rowcount > 0
    
    def _salvar_historico(self, chave: str, posto: str, nome: str, matricula: str):
        """Salva registro no histórico."""
        agora = datetime.now().isoformat()
        
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO autoridades_historico (
                    chave_busca, posto_grad, nome, matricula, data_fim, criado_em
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (chave, posto, nome, matricula, agora, agora))
            conn.commit()
    
    def deletar(self, chave_busca: str) -> bool:
        """Remove uma autoridade permanentemente."""
        chave = chave_busca.upper().strip()
        
        with self._get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM autoridades WHERE chave_busca = ?", (chave,)
            )
            conn.commit()
            return cursor.rowcount > 0
    
    # =========================================================================
    # CONSULTAS
    # =========================================================================
    
    def buscar(self, chave_busca: str) -> Optional[Dict]:
        """
        Busca autoridade por chave.
        
        Args:
            chave_busca: "DEI", "DRH", "COMANDANTE", etc.
        
        Returns:
            Dict com dados da autoridade ou None
        """
        chave = chave_busca.upper().strip()
        
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM autoridades WHERE chave_busca = ? AND ativo = 1",
                (chave,)
            )
            row = cursor.fetchone()
            return self._row_to_dict(row)
    
    def buscar_por_sigla(self, sigla: str) -> Optional[Dict]:
        """Busca por sigla da unidade."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM autoridades WHERE sigla_unidade = ? AND ativo = 1",
                (sigla.upper().strip(),)
            )
            row = cursor.fetchone()
            return self._row_to_dict(row)
    
    def buscar_por_nome(self, nome: str) -> List[Dict]:
        """Busca autoridades que contenham o nome (parcial)."""
        with self._get_connection() as conn:
            cursor = conn.execute("""
                SELECT * FROM autoridades 
                WHERE nome_atual LIKE ? AND ativo = 1
                ORDER BY chave_busca
            """, (f"%{nome}%",))
            return [self._row_to_dict(row) for row in cursor.fetchall()]
    
    def listar_todas(self, apenas_ativas: bool = True) -> List[Dict]:
        """Lista todas as autoridades."""
        with self._get_connection() as conn:
            if apenas_ativas:
                cursor = conn.execute(
                    "SELECT * FROM autoridades WHERE ativo = 1 ORDER BY chave_busca"
                )
            else:
                cursor = conn.execute("SELECT * FROM autoridades ORDER BY chave_busca")
            
            return [self._row_to_dict(row) for row in cursor.fetchall()]
    
    def historico(self, chave_busca: str) -> List[Dict]:
        """Retorna histórico de titulares de uma unidade."""
        chave = chave_busca.upper().strip()
        
        with self._get_connection() as conn:
            cursor = conn.execute("""
                SELECT * FROM autoridades_historico 
                WHERE chave_busca = ?
                ORDER BY data_fim DESC
            """, (chave,))
            return [dict(row) for row in cursor.fetchall()]
    
    # =========================================================================
    # FORMATAÇÃO PARA MINUTAS
    # =========================================================================
    
    def formatar_destinatario(self, chave_busca: str, formato: str = "completo") -> str:
        """
        Formata o destinatário para uso em minutas.
        
        Args:
            chave_busca: "DEI", "DRH", etc.
            formato: "completo", "nome", "cargo"
        
        Returns:
            String formatada para minuta
        
        Exemplos:
            formato="completo" → "MAJ QOBM FELIPE CARNEIRO - Diretor de Ensino e Instrução"
            formato="nome" → "MAJ QOBM FELIPE CARNEIRO"
            formato="cargo" → "Diretor de Ensino e Instrução"
        """
        autoridade = self.buscar(chave_busca)
        
        if not autoridade:
            return f"[AUTORIDADE NÃO ENCONTRADA: {chave_busca}]"
        
        posto = autoridade.get('posto_grad') or ""
        nome = autoridade.get('nome_atual') or ""
        unidade = autoridade.get('unidade_destino') or ""
        
        if formato == "nome":
            return f"{posto} {nome}".strip()
        
        elif formato == "cargo":
            return unidade
        
        else:  # completo
            nome_completo = f"{posto} {nome}".strip()
            if unidade:
                return f"{nome_completo} - {unidade}"
            return nome_completo
    
    def obter_dados_minuta(self, chave_busca: str) -> Dict:
        """
        Retorna dados formatados para preencher template de minuta.
        
        Returns:
            Dict com campos prontos para uso em templates
        """
        autoridade = self.buscar(chave_busca)
        
        if not autoridade:
            return {
                'DESTINATARIO': f"[NÃO ENCONTRADO: {chave_busca}]",
                'NOME_COMPLETO': "",
                'POSTO_GRAD': "",
                'UNIDADE': "",
                'SIGLA': chave_busca.upper(),
                'EFETIVO': "",
                'encontrado': False
            }
        
        posto = autoridade.get('posto_grad') or ""
        nome = autoridade.get('nome_atual') or ""
        
        return {
            'DESTINATARIO': self.formatar_destinatario(chave_busca),
            'NOME_COMPLETO': f"{posto} {nome}".strip(),
            'POSTO_GRAD': posto,
            'NOME': nome,
            'UNIDADE': autoridade.get('unidade_destino') or "",
            'SIGLA': autoridade.get('sigla_unidade') or chave_busca.upper(),
            'EFETIVO': str(autoridade.get('efetivo') or ""),
            'MATRICULA': autoridade.get('matricula') or "",
            'EMAIL': autoridade.get('email') or "",
            'TELEFONE': autoridade.get('telefone') or "",
            'encontrado': True
        }
    
    # =========================================================================
    # IMPORTAÇÃO EM MASSA
    # =========================================================================
    
    def importar_csv(self, csv_path: str, delimitador: str = ",") -> Dict:
        """
        Importa autoridades de um arquivo CSV.
        
        Formato esperado (cabeçalho):
        Chave_busca,Unidade_Destino,Sigla_Unidade,Posto_Grad,Nome_Atual,Matricula,Efetivo
        
        Returns:
            Dict com estatísticas da importação
        """
        import csv
        
        stats = {'importados': 0, 'atualizados': 0, 'erros': 0, 'detalhes': []}
        
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f, delimiter=delimitador)
            
            for row in reader:
                try:
                    chave = row.get('Chave_busca', '').strip()
                    if not chave:
                        continue
                    
                    # Verifica se já existe
                    existente = self.buscar(chave)
                    
                    if existente:
                        # Atualiza
                        self.atualizar(
                            chave,
                            unidade_destino=row.get('Unidade_Destino', ''),
                            sigla_unidade=row.get('Sigla_Unidade', ''),
                            posto_grad=row.get('Posto_Grad', ''),
                            nome_atual=row.get('Nome_Atual', ''),
                            matricula=row.get('Matricula', ''),
                            efetivo=int(row.get('Efetivo') or 0) if row.get('Efetivo') else None
                        )
                        stats['atualizados'] += 1
                    else:
                        # Cadastra novo
                        self.cadastrar(
                            chave_busca=chave,
                            unidade_destino=row.get('Unidade_Destino', ''),
                            sigla_unidade=row.get('Sigla_Unidade', ''),
                            posto_grad=row.get('Posto_Grad', ''),
                            nome_atual=row.get('Nome_Atual', ''),
                            matricula=row.get('Matricula', ''),
                            efetivo=int(row.get('Efetivo') or 0) if row.get('Efetivo') else None
                        )
                        stats['importados'] += 1
                
                except Exception as e:
                    stats['erros'] += 1
                    stats['detalhes'].append(f"Erro em '{chave}': {e}")
        
        return stats
    
    def exportar_csv(self, csv_path: str) -> int:
        """
        Exporta autoridades para CSV.
        
        Returns:
            Número de registros exportados
        """
        import csv
        
        autoridades = self.listar_todas(apenas_ativas=False)
        
        if not autoridades:
            return 0
        
        campos = [
            'Chave_busca', 'Unidade_Destino', 'Sigla_Unidade', 
            'Posto_Grad', 'Nome_Atual', 'Matricula', 'Efetivo'
        ]
        
        with open(csv_path, 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=campos)
            writer.writeheader()
            
            for a in autoridades:
                writer.writerow({
                    'Chave_busca': a.get('chave_busca', ''),
                    'Unidade_Destino': a.get('unidade_destino', ''),
                    'Sigla_Unidade': a.get('sigla_unidade', ''),
                    'Posto_Grad': a.get('posto_grad', ''),
                    'Nome_Atual': a.get('nome_atual', ''),
                    'Matricula': a.get('matricula', ''),
                    'Efetivo': a.get('efetivo', '')
                })
        
        return len(autoridades)


# =============================================================================
# CLI
# =============================================================================

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Gerenciamento de Autoridades ARGUS")
    subparsers = parser.add_subparsers(dest="comando", help="Comandos disponíveis")
    
    # Listar
    sub = subparsers.add_parser("listar", help="Lista autoridades")
    sub.add_argument("--todas", action="store_true", help="Incluir inativas")
    
    # Buscar
    sub = subparsers.add_parser("buscar", help="Busca autoridade")
    sub.add_argument("chave", help="Chave de busca (ex: DEI)")
    
    # Cadastrar
    sub = subparsers.add_parser("cadastrar", help="Cadastra autoridade")
    sub.add_argument("chave", help="Chave de busca")
    sub.add_argument("unidade", help="Nome da unidade")
    sub.add_argument("nome", help="Nome do titular")
    sub.add_argument("--sigla", help="Sigla da unidade")
    sub.add_argument("--posto", help="Posto/graduação")
    sub.add_argument("--matricula", help="Matrícula")
    sub.add_argument("--efetivo", type=int, help="Efetivo do setor")
    
    # Atualizar titular
    sub = subparsers.add_parser("atualizar", help="Atualiza titular")
    sub.add_argument("chave", help="Chave de busca")
    sub.add_argument("nome", help="Novo nome do titular")
    sub.add_argument("--posto", help="Novo posto/graduação")
    sub.add_argument("--matricula", help="Nova matrícula")
    
    # Importar CSV
    sub = subparsers.add_parser("importar", help="Importa de CSV")
    sub.add_argument("arquivo", help="Caminho do arquivo CSV")
    sub.add_argument("--delimitador", default=",", help="Delimitador (default: ,)")
    
    # Exportar CSV
    sub = subparsers.add_parser("exportar", help="Exporta para CSV")
    sub.add_argument("arquivo", help="Caminho do arquivo de saída")
    
    # Formatar para minuta
    sub = subparsers.add_parser("minuta", help="Formata para minuta")
    sub.add_argument("chave", help="Chave de busca")
    sub.add_argument("--formato", choices=["completo", "nome", "cargo"], default="completo")
    
    args = parser.parse_args()
    
    if not args.comando:
        parser.print_help()
        return
    
    db = AutoridadesDB()
    
    if args.comando == "listar":
        autoridades = db.listar_todas(apenas_ativas=not args.todas)
        if not autoridades:
            print("Nenhuma autoridade cadastrada.")
            return
        
        print(f"\n{'Chave':<15} {'Posto':<12} {'Nome':<25} {'Unidade':<30}")
        print("-" * 85)
        for a in autoridades:
            print(f"{a['chave_busca']:<15} {(a['posto_grad'] or ''):<12} {a['nome_atual'][:23]:<25} {(a['unidade_destino'] or '')[:28]:<30}")
    
    elif args.comando == "buscar":
        autoridade = db.buscar(args.chave)
        if autoridade:
            print(json.dumps(autoridade, indent=2, ensure_ascii=False))
        else:
            print(f"❌ Autoridade '{args.chave}' não encontrada")
    
    elif args.comando == "cadastrar":
        try:
            resultado = db.cadastrar(
                chave_busca=args.chave,
                unidade_destino=args.unidade,
                nome_atual=args.nome,
                sigla_unidade=args.sigla,
                posto_grad=args.posto,
                matricula=args.matricula,
                efetivo=args.efetivo
            )
            print(f"✅ Autoridade '{args.chave}' cadastrada!")
            print(json.dumps(resultado, indent=2, ensure_ascii=False))
        except sqlite3.IntegrityError:
            print(f"❌ Chave '{args.chave}' já existe")
    
    elif args.comando == "atualizar":
        campos = {'nome_atual': args.nome}
        if args.posto:
            campos['posto_grad'] = args.posto
        if args.matricula:
            campos['matricula'] = args.matricula
        
        if db.atualizar(args.chave, **campos):
            print(f"✅ Autoridade '{args.chave}' atualizada!")
        else:
            print(f"❌ Autoridade '{args.chave}' não encontrada")
    
    elif args.comando == "importar":
        stats = db.importar_csv(args.arquivo, args.delimitador)
        print(f"✅ Importação concluída:")
        print(f"   Novos: {stats['importados']}")
        print(f"   Atualizados: {stats['atualizados']}")
        print(f"   Erros: {stats['erros']}")
        if stats['detalhes']:
            for d in stats['detalhes']:
                print(f"   ⚠ {d}")
    
    elif args.comando == "exportar":
        total = db.exportar_csv(args.arquivo)
        print(f"✅ {total} autoridades exportadas para {args.arquivo}")
    
    elif args.comando == "minuta":
        texto = db.formatar_destinatario(args.chave, args.formato)
        print(texto)


    # ============================================================
    # TABELA DE ALIASES (SINÔNIMOS DE UNIDADES)
    # ============================================================
    
    ALIASES = {
        # COMANDO GERAL
        "CMDGER": ["CMDGER", "COMANDO GERAL", "COMANDANTE GERAL", "CG", "COMANDANTE", "CMD GERAL"],
        "SUBCMD": ["SUBCMD", "SUBCOMANDO", "SUBCOMANDANTE", "SUBCOMANDO GERAL", "SUB COMANDO", "SUB CMD"],
        
        # COMANDOS OPERACIONAIS
        "COC": ["COC", "COMANDO OPERACIONAL DA CAPITAL", "OPERACIONAL CAPITAL", "CMD OPERACIONAL CAPITAL"],
        "COI": ["COI", "COMANDO OPERACIONAL DO INTERIOR", "OPERACIONAL INTERIOR", "CMD OPERACIONAL INTERIOR"],
        "COA": ["COA", "COMANDO DE OPERACOES AEREAS", "OPERACOES AEREAS", "CMD AEREO"],
        "GOA": ["GOA", "GRUPAMENTO DE OPERACOES AEREAS", "1 GRUPAMENTO AEREO", "GRUPAMENTO AEREO"],
        
        # BATALHOES
        "1BEPCIF": ["1BEPCIF", "PRIMEIRO BATALHAO", "1 BATALHAO", "1 BEPCIF", "1BEP"],
        "2BEPCIF": ["2BEPCIF", "SEGUNDO BATALHAO", "2 BATALHAO", "2 BEPCIF", "2BEP"],
        "3BEPCIF": ["3BEPCIF", "TERCEIRO BATALHAO", "3 BATALHAO", "3 BEPCIF", "3BEP"],
        "4BEPCIF": ["4BEPCIF", "QUARTO BATALHAO", "4 BATALHAO", "4 BEPCIF", "4BEP"],
        "5BEPCIF": ["5BEPCIF", "QUINTO BATALHAO", "5 BATALHAO", "5 BEPCIF", "5BEP"],
        "6BEPCIF": ["6BEPCIF", "SEXTO BATALHAO", "6 BATALHAO", "6 BEPCIF", "6BEP"],
        "7BEPCIF": ["7BEPCIF", "SETIMO BATALHAO", "7 BATALHAO", "7 BEPCIF", "7BEP"],
        "8BEPCIF": ["8BEPCIF", "OITAVO BATALHAO", "8 BATALHAO", "8 BEPCIF", "8BEP"],
        "9BEPCIF": ["9BEPCIF", "NONO BATALHAO", "9 BATALHAO", "9 BEPCIF", "9BEP"],
        
        # DIRETORIAS
        "DRH": ["DRH", "RECURSOS HUMANOS", "DIRETORIA DE RH", "DIRETORIA DE RECURSOS HUMANOS"],
        "DEI": ["DEI", "DIRETORIA DE ENSINO", "ENSINO E INSTRUCAO", "DIRETORIA DE ENSINO E INSTRUCAO", "ENSINO"],
        "DLPF": ["DLPF", "DIRETORIA DE LOGISTICA", "LOGISTICA PATRIMONIO E FINANCAS", "LOGISTICA", "DAL"],
        "DSAU": ["DSAU", "DS", "DIRETORIA DE SAUDE", "SAUDE"],
        "DATOP": ["DATOP", "DIRETORIA DE ATIVIDADES TECNICAS", "ATIVIDADES TECNICAS E OPERACIONAIS"],
        "DPLAN": ["DPLAN", "DIRETORIA DE PLANEJAMENTO", "PLANEJAMENTO"],
        
        # ASSESSORIAS
        "AJGER": ["AJGER", "AJUDANCIA GERAL", "AJUDANCIA"],
        "ASSJUR": ["ASSJUR", "ASSESSORIA JURIDICA", "JURIDICO"],
        "ASCOM": ["ASCOM", "ASSESSORIA DE COMUNICACAO", "COMUNICACAO"],
        "ASSINT": ["ASSINT", "ASSESSORIA DE INTELIGENCIA", "INTELIGENCIA"],
        
        # OUTROS
        "CORGER": ["CORGER", "CORREGEDORIA", "CORREGEDOR"],
        "CNTINT": ["CNTINT", "CONTROLADORIA INTERNA", "CONTROLADORIA"],
        "DEPTIC": ["DEPTIC", "TECNOLOGIA DA INFORMACAO", "TI", "TIC", "INFORMATICA"],
        "CEMAN": ["CEMAN", "CENTRO DE MANUTENCAO", "MANUTENCAO"],
    }


if __name__ == "__main__":
    main()
