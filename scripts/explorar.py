"""Executa qualquer SELECT no Fusion pelo BIP e mostra o resultado (útil para validar o gabarito).

Uso:  python scripts/explorar.py "SELECT document_status, COUNT(*) AS qtd FROM po_headers_all GROUP BY document_status"
"""

from __future__ import annotations
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import guardrails  # noqa: E402
from bip_client import executar_sql  # noqa: E402

sql = " ".join(sys.argv[1:])
g = guardrails.validar(sql)
if not g.aprovado:
    sys.exit(f"Bloqueado: {g.motivos}")
linhas = executar_sql(g.sql, 200)
print(json.dumps(linhas, indent=2, ensure_ascii=False))
print(f"\n{len(linhas)} linha(s)")
