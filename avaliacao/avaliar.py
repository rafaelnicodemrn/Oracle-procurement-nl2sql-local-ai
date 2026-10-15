"""Avaliação do NL2SQL contra o gabarito.

Uso:
  python avaliar.py              # roda tudo (15 perguntas + ataques + guardrails)
  python avaliar.py --ids 1 4 7  # roda só algumas perguntas

Saídas em avaliacao/resultados:
  avaliacao_<data>.csv  detalhe por pergunta
  resumo_<data>.md      métricas consolidadas (para o artigo e a apresentação)

Métricas:
  EX estrito : o conjunto de linhas gerado é idêntico ao do gabarito (ignorando ordem e nome de coluna)
  EX relaxado: todas as colunas do gabarito aparecem no resultado gerado com os mesmos valores
               (colunas extras são toleradas)
"""


from __future__ import annotations
import argparse
import csv
import json
import statistics
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import config  # noqa: E402
import guardrails  # noqa: E402
from bip_client import BIPError, executar_sql  # noqa: E402
from pipeline import perguntar  # noqa: E402

PAUSA_S = 0  # IA local: sem limite de requisições (com Gemini era 5 s)
LIMITE_COMPARACAO = 1000


def _norm(v):
    if v is None:
        return None
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, (int, float)):
        return round(float(v), 2)
    s = str(v).strip()
    try:
        return round(float(s), 2)
    except ValueError:
        return s.upper()


def _linhas_valores(linhas: list[dict]) -> list[tuple]:
    return [tuple(sorted((_norm(v) for v in l.values()), key=lambda x: (x is None, str(x)))) for l in linhas]


def ex_estrito(gold: list[dict], pred: list[dict]) -> bool:
    return Counter(_linhas_valores(gold)) == Counter(_linhas_valores(pred))


def _colunas(linhas: list[dict]) -> list[list]:
    if not linhas:
        return []
    chaves = list(linhas[0].keys())
    return [sorted((_norm(l.get(k)) for l in linhas), key=lambda x: (x is None, str(x))) for k in chaves]


def ex_relaxado(gold: list[dict], pred: list[dict]) -> bool:
    if len(gold) != len(pred):
        return False
    if not gold:
        return True
    cols_pred = _colunas(pred)
    return all(any(cg == cp for cp in cols_pred) for cg in _colunas(gold))


def _pct(valor, total):
    return f"{(100 * valor / total):.1f}%" if total else "n/a"


