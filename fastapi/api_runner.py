#!/usr/bin/env python3
"""
PlattArgus Runner API v3.0
Expõe endpoints para todas as operações SEI
Roda localmente no container do PlattArgus

VERSÃO 3.0 - Suporte completo a todos os scripts + credenciais diretas

Modos suportados:
- detalhar: Analisa processo SEI
- atuar: Atua no processo (despacho)
- assinar: Assina documento individual
- assinar_bloco: Assina todos docs de um bloco
- listar_bloco: Lista documentos de um bloco
- ler_documento: Lê documento para assinatura
- enviar: Envia processo para outra unidade
- atribuir: Atribui processo a servidor
"""

import os
import sys
import json
import subprocess
from typing import Optional, Dict, List
from fastapi import FastAPI, Body
from pydantic import BaseModel

sys.path.insert(0, '/app/scripts')

app = FastAPI(title="PlattArgus Runner API", version="3.0.0")


class RunPayload(BaseModel):
    """Payload unificado para todas as operações."""
    # Modo de operação
    mode: str = "detalhar"
    
    # Identificadores (usados por quase todos)
    nup: Optional[str] = None
    sei_numero: Optional[str] = None  # Número SEI do documento
    numero_bloco: Optional[str] = None  # Número do bloco
    
    # Autenticação LEGADO (Telegram)
    sigla: Optional[str] = None
    chat_id: Optional[str] = None
    
    # Autenticação NOVA (Laravel/PlattArgus WEB)
    credentials: Optional[Dict[str, str]] = None
    # credentials = {
    #   "usuario": "gilmar.moura",
    #   "senha": "xxx",
    #   "orgao_id": "31",
    #   "nome_completo": "Gilmar Moura da Silva",  # Para assinatura
    #   "cargo": "Diretor"  # Para assinatura
    # }
    
    # Parâmetros específicos
    tipo_documento: Optional[str] = None  # atuar
    tipo_processo: Optional[str] = None   # criar_processo
    destinatario: Optional[str] = None    # atuar, enviar
    texto_despacho: Optional[str] = None  # atuar
    apelido: Optional[str] = None         # atribuir
    filtro: Optional[str] = None          # enviar
    stage: Optional[str] = None           # enviar (search/preflight/commit)
    labels: Optional[List[str]] = None    # enviar
    token: Optional[str] = None           # enviar
    interessados: Optional[str] = None    # criar_processo
    observacoes: Optional[str] = None     # criar_processo
    
    # Flags
    full: Optional[bool] = False
    apenas_ler: Optional[bool] = False
    debug: Optional[bool] = False


# Mapeamento de modos para scripts
SCRIPTS = {
    "detalhar": "/app/scripts/detalhar_processo.py",
    "atuar": "/app/scripts/atuar_no_processo.py",
    "assinar": "/app/scripts/assinar_documento.py",
    "assinar_bloco": "/app/scripts/assinar_bloco.py",
    "listar_bloco": "/app/scripts/listar_docs_bloco.py",
    "ler_documento": "/app/scripts/ler_para_assinar.py",
    "enviar": "/app/scripts/enviar_processo.py",
    "atribuir": "/app/scripts/sei_atribuir.py",
    "capturar_editor": "/app/scripts/capturar_editor_sei.py",
    "criar_processo": "/app/scripts/criar_processo.py",
}


