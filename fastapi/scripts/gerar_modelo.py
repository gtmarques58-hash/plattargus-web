import json
import sys

from templates_meta import TEMPLATES_META  # templates_meta.py está no mesmo diretório em /app/scripts


def carregar_molde(template_id: str):
    """
    Carrega o texto do template e os metadados a partir do TEMPLATES_META.
    """
    if template_id not in TEMPLATES_META:
        raise ValueError(f"Template não encontrado: {template_id!r}")

    meta = TEMPLATES_META[template_id]
    caminho = meta.get("arquivo_path")
    if caminho is None:
        raise ValueError(f"Template {template_id!r} sem 'arquivo_path' definido.")

    if not caminho.exists():
        raise FileNotFoundError(f"Arquivo de modelo não encontrado: {caminho}")

    texto = caminho.read_text(encoding="utf-8")
    return texto, meta


def montar_documento(template_id: str, dados: dict) -> dict:
    """
    Gera o corpo_html a partir de um template flexível (.txt) usando .format(**dados).
    """
    molde, meta = carregar_molde(template_id)

    # Valores padrão para evitar KeyError
    base = {
        "NOME_COMPLETO": "",
        "CARGO_DESTINO": "",
        "SIGLA_UNIDADE": "",
        "ASSUNTO_RESUMIDO": "",
        "VOCATIVO": "",
        "TEXTO_CORPO": "",
    }
    base.update(dados or {})

    try:
        corpo_html = molde.format(**base)
    except KeyError as e:
        raise ValueError(f"Campo ausente para template {template_id}: {e}")

    tipo_sei = meta.get("tipo_sei", "Memorando")

    documento = {
        "template_id": template_id,
        "tipo_sei": tipo_sei,
        "assunto": base["ASSUNTO_RESUMIDO"],
        "destinatario": base["NOME_COMPLETO"],
        "sigla_unidade_destino": base["SIGLA_UNIDADE"],
        "corpo_html": corpo_html,
    }

    return documento


def main():
    """
    Uso:
      python gerar_modelo.py MEMO_TAF_DEI '{"NOME_COMPLETO": "...", ...}'
    """
    if len(sys.argv) < 3:
        print(
            json.dumps(
                {
                    "sucesso": False,
                    "erro": "Uso: gerar_modelo.py <template_id> '<json_dados>'",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        sys.exit(1)

    template_id = sys.argv[1]
    dados_raw = sys.argv[2]

    try:
        dados = json.loads(dados_raw)
    except Exception as e:
        print(
            json.dumps(
                {
                    "sucesso": False,
                    "erro": f"JSON inválido em dados: {e}",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        sys.exit(1)

    try:
        doc = montar_documento(template_id, dados)
        print(
            json.dumps(
                {
                    "sucesso": True,
                    "documento": doc,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    except Exception as e:
        print(
            json.dumps(
                {
                    "sucesso": False,
                    "erro": str(e),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
