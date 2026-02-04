#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
formato_documentos.py - Módulo Centralizado de Formatação de Documentos
PlattArgus WEB - CBMAC

Este módulo centraliza a formatação de destinatário, remetente, vocativo
para garantir consistência em todos os documentos gerados pelo sistema.

FORMATO PADRÃO:
    Destinatário: Ao Sr. Nome Completo - POSTO GRAD
                  Cargo sem negrito

    Remetente:    Nome Completo - POSTO GRAD
                  Cargo sem negrito
                  Portaria (opcional)

REGRAS:
    - Nome: Title Case (Primeira Letra Maiúscula), SEM negrito
    - Posto/Graduação: CAIXA ALTA
    - Cargo: normal, sem negrito, sem caixa alta
    - Pronome: "Ao Sr." para homem, "À Sra." para mulher (específico)

USO:
    from formato_documentos import formatar_destinatario, formatar_remetente, determinar_genero
"""

from typing import Optional, Dict, Tuple


# =============================================================================
# DETECÇÃO DE GÊNERO
# =============================================================================

def determinar_genero(nome: str, cargo: str = "") -> str:
    """
    Determina gênero baseado no cargo e nome.
    Retorna 'F' para feminino, 'M' para masculino.

    Prioridade:
    1. Cargo explicitamente feminino (Diretora, Comandante com nome feminino)
    2. Nome em lista de nomes femininos conhecidos
    3. Heurística: nomes terminados em 'A'
    4. Default: masculino (mais comum no CBMAC)
    """
    # 1. Verifica pelo cargo (mais confiável)
    cargo_lower = (cargo or '').lower()

    # Cargos explicitamente femininos
    if any(termo in cargo_lower for termo in ['diretora', 'chefa', 'assessora', 'coordenadora', 'subcomandante-geral']):
        return 'F'

    # 2. Verifica pelo nome
    if nome:
        primeiro_nome = nome.split()[0].upper() if nome.split() else ''

        # Nomes femininos comuns
        nomes_femininos = [
            'MARIA', 'ANA', 'FRANCISCA', 'ANTONIA', 'ADRIANA', 'JULIANA', 'MARCIA',
            'FERNANDA', 'PATRICIA', 'ALINE', 'SANDRA', 'CAMILA', 'AMANDA', 'BRUNA',
            'JESSICA', 'LETICIA', 'JULIA', 'LUCIANA', 'VANESSA', 'CARLA', 'SIMONE',
            'DANIELA', 'RENATA', 'CAROLINA', 'RAFAELA', 'CRISTIANE', 'FABIANA',
            'CLAUDIA', 'HELENA', 'BEATRIZ', 'LARISSA', 'PRISCILA', 'TATIANA',
            'GABRIELA', 'NATALIA', 'MONICA', 'PAULA', 'RAQUEL', 'VIVIANE', 'ELIANE',
            'ROSANGELA', 'ROSA', 'LUCIA', 'ELIZABETH', 'TEREZA', 'EDILENE', 'EDNA',
            'ROBERTA', 'DEBORA', 'FLAVIA', 'REGINA', 'VERA', 'SILVIA', 'MARIANA',
            'ISABELA', 'IZABEL', 'CECILIA', 'ALICE', 'LUANA', 'BIANCA', 'LORENA'
        ]

        if primeiro_nome in nomes_femininos:
            return 'F'

        # Heurística: nomes terminados em 'A' geralmente são femininos
        # Exceções são sobrenomes comuns
        excecoes_masculinas = ['COSTA', 'SOUZA', 'SILVA', 'MOURA', 'VIEIRA',
                               'OLIVEIRA', 'PEREIRA', 'FERREIRA', 'ROCHA', 'BORBA']
        if primeiro_nome.endswith('A') and primeiro_nome not in excecoes_masculinas and len(primeiro_nome) > 2:
            return 'F'

    # Default: masculino
    return 'M'


# =============================================================================
# FORMATAÇÃO DE NOME
# =============================================================================

def formatar_nome(nome: str) -> str:
    """
    Formata nome em Title Case (Primeira Letra Maiúscula).
    Trata conectivos (de, da, do, dos, das) em minúsculo.

    Exemplo: "GILMAR TORRES MARQUES MOURA" -> "Gilmar Torres Marques Moura"
             "MARIA DA SILVA" -> "Maria da Silva"
    """
    if not nome:
        return ''

    conectivos = ['de', 'da', 'do', 'dos', 'das', 'e']
    palavras = nome.lower().split()

    resultado = []
    for i, palavra in enumerate(palavras):
        if palavra in conectivos and i > 0:  # Conectivo no meio
            resultado.append(palavra)
        else:
            resultado.append(palavra.capitalize())

    return ' '.join(resultado)


def formatar_posto_grad(posto_grad: str) -> str:
    """
    Formata posto/graduação em CAIXA ALTA.

    Exemplo: "Maj Qobmec" -> "MAJ QOBMEC"
    """
    if not posto_grad:
        return ''
    return posto_grad.upper()


# =============================================================================
# FORMATAÇÃO DE DESTINATÁRIO
# =============================================================================

def formatar_destinatario(
    nome: str,
    posto_grad: str = "",
    cargo: str = "",
    sigla_unidade: str = "",
    sigla_sei: str = ""
) -> Tuple[str, str]:
    """
    Formata o bloco de destinatário no padrão SEI.

    Retorna:
        Tuple[str, str]: (html_destinatario, vocativo)

    Formato:
        Ao Sr. Nome Completo - POSTO GRAD
        Cargo - CBMAC-SIGLA

    Exemplo:
        Ao Sr. Gilmar Torres Marques Moura - MAJ QOBMEC
        Diretor de Recursos Humanos - CBMAC-DRH
    """
    # Formata componentes
    nome_formatado = formatar_nome(nome)
    posto_formatado = formatar_posto_grad(posto_grad)

    # Determina gênero e pronome
    genero = determinar_genero(nome, cargo)
    pronome = "À Sra." if genero == 'F' else "Ao Sr."

    # Monta linha 1: Pronome + Nome - POSTO
    if posto_formatado:
        linha1 = f"{pronome} {nome_formatado} - {posto_formatado}"
    else:
        linha1 = f"{pronome} {nome_formatado}"

    # Monta linha 2: Cargo - Sigla SEI
    linha2_parts = []
    if cargo:
        linha2_parts.append(cargo)
    if sigla_sei:
        linha2_parts.append(sigla_sei)
    elif sigla_unidade:
        linha2_parts.append(f"CBMAC-{sigla_unidade}")

    linha2 = " - ".join(linha2_parts) if linha2_parts else ""

    # Monta HTML
    html = f'<p style="text-align: left;">{linha1}'
    if linha2:
        html += f'<br>{linha2}'
    html += '</p>'

    # Determina vocativo baseado no cargo e gênero
    vocativo = _determinar_vocativo(cargo, genero)

    return html, vocativo


def formatar_destinatario_simples(
    nome: str,
    posto_grad: str = "",
    cargo: str = ""
) -> Tuple[str, str]:
    """
    Formata destinatário de forma simplificada (sem siglas).
    Usado para memorandos internos.

    Retorna:
        Tuple[str, str]: (html_destinatario, vocativo)
    """
    nome_formatado = formatar_nome(nome)
    posto_formatado = formatar_posto_grad(posto_grad)

    genero = determinar_genero(nome, cargo)
    pronome = "À Sra." if genero == 'F' else "Ao Sr."

    # Monta linha do destinatário
    if posto_formatado:
        dest_linha = f"{nome_formatado} - {posto_formatado}"
    else:
        dest_linha = nome_formatado

    if cargo:
        dest_linha += f"<br>{cargo}"

    html = f'<p style="text-align: left;">{pronome} {dest_linha}</p>'
    vocativo = _determinar_vocativo(cargo, genero)

    return html, vocativo


def _determinar_vocativo(cargo: str, genero: str) -> str:
    """Determina o vocativo baseado no cargo e gênero."""
    cargo_lower = (cargo or '').lower()

    if 'comandante' in cargo_lower and 'sub' not in cargo_lower:
        return "Senhora Comandante" if genero == 'F' else "Senhor Comandante"
    elif 'subcomandante' in cargo_lower:
        return "Senhora Subcomandante-Geral" if genero == 'F' else "Senhor Subcomandante-Geral"
    elif 'diretor' in cargo_lower:
        return "Senhora Diretora" if genero == 'F' else "Senhor Diretor"
    elif 'chefe' in cargo_lower:
        return "Senhora Chefe" if genero == 'F' else "Senhor Chefe"
    elif 'assessor' in cargo_lower:
        return "Senhora Assessora" if genero == 'F' else "Senhor Assessor"
    else:
        return "Senhora" if genero == 'F' else "Senhor"


# =============================================================================
# FORMATAÇÃO DE REMETENTE
# =============================================================================

def formatar_remetente(
    nome: str,
    posto_grad: str = "",
    cargo: str = "",
    portaria: str = "",
    matricula: str = "",
    sigla: str = ""
) -> str:
    """
    Formata o bloco de assinatura/remetente no padrão SEI.

    Formato:
        Nome Completo - POSTO GRAD
        Cargo
        Portaria ou Matrícula (opcional)

    Exemplo:
        Gilmar Torres Marques Moura - MAJ QOBMEC
        Diretor de Recursos Humanos
        Port. nº 123/2025
    """
    # Formata componentes
    nome_formatado = formatar_nome(nome) or '[Nome do Remetente]'
    posto_formatado = formatar_posto_grad(posto_grad)
    cargo_formatado = cargo or '[Cargo/Função]'

    # Monta linha 1: Nome - POSTO
    if posto_formatado:
        linha1 = f"{nome_formatado} - {posto_formatado}"
    else:
        linha1 = nome_formatado

    # Monta HTML
    html = f'<p style="text-align: center;">{linha1}<br>{cargo_formatado}'

    # Linha 3: Portaria, Matrícula ou Sigla (opcional)
    if portaria:
        html += f'<br>Port. nº {portaria}'
    elif matricula:
        html += f'<br>Matrícula {matricula}'
    elif sigla:
        html += f'<br>{sigla}/CBMAC'

    html += '</p>'

    return html


# =============================================================================
# FORMATAÇÃO DE MÚLTIPLOS DESTINATÁRIOS (CIRCULAR)
# =============================================================================

def formatar_destinatarios_multiplos(destinatarios: list) -> Tuple[str, str]:
    """
    Formata múltiplos destinatários para documentos circulares.

    Args:
        destinatarios: Lista de dicts com {nome, posto_grad, cargo, sigla, sigla_sei}

    Retorna:
        Tuple[str, str]: (html_destinatarios, vocativo)
    """
    if not destinatarios:
        return "", "Senhor"

    if len(destinatarios) == 1:
        d = destinatarios[0]
        return formatar_destinatario(
            nome=d.get('nome', ''),
            posto_grad=d.get('posto_grad', ''),
            cargo=d.get('cargo', ''),
            sigla_unidade=d.get('sigla', ''),
            sigla_sei=d.get('sigla_sei', '')
        )

    # Múltiplos destinatários
    partes = []
    generos = []
    cargos = []

    for d in destinatarios:
        nome = d.get('nome', '')
        posto = d.get('posto_grad', '')
        cargo = d.get('cargo', '')
        sigla = d.get('sigla', '')
        sigla_sei = d.get('sigla_sei', '') or f'CBMAC-{sigla}'

        nome_formatado = formatar_nome(nome)
        posto_formatado = formatar_posto_grad(posto)

        genero = determinar_genero(nome, cargo)
        generos.append(genero)
        cargos.append(cargo)

        pronome = "À Sra." if genero == 'F' else "Ao Sr."

        linha1 = f"{pronome} {nome_formatado} - {posto_formatado}" if posto_formatado else f"{pronome} {nome_formatado}"
        linha2 = f"{cargo} - {sigla_sei}" if cargo else sigla_sei

        html_dest = f'<p style="text-align: left;">{linha1}'
        if linha2:
            html_dest += f'<br>{linha2}'
        html_dest += '</p>'

        partes.append(html_dest)

    html_final = '\n'.join(partes)

    # Vocativo para múltiplos (usa masculino plural se misto)
    todos_femininos = all(g == 'F' for g in generos)

    if all('Comandante' in c for c in cargos if c):
        vocativo = "Senhoras Comandantes" if todos_femininos else "Senhores Comandantes"
    elif all('Diretor' in c for c in cargos if c):
        vocativo = "Senhoras Diretoras" if todos_femininos else "Senhores Diretores"
    else:
        vocativo = "Senhoras" if todos_femininos else "Senhores"

    return html_final, vocativo


# =============================================================================
# FUNÇÕES DE COMPATIBILIDADE (para migração gradual)
# =============================================================================

def formatar_destinatario_dict(dados: Dict) -> Tuple[str, str]:
    """
    Wrapper para aceitar dicionário de dados do destinatário.
    Compatível com estruturas existentes.
    """
    return formatar_destinatario(
        nome=dados.get('nome', '') or dados.get('nome_atual', ''),
        posto_grad=dados.get('posto_grad', '') or dados.get('posto', ''),
        cargo=dados.get('cargo', '') or dados.get('unidade_destino', ''),
        sigla_unidade=dados.get('sigla', '') or dados.get('sigla_unidade', ''),
        sigla_sei=dados.get('sigla_sei', '')
    )


def formatar_remetente_dict(dados: Dict) -> str:
    """
    Wrapper para aceitar dicionário de dados do remetente.
    Compatível com estruturas existentes.
    """
    return formatar_remetente(
        nome=dados.get('nome', ''),
        posto_grad=dados.get('posto_grad', '') or dados.get('posto', ''),
        cargo=dados.get('cargo', ''),
        portaria=dados.get('portaria', ''),
        matricula=dados.get('matricula', ''),
        sigla=dados.get('sigla', '')
    )


# =============================================================================
# TESTE
# =============================================================================

if __name__ == "__main__":
    # Teste de formatação
    print("=== TESTE DE FORMATAÇÃO ===\n")

    # Teste destinatário masculino
    html, voc = formatar_destinatario(
        nome="GILMAR TORRES MARQUES MOURA",
        posto_grad="Maj Qobmec",
        cargo="Diretor de Recursos Humanos",
        sigla_unidade="DRH"
    )
    print("Destinatário (masculino):")
    print(html)
    print(f"Vocativo: {voc}")
    print()

    # Teste destinatário feminino
    html2, voc2 = formatar_destinatario(
        nome="MARIA DA SILVA",
        posto_grad="Cap Qobmec",
        cargo="Diretora de Ensino",
        sigla_unidade="DEI"
    )
    print("Destinatário (feminino):")
    print(html2)
    print(f"Vocativo: {voc2}")
    print()

    # Teste remetente
    html3 = formatar_remetente(
        nome="GILMAR TORRES MARQUES MOURA",
        posto_grad="Maj Qobmec",
        cargo="Diretor de Recursos Humanos",
        portaria="123/2025"
    )
    print("Remetente:")
    print(html3)
