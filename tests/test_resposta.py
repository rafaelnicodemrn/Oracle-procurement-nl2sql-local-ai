"""Testes da resposta montada localmente (resposta.py)."""

from __future__ import annotations

import pytest

import config
from resposta import NOMES_COLUNAS, formatar_valor, montar_resposta, rotulo


def test_zero_linhas():
    assert montar_resposta([]) == "Nenhum registro encontrado para essa pergunta."


@pytest.mark.parametrize("col,valor,esperado", [
    ("VALOR_TOTAL", 1234.5, "Valor total: R$ 1.234,50"),
    ("PRECO_UNITARIO", "10", "Preço unitário: R$ 10,00"),
    ("CUSTO", 5.5, "Custo: R$ 5,50"),
    ("TOTAL_AMOUNT", 1000000, "Total amount: R$ 1.000.000,00"),
    ("TOTAL_ORDENS_ABERTAS", 3897, "Total de ordens abertas: 3.897"),
    ("TOTAL_PEDIDOS", 1500, "Total de pedidos: 1.500"),
    ("QTD", 414, "Quantidade: 414"),
    ("DATA_CRIACAO", "2026-03-14T10:22:00", "Data de criação: 14/03/2026"),
    ("DATA_CRIACAO", "2026-03-14", "Data de criação: 14/03/2026"),
    ("NUMERO_ORDEM", "PO-1001", "Número da ordem: PO-1001"),
    ("ITEM_ID", 906065, "Item id: 906065"),
    ("MEDIA", 3.14159, "Média: 3,1416"),
    ("FORNECEDOR", None, "Fornecedor: (vazio)"),
])
def test_uma_linha_uma_coluna(col, valor, esperado):
    assert montar_resposta([{col: valor}]) == esperado


def test_uma_linha_varias_colunas():
    linha = {"NUMERO_ORDEM": "PO-1", "VALOR_TOTAL": 980, "DATA_CRIACAO": "2026-04-02T16:40:00"}
    assert montar_resposta([linha]) == "Número da ordem: PO-1; Valor total: R$ 980,00; Data de criação: 02/04/2026"


def test_varias_linhas_sem_order_by():
    linhas = [{"A": 1}, {"A": 2}, {"A": 3}]
    assert montar_resposta(linhas, "SELECT a FROM po_headers_all") == "Encontrei 3 registros. Veja a tabela abaixo."


def test_varias_linhas_com_order_by_cita_o_primeiro():
    linhas = [{"FORNECEDOR": "ACME", "VALOR_TOTAL": 5000}, {"FORNECEDOR": "Beta", "VALOR_TOTAL": 100}]
    sql = "SELECT fornecedor, valor_total FROM po_headers_all ORDER BY valor_total DESC"
    assert montar_resposta(linhas, sql) == (
        "Encontrei 2 registros. Veja a tabela abaixo. "
        "Primeiro da lista: Fornecedor: ACME; Valor total: R$ 5.000,00.")


def test_order_by_so_dentro_de_janela_ou_subconsulta_nao_conta():
    linhas = [{"A": 1}, {"A": 2}]
    janela = "SELECT RANK() OVER (ORDER BY amount) AS a FROM po_lines_all"
    sub = "SELECT a FROM (SELECT a FROM po_lines_all ORDER BY a)"
    assert "Primeiro" not in montar_resposta(linhas, janela)
    assert "Primeiro" not in montar_resposta(linhas, sub)


def test_order_by_com_sql_ilegivel_nao_quebra():
    assert montar_resposta([{"A": 1}, {"A": 2}], "SELECT FROM WHERE ((") == "Encontrei 2 registros. Veja a tabela abaixo."


def test_mais_de_tres_colunas_nao_cita_primeiro_da_lista():
    linha = {f"C{i}": i for i in range(4)}
    txt = montar_resposta([linha, linha], "SELECT * FROM po_lines_all ORDER BY c0")
    assert txt == "Encontrei 2 registros. Veja a tabela abaixo."


def test_tres_colunas_cita_primeiro_sem_reticencias():
    linha = {"A": 1, "B": 2, "C": 3}
    txt = montar_resposta([linha, linha], "SELECT * FROM po_lines_all ORDER BY a")
    assert txt.endswith("Primeiro da lista: A: 1; B: 2; C: 3.") and "..." not in txt


def test_rotulos_iguais_aos_da_tela():
    import re
    from pathlib import Path
    js = (Path(__file__).parent.parent / "src" / "static" / "index.html").read_text(encoding="utf-8")
    bloco = re.search(r"const NOMES_COLUNAS = \{(.*?)\n\};", js, re.S).group(1)
    assert dict(re.findall(r'(\w+): "([^"]+)"', bloco)) == NOMES_COLUNAS


def test_modo_relatorio():
    assert montar_resposta([{"A": 1}] * 3, relatorio=True) == "Planilha pronta com 3 registros."
    assert montar_resposta([{"A": 1}], relatorio=True) == "Planilha pronta com 1 registro."


