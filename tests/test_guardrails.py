"""Testes dos guardrails (sem rede)."""

from __future__ import annotations
import json

import pytest

import guardrails
from conftest import RAIZ

APROVADOS = [
    "SELECT segment1 FROM po_headers_all",
    "select segment1 from PO_HEADERS_ALL",
    "WITH x AS (SELECT po_header_id FROM po_headers_all) SELECT * FROM x",
    "SELECT 'a;b' AS t FROM dual",
    "SELECT 'DELETE FROM x' AS t FROM dual",
    "SELECT /* comentario */ segment1 FROM po_headers_all -- fim",
    "SELECT segment1 FROM po_headers_all;",
    "```sql\nSELECT segment1 FROM po_headers_all\n```",
    "SELECT pha.segment1 FROM po_headers_all pha ORDER BY pha.creation_date DESC FETCH FIRST 10 ROWS ONLY",
    "SELECT COUNT(*) AS qtd FROM po_headers_all pha JOIN po_lines_all pla ON pla.po_header_id = pha.po_header_id",
    "SELECT segment1 FROM po_headers_all UNION SELECT segment1 FROM poz_suppliers_v",
]

BLOQUEADOS = [
    ("", "SQL vazio"),
    ("DELETE FROM po_headers_all", "somente SELECT"),
    ("DROP TABLE po_headers_all", "somente SELECT"),
    ("UPDATE po_headers_all SET comments = 'x'", "somente SELECT"),
    ("INSERT INTO po_headers_all (po_header_id) VALUES (1)", "somente SELECT"),
    ("MERGE INTO po_headers_all t USING dual ON (1=1) WHEN MATCHED THEN UPDATE SET t.comments = 'x'", ""),
    ("TRUNCATE TABLE po_lines_all", ""),
    ("GRANT SELECT ON po_headers_all TO public", ""),
    ("SELECT * FROM fnd_user", "whitelist"),
    ('SELECT * FROM "FND_USER"', "whitelist"),
    ("SELECT segment1 FROM po_headers_all; DELETE FROM po_lines_all", "instrução"),
    ("SELECT dbms_random.value FROM dual", "DBMS_"),
    ("SELECT dbms_xmlgen.getxml('select 1 from dual') FROM dual", "DBMS_"),
    ("SELECT utl_http.request('http://x') FROM dual", "UTL_"),
    ("SELECT * FROM sys.dual", "SYS"),
    ("SELECT * FROM po_headers_all@outro_banco", "dblink"),
    ("SELECT * FROM fusion.po_headers_all", "schema explícito"),
    ("SELECT segment1 FROM po_headers_all FOR UPDATE", "FOR UPDATE"),
    ("SELECT segment1 FROM po_headers_all UNION SELECT username FROM all_users", "ALL_USERS"),
    ("SELECT (SELECT MAX(username) FROM all_users) FROM dual", "ALL_USERS"),
    ("SELECT * FROM po_headers_all WHERE vendor_id IN (SELECT user_id FROM fnd_user)", "FND_USER"),
    ("SELECT CURSOR(SELECT * FROM fnd_user) FROM dual", "FND_USER"),
    ("SELECT * FROM po_headers_all, LATERAL (SELECT * FROM fnd_user)", "FND_USER"),
    ("WITH x AS (SELECT * FROM fnd_user) SELECT * FROM x", "FND_USER"),
    ("SELECT * FROM ｆｎｄ_user", "whitelist"),
    # Revisão de segurança (Etapa B): rede e objetos internos
    ("SELECT HTTPURITYPE('http://x').getclob() FROM dual", "função não permitida: HTTPURITYPE"),
    ("SELECT DBURITYPE('/SCOTT/EMP').getclob() FROM dual", "função não permitida: DBURITYPE"),
    ("SELECT XDBURITYPE('/public').getclob() FROM dual", "função não permitida: XDBURITYPE"),
    ("SELECT uritype.createuri('http://x') FROM dual", "URI"),
    ("SELECT sys_dburigen(segment1) FROM po_headers_all", "função não permitida: SYS_DBURIGEN"),
    ("SELECT SYS_XMLGEN(1) FROM dual", "função não permitida: SYS_XMLGEN"),
    ("SELECT XMLTYPE('<a/>') FROM dual", "função não permitida: XMLTYPE"),
    ("SELECT ctx_doc.snippet('x','y','z') FROM dual", "pacote"),
    ("SELECT owa_util.get_cgi_env('x') FROM dual", "pacote"),
    ("SELECT htp.print('x') FROM dual", "pacote"),
    ("SELECT x.upper(segment1) FROM po_headers_all x", "pacote ou método"),
    # Funções de sistema e prefixos proibidos
    ("SELECT ora_hash(segment1) FROM po_headers_all", "função não permitida: ORA_HASH"),
    ("SELECT sys_context('USERENV','SESSION_USER') FROM dual", "função não permitida: SYS_CONTEXT"),
    ("SELECT USERENV('SESSIONID') FROM dual", "função não permitida: USERENV"),
    ("SELECT dbms_lock.sleep(100) FROM dual", "DBMS_"),
    ("SELECT utl_inaddr.get_host_name FROM dual", "UTL_"),
    ('SELECT "DBMS_RANDOM".value FROM dual', "DBMS_"),
    ("SELECT funcao_qualquer(segment1) FROM po_headers_all", "função não permitida: FUNCAO_QUALQUER"),
    # Custo explosivo
    ("SELECT LEVEL FROM dual CONNECT BY LEVEL <= 1000000000", "CONNECT BY"),
    ("WITH r (n) AS (SELECT 1 FROM dual UNION ALL SELECT n + 1 FROM r WHERE n < 1000000000) SELECT n FROM r",
     "WITH recursivo não permitido: R"),
    ("SELECT n FROM dual MODEL DIMENSION BY (0 d) MEASURES (0 n) RULES ITERATE (1000000) (n[0] = n[0] + 1)",
     "cláusula MODEL"),
    ("SELECT * FROM XMLTABLE('/a' PASSING XMLTYPE('<a/>'))", "XML"),
    ("SELECT * FROM JSON_TABLE('[1]', '$[*]' COLUMNS (x NUMBER PATH '$'))", "JSON"),
    ("SELECT * FROM TABLE(sys_odcivarchar2list('a'))", "TABLE()"),
    ("SELECT COUNT(*) FROM po_lines_all a, po_lines_all b, po_lines_all c", "junção sem condição"),
    ("SELECT * FROM po_headers_all CROSS JOIN po_lines_all", "CROSS JOIN"),
    ("SELECT * FROM po_lines_all a JOIN po_lines_all b ON 1=1", "sem coluna"),
    ("SELECT 1 AS x FROM " + ", ".join(["dual"] * 12), "tabelas demais"),
    ("SELECT segment1 FROM po_headers_all WHERE comments = '" + "x" * 5000 + "'", "SQL muito longo"),
]


