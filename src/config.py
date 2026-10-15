"""Configuração central. Valores sensíveis vêm do arquivo .env."""


from __future__ import annotations
import os
from pathlib import Path

from dotenv import load_dotenv

# Raiz do projeto (a pasta acima de src). Todos os caminhos derivam daqui.
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# Oracle BI Publisher
# Host e relatório ficam no .env (não versionar dados do ambiente da empresa)
BIP_HOST = os.getenv("BIP_HOST", "").rstrip("/")
BIP_ENDPOINT = f"{BIP_HOST}/xmlpserver/services/ExternalReportWSSService"
BIP_REPORT_PATH = os.getenv("BIP_REPORT_PATH", "")
BIP_USER = os.getenv("BIP_USER", "")
BIP_PASS = os.getenv("BIP_PASS", "")
BIP_PARAM_SQL = "p_sql"
BIP_PARAM_ROWS = "p_rows"
BIP_TIMEOUT = int(os.getenv("BIP_TIMEOUT", "60"))

# Limite de linhas aplicado fora da IA (guardrail determinístico)
MAX_ROWS = int(os.getenv("MAX_ROWS", "200"))

# IA local (Ollama). Nenhuma chamada sai para IA na nuvem.
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
# 3b: cerca de 3,5x mais rápido que o 7b na CPU (medido em 15/10/2026)
LLM_MODELO = os.getenv("LLM_MODELO", "qwen2.5-coder:3b")
# CPU sem GPU dedicada: a primeira chamada carrega o modelo e processa o schema inteiro.
# Medido em notebook i5 com Docker: cerca de 2 min com o 3b e mais de 5 min com o 7b
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "600"))
# Janela de contexto: o prompt com o schema curado passa de 2.000 tokens; o padrão do Ollama cortaria o prompt
OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "8192"))
# Threads da CPU usadas pelo modelo. 0 = padrão do Ollama. Meça com scripts\medir_threads.bat
OLLAMA_NUM_THREAD = int(os.getenv("OLLAMA_NUM_THREAD", "0"))
# Tempo que o modelo fica carregado na memória depois da última chamada
OLLAMA_KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "30m")
# Modelos com raciocínio (ex: qwen3): "false" desliga o modo pensamento. Vazio = padrão do modelo
_think = os.getenv("OLLAMA_THINK", "").strip().lower()
OLLAMA_THINK = None if not _think else _think in ("1", "true", "sim")
# Por segurança, só aceita Ollama em localhost ou IP de rede privada. "true" libera outro endereço
OLLAMA_PERMITIR_REMOTO = os.getenv("OLLAMA_PERMITIR_REMOTO", "").strip().lower() in ("1", "true", "sim")

# Pipeline
TENTATIVAS_CORRECAO = int(os.getenv("TENTATIVAS_CORRECAO", "1"))

# Limites de entrada da API e do SQL gerado (guardrail)
MAX_PERGUNTA_CHARS = 500
MAX_SQL_CHARS = 4000
MAX_TABELAS = 10

# Whitelist de tabelas (guardrail)
TABELAS_PERMITIDAS = {
    "PO_HEADERS_ALL",
    "PO_LINES_ALL",
    "POZ_SUPPLIERS_V",
    "PER_PERSON_NAMES_F",
    "EGP_SYSTEM_ITEMS_B",
    "EGP_CATEGORIES_TL",
    "DUAL",
}

# Allowlist de funções (guardrail). Vale para funções que o sqlglot não reconhece
# (nó Anonymous): qualquer outra função desconhecida é bloqueada. Funções comuns
# (SUM, NVL, TO_CHAR, ADD_MONTHS...) já são reconhecidas pelo sqlglot e passam.
# Se aparecer falso bloqueio ("função não permitida: X"), acrescente X aqui.
FUNCOES_PERMITIDAS = {
    # Encontradas como Anonymous no sqlglot atual
    "TRUNC", "RATIO_TO_REPORT", "NUMTOYMINTERVAL", "NUMTODSINTERVAL",
    # Funções Oracle comuns (protege contra mudança de versão do sqlglot)
    "MONTHS_BETWEEN", "LAST_DAY", "NEXT_DAY", "EXTRACT", "TO_NUMBER", "TO_DATE", "TO_CHAR",
    "INSTR", "SUBSTR", "LPAD", "RPAD", "INITCAP", "REGEXP_SUBSTR", "REGEXP_REPLACE", "REGEXP_LIKE",
    "DECODE", "NVL", "NVL2", "COALESCE", "NULLIF", "GREATEST", "LEAST", "MEDIAN", "PERCENTILE_CONT",
    "STDDEV", "RANK", "DENSE_RANK", "LAG", "LEAD", "FIRST_VALUE", "LAST_VALUE", "LISTAGG", "ROUND",
    "CEIL", "FLOOR", "ABS", "MOD", "ADD_MONTHS", "SYSDATE",
}

SCHEMA_PATH = BASE_DIR / "src" / "recursos" / "schema_curado.md"
STATIC_DIR = BASE_DIR / "src" / "static"
USO_LLM_PATH = BASE_DIR / "dados" / "uso_llm.csv"
GABARITO_PATH = BASE_DIR / "avaliacao" / "gabarito.json"
RESULTADOS_DIR = BASE_DIR / "avaliacao" / "resultados"