def build_auth_args(payload: RunPayload) -> tuple:
    """
    Constrói argumentos de autenticação.
    Retorna (args_list, error_message, log_message)
    """
    args = []
    
    if payload.credentials:
        cred = payload.credentials
        if cred.get("usuario") and cred.get("senha"):
            args += ["--usuario", cred.get("usuario")]
            args += ["--senha", cred.get("senha")]
            
            # orgao (sem "-id" para compatibilidade com scripts)
            orgao = cred.get("orgao_id") or cred.get("orgao") or "31"
            args += ["--orgao", orgao]
            
            # Dados para assinatura (se presentes)
            if cred.get("nome_completo") or cred.get("nome"):
                args += ["--nome", cred.get("nome_completo") or cred.get("nome")]
            
            if cred.get("cargo"):
                args += ["--cargo", cred.get("cargo")]
            
            return args, None, f"credenciais diretas: {cred.get('usuario')}"
        else:
            return [], "Credenciais incompletas (usuario/senha)", None
    
    elif payload.sigla:
        args += ["--sigla", payload.sigla]
        return args, None, f"sigla: {payload.sigla}"
    
    elif payload.chat_id:
        args += ["--chat-id", payload.chat_id]
        return args, None, f"chat_id: {payload.chat_id}"
    
    else:
        return [], "Informe 'credentials', 'sigla' ou 'chat_id'", None


def run_script(cmd: list, timeout: int = 300) -> dict:
    """Executa script e retorna resultado."""
    try:
        # Esconde a senha no log
        cmd_log = []
        hide_next = False
        for c in cmd:
            if hide_next:
                cmd_log.append("***")
                hide_next = False
            elif c == "--senha":
                cmd_log.append(c)
                hide_next = True
            else:
                cmd_log.append(c)
        
        print(f"[PlattArgus Runner] Executando: {' '.join(cmd_log)}", file=sys.stderr)
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "PYTHONUNBUFFERED": "1"}
        )
        
        output = result.stdout + result.stderr

        # Tenta parsear JSON do stdout (onde os scripts imprimem o resultado)
        json_data = None

        # 1. Tenta stdout inteiro como JSON
        stdout_stripped = result.stdout.strip()
        if stdout_stripped:
            try:
                json_data = json.loads(stdout_stripped)
            except (json.JSONDecodeError, ValueError):
                # 2. Procura último bloco JSON no stdout (scripts podem imprimir debug antes)
                # Varre de trás pra frente procurando '{' que fecha com '}'
                brace_depth = 0
                json_end = -1
                json_start = -1
                for i in range(len(stdout_stripped) - 1, -1, -1):
                    ch = stdout_stripped[i]
                    if ch == '}':
                        if json_end == -1:
                            json_end = i
                        brace_depth += 1
                    elif ch == '{':
                        brace_depth -= 1
                        if brace_depth == 0 and json_end != -1:
                            json_start = i
                            break
                if json_start != -1 and json_end != -1:
                    try:
                        json_data = json.loads(stdout_stripped[json_start:json_end + 1])
                    except (json.JSONDecodeError, ValueError):
                        pass
        
        return {
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "output": output,
            "json_data": json_data,
        }
        
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"Timeout ({timeout}s)"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/health")
def health():
    return {
        "status": "ok", 
        "service": "plattargus-runner", 
        "version": "3.0.0", 
        "python": sys.version.split()[0],
        "modes": list(SCRIPTS.keys())
    }


