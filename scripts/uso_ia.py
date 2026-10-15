"""Mostra o uso acumulado da IA local (registrado em dados/uso_llm.csv)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import config  # noqa: E402
import llm  # noqa: E402

u = llm.uso_acumulado()
print(f"IA local (Ollama) : {config.OLLAMA_URL}")
print(f"Modelo atual      : {u['modelo']}")
print(f"Chamadas          : {u['chamadas']}")
print(f"Tokens totais     : {u['tokens']:,}".replace(",", "."))
print(f"Latência média    : {u['latencia_media_s']:.1f} s")
print("Custo             : zero (modelo local)")
if u["linhas_ilegiveis"]:
    print(f"Linhas ilegíveis  : {u['linhas_ilegiveis']} (ignoradas)")