@pytest.mark.parametrize("sql", APROVADOS)
def test_aprovados(sql):
    r = guardrails.validar(sql)
    assert r.aprovado, r.motivos


@pytest.mark.parametrize("sql,trecho", BLOQUEADOS)
def test_bloqueados(sql, trecho):
    r = guardrails.validar(sql)
    assert not r.aprovado
    assert r.motivos
    if trecho:
        assert any(trecho.lower() in m.lower() for m in r.motivos), r.motivos


@pytest.mark.parametrize("sql,trecho", [b for b in BLOQUEADOS if b[0]])
def test_bloqueio_de_seguranca_nunca_e_sql_invalido(sql, trecho):
    """Bloqueio de segurança é definitivo: não pode virar sql_invalido (que ganharia correção)."""
    assert not guardrails.validar(sql).sql_invalido


# Funções Oracle comuns que a IA pode usar: não podem ser bloqueadas
FUNCOES_LEGITIMAS = [
    "MONTHS_BETWEEN(SYSDATE, pha.creation_date)", "LAST_DAY(pha.creation_date)",
    "NEXT_DAY(pha.creation_date, 'MONDAY')", "EXTRACT(YEAR FROM pha.creation_date)", "TO_NUMBER(pha.segment1)",
    "TO_DATE('2026-01-01','YYYY-MM-DD')", "TO_CHAR(pha.creation_date,'YYYY-MM')", "INSTR(pha.segment1,'-')",
    "SUBSTR(pha.segment1,1,2)", "LPAD(pha.segment1,10,'0')", "RPAD(pha.segment1,10)", "INITCAP(pha.comments)",
    "REGEXP_SUBSTR(pha.segment1,'[0-9]+')", "REGEXP_REPLACE(pha.segment1,'-','')", "DECODE(pha.document_status,'OPEN',1,0)",
    "NVL2(pha.cancel_flag,1,0)", "COALESCE(pha.cancel_flag,'N')", "NULLIF(pha.cancel_flag,'N')",
    "GREATEST(pha.creation_date, pha.approved_date)", "LEAST(pha.creation_date, pha.approved_date)",
    "MEDIAN(pha.po_header_id)", "PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY pha.po_header_id)",
    "STDDEV(pha.po_header_id)", "RANK() OVER (ORDER BY pha.creation_date)", "DENSE_RANK() OVER (ORDER BY pha.creation_date)",
    "LAG(pha.creation_date) OVER (ORDER BY pha.creation_date)", "LEAD(pha.creation_date) OVER (ORDER BY pha.creation_date)",
    "FIRST_VALUE(pha.segment1) OVER (ORDER BY pha.creation_date)", "LAST_VALUE(pha.segment1) OVER (ORDER BY pha.creation_date)",
    "LISTAGG(pha.segment1, ',') WITHIN GROUP (ORDER BY pha.segment1)", "ROUND(pha.po_header_id, 2)",
    "CEIL(pha.po_header_id)", "FLOOR(pha.po_header_id)", "ABS(pha.po_header_id)", "MOD(pha.po_header_id, 2)",
    "TRUNC(pha.creation_date)", "TRUNC(pha.creation_date,'MM')", "ADD_MONTHS(pha.creation_date, -3)", "SYSDATE",
    "NVL(pha.cancel_flag,'N')", "RATIO_TO_REPORT(COUNT(*)) OVER ()", "NUMTOYMINTERVAL(1,'MONTH')",
    "REGEXP_LIKE(pha.segment1,'^PO')",
]