@app.post("/run")
def run_job(payload: RunPayload = Body(...)):
    """
    Endpoint unificado para todas as operações.
    
    Modos:
    - detalhar: Analisa processo (nup obrigatório)
    - atuar: Atua no processo (nup, tipo_documento obrigatórios)
    - assinar: Assina documento (sei_numero obrigatório)
    - assinar_bloco: Assina bloco (numero_bloco obrigatório)
    - listar_bloco: Lista docs do bloco (numero_bloco obrigatório)
    - ler_documento: Lê documento (sei_numero obrigatório)
    - enviar: Envia processo (nup, stage obrigatórios)
    - atribuir: Atribui processo (nup, apelido obrigatórios)
    """
    
    mode = payload.mode.lower().strip()
    
    # Verifica se modo é suportado
    if mode not in SCRIPTS:
        return {"ok": False, "error": f"Modo desconhecido: {mode}. Modos: {list(SCRIPTS.keys())}"}
    
    script_path = SCRIPTS[mode]
    
    if not os.path.exists(script_path):
        return {"ok": False, "error": f"Script não encontrado: {script_path}"}
    
    # Build argumentos de autenticação
    auth_args, auth_error, auth_log = build_auth_args(payload)
    if auth_error:
        return {"ok": False, "error": auth_error}
    
    print(f"[Runner] Modo: {mode}, Auth: {auth_log}", file=sys.stderr)
    
    # Build comando baseado no modo
    cmd = [sys.executable, script_path]
    
    # ==========================================
    # DETALHAR
    # ==========================================
    if mode == "detalhar":
        if not payload.nup:
            return {"ok": False, "error": "Campo 'nup' é obrigatório para detalhar"}
        
        cmd += [payload.nup]
        cmd += auth_args
        cmd += ["--headless"]
        
        if payload.full:
            cmd += ["--full"]
    
    # ==========================================
    # ATUAR
    # ==========================================
    elif mode == "atuar":
        if not payload.nup:
            return {"ok": False, "error": "Campo 'nup' é obrigatório para atuar"}
        if not payload.tipo_documento:
            return {"ok": False, "error": "Campo 'tipo_documento' é obrigatório para atuar"}
        
        cmd += [
            payload.nup,
            payload.tipo_documento,
            payload.destinatario or "",
            payload.texto_despacho or "",
        ]
        cmd += auth_args
    
    # ==========================================
    # ASSINAR DOCUMENTO
    # ==========================================
    elif mode == "assinar":
        if not payload.sei_numero:
            return {"ok": False, "error": "Campo 'sei_numero' é obrigatório para assinar"}
        
        cmd += [payload.sei_numero]
        cmd += auth_args
        
        if payload.debug:
            cmd += ["--debug"]
    
    # ==========================================
    # ASSINAR BLOCO
    # ==========================================
    elif mode == "assinar_bloco":
        if not payload.numero_bloco:
            return {"ok": False, "error": "Campo 'numero_bloco' é obrigatório para assinar_bloco"}
        
        cmd += [payload.numero_bloco]
        cmd += auth_args
        
        if payload.debug:
            cmd += ["--debug"]
    
    # ==========================================
    # LISTAR DOCUMENTOS DO BLOCO
    # ==========================================
    elif mode == "listar_bloco":
        if not payload.numero_bloco:
            return {"ok": False, "error": "Campo 'numero_bloco' é obrigatório para listar_bloco"}
        
        cmd += [payload.numero_bloco]
        cmd += auth_args
        
        if payload.debug:
            cmd += ["--debug"]
    
    # ==========================================
    # LER DOCUMENTO (PARA ASSINATURA)
    # ==========================================
    elif mode == "ler_documento":
        if not payload.sei_numero:
            return {"ok": False, "error": "Campo 'sei_numero' é obrigatório para ler_documento"}
        
        cmd += [payload.sei_numero]
        cmd += auth_args
        
        if payload.apenas_ler:
            cmd += ["--apenas-ler"]
        
        if payload.debug:
            cmd += ["--debug"]
    
    # ==========================================
    # ENVIAR PROCESSO
    # ==========================================
    elif mode == "enviar":
        if not payload.nup:
            return {"ok": False, "error": "Campo 'nup' é obrigatório para enviar"}
        if not payload.stage:
            return {"ok": False, "error": "Campo 'stage' é obrigatório para enviar"}
        
        cmd += ["--nup", payload.nup]
        cmd += ["--stage", payload.stage]
        cmd += auth_args
        
        if payload.filtro:
            cmd += ["--filtro", payload.filtro]
        
        if payload.labels:
            for label in payload.labels:
                cmd += ["--labels", label]
        
        if payload.token:
            cmd += ["--token", payload.token]
        
        if payload.debug:
            cmd += ["--debug"]
    
    # ==========================================
    # ATRIBUIR PROCESSO
    # ==========================================
    elif mode == "atribuir":
        if not payload.nup:
            return {"ok": False, "error": "Campo 'nup' é obrigatório para atribuir"}
        if not payload.apelido:
            return {"ok": False, "error": "Campo 'apelido' é obrigatório para atribuir"}

        cmd += [payload.nup, payload.apelido]
        cmd += auth_args

        # Busca sigla do usuário (necessária para o script buscar servidor)
        sigla = payload.sigla
        if not sigla and payload.credentials:
            try:
                from diretorias_db import DiretoriasDB
                db = DiretoriasDB()
                diretoria = db.buscar_por_usuario(payload.credentials.get("usuario", ""))
                if diretoria:
                    sigla = diretoria.get("sigla")
            except Exception:
                pass
        if sigla:
            cmd += ["--sigla", sigla]

        if payload.debug:
            cmd += ["--debug"]

    # ==========================================
    # CAPTURAR ESTRUTURA DO EDITOR
    # ==========================================
    elif mode == "capturar_editor":
        if not payload.nup:
            return {"ok": False, "error": "Campo 'nup' é obrigatório para capturar_editor"}
        if not payload.tipo_documento:
            return {"ok": False, "error": "Campo 'tipo_documento' é obrigatório para capturar_editor"}

        cmd += [
            payload.nup,
            payload.tipo_documento,
        ]
        cmd += auth_args

    # ==========================================
    # CRIAR PROCESSO
    # ==========================================
    elif mode == "criar_processo":
        if not payload.tipo_processo:
            return {"ok": False, "error": "Campo 'tipo_processo' é obrigatório para criar_processo"}

        cmd += [payload.tipo_processo]
        cmd += auth_args

        if payload.interessados:
            cmd += ["--interessados", payload.interessados]
        if payload.observacoes:
            cmd += ["--observacoes", payload.observacoes]

    # Executa
    return run_script(cmd)


