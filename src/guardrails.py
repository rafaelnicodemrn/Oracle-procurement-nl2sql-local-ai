"""Guardrails determinísticos. Nenhuma decisão de segurança é delegada à IA.

Regras:
  1. Uma única instrução SQL
  2. Somente leitura (SELECT / WITH / UNION), sem DML, DDL ou comandos
  3. Somente tabelas da whitelist
  4. Sem pacotes de sistema (DBMS_, UTL_, ORA_, SYS.), dblink (@) ou FOR UPDATE
  5. Limite de linhas aplicado pelo parâmetro p_rows do BIP (fora do SQL gerado)
  6. Sem acesso a rede ou objetos internos (*URITYPE, SYS_DBURIGEN, XMLTYPE, SYS_CONTEXT...)
  7. Funções desconhecidas só passam se estiverem em config.FUNCOES_PERMITIDAS
  8. Sem chamada de função de pacote ou método (x.y(...))
  9. Sem consultas de custo explosivo: CONNECT BY, WITH recursivo, MODEL, CROSS JOIN,
     junção sem ON/USING, ON sem coluna, funções de tabela (TABLE, XMLTABLE, JSON_TABLE)
 10. Tamanho máximo do SQL e número máximo de tabelas referenciadas

SQL que não pode ser interpretado e não tem nenhum motivo de segurança é marcado
como sql_invalido (o pipeline pode pedir uma correção). Qualquer motivo de segurança
torna o bloqueio definitivo.
"""


from __future__ import annotations
import re
from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp

import config

PADROES_PROIBIDOS = [
    (r"\bDBMS_\w*", "pacote DBMS_ não permitido"),
    (r"\bUTL_\w*", "pacote UTL_ não permitido"),
    (r"\bORA_\w*", "função ORA_ não permitida"),
    (r"\b(?:CTX|OWA|APEX)_\w*", "pacote de sistema não permitido"),
    (r"\bHT[PF]\s*\.", "pacote de sistema não permitido"),
    (r"\bSYS\s*\.", "objetos do schema SYS não permitidos"),
    (r"\bFOR\s+UPDATE\b", "FOR UPDATE não permitido"),
    (r"@\w+", "dblink não permitido"),
    (r"\bEXECUTE\s+IMMEDIATE\b", "execução dinâmica não permitida"),
    (r"\b\w*URITYPE\b", "tipo URI não permitido (acesso a rede ou a objetos do banco)"),
    (r"\bSYS_(?:DBURIGEN|XMLGEN|XMLAGG|CONTEXT)\b", "função de sistema não permitida"),
    (r"\bUSERENV\b", "função de sistema não permitida"),
    (r"\b(?:XMLTYPE|XMLTABLE|XMLQUERY|JSON_TABLE)\b", "função de XML/JSON não permitida"),
    (r"\bTABLE\s*\(", "função de tabela TABLE() não permitida"),
    (r"\bCONNECT\s+BY\b", "CONNECT BY não permitido"),
    (r"\bMODEL\b[\s\S]*\bDIMENSION\s+BY\b", "cláusula MODEL não permitida"),
    (r"\bCROSS\s+JOIN\b", "CROSS JOIN não permitido"),
]

NOS_PROIBIDOS = (
    exp.Insert, exp.Update, exp.Delete, exp.Merge, exp.Drop, exp.Create,
    exp.Alter, exp.Command, exp.TruncateTable, exp.Grant,
)

NOS_CUSTO_PROIBIDOS = (
    (exp.Connect, "CONNECT BY não permitido"),
    (exp.XMLTable, "função de XML/JSON não permitida"),
    (exp.JSONTable, "função de XML/JSON não permitida"),
)

IDENTIFICADOR_PROIBIDO = re.compile(r"^(?:(?:DBMS|UTL|ORA|CTX|OWA|APEX)_.*|SYS|HTP|HTF|USERENV|.*URITYPE)$")

# Trechos que indicam comando (não prosa). Texto descartado na extração nunca pode conter isto.
_COMANDO = re.compile(
    r";|\b(?:INSERT|UPDATE|DELETE|MERGE|DROP|ALTER|CREATE|GRANT|REVOKE|TRUNCATE|EXEC|EXECUTE|BEGIN|DECLARE|CALL)\b",
    re.I)
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


@dataclass
class ResultadoGuardrail:
    aprovado: bool
    sql: str
    motivos: list[str] = field(default_factory=list)
    sql_invalido: bool = False  # True: só falhou a interpretação, sem motivo de segurança