@pytest.mark.parametrize("f", FUNCOES_LEGITIMAS)
def test_funcoes_oracle_comuns_aprovadas(f):
    if f.startswith("REGEXP_LIKE"):
        sql = f"SELECT pha.segment1 FROM po_headers_all pha WHERE {f}"
    else:
        sql = f"SELECT {f} AS x FROM po_headers_all pha"
    r = guardrails.validar(sql)
    assert r.aprovado, r.motivos


def test_allowlist_vem_do_config(monkeypatch):
    import config
    sql = "SELECT TRUNC(creation_date) AS dia FROM po_headers_all"
    assert guardrails.validar(sql).aprovado
    monkeypatch.setattr(config, "FUNCOES_PERMITIDAS", set())
    r = guardrails.validar(sql)
    assert not r.aprovado
    assert "função não permitida: TRUNC" in r.motivos


def test_with_comum_continua_permitido():
    sql = ("WITH c AS (SELECT pla.item_id FROM po_lines_all pla) "
           "SELECT u.item_id FROM c u JOIN c a ON a.item_id = u.item_id")
    assert guardrails.validar(sql).aprovado


def test_join_using_permitido():
    assert guardrails.validar(
        "SELECT pha.segment1 FROM po_headers_all pha JOIN po_lines_all pla USING (po_header_id)").aprovado


