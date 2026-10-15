# Schema curado: Oracle Fusion Procurement

Banco Oracle. Use somente as tabelas e colunas listadas abaixo.

## Tabelas

### PO_HEADERS_ALL (alias pha): cabeçalho da ordem de compra
- PO_HEADER_ID: chave primária
- SEGMENT1: número da ordem de compra exibido ao usuário (ex: 'PO-CT-7')
- TYPE_LOOKUP_CODE: tipo do documento. 'STANDARD' = ordem de compra; 'BLANKET' = acordo de compra; 'CONTRACT' = contrato
- DOCUMENT_STATUS: status. Valores comuns: 'OPEN' (aberta), 'CLOSED' (fechada), 'CANCELED' (cancelada), 'INCOMPLETE' (incompleta), 'PENDING APPROVAL' (em aprovação), 'REJECTED' (rejeitada), 'FINALLY CLOSED' (finalizada)
- AGENT_ID: comprador (= PER_PERSON_NAMES_F.PERSON_ID)
- VENDOR_ID: fornecedor (= POZ_SUPPLIERS_V.VENDOR_ID)
- CREATION_DATE: data de criação/emissão da ordem (TIMESTAMP)
- APPROVED_DATE: data da última aprovação (DATE)
- APPROVED_FLAG: 'Y' = aprovada
- CANCEL_FLAG: 'Y' = cancelada
- CURRENCY_CODE: moeda (ex: 'BRL')
- TERMS_ID: condição de pagamento
- COMMENTS: descrição da ordem

### PO_LINES_ALL (alias pla): linhas (itens) da ordem de compra
- PO_LINE_ID: chave primária
- PO_HEADER_ID: = PO_HEADERS_ALL.PO_HEADER_ID
- LINE_NUM: número da linha
- ITEM_ID: item (= EGP_SYSTEM_ITEMS_B.INVENTORY_ITEM_ID)
- CATEGORY_ID: categoria de compra (= EGP_CATEGORIES_TL.CATEGORY_ID)
- ITEM_DESCRIPTION: descrição do item na linha
- UOM_CODE: unidade de medida
- QUANTITY: quantidade comprada
- UNIT_PRICE: preço unitário pago
- AMOUNT: valor da linha quando a linha é por valor
- ORDER_TYPE_LOOKUP_CODE: 'QUANTITY' (por quantidade) ou 'AMOUNT' (por valor)
- LINE_STATUS: status da linha
- CANCEL_FLAG: 'Y' = linha cancelada
- VENDOR_PRODUCT_NUM: código do item no fornecedor
- CREATION_DATE: data de criação da linha

### POZ_SUPPLIERS_V (alias psv): fornecedores
- VENDOR_ID: chave
- VENDOR_NAME: razão social / nome do fornecedor
- SEGMENT1: código do fornecedor

### PER_PERSON_NAMES_F (alias ppn): nomes de pessoas (compradores)
- PERSON_ID: = PO_HEADERS_ALL.AGENT_ID
- DISPLAY_NAME: nome completo para exibição
- FIRST_NAME, LAST_NAME
- NAME_TYPE: usar sempre 'GLOBAL'
- EFFECTIVE_START_DATE, EFFECTIVE_END_DATE: vigência do registro

### EGP_SYSTEM_ITEMS_B (alias esi): cadastro de itens
- INVENTORY_ITEM_ID: = PO_LINES_ALL.ITEM_ID
- ORGANIZATION_ID: organização (o mesmo item se repete em centenas de organizações)
- ITEM_NUMBER: código do item (formato 'CT_906065')

### EGP_CATEGORIES_TL (alias ect): nome das categorias de compra
- CATEGORY_ID: = PO_LINES_ALL.CATEGORY_ID
- CATEGORY_NAME: nome da categoria
- LANGUAGE: idioma. Usar sempre 'PTB'

## Relacionamentos e regras obrigatórias