def test_aviso_de_limite_de_linhas(monkeypatch):
    monkeypatch.setattr(config, "MAX_ROWS", 3)
    txt = montar_resposta([{"A": 1}] * 3)
    assert txt == ("Encontrei 3 registros. Veja a tabela abaixo. O resultado foi limitado a 3 linhas. "
                   "Para ver tudo, refine a pergunta (por exemplo, por período ou fornecedor).")


def test_sem_aviso_abaixo_do_limite(monkeypatch):
    monkeypatch.setattr(config, "MAX_ROWS", 3)
    assert montar_resposta([{"A": 1}] * 2) == "Encontrei 2 registros. Veja a tabela abaixo."


def test_aviso_de_limite_vem_depois_do_primeiro_da_lista(monkeypatch):
    monkeypatch.setattr(config, "MAX_ROWS", 2)
    txt = montar_resposta([{"A": 1}, {"A": 2}], "SELECT a FROM po_lines_all ORDER BY a")
    assert txt.endswith("refine a pergunta (por exemplo, por período ou fornecedor).")
    assert "Primeiro da lista: A: 1." in txt


def test_resultado_informa_limitado(monkeypatch):
    from pipeline import Resultado
    monkeypatch.setattr(config, "MAX_ROWS", 2)
    assert Resultado(pergunta="x", linhas=[{"A": 1}] * 2).dict()["limitado"] is True
    assert Resultado(pergunta="x", linhas=[{"A": 1}]).dict()["limitado"] is False
    assert Resultado(pergunta="x").dict()["max_rows"] == 2


@pytest.mark.parametrize("col,esperado", [
    ("total_ordens_abertas", "Total de ordens abertas"),
    ("total_ordens_canceladas", "Total de ordens canceladas"),
    ("qtd_pedidos", "Quantidade de pedidos"),
    ("quantidade_itens", "Quantidade de itens"),
    ("data_criacao", "Data de criação"),
    ("data_aprovacao", "Data de aprovacao"),
    ("valor_total", "Valor total"),
    ("preco_medio", "Preço médio"),
    ("valor_total_gasto", "Valor total gasto"),
    ("valor_pago", "Valor pago"),
    ("numero_requisicao", "Número de requisição"),
    ("ultima_compra", "Última compra"),
    ("situacao_ordem", "Situação ordem"),
    ("mes_ano", "Mês ano"),
    ("organizacao", "Organização"),
])
def test_fallback_de_rotulos(col, esperado):
    assert rotulo(col) == esperado
    assert rotulo(col.upper()) == esperado


def test_mapa_tem_prioridade_sobre_o_fallback():
    assert rotulo("total_ordens") == "Total de ordens"
    assert rotulo("numero_ordem") == "Número da ordem"
    assert rotulo("descricao_item") == "Descrição do item"


EXEMPLOS_FALLBACK = [
    "total_ordens_abertas", "total_ordens_canceladas", "qtd_pedidos", "quantidade_itens", "valor_total_gasto",
    "valor_pago", "preco_medio_ponderado", "numero_requisicao", "data_aprovacao", "ultima_compra",
    "ultimo_preco", "situacao_ordem", "mes_ano", "TOTAL_AMOUNT", "valor_unitario",
]


def test_fallback_igual_na_tela_e_no_python(tmp_path):
    """Executa nomeColuna() do index.html no Node e compara com rotulo() do Python."""
    import json
    import re
    import shutil
    import subprocess
    from pathlib import Path
    node = shutil.which("node")
    if not node:
        pytest.skip("Node não instalado")
    html = (Path(__file__).parent.parent / "src" / "static" / "index.html").read_text(encoding="utf-8")
    ini = html.index("const NOMES_COLUNAS = {")
    fim = html.index("function tabela(")
    js = html[ini:fim] + f"\nconsole.log(JSON.stringify({json.dumps(EXEMPLOS_FALLBACK)}.map(nomeColuna)));"
    arq = tmp_path / "rotulos.js"
    arq.write_text(js, encoding="utf-8")
    saida = subprocess.run([node, str(arq)], capture_output=True, text=True, encoding="utf-8", check=True).stdout
    assert json.loads(saida) == [rotulo(c) for c in EXEMPLOS_FALLBACK]


def test_tabela_da_tela_trata_o_limite_do_servidor():
    from pathlib import Path
    html = (Path(__file__).parent.parent / "src" / "static" / "index.html").read_text(encoding="utf-8")
    assert "O CSV traz todas." in html
    assert "O resultado foi limitado a ${maxRows ?? linhas.length} linhas pelo sistema." in html


def test_milhar_nas_contagens_de_varias_linhas():
    assert montar_resposta([{"A": 1}] * 1200).startswith("Encontrei 1.200 registros.")


def test_rotulo_e_sem_travessao():
    assert rotulo("VALOR_TOTAL_BRL") == "Valor total brl"
    assert "—" not in montar_resposta([{"A": None}, {"A": 1}])
    assert formatar_valor("X", None) == "(vazio)"
