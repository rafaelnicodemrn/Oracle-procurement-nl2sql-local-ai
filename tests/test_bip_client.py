"""Testes do cliente BIP com requests.post simulado. O contrato SOAP não é alterado."""

from __future__ import annotations
import base64
import json

import pytest

import bip_client
import config
from bip_client import BIPError


class RespostaFalsa:
    def __init__(self, status_code=200, text=""):
        self.status_code = status_code
        self.text = text


def _soap(xml_relatorio: str) -> str:
    b64 = base64.b64encode(xml_relatorio.encode("utf-8")).decode()
    return ("<env:Envelope xmlns:env=\"http://www.w3.org/2003/05/soap-envelope\"><env:Body>"
            "<ns2:runReportResponse xmlns:ns2=\"http://xmlns.oracle.com/oxp/service/PublicReportService\">"
            f"<ns2:runReportReturn><ns2:reportBytes>{b64}</ns2:reportBytes></ns2:runReportReturn>"
            "</ns2:runReportResponse></env:Body></env:Envelope>")


@pytest.fixture
def post_falso(monkeypatch):
    chamadas = []

    def configurar(resposta: RespostaFalsa):
        def post(url, data=None, headers=None, auth=None, timeout=None):
            chamadas.append({"url": url, "data": data.decode("utf-8"), "headers": headers,
                             "auth": auth, "timeout": timeout})
            return resposta
        monkeypatch.setattr(bip_client.requests, "post", post)
        return chamadas

    return configurar


def test_json_doc_simples(post_falso):
    linhas = [{"NUMERO": "PO-1", "VALOR": 10.5}, {"NUMERO": "PO-2", "VALOR": 3}]
    post_falso(RespostaFalsa(200, _soap(f"<DATA_DS><G_1><JSON_DOC>{json.dumps(linhas)}</JSON_DOC></G_1></DATA_DS>")))
    assert bip_client.executar_sql("SELECT 1 FROM dual", 5) == linhas


def test_json_doc_com_cdata(post_falso):
    linhas = [{"NOME": "A & B <ltda>"}]
    xml = f"<DATA_DS><JSON_DOC><![CDATA[{json.dumps(linhas)}]]></JSON_DOC></DATA_DS>"
    post_falso(RespostaFalsa(200, _soap(xml)))
    assert bip_client.executar_sql("SELECT 1 FROM dual") == linhas


def test_json_doc_com_entidades_html(post_falso):
    xml = '<DATA_DS><JSON_DOC>[{&quot;NOME&quot;:&quot;A &amp; B&quot;}]</JSON_DOC></DATA_DS>'
    post_falso(RespostaFalsa(200, _soap(xml)))
    assert bip_client.executar_sql("SELECT 1 FROM dual") == [{"NOME": "A & B"}]


def test_resposta_sem_json_doc_e_lista_vazia(post_falso):
    post_falso(RespostaFalsa(200, _soap("<DATA_DS><G_1/></DATA_DS>")))
    assert bip_client.executar_sql("SELECT 1 FROM dual") == []


def test_json_doc_vazio(post_falso):
    post_falso(RespostaFalsa(200, _soap("<DATA_DS><JSON_DOC></JSON_DOC></DATA_DS>")))
    assert bip_client.executar_sql("SELECT 1 FROM dual") == []


def test_erro_ora_no_relatorio(post_falso):
    xml = "<DATA_DS><ERRO>ORA-00942: table or view does not exist\n</ERRO></DATA_DS>"
    post_falso(RespostaFalsa(200, _soap(xml)))
    with pytest.raises(BIPError, match="ORA-00942: table or view does not exist"):
        bip_client.executar_sql("SELECT 1 FROM dual")


def test_erro_ora_em_http_500(post_falso):
    post_falso(RespostaFalsa(500, "<faultstring>oracle.xdo: ORA-00904: &quot;X&quot;: invalid identifier</faultstring>"))
    with pytest.raises(BIPError, match=r'HTTP 500: ORA-00904: "X": invalid identifier'):
        bip_client.executar_sql("SELECT x FROM dual")


def test_http_401(post_falso):
    post_falso(RespostaFalsa(401, "Unauthorized"))
    with pytest.raises(BIPError, match="HTTP 401"):
        bip_client.executar_sql("SELECT 1 FROM dual")


def test_resposta_sem_report_bytes(post_falso):
    post_falso(RespostaFalsa(200, "<env:Envelope><env:Body/></env:Envelope>"))
    with pytest.raises(BIPError, match="sem reportBytes"):
        bip_client.executar_sql("SELECT 1 FROM dual")


def test_sem_credenciais_nao_chama_rede(monkeypatch):
    monkeypatch.setattr(config, "BIP_USER", "")
    with pytest.raises(BIPError, match="BIP_USER"):
        bip_client.executar_sql("SELECT 1 FROM dual")


def test_contrato_do_envelope(post_falso):
    """Protege o contrato validado: p_sql, p_rows, caminho do relatório e escape do SQL."""
    chamadas = post_falso(RespostaFalsa(200, _soap("<DATA_DS/>")))
    bip_client.executar_sql("SELECT 'a<b' AS t FROM dual", 7)
    c = chamadas[0]
    assert c["url"] == config.BIP_ENDPOINT
    assert c["auth"] == (config.BIP_USER, config.BIP_PASS)
    assert c["headers"]["Content-Type"].startswith("application/soap+xml")
    assert c["timeout"] == config.BIP_TIMEOUT
    corpo = c["data"]
    assert "<pub:runReport>" in corpo
    assert f"<pub:name>{config.BIP_PARAM_SQL}</pub:name>" in corpo
    assert f"<pub:name>{config.BIP_PARAM_ROWS}</pub:name>" in corpo
    assert "<pub:item>7</pub:item>" in corpo
    assert "SELECT &apos;a&lt;b&apos; AS t FROM dual" in corpo or "SELECT 'a&lt;b' AS t FROM dual" in corpo
    assert f"<pub:reportAbsolutePath>{config.BIP_REPORT_PATH}</pub:reportAbsolutePath>" in corpo
    assert config.BIP_PARAM_SQL == "p_sql" and config.BIP_PARAM_ROWS == "p_rows"


def test_limite_padrao_e_max_rows(post_falso):
    chamadas = post_falso(RespostaFalsa(200, _soap("<DATA_DS/>")))
    bip_client.executar_sql("SELECT 1 FROM dual")
    assert f"<pub:item>{config.MAX_ROWS}</pub:item>" in chamadas[0]["data"]