1. Comprador: `JOIN per_person_names_f ppn ON ppn.person_id = pha.agent_id AND ppn.name_type = 'GLOBAL' AND TRUNC(SYSDATE) BETWEEN ppn.effective_start_date AND ppn.effective_end_date`
2. Fornecedor: `JOIN poz_suppliers_v psv ON psv.vendor_id = pha.vendor_id`
3. Linhas: `JOIN po_lines_all pla ON pla.po_header_id = pha.po_header_id`
4. Categoria: `JOIN egp_categories_tl ect ON ect.category_id = pla.category_id AND ect.language = 'PTB'`
5. Item: NUNCA fazer JOIN direto com EGP_SYSTEM_ITEMS_B (duplica linhas). Para filtrar por código use subconsulta: `pla.item_id IN (SELECT esi.inventory_item_id FROM egp_system_items_b esi WHERE esi.item_number = 'CT_906065')`. Para exibir o código use subconsulta escalar: `(SELECT MAX(esi.item_number) FROM egp_system_items_b esi WHERE esi.inventory_item_id = pla.item_id) AS codigo_item`
6. Código de item informado só com números (ex: 906065): comparar com `esi.item_number IN ('906065', 'CT_906065')`
7. "Ordem", "pedido", "OC", "compra": considerar `pha.type_lookup_code = 'STANDARD'`
8. Valor de uma linha: `CASE WHEN pla.order_type_lookup_code = 'AMOUNT' THEN pla.amount ELSE pla.quantity * pla.unit_price END`
9. Valor de uma ordem = soma do valor das linhas não canceladas (`NVL(pla.cancel_flag,'N') = 'N'`)
10. "Comprado", "valor total", "gasto", "preço pago", "compras", "comprou", "preço médio": toda pergunta sobre compras efetivas desconsidera ordens canceladas (`NVL(pha.cancel_flag,'N') = 'N'`), ordens incompletas, rejeitadas ou canceladas por status (`pha.document_status NOT IN ('INCOMPLETE','REJECTED','CANCELED')`) e linhas canceladas (`NVL(pla.cancel_flag,'N') = 'N'`)
10b. "Criadas", "emitidas", "quantas ordens": contar todas as ordens STANDARD, sem filtrar status ou cancelamento, a menos que a pergunta peça um status específico
11. Data da ordem/emissão = `pha.creation_date`. Ano 2026: `pha.creation_date >= DATE '2026-01-01' AND pha.creation_date < DATE '2027-01-01'`. "Este mês": `pha.creation_date >= TRUNC(SYSDATE,'MM')`. "Último trimestre": `pha.creation_date >= ADD_MONTHS(TRUNC(SYSDATE,'Q'),-3) AND pha.creation_date < TRUNC(SYSDATE,'Q')`. "Últimos N meses": `pha.creation_date >= ADD_MONTHS(TRUNC(SYSDATE), -N)`
12. Nomes de pessoas e fornecedores: busca parcial e sem diferenciar maiúsculas: `UPPER(psv.vendor_name) LIKE '%FERRAGEM%MEDIANEIRA%'`. Troque letras acentuadas por `_` (ex: Sérgio vira `'%S_RGIO%'`)
13. "Últimas N": ordenar por `pha.creation_date DESC` e usar `FETCH FIRST N ROWS ONLY`
14. Todas as colunas do SELECT devem ter alias único em minúsculas e sem acento (ex: `pha.segment1 AS numero_ordem`)
15. Não usar ponto e vírgula no final
16. Use sempre JOIN ... ON explícito. Nunca use junção por vírgula no FROM.
17. Ordem cancelada = `(pha.cancel_flag = 'Y' OR pha.document_status = 'CANCELED')`
18. Comparações entre compras de um mesmo item (última x penúltima compra, variação ou aumento de preço) usam CTE com `ROW_NUMBER() OVER (PARTITION BY pla.item_id ORDER BY pha.creation_date DESC, pla.po_line_id DESC) AS rn` e junção da CTE com ela mesma (ex: `FROM c u JOIN c a ON a.item_id = u.item_id AND a.rn = 2 WHERE u.rn = 1`). Não responda SEM_RESPOSTA para esse tipo de pergunta.
19. Preço médio usa `AVG(pla.unit_price)`, nunca `pla.amount`
20. Ao filtrar categoria por um nome citado pelo usuário, use igualdade: `UPPER(ect.category_name) = UPPER('<nome>')`. Use LIKE só se o usuário disser 'contém' ou 'parecido com'. Fornecedor continua com LIKE, conforme a regra 12.
