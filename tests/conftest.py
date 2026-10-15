"""Configuração comum dos testes.

Nenhum teste pode chamar a IA local (Ollama) nem o BIP de verdade. As travas abaixo fazem
o teste falhar se algum código tentar sair para a rede sem mock.
"""

from __future__ import annotations
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(RAIZ / "avaliacao"))

import bip_client  # noqa: E402
import config  # noqa: E402
import llm  # noqa: E402
import pipeline  # noqa: E402


class ChamadaRealProibida(AssertionError):
    pass


def _proibido(nome):
    def _f(*args, **kwargs):
        raise ChamadaRealProibida(f"Teste tentou chamar {nome} de verdade. Use mock.")
    return _f


@pytest.fixture(autouse=True)
def bloquear_rede(monkeypatch, tmp_path):
    """Bloqueia requests (BIP e Ollama) e a chamada à IA local, e isola o CSV de uso."""
    import requests
    monkeypatch.setattr(requests, "post", _proibido("requests.post (BIP ou Ollama)"))
    monkeypatch.setattr(requests, "get", _proibido("requests.get (Ollama)"))
    monkeypatch.setattr(bip_client.requests, "post", _proibido("requests.post (BIP)"))
    monkeypatch.setattr(llm, "_post", _proibido("a IA local (Ollama)"))
    monkeypatch.setattr(llm, "ARQ_USO", tmp_path / "uso_teste.csv")
    monkeypatch.setattr(config, "BIP_HOST", "https://bip.exemplo.invalid")
    monkeypatch.setattr(config, "BIP_REPORT_PATH", "/Custom/Teste/RunSQL.xdo")
    monkeypatch.setattr(config, "BIP_USER", "usuario_teste")
    monkeypatch.setattr(config, "BIP_PASS", "senha_teste")
    yield


def resp_llm(texto: str, tin: int = 100, tout: int = 20, lat: float = 0.1) -> llm.RespostaLLM:
    return llm.RespostaLLM(texto=texto, tokens_entrada=tin, tokens_saida=tout, latencia_s=lat)


@pytest.fixture
def mock_pipeline(monkeypatch):
    """Substitui as funções de IA e BIP usadas pelo pipeline.

    Uso: m = mock_pipeline(sqls=[...], bip=[linhas ou BIPError])
    Devolve um objeto com as listas de chamadas registradas.
    """
    class Mock:
        pass

    def configurar(sqls, bip=None):
        m = Mock()
        m.sqls = list(sqls)
        m.bip = list(bip or [])
        m.chamadas_gerar, m.chamadas_corrigir, m.chamadas_bip = [], [], []

        def gerar_sql(pergunta):
            m.chamadas_gerar.append(pergunta)
            return resp_llm(m.sqls.pop(0))

        def corrigir_sql(pergunta, sql_anterior, erro):
            m.chamadas_corrigir.append((pergunta, sql_anterior, erro))
            return resp_llm(m.sqls.pop(0))

        def executar_sql(sql, limite=None):
            m.chamadas_bip.append((sql, limite))
            r = m.bip.pop(0)
            if isinstance(r, Exception):
                raise r
            return r

        monkeypatch.setattr(pipeline.llm, "gerar_sql", gerar_sql)
        monkeypatch.setattr(pipeline.llm, "corrigir_sql", corrigir_sql)
        monkeypatch.setattr(pipeline, "executar_sql", executar_sql)
        return m

    return configurar
