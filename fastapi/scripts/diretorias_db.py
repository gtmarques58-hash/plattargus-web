#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
diretorias_db.py - Gerenciamento de diretorias do ARGUS

Banco SQLite com credenciais criptografadas para cada diretoria.

Uso:
    from diretorias_db import DiretoriasDB
    
    db = DiretoriasDB()
    
    # Cadastrar diretoria
    db.cadastrar("DRH", "Diretoria de RH", "-1001234567890", "gilmar.moura", "senha123")
    
    # Buscar por chat_id
    diretoria = db.buscar_por_chat_id("-1001234567890")
    
    # Obter credenciais (descriptografadas)
    user, senha = db.obter_credenciais("DRH")
"""

import os
import sys
import sqlite3
import json
from datetime import datetime
from typing import Optional, List, Dict, Tuple
from pathlib import Path

from crypto_utils import encrypt_password, decrypt_password, mask_password


# =============================================================================
# CONFIGURAÇÃO
# =============================================================================

# Caminho do banco de dados
DB_PATH = os.getenv("ARGUS_DB_PATH", "/data/argus_diretorias.db")

# Schema da tabela
SCHEMA = """
CREATE TABLE IF NOT EXISTS diretorias (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sigla TEXT UNIQUE NOT NULL,
    nome TEXT NOT NULL,
    telegram_chat_id TEXT UNIQUE NOT NULL,
    sei_usuario TEXT NOT NULL,
    sei_senha_encrypted TEXT NOT NULL,
    sei_orgao_id TEXT DEFAULT '31',
    ativo INTEGER DEFAULT 1,
    admin_chat_ids TEXT DEFAULT '[]',
    criado_em TEXT NOT NULL,
    atualizado_em TEXT NOT NULL,
    ultimo_login_em TEXT,
    total_logins INTEGER DEFAULT 0,
    observacoes TEXT
);

