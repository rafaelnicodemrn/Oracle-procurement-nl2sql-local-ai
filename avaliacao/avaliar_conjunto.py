r"""Avaliação repetida sobre um conjunto de teste separado (hold-out).

Uso (a partir da raiz do projeto):
  .venv\Scripts\python.exe avaliacao\avaliar_conjunto.py                  # 3 repetições do gabarito_teste.json
  .venv\Scripts\python.exe avaliacao\avaliar_conjunto.py --repeticoes 1
  .venv\Scripts\python.exe avaliacao\avaliar_conjunto.py --gabarito avaliacao\gabarito.json --rotulo treino
  .venv\Scripts\python.exe avaliacao\avaliar_conjunto.py --ids 1 5 9 --sem-ataques

Diferenças em relação ao avaliar.py (que continua intacto):
  - lê o gabarito de um arquivo informado (padrão: avaliacao/gabarito_teste.json);
  - roda cada pergunta N vezes e reporta média, mínimo e máximo, porque o SQL gerado varia entre execuções;
  - executa o SQL de referência uma única vez por pergunta (não repete a cada rodada);
  - ignora perguntas cujo gabarito é inútil (falhou, veio vazio ou só com zeros), para não contar falso acerto;
  - roda os ataques em linguagem natural uma única vez (primeira rodada).

Saídas em avaliacao/resultados:
  conjunto_<rotulo>_<data>.csv       uma linha por pergunta e por repetição
  resumo_conjunto_<rotulo>_<data>.md métricas consolidadas
  metricas_<rotulo>_<data>.json      mesmos números em JSON (para gráficos)

Nenhum dado retornado do Oracle é gravado: o CSV guarda apenas SQL, contagens e métricas.
Cada rodada chama a IA local (Ollama) e o BIP. Na CPU, cada pergunta leva de segundos a minutos.
"""

from __future__ import annotations
import argparse
import csv
import json
import math
import statistics
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(_AQUI.parent / "src"))
sys.path.insert(0, str(_AQUI))

import config  # noqa: E402
from avaliar import LIMITE_COMPARACAO, PAUSA_S, _percentil, _pct, ex_estrito, ex_relaxado  # noqa: E402
from bip_client import BIPError, executar_sql  # noqa: E402
from pipeline import perguntar  # noqa: E402

GABARITO_PADRAO = _AQUI / "gabarito_teste.json"


# ---------------------------------------------------------------- funções puras (testadas sem rede)

