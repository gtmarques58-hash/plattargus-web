"""
Configuracao do Pipeline v2.0 - Standalone para FastAPI
"""
import os

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
USAR_LLM = os.getenv("USAR_LLM", "true").lower() == "true"

MODELO_CURADOR = "gpt-4o-mini"
MODELO_ANALISTA = "gpt-4.1-mini"

# Limites para decidir se precisa curador
LIMITE_DOCS_DIRETO = 10
LIMITE_CHARS_DIRETO = 120000

def get_openai_key():
    if not OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY nao configurada")
    return OPENAI_API_KEY
