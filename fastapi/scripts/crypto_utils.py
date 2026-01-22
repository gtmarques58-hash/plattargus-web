#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
crypto_utils.py - Utilitários de criptografia para o ARGUS

Usa Fernet (AES-128-CBC) para criptografar senhas das diretorias.
A chave mestra fica em variável de ambiente (ARGUS_MASTER_KEY).

IMPORTANTE:
- Gere a chave mestra uma vez e guarde em local seguro
- Nunca commite a chave no git
- Se perder a chave, todas as senhas precisam ser recadastradas

Uso:
    # Gerar nova chave mestra (faça isso UMA VEZ)
    python crypto_utils.py --gerar-chave
    
    # Testar criptografia
    python crypto_utils.py --testar
"""

import os
import sys
import base64
import hashlib
from typing import Optional

# Tenta importar cryptography, se não tiver usa implementação básica
try:
    from cryptography.fernet import Fernet, InvalidToken
    HAS_CRYPTOGRAPHY = True
except ImportError:
    HAS_CRYPTOGRAPHY = False
    print("⚠️ Biblioteca 'cryptography' não instalada. Usando fallback básico.", file=sys.stderr)


# =============================================================================
# CONFIGURAÇÃO
# =============================================================================

def get_master_key() -> bytes:
    """
    Obtém a chave mestra do ambiente.
    A chave deve ser uma string base64 de 32 bytes (gerada pelo Fernet).
    """
    key = os.getenv("ARGUS_MASTER_KEY")
    
    if not key:
        raise ValueError(
            "ARGUS_MASTER_KEY não definida!\n"
            "Gere uma chave com: python crypto_utils.py --gerar-chave\n"
            "E adicione ao .env ou docker-compose.yml"
        )
    
    # Valida formato
    try:
        decoded = base64.urlsafe_b64decode(key)
        if len(decoded) != 32:
            raise ValueError("Chave deve ter 32 bytes")
    except Exception as e:
        raise ValueError(f"ARGUS_MASTER_KEY inválida: {e}")
    
    return key.encode() if isinstance(key, str) else key


def generate_master_key() -> str:
    """Gera uma nova chave mestra Fernet (32 bytes, base64)."""
    if HAS_CRYPTOGRAPHY:
        return Fernet.generate_key().decode()
    else:
        # Fallback: gera 32 bytes aleatórios
        import secrets
        return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()


# =============================================================================
# CRIPTOGRAFIA COM FERNET (RECOMENDADO)
# =============================================================================

if HAS_CRYPTOGRAPHY:
    
    def encrypt_password(senha: str) -> str:
        """
        Criptografa uma senha usando Fernet (AES-128-CBC).
        
        Args:
            senha: Senha em texto plano
            
        Returns:
            String criptografada (base64)
        """
        if not senha:
            raise ValueError("Senha não pode ser vazia")
        
        key = get_master_key()
        f = Fernet(key)
        encrypted = f.encrypt(senha.encode('utf-8'))
        return encrypted.decode('utf-8')
    
    
    def decrypt_password(senha_encrypted: str) -> str:
        """
        Descriptografa uma senha.
        
        Args:
            senha_encrypted: String criptografada (base64)
            
        Returns:
            Senha em texto plano
        """
        if not senha_encrypted:
            raise ValueError("Senha criptografada não pode ser vazia")
        
        key = get_master_key()
        f = Fernet(key)
        
        try:
            decrypted = f.decrypt(senha_encrypted.encode('utf-8'))
            return decrypted.decode('utf-8')
        except InvalidToken:
            raise ValueError("Falha ao descriptografar - chave incorreta ou dados corrompidos")


# =============================================================================
# FALLBACK SEM CRYPTOGRAPHY (MENOS SEGURO, MAS FUNCIONA)
# =============================================================================

else:
    import hmac
    
    def _derive_key(master_key: bytes) -> bytes:
        """Deriva uma chave de 32 bytes da master key."""
        return hashlib.sha256(master_key).digest()
    
    def _xor_bytes(data: bytes, key: bytes) -> bytes:
        """XOR simples (NÃO é seguro para produção!)."""
        return bytes(a ^ b for a, b in zip(data, key * (len(data) // len(key) + 1)))
    
    def encrypt_password(senha: str) -> str:
        """Criptografia básica (fallback sem cryptography)."""
        import secrets
        
        key = _derive_key(get_master_key())
        iv = secrets.token_bytes(16)
        
        senha_bytes = senha.encode('utf-8')
        encrypted = _xor_bytes(senha_bytes, key)
        
        # Formato: IV (16 bytes) + encrypted + HMAC (32 bytes)
        mac = hmac.new(key, iv + encrypted, hashlib.sha256).digest()
        result = iv + encrypted + mac
        
        return base64.urlsafe_b64encode(result).decode('utf-8')
    
    def decrypt_password(senha_encrypted: str) -> str:
        """Descriptografia básica (fallback sem cryptography)."""
        key = _derive_key(get_master_key())
        
        data = base64.urlsafe_b64decode(senha_encrypted.encode('utf-8'))
        
        iv = data[:16]
        mac_stored = data[-32:]
        encrypted = data[16:-32]
        
        # Verifica HMAC
        mac_calculated = hmac.new(key, iv + encrypted, hashlib.sha256).digest()
        if not hmac.compare_digest(mac_stored, mac_calculated):
            raise ValueError("Falha ao descriptografar - dados corrompidos")
        
        decrypted = _xor_bytes(encrypted, key)
        return decrypted.decode('utf-8')


# =============================================================================
# FUNÇÕES AUXILIARES
# =============================================================================

def is_encrypted(value: str) -> bool:
    """Verifica se um valor parece estar criptografado (base64 válido)."""
    if not value or len(value) < 20:
        return False
    try:
        decoded = base64.urlsafe_b64decode(value)
        return len(decoded) >= 16  # Mínimo: IV ou dados Fernet
    except Exception:
        return False


def mask_password(senha: str, show_chars: int = 2) -> str:
    """Mascara uma senha para exibição (ex: 'gi****ra')."""
    if not senha:
        return "****"
    if len(senha) <= show_chars * 2:
        return "*" * len(senha)
    return senha[:show_chars] + "*" * (len(senha) - show_chars * 2) + senha[-show_chars:]


# =============================================================================
# CLI
# =============================================================================

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Utilitários de criptografia ARGUS")
    parser.add_argument("--gerar-chave", action="store_true", help="Gera nova chave mestra")
    parser.add_argument("--testar", action="store_true", help="Testa criptografia")
    parser.add_argument("--encrypt", type=str, help="Criptografa uma senha")
    parser.add_argument("--decrypt", type=str, help="Descriptografa uma senha")
    
    args = parser.parse_args()
    
    if args.gerar_chave:
        key = generate_master_key()
        print("=" * 60)
        print("🔐 NOVA CHAVE MESTRA GERADA")
        print("=" * 60)
        print(f"\n{key}\n")
        print("=" * 60)
        print("⚠️  IMPORTANTE:")
        print("1. Guarde esta chave em local SEGURO")
        print("2. Adicione ao .env: ARGUS_MASTER_KEY=" + key)
        print("3. Ou ao docker-compose.yml em environment:")
        print(f"   - ARGUS_MASTER_KEY={key}")
        print("4. NUNCA commite esta chave no git!")
        print("5. Se perder, todas as senhas precisam ser recadastradas")
        print("=" * 60)
        return
    
    if args.testar:
        # Verifica se tem chave
        try:
            key = get_master_key()
            print(f"✅ Chave mestra encontrada")
        except ValueError as e:
            print(f"❌ {e}")
            return
        
        # Testa encrypt/decrypt
        senha_teste = "SenhaT3ste!@#123"
        print(f"\n🔐 Testando com senha: {mask_password(senha_teste)}")
        
        encrypted = encrypt_password(senha_teste)
        print(f"📦 Criptografado: {encrypted[:50]}...")
        
        decrypted = decrypt_password(encrypted)
        print(f"📖 Descriptografado: {mask_password(decrypted)}")
        
        if decrypted == senha_teste:
            print("\n✅ Teste OK! Criptografia funcionando corretamente.")
        else:
            print("\n❌ ERRO! Senha descriptografada não confere.")
        return
    
    if args.encrypt:
        try:
            encrypted = encrypt_password(args.encrypt)
            print(encrypted)
        except Exception as e:
            print(f"Erro: {e}", file=sys.stderr)
            sys.exit(1)
        return
    
    if args.decrypt:
        try:
            decrypted = decrypt_password(args.decrypt)
            print(decrypted)
        except Exception as e:
            print(f"Erro: {e}", file=sys.stderr)
            sys.exit(1)
        return
    
    parser.print_help()


if __name__ == "__main__":
    main()
