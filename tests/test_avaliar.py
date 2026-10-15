"""Testes das métricas de acurácia (sem rede)."""

from __future__ import annotations

from avaliar import _norm, _percentil, ex_estrito, ex_relaxado


def test_norm():
    assert _norm(None) is None
    assert _norm(10) == 10.0
    assert _norm("10.004") == 10.0
    assert _norm(" po-ct-7 ") == "PO-CT-7"
    assert _norm(True) == "True"


def test_estrito_ignora_ordem_e_nome_de_coluna():
    gold = [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}]
    pred = [{"num": "y", "valor": 2}, {"num": "x", "valor": 1.0}]
    assert ex_estrito(gold, pred)


def test_estrito_falha_com_coluna_extra():
    gold = [{"a": 1}]
    pred = [{"a": 1, "b": 2}]
    assert not ex_estrito(gold, pred)


def test_estrito_considera_duplicatas():
    assert not ex_estrito([{"a": 1}, {"a": 1}], [{"a": 1}])


def test_estrito_vazios():
    assert ex_estrito([], [])


def test_relaxado_tolera_coluna_extra():
    gold = [{"qtd": 5}]
    pred = [{"total": 5, "descricao": "ordens"}]
    assert ex_relaxado(gold, pred)


def test_relaxado_falha_com_valor_diferente():
    assert not ex_relaxado([{"qtd": 5}], [{"qtd": 6}])


def test_relaxado_falha_com_numero_de_linhas_diferente():
    assert not ex_relaxado([{"a": 1}], [{"a": 1}, {"a": 2}])


def test_relaxado_vazios():
    assert ex_relaxado([], [])


def test_relaxado_arredonda_duas_casas():
    assert ex_relaxado([{"v": 10.001}], [{"v": "10.004", "x": 1}])


def test_percentil():
    assert _percentil([], 95) == 0.0
    assert _percentil([1, 2, 3, 4, 5], 50) == 3
    assert _percentil([1, 2, 3, 4, 5], 100) == 5
