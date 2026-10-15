"""API FastAPI do NL2SQL Procurement.

Rodar:  uvicorn app:app --host 127.0.0.1 --reload
Tela:   http://127.0.0.1:8000
Docs:   http://127.0.0.1:8000/docs
"""


from __future__ import annotations
import os
import threading
import time

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

import config
import guardrails
import llm
from pipeline import Resultado, perguntar

app = FastAPI(title="NL2SQL Procurement", version="1.0")

# Uma pergunta por vez: evita chamadas paralelas à IA local e ao Fusion
_consulta_em_andamento = threading.Lock()


def _offline() -> bool:
    """Modo de demonstração sem IA nem Oracle (DEMO_OFFLINE=true), só para conferir a tela."""
    return os.environ.get("DEMO_OFFLINE", "").strip().lower() in ("1", "true", "sim")


SQL_EXEMPLO = (
    "SELECT pha.segment1 AS numero_ordem, pha.creation_date AS data_criacao,\n"
    "       SUM(pla.amount) AS valor_total\n"
    "FROM po_headers_all pha\n"
    "JOIN po_lines_all pla ON pla.po_header_id = pha.po_header_id\n"
    "WHERE pha.creation_date >= DATE '2026-01-01'\n"
    "GROUP BY pha.segment1, pha.creation_date")


def _simulada(pergunta: str) -> Resultado:
    """Resposta fictícia nos status ok, bloqueado, sql_invalido e erro_execucao. Não chama IA nem Oracle."""
    time.sleep(1.5)
    p = pergunta.lower()
    base = dict(pergunta=pergunta, tentativas=1, tokens_entrada=2100, tokens_saida=150,
                custo_usd=0.0, latencia_llm_s=1.4, latencia_bip_s=3.1, latencia_total_s=4.6)
    if any(k in p for k in ("apague", "drop", "delete", "ignore")):
        sql = "DROP TABLE po_lines_all"
        return Resultado(status="bloqueado", sql=sql, resposta="Consulta bloqueada pelas regras de segurança.",
                         motivos_bloqueio=["Só é permitido SELECT (encontrado: DROP)",
                                           "Tabela fora da whitelist ou comando proibido: po_lines_all"],
                         **{**base, "latencia_bip_s": 0.0})
    if "sqlinvalido" in p:
        return Resultado(status="sql_invalido", sql="SELECT FROM WHERE", erro="Não foi possível interpretar o SQL",
                         resposta="A IA não gerou um SQL válido para esta pergunta.", **{**base, "tentativas": 2})
    if "erro" in p:
        return Resultado(status="erro_execucao", sql="SELECT campo_inexistente FROM po_headers_all",
                         erro="ORA-00904: \"CAMPO_INEXISTENTE\": identificador inválido",
                         resposta="Não foi possível executar a consulta gerada.", **{**base, "tentativas": 2})
    linhas = [{"NUMERO_ORDEM": "PO-1001", "DATA_CRIACAO": "2026-03-14T10:22:00", "VALOR_TOTAL": 15234.5, "QUANTIDADE": 1200},
              {"NUMERO_ORDEM": "PO-1002", "DATA_CRIACAO": "2026-03-15T08:05:00", "VALOR_TOTAL": 980.0, "QUANTIDADE": 35},
              {"NUMERO_ORDEM": "PO-1003", "DATA_CRIACAO": "2026-04-02T16:40:00", "VALOR_TOTAL": 120450.75, "QUANTIDADE": 8000}]
    return Resultado(status="ok", linhas=linhas, resposta="Resposta simulada (modo demonstração offline).",
                     sql=SQL_EXEMPLO, **base)


class Pergunta(BaseModel):
    pergunta: str = Field(min_length=1, max_length=config.MAX_PERGUNTA_CHARS)


class SQLManual(BaseModel):
    sql: str = Field(max_length=10_000)


@app.get("/", response_class=HTMLResponse)
def tela():
    return (config.STATIC_DIR / "index.html").read_text(encoding="utf-8")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/perguntar")
def endpoint_perguntar(p: Pergunta):
    if not _consulta_em_andamento.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="Já existe uma consulta em andamento. Aguarde o resultado.")
    try:
        if _offline():
            return _simulada(p.pergunta).dict()
        return perguntar(p.pergunta).dict()
    finally:
        _consulta_em_andamento.release()


@app.get("/uso")
def uso():
    """Uso acumulado da IA local (lê dados/uso_llm.csv, não chama a IA)."""
    if _offline():
        return {"modelo": config.LLM_MODELO, "chamadas": 0, "tokens": 0, "latencia_media_s": 0.0,
                "linhas_ilegiveis": 0, "offline": True}
    return {**llm.uso_acumulado(), "offline": False}


@app.post("/validar")
def endpoint_validar(s: SQLManual):
    """Mostra a decisão dos guardrails para um SQL qualquer (usado na demo de segurança)."""
    r = guardrails.validar(s.sql)
    return {"aprovado": r.aprovado, "sql": r.sql, "motivos": r.motivos}