# ==========================================
# ENDPOINT BLOCOS (listar, visualizar, assinar)
# ==========================================

BLOCOS_SCRIPTS = {
    "listar": "/app/scripts/listar_docs_bloco.py",
    "visualizar": "/app/scripts/ler_para_assinar.py",
    "assinar_doc": "/app/scripts/assinar_documento.py",
    "assinar_bloco": "/app/scripts/assinar_bloco.py",
}


@app.post("/run-blocos")
def run_blocos(payload: dict = Body(...)):
    """
    Endpoint para operações de blocos de assinatura.

    Payload:
        acao: listar | visualizar | assinar_doc | assinar_bloco
        credentials: {usuario, senha, orgao_id, nome, cargo}
        bloco_id: Número do bloco (listar, assinar_bloco)
        documento_id: Número SEI do documento (visualizar, assinar_doc)
    """
    acao = payload.get("acao", "").lower().strip()
    credentials = payload.get("credentials", {})
    bloco_id = payload.get("bloco_id")
    documento_id = payload.get("documento_id")

    if acao not in BLOCOS_SCRIPTS:
        return {"ok": False, "error": f"Ação desconhecida: {acao}. Ações: {list(BLOCOS_SCRIPTS.keys())}"}

    script_path = BLOCOS_SCRIPTS[acao]

    if not credentials or not credentials.get("usuario") or not credentials.get("senha"):
        return {"ok": False, "error": "Campo 'credentials' com usuario/senha é obrigatório"}

    # Auth args
    auth_args = [
        "--usuario", credentials["usuario"],
        "--senha", credentials["senha"],
        "--orgao", credentials.get("orgao_id", "31"),
    ]
    if credentials.get("nome"):
        auth_args += ["--nome", credentials["nome"]]
    if credentials.get("cargo"):
        auth_args += ["--cargo", credentials["cargo"]]

    # Build comando
    cmd = [sys.executable, script_path]

    if acao == "listar":
        if not bloco_id:
            return {"ok": False, "error": "Campo 'bloco_id' é obrigatório para listar"}
        cmd += [str(bloco_id)] + auth_args

    elif acao == "visualizar":
        if not documento_id:
            return {"ok": False, "error": "Campo 'documento_id' é obrigatório para visualizar"}
        cmd += [str(documento_id)] + auth_args + ["--apenas-ler"]

    elif acao == "assinar_doc":
        if not documento_id:
            return {"ok": False, "error": "Campo 'documento_id' é obrigatório para assinar_doc"}
        cmd += [str(documento_id)] + auth_args

    elif acao == "assinar_bloco":
        if not bloco_id:
            return {"ok": False, "error": "Campo 'bloco_id' é obrigatório para assinar_bloco"}
        cmd += [str(bloco_id)] + auth_args

    print(f"[Runner/Blocos] Ação: {acao}, Usuario: {credentials['usuario']}", file=sys.stderr)

    return run_script(cmd, timeout=300)