def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Intervalo de confiança de Wilson (95%) para uma proporção k/n, em fração de 0 a 1."""
    if n <= 0:
        return (0.0, 0.0)
    p = k / n
    den = 1 + z * z / n
    centro = (p + z * z / (2 * n)) / den
    meia = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, centro - meia), min(1.0, centro + meia))


def gabarito_valido(gold: list[dict], erro: str = "") -> tuple[bool, str]:
    """Um gabarito vazio ou só com zeros faz qualquer resposta vazia parecer acerto."""
    if erro:
        return False, "SQL de referência falhou no Oracle"
    if not gold:
        return False, "SQL de referência devolveu zero linhas"
    valores = [v for linha in gold for v in linha.values()]
    if all(v is None or (isinstance(v, (int, float)) and not isinstance(v, bool) and float(v) == 0.0)
           or str(v).strip() in ("", "0", "0.0") for v in valores):
        return False, "SQL de referência devolveu só zeros ou nulos"
    return True, ""


def diagnostico(status: str, estrito: bool, relaxado: bool, n_gold: int, n_pred: int, erro: str = "") -> str:
    if status != "ok":
        return {"sem_resposta": "IA recusou (SEM_RESPOSTA)", "bloqueado": "bloqueado pelo guardrail",
                "sql_invalido": "SQL não interpretável", "erro_execucao": f"erro de execução: {erro}"[:120],
                }.get(status, f"falha: {status}")
    if relaxado and estrito:
        return "correto"
    if relaxado:
        return "correto com colunas extras"
    if n_gold != n_pred:
        return f"número de linhas diferente ({n_pred} contra {n_gold})"
    return "mesmas linhas, valores diferentes"


def _stats(valores: list[float]) -> dict:
    if not valores:
        return {"media": 0.0, "min": 0.0, "max": 0.0, "dp": 0.0}
    return {"media": statistics.mean(valores), "min": min(valores), "max": max(valores),
            "dp": statistics.stdev(valores) if len(valores) > 1 else 0.0}


def agregar(registros: list[dict], repeticoes: int) -> dict:
    """Consolida as rodadas. Só entram perguntas com gabarito válido."""
    validos = [r for r in registros if r["valido_gabarito"]]
    niveis = sorted({r["nivel"] for r in validos})

    def pct_rodada(sub: list[dict], campo: str, rep: int) -> float | None:
        grupo = [r for r in sub if r["rep"] == rep]
        return 100 * sum(bool(r[campo]) for r in grupo) / len(grupo) if grupo else None

    def bloco(sub: list[dict]) -> dict:
        saida = {"perguntas": len({r["id"] for r in sub})}
        for campo, nome in (("ex_estrito", "estrito"), ("ex_relaxado", "relaxado")):
            vals = [v for v in (pct_rodada(sub, campo, rep) for rep in range(1, repeticoes + 1)) if v is not None]
            saida[nome] = _stats(vals)
        k = sum(bool(r["ex_relaxado"]) for r in sub)
        n = len(sub)
        saida["relaxado_agrupado"] = {"acertos": k, "execucoes": n, "ic95": wilson(k, n)}
        k = sum(bool(r["ex_estrito"]) for r in sub)
        saida["estrito_agrupado"] = {"acertos": k, "execucoes": n, "ic95": wilson(k, n)}
        return saida

    por_pergunta = {}
    for qid in sorted({r["id"] for r in validos}):
        sub = [r for r in validos if r["id"] == qid]
        diag = Counter(r["diagnostico"] for r in sub).most_common(1)[0][0]
        por_pergunta[qid] = {
            "nivel": sub[0]["nivel"], "pergunta": sub[0]["pergunta"], "execucoes": len(sub),
            "acertos_estrito": sum(bool(r["ex_estrito"]) for r in sub),
            "acertos_relaxado": sum(bool(r["ex_relaxado"]) for r in sub),
            "latencia_media_s": statistics.mean(r["latencia_total_s"] for r in sub),
            "diagnostico_mais_frequente": diag,
        }
    lat = [r["latencia_total_s"] for r in validos]
    return {
        "repeticoes": repeticoes,
        "perguntas_validas": len({r["id"] for r in validos}),
        "perguntas_descartadas": sorted({r["id"] for r in registros if not r["valido_gabarito"]}),
        "total": bloco(validos),
        "por_nivel": {n: bloco([r for r in validos if r["nivel"] == n]) for n in niveis},
        "por_pergunta": por_pergunta,
        "sempre_certas": [q for q, v in por_pergunta.items() if v["acertos_relaxado"] == v["execucoes"]],
        "instaveis": [q for q, v in por_pergunta.items() if 0 < v["acertos_relaxado"] < v["execucoes"]],
        "sempre_erradas": [q for q, v in por_pergunta.items() if v["acertos_relaxado"] == 0],
        "desempenho": {
            "latencia_media_s": statistics.mean(lat) if lat else 0.0,
            "latencia_mediana_s": statistics.median(lat) if lat else 0.0,
            "latencia_p95_s": _percentil(lat, 95),
            "latencia_llm_media_s": statistics.mean(r["latencia_llm_s"] for r in validos) if validos else 0.0,
            "latencia_bip_media_s": statistics.mean(r["latencia_bip_s"] for r in validos) if validos else 0.0,
            "custo_medio_usd": statistics.mean(r["custo_usd"] for r in validos) if validos else 0.0,
            "custo_total_usd": sum(r["custo_usd"] for r in registros),
            "tokens_medios": statistics.mean(r["tokens_entrada"] + r["tokens_saida"] for r in validos) if validos else 0.0,
            "acerto_1a_tentativa_pct": (100 * sum(bool(r["ex_relaxado"]) and r["tentativas"] == 1 for r in validos) / len(validos)) if validos else 0.0,
        },
        "status": dict(Counter(r["status"] for r in validos)),
    }


# ---------------------------------------------------------------- execução (usa IA local e BIP)

def executar_gabaritos(perguntas: list[dict]) -> dict[int, dict]:
    """Roda cada SQL de referência uma vez."""
    saida = {}
    for q in perguntas:
        t0 = time.perf_counter()
        try:
            gold, erro = executar_sql(q["sql_referencia"], LIMITE_COMPARACAO), ""
        except BIPError as e:
            gold, erro = [], str(e)
        ok, motivo = gabarito_valido(gold, erro)
        saida[q["id"]] = {"linhas": gold, "valido": ok, "motivo": motivo, "tempo_s": time.perf_counter() - t0}
        marca = "ok " if ok else "!! "
        print(f"  gabarito [{q['id']:>2}] {marca}{len(gold)} linhas {motivo}")
    return saida


def rodar(perguntas: list[dict], golds: dict[int, dict], repeticoes: int, pausa: float = PAUSA_S) -> list[dict]:
    registros = []
    for rep in range(1, repeticoes + 1):
        print(f"\n=== Repetição {rep} de {repeticoes}")
        for q in perguntas:
            g = golds[q["id"]]
            if not g["valido"]:
                registros.append(_registro(rep, q, g, None, False, False, 0))
                continue
            r = perguntar(q["pergunta"], resumir=False)
            estrito = relaxado = False
            n_pred = len(r.linhas)
            if r.status == "ok":
                try:
                    pred = executar_sql(r.sql, LIMITE_COMPARACAO) if len(r.linhas) >= config.MAX_ROWS else r.linhas
                except BIPError:
                    pred = r.linhas
                n_pred = len(pred)
                estrito = ex_estrito(g["linhas"], pred)
                relaxado = estrito or ex_relaxado(g["linhas"], pred)
            print(f"[{q['id']:>2}] N{q['nivel']} {r.status:<13} estrito={int(estrito)} relaxado={int(relaxado)} "
                  f"{r.latencia_total_s:5.1f}s  {q['pergunta'][:70]}")
            registros.append(_registro(rep, q, g, r, estrito, relaxado, n_pred))
            time.sleep(pausa)
    return registros


def _registro(rep, q, g, r, estrito, relaxado, n_pred) -> dict:
    base = {"rep": rep, "id": q["id"], "nivel": q["nivel"], "pergunta": q["pergunta"],
            "valido_gabarito": g["valido"], "motivo_gabarito": g["motivo"], "linhas_gabarito": len(g["linhas"]),
            "sql_referencia": q["sql_referencia"]}
    if r is None:
        base.update({"status": "gabarito_invalido", "ex_estrito": False, "ex_relaxado": False, "tentativas": 0,
                     "linhas_gerado": 0, "latencia_total_s": 0.0, "latencia_llm_s": 0.0, "latencia_bip_s": 0.0,
                     "tokens_entrada": 0, "tokens_saida": 0, "custo_usd": 0.0, "diagnostico": "gabarito inválido",
                     "erro": g["motivo"], "sql_gerado": ""})
        return base
    base.update({"status": r.status, "ex_estrito": estrito, "ex_relaxado": relaxado, "tentativas": r.tentativas,
                 "linhas_gerado": n_pred, "latencia_total_s": round(r.latencia_total_s, 2),
                 "latencia_llm_s": round(r.latencia_llm_s, 2), "latencia_bip_s": round(r.latencia_bip_s, 2),
                 "tokens_entrada": r.tokens_entrada, "tokens_saida": r.tokens_saida, "custo_usd": round(r.custo_usd, 6),
                 "diagnostico": diagnostico(r.status, estrito, relaxado, len(g["linhas"]), n_pred, r.erro),
                 "erro": r.erro, "sql_gerado": r.sql})
    return base


def rodar_ataques(ataques: list[dict], pausa: float = PAUSA_S) -> list[dict]:
    print("\nAtaques em linguagem natural")
    saida = []
    for a in ataques:
        r = perguntar(a["pergunta"], resumir=False)
        contido = r.status != "ok"
        saida.append({"id": a["id"], "pergunta": a["pergunta"], "status": r.status, "contido": contido,
                      "motivos": "; ".join(r.motivos_bloqueio)})
        print(f"  [{a['id']}] {'CONTIDO ' if contido else 'EXECUTOU'} {r.status} | {a['pergunta']}")
        time.sleep(pausa)
    return saida


# ---------------------------------------------------------------- relatório

def _fmt(s: dict) -> str:
    if abs(s["max"] - s["min"]) < 1e-9:
        return f"{s['media']:.1f}%"
    return f"{s['media']:.1f}% ({s['min']:.1f} a {s['max']:.1f})"


def _ic(b: dict) -> str:
    lo, hi = b["ic95"]
    return f"{b['acertos']}/{b['execucoes']}, IC95% {100 * lo:.1f}% a {100 * hi:.1f}%"


def montar_resumo(agg: dict, registros: list[dict], ataques: list[dict], rotulo: str, gabarito: Path) -> str:
    t, d = agg["total"], agg["desempenho"]
    md = [f"# Avaliação do conjunto '{rotulo}' ({datetime.now():%d/%m/%Y %H:%M})", "",
          f"Modelo: `{config.LLM_MODELO}` · Gabarito: `{gabarito.name}` · Perguntas válidas: {agg['perguntas_validas']} "
          f"· Repetições: {agg['repeticoes']} · Correção automática: até {config.TENTATIVAS_CORRECAO} tentativa(s)", ""]
    if agg["perguntas_descartadas"]:
        md += [f"**Perguntas descartadas por gabarito inválido (vazio, zeros ou erro):** {agg['perguntas_descartadas']}", ""]
    md += ["## Acurácia de execução (média das repetições, com mínimo e máximo)", "",
           "| Nível | Perguntas | EX estrito | EX relaxado |", "|---|---|---|---|"]
    for n, b in agg["por_nivel"].items():
        md.append(f"| {n} | {b['perguntas']} | {_fmt(b['estrito'])} | {_fmt(b['relaxado'])} |")
    md += [f"| **Total** | **{t['perguntas']}** | **{_fmt(t['estrito'])}** | **{_fmt(t['relaxado'])}** |", "",
           f"- EX relaxado agrupado: {_ic(t['relaxado_agrupado'])}",
           f"- EX estrito agrupado: {_ic(t['estrito_agrupado'])}",
           "- O intervalo trata as execuções como independentes. Como a mesma pergunta se repete, ele é otimista; "
           "a amplitude entre repetições (mínimo a máximo) mostra a variação real do modelo.",
           f"- Acerto na 1ª tentativa (relaxado): {d['acerto_1a_tentativa_pct']:.1f}%", "",
           "## Estabilidade entre repetições", "",
           f"- Sempre certas (relaxado): {len(agg['sempre_certas'])} de {agg['perguntas_validas']}",
           f"- Instáveis (acertaram em algumas repetições): {agg['instaveis']}",
           f"- Sempre erradas: {agg['sempre_erradas']}", "",
           "## Status das execuções", ""]
    md += [f"- {k}: {v}" for k, v in sorted(agg["status"].items())]
    md += ["", "## Desempenho", "",
           f"- Latência média: {d['latencia_media_s']:.1f} s · mediana: {d['latencia_mediana_s']:.1f} s · p95: {d['latencia_p95_s']:.1f} s",
           f"- Latência média da IA: {d['latencia_llm_media_s']:.1f} s · do Oracle (BIP): {d['latencia_bip_media_s']:.1f} s",
           f"- Custo médio por pergunta: US$ {d['custo_medio_usd']:.6f} · custo total da avaliação: US$ {d['custo_total_usd']:.6f}",
           f"- Tokens médios por pergunta: {d['tokens_medios']:.0f}", ""]
    if ataques:
        md += ["## Segurança: ataques em linguagem natural", "",
               f"Contidos: {sum(a['contido'] for a in ataques)} de {len(ataques)}", "",
               "| Pergunta | Resultado |", "|---|---|"]
        md += [f"| {a['pergunta']} | {a['status']} |" for a in ataques]
        md.append("")
    md += ["## Detalhe por pergunta", "",
           "| # | Nível | Pergunta | Relaxado | Estrito | Diagnóstico mais frequente | Tempo médio |",
           "|---|---|---|---|---|---|---|"]
    for qid, v in agg["por_pergunta"].items():
        md.append(f"| {qid} | {v['nivel']} | {v['pergunta']} | {v['acertos_relaxado']}/{v['execucoes']} "
                  f"| {v['acertos_estrito']}/{v['execucoes']} | {v['diagnostico_mais_frequente']} | {v['latencia_media_s']:.1f} s |")
    return "\n".join(md) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gabarito", type=Path, default=GABARITO_PADRAO)
    ap.add_argument("--repeticoes", type=int, default=3)
    ap.add_argument("--ids", nargs="*", type=int)
    ap.add_argument("--rotulo", default="teste")
    ap.add_argument("--sem-ataques", action="store_true")
    args = ap.parse_args()

    dados = json.loads(args.gabarito.read_text(encoding="utf-8"))
    perguntas = [q for q in dados["perguntas"] if not args.ids or q["id"] in args.ids]
    print(f"Modelo: {config.LLM_MODELO} | {len(perguntas)} perguntas x {args.repeticoes} repetições | {args.gabarito.name}")
    print("\nExecutando os SQLs de referência (uma vez)")
    golds = executar_gabaritos(perguntas)

    registros = rodar(perguntas, golds, args.repeticoes)
    ataques = [] if args.sem_ataques else rodar_ataques(dados.get("ataques", []))

    config.RESULTADOS_DIR.mkdir(parents=True, exist_ok=True)
    carimbo = datetime.now().strftime("%Y%m%d_%H%M")
    base = f"{args.rotulo}_{carimbo}"
    agg = agregar(registros, args.repeticoes)

    with (config.RESULTADOS_DIR / f"conjunto_{base}.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(registros[0].keys()), delimiter=";")
        w.writeheader()
        w.writerows(registros)
    (config.RESULTADOS_DIR / f"metricas_{base}.json").write_text(
        json.dumps({"agregado": agg, "ataques": ataques, "modelo": config.LLM_MODELO}, ensure_ascii=False, indent=1, default=str),
        encoding="utf-8")
    resumo = montar_resumo(agg, registros, ataques, args.rotulo, args.gabarito)
    (config.RESULTADOS_DIR / f"resumo_conjunto_{base}.md").write_text(resumo, encoding="utf-8")

    t = agg["total"]
    print(f"\nEX estrito {_fmt(t['estrito'])} | EX relaxado {_fmt(t['relaxado'])}")
    print(f"Arquivos em {config.RESULTADOS_DIR}: conjunto_{base}.csv, resumo_conjunto_{base}.md, metricas_{base}.json")


if __name__ == "__main__":
    main()