CREATE INDEX IF NOT EXISTS idx_chat_id ON diretorias(telegram_chat_id);
CREATE INDEX IF NOT EXISTS idx_sigla ON diretorias(sigla);
CREATE INDEX IF NOT EXISTS idx_ativo ON diretorias(ativo);
"""


# =============================================================================
# CLASSE PRINCIPAL
# =============================================================================

class DiretoriasDB:
    """Gerenciador de diretorias com SQLite."""
    
    def __init__(self, db_path: str = None):
        """
        Inicializa o banco de dados.
        
        Args:
            db_path: Caminho do arquivo SQLite (default: /data/argus_diretorias.db)
        """
        self.db_path = db_path or DB_PATH
        self._ensure_db_exists()
    
    def _ensure_db_exists(self):
        """Cria o banco e tabelas se não existirem."""
        # Cria diretório se necessário
        db_dir = os.path.dirname(self.db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
        
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(SCHEMA)
            conn.commit()
    
    def _get_connection(self) -> sqlite3.Connection:
        """Retorna conexão com row_factory para dict."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    # =========================================================================
    # CRUD
    # =========================================================================
    
    def cadastrar(
        self,
        sigla: str,
        nome: str,
        telegram_chat_id: str,
        sei_usuario: str,
        sei_senha: str,
        sei_orgao_id: str = "31",
        admin_chat_ids: List[str] = None,
        observacoes: str = None
    ) -> Dict:
        """
        Cadastra uma nova diretoria.
        
        Args:
            sigla: Sigla da diretoria (ex: "DRH", "DEI")
            nome: Nome completo
            telegram_chat_id: ID do chat/grupo do Telegram
            sei_usuario: Usuário do SEI
            sei_senha: Senha do SEI (será criptografada)
            sei_orgao_id: ID do órgão no SEI (default: 31 = CBMAC)
            admin_chat_ids: Lista de chat_ids dos admins
            observacoes: Notas adicionais
        
        Returns:
            Dict com dados da diretoria cadastrada
        """
        agora = datetime.now().isoformat()
        senha_encrypted = encrypt_password(sei_senha)
        admin_json = json.dumps(admin_chat_ids or [])
        
        with self._get_connection() as conn:
            cursor = conn.execute("""
                INSERT INTO diretorias (
                    sigla, nome, telegram_chat_id, sei_usuario, sei_senha_encrypted,
                    sei_orgao_id, admin_chat_ids, observacoes, criado_em, atualizado_em
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                sigla.upper().strip(),
                nome.strip(),
                str(telegram_chat_id).strip(),
                sei_usuario.strip(),
                senha_encrypted,
                sei_orgao_id,
                admin_json,
                observacoes,
                agora,
                agora
            ))
            conn.commit()
            
            return self.buscar_por_sigla(sigla)
    
    def atualizar_senha(self, sigla: str, nova_senha: str) -> bool:
        """
        Atualiza a senha de uma diretoria.
        
        Args:
            sigla: Sigla da diretoria
            nova_senha: Nova senha (será criptografada)
        
        Returns:
            True se atualizou
        """
        agora = datetime.now().isoformat()
        senha_encrypted = encrypt_password(nova_senha)
        
        with self._get_connection() as conn:
            cursor = conn.execute("""
                UPDATE diretorias 
                SET sei_senha_encrypted = ?, atualizado_em = ?
                WHERE sigla = ?
            """, (senha_encrypted, agora, sigla.upper()))
            conn.commit()
            return cursor.rowcount > 0
    
    def atualizar(self, sigla: str, **campos) -> bool:
        """
        Atualiza campos de uma diretoria.
        
        Args:
            sigla: Sigla da diretoria
            **campos: Campos a atualizar (nome, telegram_chat_id, sei_usuario, etc)
        
        Returns:
            True se atualizou
        """
        if not campos:
            return False
        
        # Campos permitidos
        campos_permitidos = {
            'nome', 'telegram_chat_id', 'sei_usuario', 'sei_orgao_id',
            'ativo', 'admin_chat_ids', 'observacoes'
        }
        
        campos_update = {k: v for k, v in campos.items() if k in campos_permitidos}
        if not campos_update:
            return False
        
        # Trata admin_chat_ids como JSON
        if 'admin_chat_ids' in campos_update and isinstance(campos_update['admin_chat_ids'], list):
            campos_update['admin_chat_ids'] = json.dumps(campos_update['admin_chat_ids'])
        
        campos_update['atualizado_em'] = datetime.now().isoformat()
        
        set_clause = ', '.join(f"{k} = ?" for k in campos_update.keys())
        values = list(campos_update.values()) + [sigla.upper()]
        
        with self._get_connection() as conn:
            cursor = conn.execute(f"""
                UPDATE diretorias SET {set_clause} WHERE sigla = ?
            """, values)
            conn.commit()
            return cursor.rowcount > 0
    
    def desativar(self, sigla: str) -> bool:
        """Desativa uma diretoria (soft delete)."""
        return self.atualizar(sigla, ativo=0)
    
    def ativar(self, sigla: str) -> bool:
        """Reativa uma diretoria."""
        return self.atualizar(sigla, ativo=1)
    
    def deletar(self, sigla: str) -> bool:
        """Remove uma diretoria permanentemente."""
        with self._get_connection() as conn:
            cursor = conn.execute("DELETE FROM diretorias WHERE sigla = ?", (sigla.upper(),))
            conn.commit()
            return cursor.rowcount > 0
    
    # =========================================================================
    # CONSULTAS
    # =========================================================================
    
    def _row_to_dict(self, row: sqlite3.Row) -> Dict:
        """Converte Row para dict, parseando JSON."""
        if not row:
            return None
        
        d = dict(row)
        
        # Parse admin_chat_ids
        if 'admin_chat_ids' in d and d['admin_chat_ids']:
            try:
                d['admin_chat_ids'] = json.loads(d['admin_chat_ids'])
            except:
                d['admin_chat_ids'] = []
        
        # Converte ativo para bool
        if 'ativo' in d:
            d['ativo'] = bool(d['ativo'])
        
        return d
    
    def buscar_por_sigla(self, sigla: str) -> Optional[Dict]:
        """Busca diretoria por sigla."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM diretorias WHERE sigla = ?",
                (sigla.upper(),)
            )
            row = cursor.fetchone()
            return self._row_to_dict(row)
    
    def buscar_por_chat_id(self, chat_id: str) -> Optional[Dict]:
        """Busca diretoria pelo chat_id do Telegram."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM diretorias WHERE telegram_chat_id = ? AND ativo = 1",
                (str(chat_id),)
            )
            row = cursor.fetchone()
            return self._row_to_dict(row)

    def buscar_por_usuario(self, sei_usuario: str) -> Optional[Dict]:
        """Busca diretoria pelo usuario SEI."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM diretorias WHERE sei_usuario = ? AND ativo = 1",
                (sei_usuario.strip(),)
            )
            row = cursor.fetchone()
            return self._row_to_dict(row)

    def listar_todas(self, apenas_ativas: bool = True) -> List[Dict]:
        """Lista todas as diretorias."""
        with self._get_connection() as conn:
            if apenas_ativas:
                cursor = conn.execute(
                    "SELECT * FROM diretorias WHERE ativo = 1 ORDER BY sigla"
                )
            else:
                cursor = conn.execute("SELECT * FROM diretorias ORDER BY sigla")
            
            return [self._row_to_dict(row) for row in cursor.fetchall()]
    
    def existe(self, sigla: str) -> bool:
        """Verifica se diretoria existe."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT 1 FROM diretorias WHERE sigla = ?",
                (sigla.upper(),)
            )
            return cursor.fetchone() is not None
    
    # =========================================================================
    # CREDENCIAIS
    # =========================================================================
    
    def obter_credenciais(self, sigla: str) -> Tuple[str, str, str]:
        """
        Obtém credenciais descriptografadas de uma diretoria.
        
        Args:
            sigla: Sigla da diretoria
        
        Returns:
            Tuple (usuario, senha, orgao_id)
        
        Raises:
            ValueError se diretoria não existe ou está inativa
        """
        diretoria = self.buscar_por_sigla(sigla)
        
        if not diretoria:
            raise ValueError(f"Diretoria '{sigla}' não encontrada")
        
        if not diretoria['ativo']:
            raise ValueError(f"Diretoria '{sigla}' está desativada")
        
        usuario = diretoria['sei_usuario']
        senha = decrypt_password(diretoria['sei_senha_encrypted'])
        orgao_id = diretoria['sei_orgao_id']
        
        return usuario, senha, orgao_id
    
    def obter_credenciais_por_chat(self, chat_id: str) -> Tuple[str, str, str, str]:
        """
        Obtém credenciais pela chat_id do Telegram.
        
        Args:
            chat_id: ID do chat do Telegram
        
        Returns:
            Tuple (sigla, usuario, senha, orgao_id)
        
        Raises:
            ValueError se chat não está cadastrado
        """
        diretoria = self.buscar_por_chat_id(chat_id)
        
        if not diretoria:
            raise ValueError(f"Chat '{chat_id}' não está vinculado a nenhuma diretoria")
        
        sigla = diretoria['sigla']
        usuario = diretoria['sei_usuario']
        senha = decrypt_password(diretoria['sei_senha_encrypted'])
        orgao_id = diretoria['sei_orgao_id']
        
        return sigla, usuario, senha, orgao_id
    
    # =========================================================================
    # ESTATÍSTICAS
    # =========================================================================
    
    def registrar_login(self, sigla: str) -> bool:
        """Registra um login bem-sucedido."""
        agora = datetime.now().isoformat()
        
        with self._get_connection() as conn:
            cursor = conn.execute("""
                UPDATE diretorias 
                SET ultimo_login_em = ?, total_logins = total_logins + 1
                WHERE sigla = ?
            """, (agora, sigla.upper()))
            conn.commit()
            return cursor.rowcount > 0
    
    def estatisticas(self) -> Dict:
        """Retorna estatísticas gerais."""
        with self._get_connection() as conn:
            cursor = conn.execute("""
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN ativo = 1 THEN 1 ELSE 0 END) as ativas,
                    SUM(total_logins) as total_logins
                FROM diretorias
            """)
            row = cursor.fetchone()
            return {
                'total_diretorias': row['total'] or 0,
                'diretorias_ativas': row['ativas'] or 0,
                'total_logins': row['total_logins'] or 0
            }


# =============================================================================
# CLI
# =============================================================================

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Gerenciamento de diretorias ARGUS")
    subparsers = parser.add_subparsers(dest="comando", help="Comandos disponíveis")
    
    # Listar
    sub_list = subparsers.add_parser("listar", help="Lista diretorias")
    sub_list.add_argument("--todas", action="store_true", help="Incluir inativas")
    
    # Cadastrar
    sub_add = subparsers.add_parser("cadastrar", help="Cadastra diretoria")
    sub_add.add_argument("sigla", help="Sigla (ex: DRH)")
    sub_add.add_argument("nome", help="Nome completo")
    sub_add.add_argument("chat_id", help="Chat ID do Telegram")
    sub_add.add_argument("usuario", help="Usuário SEI")
    sub_add.add_argument("senha", help="Senha SEI")
    
    # Atualizar senha
    sub_pwd = subparsers.add_parser("senha", help="Atualiza senha")
    sub_pwd.add_argument("sigla", help="Sigla da diretoria")
    sub_pwd.add_argument("nova_senha", help="Nova senha")
    
    # Ver credenciais
    sub_cred = subparsers.add_parser("credenciais", help="Mostra credenciais")
    sub_cred.add_argument("sigla", help="Sigla da diretoria")
    
    # Estatísticas
    subparsers.add_parser("stats", help="Estatísticas")
    
    args = parser.parse_args()
    
    if not args.comando:
        parser.print_help()
        return
    
    db = DiretoriasDB()
    
    if args.comando == "listar":
        diretorias = db.listar_todas(apenas_ativas=not args.todas)
        if not diretorias:
            print("Nenhuma diretoria cadastrada.")
            return
        
        print(f"\n{'Sigla':<8} {'Nome':<30} {'Usuário SEI':<20} {'Ativo':<6}")
        print("-" * 70)
        for d in diretorias:
            status = "✅" if d['ativo'] else "❌"
            print(f"{d['sigla']:<8} {d['nome'][:28]:<30} {d['sei_usuario']:<20} {status}")
    
    elif args.comando == "cadastrar":
        try:
            diretoria = db.cadastrar(
                args.sigla, args.nome, args.chat_id, args.usuario, args.senha
            )
            print(f"✅ Diretoria '{args.sigla}' cadastrada com sucesso!")
        except sqlite3.IntegrityError as e:
            print(f"❌ Erro: Sigla ou Chat ID já existe")
        except Exception as e:
            print(f"❌ Erro: {e}")
    
    elif args.comando == "senha":
        if db.atualizar_senha(args.sigla, args.nova_senha):
            print(f"✅ Senha da '{args.sigla}' atualizada!")
        else:
            print(f"❌ Diretoria '{args.sigla}' não encontrada")
    
    elif args.comando == "credenciais":
        try:
            usuario, senha, orgao = db.obter_credenciais(args.sigla)
            print(f"\nDiretoria: {args.sigla}")
            print(f"Usuário: {usuario}")
            print(f"Senha: {mask_password(senha)}")
            print(f"Órgão ID: {orgao}")
        except ValueError as e:
            print(f"❌ {e}")
    
    elif args.comando == "stats":
        stats = db.estatisticas()
        print(f"\n📊 Estatísticas ARGUS")
        print(f"Total de diretorias: {stats['total_diretorias']}")
        print(f"Diretorias ativas: {stats['diretorias_ativas']}")
        print(f"Total de logins: {stats['total_logins']}")


if __name__ == "__main__":
    main()