# Extração do SQL de dentro do texto da IA
@pytest.mark.parametrize("texto", [
    "Aqui está a consulta:\nSELECT segment1 FROM po_headers_all\nEspero ter ajudado.",
    "Claro! Segue:\n```sql\nSELECT segment1 FROM po_headers_all;\n```\nQualquer dúvida, pergunte.",
    "SQL: SELECT segment1 FROM po_headers_all",
    "  SELECT segment1 FROM po_headers_all  ",
])
def test_extrai_sql_de_texto(texto):
    r = guardrails.validar(texto)
    assert r.aprovado, r.motivos
    assert r.sql == "SELECT segment1 FROM po_headers_all"


@pytest.mark.parametrize("texto", [
    "DELETE FROM po_lines_all;\nSELECT segment1 FROM po_headers_all",
    "SELECT segment1 FROM po_headers_all;\nDELETE FROM po_lines_all",
    "SELECT segment1 FROM po_headers_all\nFOR UPDATE",
    "```sql\nSELECT segment1 FROM po_headers_all\n```\nDepois rode: DROP TABLE po_lines_all",
    "Execute isto: UPDATE po_headers_all SET comments = 'x'",
])
def test_extracao_nunca_esconde_ataque(texto):
    r = guardrails.validar(texto)
    assert not r.aprovado
    assert not r.sql_invalido, "ataque deve ser bloqueio definitivo"


@pytest.mark.parametrize("texto", [
    "SELECT FROM WHERE",
    "Desculpe, não consegui montar a consulta.",
    "",
])
def test_sql_invalido_sem_motivo_de_seguranca(texto):
    r = guardrails.validar(texto)
    assert not r.aprovado
    assert r.sql_invalido


def test_motivo_de_parse_sem_codigos_ansi():
    r = guardrails.validar("SELECT FROM WHERE")
    assert all("\x1b" not in m for m in r.motivos)
    assert all("\n" not in m for m in r.motivos)


def _gabarito():
    """Gabarito real (com dados da empresa, fora do Git). Sem ele, usa o exemplo público."""
    real = RAIZ / "avaliacao" / "gabarito.json"
    arq = real if real.exists() else RAIZ / "avaliacao" / "gabarito_exemplo.json"
    return json.loads(arq.read_text(encoding="utf-8"))["perguntas"]


@pytest.mark.parametrize("q", _gabarito(), ids=lambda q: f"gabarito_{q['id']}")
def test_sql_referencia_do_gabarito_aprovado(q):
    """Os SQLs de referência não podem ser bloqueados por nenhum endurecimento futuro."""
    r = guardrails.validar(q["sql_referencia"])
    assert r.aprovado, r.motivos


@pytest.mark.skipif(not (RAIZ / "avaliacao" / "gabarito.json").exists(), reason="gabarito real não versionado")
def test_gabarito_tem_15_perguntas():
    assert len(_gabarito()) == 15


def test_limpar_sql_remove_cercas_e_ponto_e_virgula():
    assert guardrails.limpar_sql("```sql\nSELECT 1 FROM dual;\n```") == "SELECT 1 FROM dual"


def test_sql_devolvido_e_o_limpo():
    r = guardrails.validar("```sql\nSELECT segment1 FROM po_headers_all;\n```")
    assert r.sql == "SELECT segment1 FROM po_headers_all"


def test_texto_sem_select_tem_motivo_neutro():
    """O mesmo motivo aparece no painel da tela (sem IA) e no pipeline, então não cita a IA."""
    import guardrails
    r = guardrails.validar("DELETRE FROM po_headers_all")
    assert not r.aprovado
    assert r.motivos == ["o texto não contém um comando SELECT válido"]
    assert not any("IA" in m for m in r.motivos)
