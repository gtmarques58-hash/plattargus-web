#!/usr/bin/env python3
"""
decrypt_laravel.py - Descriptografa senhas do Laravel (AES-256-GCM)
"""
import os
import base64
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

def get_master_key_bytes() -> bytes:
    """Obtém a chave mestra como bytes (32 bytes para AES-256)."""
    key = os.getenv("ARGUS_MASTER_KEY", "")
    if not key:
        raise ValueError("ARGUS_MASTER_KEY não definida")
    
    # A chave pode ser base64 ou hex
    try:
        # Tenta base64 primeiro
        key_bytes = base64.b64decode(key)
        if len(key_bytes) == 32:
            return key_bytes
    except:
        pass
    
    # Tenta hex
    try:
        key_bytes = bytes.fromhex(key)
        if len(key_bytes) == 32:
            return key_bytes
    except:
        pass
    
    # Tenta usar diretamente (padding se necessário)
    key_bytes = key.encode('utf-8')
    if len(key_bytes) < 32:
        key_bytes = key_bytes.ljust(32, b'\0')
    return key_bytes[:32]


def decrypt_laravel_aes_gcm(cipher: bytes, iv: bytes, tag: bytes) -> str:
    """
    Descriptografa senha do Laravel usando AES-256-GCM.
    
    Args:
        cipher: Ciphertext (bytea do PostgreSQL)
        iv: Initialization Vector (bytea)
        tag: Authentication Tag (bytea)
    
    Returns:
        Senha em texto plano
    """
    key = get_master_key_bytes()
    aesgcm = AESGCM(key)
    
    # AES-GCM espera: nonce + ciphertext com tag anexada
    # Laravel armazena tag separadamente, então concatenamos
    ciphertext_with_tag = cipher + tag
    
    plaintext = aesgcm.decrypt(iv, ciphertext_with_tag, None)
    return plaintext.decode('utf-8')


if __name__ == "__main__":
    # Teste
    print("Módulo de descriptografia Laravel carregado")
