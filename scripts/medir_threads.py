r"""Mede a velocidade da IA local com diferentes números de threads. Não acessa o Oracle.

Uso (a partir da raiz do projeto):
  .venv\Scripts\python.exe scripts\medir_threads.py                          # modelo do .env, threads 0 8 6 4 2
  .venv\Scripts\python.exe scripts\medir_threads.py qwen2.5-coder:3b 0 4 6

0 = padrão do Ollama. Antes de cada medição o modelo é descarregado, para que todas
partam do mesmo ponto (carregar o modelo e processar o schema inteiro).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import requests  # noqa: E402

import config  # noqa: E402
import llm  # noqa: E402

PERGUNTA = "Qual comprador emitiu mais ordens de compra em 2026?"
TOKENS_SAIDA = 64      # suficiente para medir a velocidade de geração
TOKENS_SQL_MEDIO = 150  # tamanho típico de um SQL com junções
NS = 1e9


def descarregar(modelo: str) -> None:
    requests.post(llm._url("/api/generate"), json={"model": modelo, "keep_alive": 0}, timeout=120)


def medir(modelo: str, threads: int) -> dict:
    opcoes = {"temperature": 0, "seed": 42, "num_ctx": config.OLLAMA_NUM_CTX, "num_predict": TOKENS_SAIDA}
    if threads > 0:
        opcoes["num_thread"] = threads
    payload = {
        "model": modelo, "stream": False, "keep_alive": "5m", "options": opcoes,
        "messages": [{"role": "system", "content": llm.INSTRUCAO_SQL},
                     {"role": "user", "content": llm._delimitar("pergunta", PERGUNTA)}],
    }
    inicio = time.perf_counter()
    r = requests.post(llm._url("/api/chat"), json=payload, timeout=1200)
    r.raise_for_status()
    d = r.json()
    pe_n, pe_t = d.get("prompt_eval_count", 0), d.get("prompt_eval_duration", 0) / NS
    ev_n, ev_t = d.get("eval_count", 0), d.get("eval_duration", 0) / NS
    return {
        "total": time.perf_counter() - inicio,
        "carga": d.get("load_duration", 0) / NS,
        "schema": pe_t,
        "leitura": pe_n / pe_t if pe_t else 0.0,
        "geracao": ev_n / ev_t if ev_t else 0.0,
    }


def main() -> None:
    llm._conferir_execucao_local()
    args = sys.argv[1:]
    modelo = args[0] if args and not args[0].isdigit() else config.LLM_MODELO
    threads = [int(a) for a in args if a.isdigit()] or [0, 8, 6, 4, 2]
    print(f"Modelo: {modelo} | threads: {threads} | pergunta: {PERGUNTA}\n")
    print(f"{'threads':>8} | {'carga':>7} | {'schema':>8} | {'leitura':>11} | {'geração':>11} | {'SQL médio*':>10}")
    print("-" * 72)
    for t in threads:
        descarregar(modelo)
        try:
            m = medir(modelo, t)
        except requests.RequestException as e:
            print(f"{t or 'padrão':>8} | erro: {e}")
            continue
        sql_medio = TOKENS_SQL_MEDIO / m["geracao"] if m["geracao"] else 0
        print(f"{t or 'padrão':>8} | {m['carga']:6.1f}s | {m['schema']:7.1f}s | {m['leitura']:6.1f} tok/s"
              f" | {m['geracao']:6.2f} tok/s | {sql_medio:9.0f}s", flush=True)
    print(f"\n* SQL médio: tempo estimado para gerar {TOKENS_SQL_MEDIO} tokens com o schema já processado "
          "(caso das perguntas seguintes à primeira).")
    print("Para usar o melhor valor, coloque OLLAMA_NUM_THREAD=<threads> no .env.")


if __name__ == "__main__":
    main()