# ==========================================
# ENDPOINTS AUXILIARES
# ==========================================

@app.post("/testar-login")
def testar_login(usuario: str = Body(...), senha: str = Body(...), orgao_id: str = Body("31")):
    """Testa se credenciais são válidas."""
    try:
        from sei_auth_multi import testar_credenciais
        import asyncio
        
        resultado = asyncio.run(testar_credenciais(usuario, senha, orgao_id))
        
        return {
            "ok": resultado.get("sucesso", False),
            "message": "Login válido" if resultado.get("sucesso") else resultado.get("erro", "Falha no login"),
            "tempo_login": resultado.get("tempo_login"),
        }
        
    except Exception as e:
        return {"ok": False, "message": str(e)}


@app.post("/consultar-autoridade")
def consultar_autoridade(sigla: str = Body(None), nome: str = Body(None)):
    """Consulta autoridade no banco SQLite local."""
    try:
        from autoridades_db import AutoridadesDB
        
        db = AutoridadesDB()
        
        if sigla:
            resultado = db.buscar(sigla.upper())
            if resultado:
                return {
                    "sucesso": True,
                    "total_encontrado": 1,
                    "principal": {
                        "sigla": resultado.get('chave_busca', ''),
                        "unidade_destino": resultado.get('unidade_destino', ''),
                        "posto_grad": resultado.get('posto_grad', ''),
                        "nome": resultado.get('nome_atual', ''),
                        "cargo": resultado.get('observacoes', ''),
                        "matricula": resultado.get('matricula', ''),
                        "portaria": resultado.get('portaria_nomeacao', ''),
                    },
                    "resultados": [resultado]
                }
            else:
                return {"sucesso": False, "erro": f"Autoridade '{sigla}' não encontrada"}
        
        return {"sucesso": False, "erro": "Informe sigla ou nome"}
        
    except Exception as e:
        return {"sucesso": False, "erro": str(e)}


@app.get("/listar-diretorias")
def listar_diretorias():
    """Lista todas as diretorias cadastradas."""
    try:
        from diretorias_db import DiretoriasDB
        
        db = DiretoriasDB()
        diretorias = db.listar_todas()
        
        return {
            "sucesso": True,
            "total": len(diretorias),
            "diretorias": [
                {
                    "sigla": d.get("sigla"),
                    "nome": d.get("nome"),
                    "sei_usuario": d.get("sei_usuario"),
                    "ativo": d.get("ativo", True)
                }
                for d in diretorias
            ]
        }
        
    except Exception as e:
        return {"sucesso": False, "erro": str(e)}


@app.get("/scripts")
def listar_scripts():
    """Lista scripts disponíveis e status."""
    result = {}
    for mode, path in SCRIPTS.items():
        result[mode] = {
            "path": path,
            "exists": os.path.exists(path)
        }
    return result


if __name__ == "__main__":
    import uvicorn
    print("🔥 PlattArgus Runner v3.0 - Todos os modos + Credenciais Diretas")
    print(f"   Modos: {', '.join(SCRIPTS.keys())}")
    uvicorn.run(app, host="0.0.0.0", port=8001)
