"""
Configuração do Pipeline v2.0
"""
import os
from pathlib import Path

def load_env_file(path):
    if not path.exists():
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ.setdefault(key.strip(), value.strip())

# Tentar carregar .env de vários lugares
for env_path in [Path("/app/.env"), Path("/root/detalhar-service/.env")]:
    if env_path.exists():
        load_env_file(env_path)
        break

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
ARGUS_API_KEY = os.getenv("ARGUS_API_KEY", "")
USAR_LLM = os.getenv("USAR_LLM", "true").lower() == "true"

MODELO_CURADOR = "gpt-4o-mini"
MODELO_ANALISTA = "gpt-4.1-mini"

DATA_DIR = Path("/data/detalhar")
RAW_DIR = DATA_DIR / "raw"
HEUR_DIR = DATA_DIR / "heur_v2"
ANALISE_DIR = DATA_DIR / "analise_v2"

for d in [RAW_DIR, HEUR_DIR, ANALISE_DIR]:
    d.mkdir(parents=True, exist_ok=True)

def get_openai_key():
    if not OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY não configurada")
    return OPENAI_API_KEY
