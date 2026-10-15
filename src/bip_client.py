"""Cliente do Oracle BI Publisher: executa SQL pelo relatório RunSQL e devolve linhas em JSON."""


from __future__ import annotations
import base64
import html
import json
import re
from xml.sax.saxutils import escape

import requests

import config


class BIPError(Exception):
    """Erro devolvido pelo BIP ou pelo banco Oracle (ex: ORA-00904)."""


def _envelope(sql: str, limite: int) -> str:
    return f"""<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
               xmlns:pub="http://xmlns.oracle.com/oxp/service/PublicReportService">
  <soap:Header/>
  <soap:Body>
    <pub:runReport>
      <pub:reportRequest>
        <pub:attributeFormat>xml</pub:attributeFormat>
        <pub:flattenXML>false</pub:flattenXML>
        <pub:parameterNameValues>
          <pub:item>
            <pub:name>{config.BIP_PARAM_SQL}</pub:name>
            <pub:values><pub:item>{escape(sql)}</pub:item></pub:values>
          </pub:item>
          <pub:item>
            <pub:name>{config.BIP_PARAM_ROWS}</pub:name>
            <pub:values><pub:item>{int(limite)}</pub:item></pub:values>
          </pub:item>
        </pub:parameterNameValues>
        <pub:reportAbsolutePath>{escape(config.BIP_REPORT_PATH)}</pub:reportAbsolutePath>
        <pub:sizeOfDataChunkDownload>-1</pub:sizeOfDataChunkDownload>
      </pub:reportRequest>
      <pub:appParams></pub:appParams>
    </pub:runReport>
  </soap:Body>
</soap:Envelope>"""


def _extrair_erro(texto: str) -> str:
    m = re.search(r"(ORA-\d{5}[^<\n]*)", texto)
    if m:
        return html.unescape(m.group(1)).strip()
    m = re.search(r"<[^>]*Text[^>]*>(.*?)</[^>]*Text>", texto, re.S)
    if m:
        return html.unescape(m.group(1)).strip()[:500]
    return texto[:500]


def executar_sql(sql: str, limite: int | None = None) -> list[dict]:
    """Executa o SQL no Fusion via BIP e devolve lista de dicionários (uma por linha)."""
    if not config.BIP_USER or not config.BIP_PASS:
        raise BIPError("BIP_USER e BIP_PASS não definidos no .env")
    if not config.BIP_HOST or not config.BIP_REPORT_PATH:
        raise BIPError("BIP_HOST e BIP_REPORT_PATH não definidos no .env")

    limite = limite or config.MAX_ROWS
    resp = requests.post(
        config.BIP_ENDPOINT,
        data=_envelope(sql, limite).encode("utf-8"),
        headers={"Content-Type": "application/soap+xml; charset=utf-8"},
        auth=(config.BIP_USER, config.BIP_PASS),
        timeout=config.BIP_TIMEOUT,
    )

    if resp.status_code == 401:
        raise BIPError("HTTP 401: usuário ou senha recusados pelo BIP")
    if resp.status_code != 200:
        raise BIPError(f"HTTP {resp.status_code}: {_extrair_erro(resp.text)}")

    m = re.search(r"<[^>]*reportBytes>(.*?)</[^>]*reportBytes>", resp.text, re.S)
    if not m:
        raise BIPError(f"Resposta sem reportBytes: {_extrair_erro(resp.text)}")

    xml_saida = base64.b64decode(m.group(1)).decode("utf-8", errors="replace")

    if "ORA-" in xml_saida and "<JSON_DOC>" not in xml_saida:
        raise BIPError(_extrair_erro(xml_saida))

    j = re.search(r"<JSON_DOC>(.*?)</JSON_DOC>", xml_saida, re.S)
    if not j:
        # Sem JSON_DOC: consulta sem linhas (JSON_ARRAYAGG de zero linhas é NULL)
        return []

    texto = j.group(1).strip()
    if texto.startswith("<![CDATA["):
        texto = texto[9:-3]
    texto = html.unescape(texto)
    return json.loads(texto) if texto else []


if __name__ == "__main__":
    import sys

    sql = sys.argv[1] if len(sys.argv) > 1 else "SELECT segment1, document_status FROM po_headers_all"
    linhas = executar_sql(sql, 5)
    print(json.dumps(linhas, indent=2, ensure_ascii=False))