def limpar_sql(texto: str) -> str:
    """Remove cercas de markdown e ponto e vírgula final."""
    t = texto.strip()
    t = re.sub(r"^```(?:sql)?\s*", "", t, flags=re.I)
    t = re.sub(r"\s*```$", "", t)
    t = t.strip().rstrip(";").strip()
    return t


def _interpreta(sql: str) -> bool:
    try:
        return any(a is not None for a in sqlglot.parse(sql, read="oracle"))
    except Exception:  # noqa: BLE001
        return False


def extrair_sql(texto: str) -> str:
    """Extrai o SQL de uma resposta da IA que veio com texto em volta.

    Só descarta trechos que não parecem comando (sem ';' nem DML/DDL). Assim um ataque
    escondido antes ou depois do SELECT nunca é removido: ele chega à validação e é bloqueado.
    """
    t = (texto or "").strip()

    m = re.search(r"```(?:sql)?\s*(.*?)```", t, re.S | re.I)
    if m and not _COMANDO.search(t[:m.start()] + t[m.end():]):
        t = m.group(1)
    t = limpar_sql(t)

    m = re.search(r"\b(?:SELECT|WITH)\b", t, re.I)
    if m and m.start() > 0 and not _COMANDO.search(t[:m.start()]):
        t = limpar_sql(t[m.start():])

    if _interpreta(t):
        return t
    linhas = t.splitlines()
    for n in range(len(linhas) - 1, 0, -1):
        if _COMANDO.search("\n".join(linhas[n:])):
            break
        candidato = limpar_sql("\n".join(linhas[:n]))
        if _interpreta(candidato):
            return candidato
    return t


def _msg_parse(e: Exception) -> str:
    texto = _ANSI.sub("", str(e)).strip().splitlines()
    return f"SQL inválido: {texto[0][:200] if texto else 'não foi possível interpretar'}"


def validar(sql_bruto: str) -> ResultadoGuardrail:
    sql = extrair_sql(sql_bruto)
    motivos: list[str] = []

    if not sql:
        return ResultadoGuardrail(False, sql, ["SQL vazio"], sql_invalido=True)

    if len(sql) > config.MAX_SQL_CHARS:
        return ResultadoGuardrail(False, sql[:200], [f"SQL muito longo (máximo {config.MAX_SQL_CHARS} caracteres)"])

    sem_strings = re.sub(r"'(?:[^']|'')*'", "''", sql)
    if ";" in sem_strings:
        motivos.append("mais de uma instrução SQL")

    for padrao, motivo in PADROES_PROIBIDOS:
        if re.search(padrao, sem_strings, re.I):
            motivos.append(motivo)

    if not motivos and not _COMANDO.search(sem_strings) and not re.match(r"^\(*\s*(?:SELECT|WITH)\b", sql, re.I):
        return ResultadoGuardrail(False, sql, ["o texto não contém um comando SELECT válido"], sql_invalido=True)

    try:
        arvores = sqlglot.parse(sql, read="oracle")
    except Exception as e:  # noqa: BLE001
        m = _COMANDO.search(sem_strings)
        if m:
            motivos.append(f"comando não permitido no texto: {m.group(0).upper()}")
        motivos_finais = sorted(set(motivos)) + [_msg_parse(e)]
        return ResultadoGuardrail(False, sql, motivos_finais, sql_invalido=not motivos)

    arvores = [a for a in arvores if a is not None]
    if len(arvores) != 1:
        motivos.append("é permitida exatamente uma instrução")
        return ResultadoGuardrail(False, sql, sorted(set(motivos)))

    arvore = arvores[0]

    if not isinstance(arvore, exp.Query):
        motivos.append(f"somente SELECT é permitido (recebido: {type(arvore).__name__})")

    for tipo in NOS_PROIBIDOS:
        if arvore.find(tipo):
            motivos.append(f"operação proibida: {tipo.__name__}")

    for tipo, motivo in NOS_CUSTO_PROIBIDOS:
        if arvore.find(tipo):
            motivos.append(motivo)

    # Funções: desconhecidas só com allowlist; chamadas de pacote/método nunca
    for f in arvore.find_all(exp.Anonymous):
        nome = str(f.name).upper()
        if nome not in config.FUNCOES_PERMITIDAS:
            motivos.append(f"função não permitida: {nome}")
    for d in arvore.find_all(exp.Dot):
        if isinstance(d.expression, exp.Func):
            motivos.append(f"chamada de pacote ou método não permitida: {d.sql(dialect='oracle')[:80]}")

    for ident in arvore.find_all(exp.Identifier):
        nome = str(ident.name).upper()
        if IDENTIFICADOR_PROIBIDO.match(nome):
            motivos.append(f"identificador não permitido: {nome}")

    # WITH recursivo: CTE que referencia a si mesma
    for cte in arvore.find_all(exp.CTE):
        nome_cte = cte.alias_or_name.upper()
        if any(t.name.upper() == nome_cte for t in cte.this.find_all(exp.Table)):
            motivos.append(f"WITH recursivo não permitido: {nome_cte}")

    # Junções: sempre com ON/USING, e o ON precisa comparar colunas
    for j in arvore.find_all(exp.Join):
        if str(j.args.get("kind") or "").upper() == "CROSS":
            motivos.append("CROSS JOIN não permitido")
        elif not j.args.get("on") and not j.args.get("using"):
            motivos.append("junção sem condição (use JOIN ... ON)")
        elif j.args.get("on") and not j.args["on"].find(exp.Column):
            motivos.append("junção com condição sem coluna (ex: ON 1=1) não permitida")

    nomes_cte = {cte.alias_or_name.upper() for cte in arvore.find_all(exp.CTE)}
    tabelas = list(arvore.find_all(exp.Table))
    if len(tabelas) > config.MAX_TABELAS:
        motivos.append(f"tabelas demais na consulta ({len(tabelas)}; máximo {config.MAX_TABELAS})")
    for tabela in tabelas:
        nome = tabela.name.upper()
        if not nome or nome in nomes_cte:
            continue
        if tabela.args.get("db") or tabela.args.get("catalog"):
            motivos.append(f"tabela com schema explícito não permitida: {tabela.sql()}")
        elif nome not in config.TABELAS_PERMITIDAS:
            motivos.append(f"tabela fora da whitelist: {nome}")

    return ResultadoGuardrail(not motivos, sql, sorted(set(motivos)))


