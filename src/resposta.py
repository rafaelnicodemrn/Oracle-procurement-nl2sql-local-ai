"""Monta a resposta em português a partir do resultado do Oracle, só com regras fixas.

Nenhuma IA participa: o resultado da consulta nunca sai da empresa. Este módulo não
importa llm nem faz chamadas de rede.
"""

from __future__ import annotations
import re
from datetime import datetime

import sqlglot
from sqlglot import exp

import config

# Mesmas regras de nome de coluna usadas na tela (src/static/index.html, fmtValor)
_RE_MOEDA = re.compile(r"(valor|preco|preço|custo|amount|price)", re.I)
_RE_CONTAGEM = re.compile(r"(qtd|quantidade|count|total_pedidos|total_ordens|^total_)", re.I)
_RE_CODIGO = re.compile(r"(^id$|_id$|^id_|codigo|código|numero|número|segment|item|cnpj|cpf|nf$)", re.I)
_RE_NUM = re.compile(r"^-?\d+(\.\d+)?$")
_RE_DATA = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:[T ]\d{2}:\d{2})?")

# Acima disso o "primeiro da lista" fica longo demais e a resposta só aponta a tabela
_MAX_COLUNAS_CITADAS = 3

# Mesmo mapa de rótulos da tela (NOMES_COLUNAS em src/static/index.html). Manter os dois iguais.
NOMES_COLUNAS = {
    "numero_ordem": "Número da ordem",
    "numero_oc": "Número da OC",
    "numero_pedido": "Número do pedido",
    "data_criacao": "Data de criação",
    "data_ordem": "Data da ordem",
    "data_emissao": "Data de emissão",
    "data_compra": "Data da compra",
    "data_entrega": "Data de entrega",
    "valor_total": "Valor total",
    "valor_comprado": "Valor comprado",
    "valor_linha": "Valor da linha",
    "valor_ordem": "Valor da ordem",
    "valor": "Valor",
    "preco_unitario": "Preço unitário",
    "preco_medio": "Preço médio",
    "preco_pago": "Preço pago",
    "preco": "Preço",
    "quantidade": "Quantidade",
    "qtd": "Quantidade",
    "total_ordens": "Total de ordens",
    "total_pedidos": "Total de pedidos",
    "total_compras": "Total de compras",
    "fornecedor": "Fornecedor",
    "nome_fornecedor": "Nome do fornecedor",
    "codigo_fornecedor": "Código do fornecedor",
    "comprador": "Comprador",
    "nome_comprador": "Nome do comprador",
    "categoria": "Categoria",
    "nome_categoria": "Nome da categoria",
    "codigo_item": "Código do item",
    "item": "Item",
    "descricao": "Descrição",
    "descricao_item": "Descrição do item",
    "unidade": "Unidade",
    "situacao": "Situação",
    "status": "Status",
    "mes": "Mês",
    "ano": "Ano",
    "numero_linha": "Número da linha",
}


def _milhar(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def _decimal(n: float, casas: int) -> str:
    return f"{n:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


# Fallback para colunas fora de NOMES_COLUNAS. Manter igual a src/static/index.html (ACENTOS, PREFIXOS_DE, SEM_DE).
ACENTOS = {
    "numero": "número", "descricao": "descrição", "criacao": "criação", "emissao": "emissão",
    "preco": "preço", "unitario": "unitário", "codigo": "código", "media": "média", "medio": "médio",
    "mes": "mês", "situacao": "situação", "organizacao": "organização", "requisicao": "requisição",
    "ultima": "última", "ultimo": "último", "qtd": "quantidade",
}
# Primeira palavra que pede "de" antes de um substantivo (total_ordens_abertas -> Total de ordens abertas)
PREFIXOS_DE = ("total", "qtd", "quantidade", "valor", "numero", "data")
# Segunda palavra que NÃO recebe "de": adjetivos, preposições e termos já tratados
SEM_DE = (
    "total", "medio", "media", "unitario", "unitaria", "maximo", "maxima", "minimo", "minima", "pago", "paga",
    "comprado", "comprada", "liquido", "liquida", "bruto", "bruta", "atual", "anterior", "geral", "final",
    "inicial", "parcial", "estimado", "estimada", "restante", "amount", "de", "da", "do", "das", "dos",
    "em", "na", "no", "por", "para", "com",
)


def rotulo(coluna: str) -> str:
    """NUMERO_ORDEM vira 'Número da ordem'. Mesma regra de nomeColuna() em src/static/index.html."""
    chave = str(coluna).lower()
    if chave in NOMES_COLUNAS:
        return NOMES_COLUNAS[chave]
    palavras = [p for p in chave.split("_") if p]
    if not palavras:
        return str(coluna)
    if len(palavras) > 1 and palavras[0] in PREFIXOS_DE and palavras[1] not in SEM_DE and palavras[1] not in PREFIXOS_DE:
        palavras.insert(1, "de")
    texto = " ".join(ACENTOS.get(p, p) for p in palavras)
    return texto[:1].upper() + texto[1:]


def formatar_valor(coluna: str, valor) -> str:
    if valor is None or valor == "":
        return "(vazio)"
    if isinstance(valor, bool):
        return "Sim" if valor else "Não"
    if isinstance(valor, str):
        m = _RE_DATA.match(valor)
        if m:
            try:
                datetime(int(m[1]), int(m[2]), int(m[3]))
                return f"{m[3]}/{m[2]}/{m[1]}"
            except ValueError:
                pass
    eh_num = isinstance(valor, (int, float)) or (isinstance(valor, str) and _RE_NUM.match(valor))
    if eh_num and not _RE_CODIGO.search(coluna):
        n = float(valor)
        if _RE_MOEDA.search(coluna):
            return ("-" if n < 0 else "") + "R$ " + _decimal(abs(n), 2)
        if _RE_CONTAGEM.search(coluna) and n == int(n):
            return _milhar(int(n))
        if n == int(n):
            return _milhar(int(n))
        return _decimal(n, 4).rstrip("0").rstrip(",")
    return str(valor)


def _tem_order_by(sql: str) -> bool:
    """True se a consulta tem ORDER BY no nível principal (não conta janela nem subconsulta)."""
    if not sql:
        return False
    try:
        arvore = sqlglot.parse_one(sql, read="oracle")
    except Exception:  # noqa: BLE001
        return False
    return bool(arvore is not None and isinstance(arvore, (exp.Select, exp.Union)) and arvore.args.get("order"))


def _pares(linha: dict) -> str:
    return "; ".join(f"{rotulo(c)}: {formatar_valor(c, v)}" for c, v in linha.items())


def montar_resposta(linhas: list[dict], sql: str = "", relatorio: bool = False) -> str:
    n = len(linhas)
    if n == 0:
        return "Nenhum registro encontrado para essa pergunta."
    if relatorio:
        return f"Planilha pronta com {_milhar(n)} registro{'s' if n != 1 else ''}."
    if n == 1:
        linha = linhas[0]
        if len(linha) == 1:
            (col, val), = linha.items()
            return f"{rotulo(col)}: {formatar_valor(col, val)}"
        return _pares(linha)
    texto = f"Encontrei {_milhar(n)} registros. Veja a tabela abaixo."
    if len(linhas[0]) <= _MAX_COLUNAS_CITADAS and _tem_order_by(sql):
        texto += f" Primeiro da lista: {_pares(linhas[0])}."
    if n == config.MAX_ROWS:
        texto += (f" O resultado foi limitado a {config.MAX_ROWS} linhas. "
                  "Para ver tudo, refine a pergunta (por exemplo, por período ou fornecedor).")
    return texto
