"""Pipeline NL2SQL: pergunta -> IA local (Ollama) -> guardrails -> BIP -> resposta local."""


from __future__ import annotations
import logging
import re
import time
from dataclasses import asdict, dataclass, field

import requests

import config
import guardrails
import llm
from bip_client import BIPError, executar_sql
from resposta import montar_resposta

log = logging.getLogger("nl2sql")


@dataclass
class Resultado:
    pergunta: str
    status: str = "erro"  # ok | bloqueado | sql_invalido | erro_execucao | sem_resposta | erro
    sql: str = ""
    linhas: list[dict] = field(default_factory=list)
    resposta: str = ""
    motivos_bloqueio: list[str] = field(default_factory=list)
    erro: str = ""
    tentativas: int = 0
    tokens_entrada: int = 0
    tokens_saida: int = 0
    custo_usd: float = 0.0
    latencia_llm_s: float = 0.0
    latencia_bip_s: float = 0.0
    latencia_total_s: float = 0.0

    def dict(self) -> dict:
        d = asdict(self)
        # True quando o servidor cortou o resultado no limite (nem o CSV traz tudo)
        d["limitado"] = len(self.linhas) >= config.MAX_ROWS
        d["max_rows"] = config.MAX_ROWS
        return d


def _somar(r: Resultado, resp: llm.RespostaLLM) -> None:
    r.tokens_entrada += resp.tokens_entrada
    r.tokens_saida += resp.tokens_saida
    r.custo_usd += resp.custo_usd
    r.latencia_llm_s += resp.latencia_s


def erro_bip_seguro(e: BIPError) -> str:
    """Mensagem do BIP para a tela: mantém código e texto ORA, esconde o resto da resposta do servidor."""
    texto = str(e)
    m = re.search(r"ORA-\d{5}[^\n<]*", texto)
    if m:
        return m.group(0).strip()[:300]
    if texto.startswith("HTTP 401") or texto.startswith("BIP_USER") or texto.startswith("BIP_HOST"):
        return texto
    m = re.match(r"HTTP (\d{3})", texto)
    if m:
        return f"O Oracle respondeu com erro HTTP {m.group(1)}."
    return "Resposta inesperada do Oracle."


def erro_seguro(e: Exception) -> str:
    """Mensagem para a tela sem stack trace, URL ou caminho interno. O detalhe vai para o log."""
    if isinstance(e, llm.IAIndisponivel):
        return str(e)
    if isinstance(e, BIPError):
        return erro_bip_seguro(e)
    if isinstance(e, requests.Timeout):
        return f"O Oracle não respondeu em {config.BIP_TIMEOUT} s."
    if isinstance(e, requests.ConnectionError):
        return "Sem conexão com o Oracle. Verifique a rede ou a VPN."
    return "Erro interno. Detalhes no console do servidor."


def perguntar(pergunta: str, resumir: bool | None = None) -> Resultado:
    # `resumir` é ignorado: a resposta agora é sempre montada localmente (resposta.py).
    # O parâmetro continua aceito só para não quebrar chamadas antigas, como a do avaliar.py.
    inicio = time.perf_counter()
    r = Resultado(pergunta=pergunta)

    try:
        resp = llm.gerar_sql(pergunta)
        _somar(r, resp)
        sql_atual = resp.texto

        for tentativa in range(1 + config.TENTATIVAS_CORRECAO):
            r.tentativas = tentativa + 1
            pode_corrigir = tentativa < config.TENTATIVAS_CORRECAO

            if sql_atual.strip().upper().startswith("SEM_RESPOSTA"):
                r.status = "sem_resposta"
                r.resposta = "Não consigo responder essa pergunta com os dados de compras disponíveis."
                break

            g = guardrails.validar(sql_atual)
            r.sql = g.sql
            if not g.aprovado and g.sql_invalido:
                # SQL que não pôde ser interpretado e sem motivo de segurança: pede correção
                r.status = "sql_invalido"
                r.erro = "; ".join(g.motivos)
                if pode_corrigir:
                    resp = llm.corrigir_sql(pergunta, g.sql, r.erro)
                    _somar(r, resp)
                    sql_atual = resp.texto
                    continue
                break
            if not g.aprovado:
                # Bloqueio de guardrail é definitivo: não pede correção à IA
                r.status = "bloqueado"
                r.motivos_bloqueio = g.motivos
                r.erro = ""
                r.resposta = "Consulta bloqueada pelas regras de segurança."
                break

            try:
                t0 = time.perf_counter()
                r.linhas = executar_sql(g.sql, config.MAX_ROWS)
                r.latencia_bip_s += time.perf_counter() - t0
                r.status = "ok"
                r.erro = ""
                break
            except BIPError as e:
                r.latencia_bip_s += time.perf_counter() - t0
                log.warning("Erro do BIP: %s", e)
                r.status = "erro_execucao"
                r.erro = erro_bip_seguro(e)
                if pode_corrigir:
                    resp = llm.corrigir_sql(pergunta, g.sql, r.erro)
                    _somar(r, resp)
                    sql_atual = resp.texto

        if r.status == "ok":
            r.resposta = montar_resposta(r.linhas, r.sql)
        elif r.status == "erro_execucao":
            r.resposta = "Não foi possível executar a consulta gerada."
        elif r.status == "sql_invalido":
            r.resposta = "A IA não gerou um SQL válido para esta pergunta."

    except Exception as e:  # noqa: BLE001
        log.exception("Erro ao processar a pergunta")
        r.status = "erro"
        r.erro = erro_seguro(e)
        r.resposta = "Erro interno ao processar a pergunta."

    r.latencia_total_s = time.perf_counter() - inicio
    return r


if __name__ == "__main__":
    import json
    import sys

    p = " ".join(sys.argv[1:]) or "Quais as 5 últimas ordens de compra criadas?"
    res = perguntar(p)
    print(json.dumps(res.dict(), indent=2, ensure_ascii=False, default=str))