if __name__ == "__main__":
    testes = [
        "SELECT segment1 FROM po_headers_all",
        "DELETE FROM po_headers_all",
        "DROP TABLE po_headers_all",
        "SELECT * FROM fnd_user",
        "SELECT segment1 FROM po_headers_all; DELETE FROM po_lines_all",
        "SELECT dbms_random.value FROM dual",
        "SELECT * FROM po_headers_all@outro_banco",
        "SELECT * FROM fusion.po_headers_all",
        "UPDATE po_headers_all SET comments = 'x'",
        "SELECT segment1 FROM po_headers_all FOR UPDATE",
        "WITH x AS (SELECT po_header_id FROM po_headers_all) SELECT * FROM x",
        "SELECT 'a;b' AS t FROM dual",
        # Casos da revisão de segurança
        "SELECT HTTPURITYPE('http://x').getclob() FROM dual",
        "SELECT DBURITYPE('/SCOTT/EMP').getclob() FROM dual",
        "SELECT XDBURITYPE('/public').getclob() FROM dual",
        "SELECT ora_hash(segment1) FROM po_headers_all",
        "SELECT sys_context('USERENV','SESSION_USER') FROM dual",
        "SELECT owa_util.get_cgi_env('x') FROM dual",
        "SELECT LEVEL FROM dual CONNECT BY LEVEL <= 1000000000",
        "WITH r (n) AS (SELECT 1 FROM dual UNION ALL SELECT n + 1 FROM r WHERE n < 1000000000) SELECT n FROM r",
        "SELECT n FROM dual MODEL DIMENSION BY (0 d) MEASURES (0 n) RULES ITERATE (1000000) (n[0] = n[0] + 1)",
        "SELECT * FROM XMLTABLE('/a' PASSING XMLTYPE('<a/>'))",
        "SELECT * FROM TABLE(sys_odcivarchar2list('a'))",
        "SELECT COUNT(*) FROM po_lines_all a, po_lines_all b, po_lines_all c",
        "SELECT * FROM po_headers_all CROSS JOIN po_lines_all",
        "SELECT * FROM po_lines_all a JOIN po_lines_all b ON 1=1",
        "SELECT TRUNC(creation_date) AS dia FROM po_headers_all",
        "Aqui está a consulta:\nSELECT segment1 FROM po_headers_all\nEspero ter ajudado.",
    ]
    for t in testes:
        r = validar(t)
        rotulo = "APROVADO " if r.aprovado else ("INVALIDO " if r.sql_invalido else "BLOQUEADO")
        print(f"{rotulo} | {t[:60].replace(chr(10), ' '):<60} | {'; '.join(r.motivos)}")
