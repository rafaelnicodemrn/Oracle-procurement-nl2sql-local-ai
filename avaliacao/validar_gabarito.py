r"""Valida um arquivo de gabarito antes de gastar uma rodada de avaliação.

Uso (a partir da raiz do projeto):
  .venv\Scripts\python.exe avaliacao\validar_gabarito.py                      # offline: só guardrails e estrutura
  .venv\Scripts\python.exe avaliacao\validar_gabarito.py --executar           # também roda os SQLs de referência no Oracle
  .venv\Scripts\python.exe avaliacao\validar_gabarito.py --gabarito avaliacao\gabarito.json

Sem --executar não há nenhuma chamada de rede. Com --executar há uma consulta SELECT ao BIP por pergunta
(sem IA), e o relatório mostra quantas linhas cada referência devolveu e se alguma ficou vazia ou só com zeros.
"""

from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(_AQUI.parent / "src"))
sys.path.insert(0, str(_AQUI))

import config  # noqa: E402
import guardrails  # noqa: E402
from avaliar_conjunto import GABARITO_PADRAO, gabarito_valido  # noqa: E402
from bip_client import BIPError, executar_sql  # noqa: E402


def validar_estrutura(dados: dict) -> list[str]:
    problemas = []
    ids = [q["id"] for q in dados.get("perguntas", [])]
    if len(ids) != len(set(ids)):
        problemas.append("ids de perguntas repetidos")
    for q in dados.get("perguntas", []):
        for campo in ("id", "nivel", "pergunta", "sql_referencia"):
            if campo not in q:
                problemas.append(f"pergunta {q.get('id', '?')}: falta o campo {campo}")
        if len(q.get("pergunta", "")) > config.MAX_PERGUNTA_CHARS:
            problemas.append(f"pergunta {q.get('id')}: passa de {config.MAX_PERGUNTA_CHARS} caracteres")
        g = guardrails.validar(q.get("sql_referencia", ""))
        if not g.aprovado:
            problemas.append(f"pergunta {q.get('id')}: SQL de referência reprovado nos guardrails: {'; '.join(g.motivos)}")
    return problemas


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gabarito", type=Path, default=GABARITO_PADRAO)
    ap.add_argument("--executar", action="store_true")
    args = ap.parse_args()

    dados = json.loads(args.gabarito.read_text(encoding="utf-8"))
    problemas = validar_estrutura(dados)
    print(f"{args.gabarito.name}: {len(dados['perguntas'])} perguntas, {len(dados.get('ataques', []))} ataques")
    print("Estrutura e guardrails:", "OK" if not problemas else "PROBLEMAS")
    for p in problemas:
        print("  -", p)

    inuteis = []
    if args.executar:
        print("\nExecutando referências no Oracle (uma consulta por pergunta)")
        for q in dados["perguntas"]:
            try:
                gold, erro = executar_sql(q["sql_referencia"], 1000), ""
            except BIPError as e:
                gold, erro = [], str(e)
            ok, motivo = gabarito_valido(gold, erro)
            print(f"  [{q['id']:>2}] N{q['nivel']} {len(gold):>4} linhas  {'ok' if ok else 'INUTIL: ' + motivo}  {erro[:100]}")
            if not ok:
                inuteis.append(q["id"])
        print("\nReferências inúteis (serão descartadas na avaliação):", inuteis or "nenhuma")
    sys.exit(1 if problemas else 0)


if __name__ == "__main__":
    main()