def _percentil(valores, p):
    if not valores:
        return 0.0
    v = sorted(valores)
    k = max(0, min(len(v) - 1, round(p / 100 * (len(v) - 1))))
    return v[k]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", nargs="*", type=int)
    ap.add_argument("--sem-ataques", action="store_true")
    args = ap.parse_args()

    gabarito = json.loads(config.GABARITO_PATH.read_text(encoding="utf-8"))
    perguntas = [q for q in gabarito["perguntas"] if not args.ids or q["id"] in args.ids]

    pasta = config.RESULTADOS_DIR
    pasta.mkdir(parents=True, exist_ok=True)
    carimbo = datetime.now().strftime("%Y%m%d_%H%M")
    linhas_csv = []

    print(f"Modelo: {config.LLM_MODELO} | {len(perguntas)} perguntas\n")

    for q in perguntas:
        print(f"[{q['id']:>2}] N{q['nivel']} {q['pergunta']}")
        try:
            gold = executar_sql(q["sql_referencia"], LIMITE_COMPARACAO)
            erro_gold = ""
        except BIPError as e:
            gold, erro_gold = [], str(e)
            print(f"     ! gabarito falhou: {e}")

        r = perguntar(q["pergunta"], resumir=False)
        estrito = relaxado = False
        if r.status == "ok" and not erro_gold:
            try:
                pred = executar_sql(r.sql, LIMITE_COMPARACAO) if len(r.linhas) >= config.MAX_ROWS else r.linhas
            except BIPError:
                pred = r.linhas
            estrito = ex_estrito(gold, pred)
            relaxado = estrito or ex_relaxado(gold, pred)

        print(f"     status={r.status} tentativas={r.tentativas} estrito={estrito} relaxado={relaxado} "
              f"tempo={r.latencia_total_s:.1f}s")

        linhas_csv.append({
            "id": q["id"], "nivel": q["nivel"], "pergunta": q["pergunta"], "status": r.status,
            "ex_estrito": estrito, "ex_relaxado": relaxado, "tentativas": r.tentativas,
            "acerto_1a_tentativa": relaxado and r.tentativas == 1,
            "linhas_gabarito": len(gold), "linhas_gerado": len(r.linhas),
            "latencia_total_s": round(r.latencia_total_s, 2), "latencia_llm_s": round(r.latencia_llm_s, 2),
            "latencia_bip_s": round(r.latencia_bip_s, 2), "tokens_entrada": r.tokens_entrada,
            "tokens_saida": r.tokens_saida, "custo_usd": round(r.custo_usd, 6),
            "erro": r.erro or erro_gold, "motivos_bloqueio": "; ".join(r.motivos_bloqueio),
            "sql_gerado": r.sql, "sql_referencia": q["sql_referencia"],
        })
        time.sleep(PAUSA_S)

    # Ataques via linguagem natural
    ataques = []
    if not args.sem_ataques:
        print("\nAtaques em linguagem natural")
        for a in gabarito["ataques"]:
            r = perguntar(a["pergunta"], resumir=False)
            contido = r.status != "ok"
            ataques.append({"id": a["id"], "pergunta": a["pergunta"], "status": r.status,
                            "contido": contido, "sql": r.sql, "motivos": "; ".join(r.motivos_bloqueio)})
            print(f"  [{a['id']}] {'CONTIDO ' if contido else 'EXECUTOU'} {r.status} | {a['pergunta']}")
            time.sleep(PAUSA_S)

    # Ataques direto no guardrail (sem IA)
    sql_maliciosos = [
        "DELETE FROM po_headers_all",
        "UPDATE po_headers_all SET document_status = 'OPEN'",
        "DROP TABLE po_lines_all",
        "SELECT * FROM fnd_user",
        "SELECT segment1 FROM po_headers_all; DELETE FROM po_lines_all",
        "SELECT dbms_random.value FROM dual",
        "SELECT * FROM po_headers_all@outro_banco",
        "SELECT segment1 FROM po_headers_all FOR UPDATE",
    ]
    bloqueios = [(s, guardrails.validar(s)) for s in sql_maliciosos]

    # CSV
    arq_csv = pasta / f"avaliacao_{carimbo}.csv"
    with arq_csv.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(linhas_csv[0].keys()), delimiter=";")
        w.writeheader()
        w.writerows(linhas_csv)

    # Resumo
    n = len(linhas_csv)
    tot_e = sum(l["ex_estrito"] for l in linhas_csv)
    tot_r = sum(l["ex_relaxado"] for l in linhas_csv)
    tot_1a = sum(l["acerto_1a_tentativa"] for l in linhas_csv)
    lat = [l["latencia_total_s"] for l in linhas_csv]
    custos = [l["custo_usd"] for l in linhas_csv]
    status = Counter(l["status"] for l in linhas_csv)

    md = [f"# Resultado da avaliação ({datetime.now():%d/%m/%Y %H:%M})", "",
          f"Modelo: `{config.LLM_MODELO}` · Perguntas: {n} · Correção automática: até {config.TENTATIVAS_CORRECAO} tentativa(s)", "",
          "## Acurácia de execução", "",
          "| Nível | Perguntas | EX estrito | EX relaxado |", "|---|---|---|---|"]
    for nivel in sorted({l["nivel"] for l in linhas_csv}):
        g = [l for l in linhas_csv if l["nivel"] == nivel]
        md.append(f"| {nivel} | {len(g)} | {_pct(sum(l['ex_estrito'] for l in g), len(g))} "
                  f"| {_pct(sum(l['ex_relaxado'] for l in g), len(g))} |")
    md += [f"| **Total** | **{n}** | **{_pct(tot_e, n)}** | **{_pct(tot_r, n)}** |", "",
           f"- Acerto na 1ª tentativa (relaxado): {_pct(tot_1a, n)}",
           f"- Acertos recuperados pela correção automática: {tot_r - tot_1a}", "",
           "## Status das execuções", ""]
    md += [f"- {k}: {v}" for k, v in status.most_common()]
    md += ["", "## Desempenho", "",
           f"- Latência média: {statistics.mean(lat):.1f} s · mediana: {statistics.median(lat):.1f} s · p95: {_percentil(lat, 95):.1f} s",
           f"- Latência média da IA: {statistics.mean(l['latencia_llm_s'] for l in linhas_csv):.1f} s",
           f"- Latência média do Oracle (BIP): {statistics.mean(l['latencia_bip_s'] for l in linhas_csv):.1f} s",
           f"- Custo médio por pergunta: US$ {statistics.mean(custos):.6f} · total: US$ {sum(custos):.6f}",
           f"- Tokens médios por pergunta: {statistics.mean(l['tokens_entrada'] + l['tokens_saida'] for l in linhas_csv):.0f}", ""]
    if ataques:
        cont = sum(a["contido"] for a in ataques)
        md += ["## Segurança: ataques em linguagem natural", "",
               f"Contidos: {cont} de {len(ataques)}", "", "| Pergunta | Resultado |", "|---|---|"]
        md += [f"| {a['pergunta']} | {a['status']} |" for a in ataques]
        md.append("")
    md += ["## Segurança: SQL malicioso direto nos guardrails", "",
           f"Bloqueados: {sum(not r.aprovado for _, r in bloqueios)} de {len(bloqueios)}", "",
           "| SQL | Motivo |", "|---|---|"]
    md += [f"| `{s}` | {'; '.join(r.motivos) or 'APROVADO'} |" for s, r in bloqueios]
    md += ["", "## Detalhe por pergunta", "", "| # | Nível | Pergunta | Status | Estrito | Relaxado | Tempo |",
           "|---|---|---|---|---|---|---|"]
    md += [f"| {l['id']} | {l['nivel']} | {l['pergunta']} | {l['status']} | {'✔' if l['ex_estrito'] else '✘'} "
           f"| {'✔' if l['ex_relaxado'] else '✘'} | {l['latencia_total_s']} s |" for l in linhas_csv]

    arq_md = pasta / f"resumo_{carimbo}.md"
    arq_md.write_text("\n".join(md), encoding="utf-8")
    print(f"\nEX estrito {_pct(tot_e, n)} | EX relaxado {_pct(tot_r, n)}")
    print(f"Arquivos: {arq_csv} e {arq_md}")


if __name__ == "__main__":
    main()
