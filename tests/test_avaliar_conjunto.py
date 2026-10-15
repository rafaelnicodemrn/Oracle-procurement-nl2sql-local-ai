"""Testes do avaliador de conjunto de teste (sem rede)."""

from __future__ import annotations
import json
from pathlib import Path

import pytest

import avaliar_conjunto as ac
import config
import guardrails
from bip_client import BIPError

RAIZ = Path(__file__).resolve().parent.parent
GABARITO_TESTE = RAIZ / "avaliacao" / "gabarito_teste.json"
GABARITO_ORIGINAL = RAIZ / "avaliacao" / "gabarito.json"


def test_wilson_limites():
    assert ac.wilson(0, 0) == (0.0, 0.0)
    lo, hi = ac.wilson(10, 10)
    assert hi == pytest.approx(1.0) and 0.7 < lo < 1.0
    lo, hi = ac.wilson(5, 10)
    assert lo < 0.5 < hi


def test_gabarito_valido():
    assert ac.gabarito_valido([{"a": 3}]) == (True, "")
    assert not ac.gabarito_valido([])[0]
    assert not ac.gabarito_valido([{"qtd": 0}])[0]
    assert not ac.gabarito_valido([{"qtd": None}])[0]
    assert not ac.gabarito_valido([{"a": 1}], "ORA-00942")[0]
    assert ac.gabarito_valido([{"a": 0}, {"a": 2}])[0]


def test_diagnostico():
    assert ac.diagnostico("ok", True, True, 1, 1) == "correto"
    assert ac.diagnostico("ok", False, True, 1, 1) == "correto com colunas extras"
    assert "diferente" in ac.diagnostico("ok", False, False, 5, 4)
    assert ac.diagnostico("ok", False, False, 5, 5) == "mesmas linhas, valores diferentes"
    assert ac.diagnostico("sem_resposta", False, False, 1, 0).startswith("IA recusou")


def _reg(rep, qid, nivel, estrito, relaxado, valido=True, lat=2.0):
    return {"rep": rep, "id": qid, "nivel": nivel, "pergunta": f"p{qid}", "valido_gabarito": valido,
            "ex_estrito": estrito, "ex_relaxado": relaxado, "status": "ok", "tentativas": 1,
            "latencia_total_s": lat, "latencia_llm_s": 1.0, "latencia_bip_s": 1.0,
            "tokens_entrada": 100, "tokens_saida": 10, "custo_usd": 0.001,
            "diagnostico": "correto" if relaxado else "mesmas linhas, valores diferentes"}


def test_agregar_media_minimo_maximo_e_estabilidade():
    regs = []
    # pergunta 1 sempre certa; pergunta 2 certa só na rodada 1; pergunta 3 sempre errada; pergunta 4 inválida
    for rep in (1, 2):
        regs.append(_reg(rep, 1, 1, True, True))
        regs.append(_reg(rep, 2, 2, rep == 1, rep == 1))
        regs.append(_reg(rep, 3, 2, False, False))
        regs.append(_reg(rep, 4, 3, False, False, valido=False))
    agg = ac.agregar(regs, 2)
    assert agg["perguntas_validas"] == 3
    assert agg["perguntas_descartadas"] == [4]
    t = agg["total"]
    assert t["relaxado"]["max"] == pytest.approx(200 / 3)
    assert t["relaxado"]["min"] == pytest.approx(100 / 3)
    assert t["relaxado"]["media"] == pytest.approx(50.0)
    assert agg["sempre_certas"] == [1]
    assert agg["instaveis"] == [2]
    assert agg["sempre_erradas"] == [3]
    assert agg["por_nivel"][2]["perguntas"] == 2
    assert t["relaxado_agrupado"]["acertos"] == 3 and t["relaxado_agrupado"]["execucoes"] == 6


def test_rodar_com_mocks(monkeypatch):
    from pipeline import Resultado

    def falso_perguntar(pergunta, resumir=None):
        if "errada" in pergunta:
            return Resultado(pergunta=pergunta, status="ok", sql="SELECT 1 FROM dual", linhas=[{"x": 9}], tentativas=1)
        return Resultado(pergunta=pergunta, status="ok", sql="SELECT 1 FROM dual", linhas=[{"x": 5, "extra": 1}], tentativas=1)

    monkeypatch.setattr(ac, "perguntar", falso_perguntar)
    perguntas = [{"id": 1, "nivel": 1, "pergunta": "certa", "sql_referencia": "x"},
                 {"id": 2, "nivel": 1, "pergunta": "errada", "sql_referencia": "x"},
                 {"id": 3, "nivel": 2, "pergunta": "inutil", "sql_referencia": "x"}]
    golds = {1: {"linhas": [{"a": 5}], "valido": True, "motivo": ""},
             2: {"linhas": [{"a": 5}], "valido": True, "motivo": ""},
             3: {"linhas": [], "valido": False, "motivo": "vazio"}}
    regs = ac.rodar(perguntas, golds, 2, pausa=0)
    assert len(regs) == 6
    agg = ac.agregar(regs, 2)
    assert agg["perguntas_descartadas"] == [3]
    assert agg["sempre_certas"] == [1] and agg["sempre_erradas"] == [2]
    assert all(r["ex_estrito"] is False for r in regs if r["id"] == 1)  # coluna extra reprova o estrito
    assert all(r["ex_relaxado"] for r in regs if r["id"] == 1)
    md = ac.montar_resumo(agg, regs, [], "t", GABARITO_TESTE)
    assert "Acurácia de execução" in md and "—" not in md


def test_executar_gabaritos_trata_erro_do_bip(monkeypatch):
    def falso(sql, limite=None):
        if "ruim" in sql:
            raise BIPError("ORA-00942: table or view does not exist")
        return [{"a": 1}]

    monkeypatch.setattr(ac, "executar_sql", falso)
    saida = ac.executar_gabaritos([{"id": 1, "sql_referencia": "bom"}, {"id": 2, "sql_referencia": "ruim"}])
    assert saida[1]["valido"] and not saida[2]["valido"]


# --- integridade do arquivo gabarito_teste.json

def _teste():
    if not GABARITO_TESTE.exists():
        pytest.skip("gabarito_teste.json tem dados reais e não é versionado")
    return json.loads(GABARITO_TESTE.read_text(encoding="utf-8"))


def test_gabarito_teste_estrutura():
    d = _teste()
    ids = [q["id"] for q in d["perguntas"]]
    assert len(ids) == len(set(ids)) == 20
    assert {q["nivel"] for q in d["perguntas"]} == {1, 2, 3}
    assert len(d["ataques"]) == 6


def test_gabarito_teste_referencias_passam_nos_guardrails():
    for q in _teste()["perguntas"]:
        r = guardrails.validar(q["sql_referencia"])
        assert r.aprovado, (q["id"], r.motivos)
        assert len(q["pergunta"]) <= config.MAX_PERGUNTA_CHARS
        assert not q["sql_referencia"].rstrip().endswith(";")


def test_gabarito_teste_nao_repete_perguntas_do_gabarito_original():
    if not GABARITO_ORIGINAL.exists():
        pytest.skip("gabarito.json tem dados reais e não é versionado")
    original = {q["pergunta"].strip().lower() for q in json.loads(GABARITO_ORIGINAL.read_text(encoding="utf-8"))["perguntas"]}
    novas = {q["pergunta"].strip().lower() for q in _teste()["perguntas"]}
    assert not (original & novas)
    original_sql = {q["sql_referencia"] for q in json.loads(GABARITO_ORIGINAL.read_text(encoding="utf-8"))["perguntas"]}
    assert not (original_sql & {q["sql_referencia"] for q in _teste()["perguntas"]})


def test_validador_de_estrutura():
    import validar_gabarito as vg
    assert vg.validar_estrutura(_teste()) == []
    ruim = {"perguntas": [{"id": 1, "nivel": 1, "pergunta": "x", "sql_referencia": "DELETE FROM po_headers_all"},
                          {"id": 1, "nivel": 1, "pergunta": "y", "sql_referencia": "SELECT 1 FROM dual"}]}
    probs = vg.validar_estrutura(ruim)
    assert any("repetidos" in p for p in probs) and any("reprovado" in p for p in probs)


def test_gabarito_exemplo_publico_e_valido():
    """O exemplo versionado precisa passar na mesma validação do gabarito real."""
    import validar_gabarito as vg
    d = json.loads((RAIZ / "avaliacao" / "gabarito_exemplo.json").read_text(encoding="utf-8"))
    assert vg.validar_estrutura(d) == []
    assert d["perguntas"] and d["ataques"]
