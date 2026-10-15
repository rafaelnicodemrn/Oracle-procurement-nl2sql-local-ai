# Revisão de segurança: NL2SQL Procurement

Data: 06/10/2026. Revisão feita sem nenhuma chamada ao Gemini ou ao Oracle Fusion: todos os testes
usam o validador local (`guardrails.validar`), o `TestClient` do FastAPI e mocks.

## Resumo

| # | Achado | Gravidade | Situação |
|---|---|---|---|
| G1 | Funções de rede e de objetos internos aprovadas (HTTPURITYPE, DBURITYPE...) | Alta | Corrigido |
| G2 | Consultas de custo explosivo aprovadas (CONNECT BY, WITH recursivo, CROSS JOIN...) | Alta | Corrigido, com risco residual |
| G3 | Funções de tabela aprovadas (XMLTABLE, JSON_TABLE, TABLE) | Média | Corrigido |
| G4 | Funções que revelam dados da sessão (SYS_CONTEXT, USERENV) | Baixa | Corrigido (exceto pseudo-coluna USER) |
| I1 | Erros crus na tela (URL do servidor, resposta do BIP, internals do parser) | Média | Corrigido |
| A1 | API sem limite de tamanho de entrada | Média | Corrigido |
| A2 | Consultas simultâneas sem controle | Baixa | Corrigido |
| A3 | CSRF, CORS e exposição de rede | Baixa | Já protegido, coberto por teste |
| A4 | XSS na tela | Baixa | Já protegido; reforço na nova interface |
| D1 | Dados reais enviados ao Gemini no resumo | Média | Corrigido: nenhum dado do Oracle sai da empresa |
| P1 | Prompt injection | Baixa | Mitigado |
| C1 | Teto de custo furável por concorrência; CSV corrompido derrubava o sistema | Média | Corrigido |
| R1 | Texto em volta do SQL era tratado como bloqueio de segurança | Robustez | Corrigido (status `sql_invalido`) |

## Atualização de 15/10/2026: IA local

O Gemini foi substituído por um modelo local servido pelo Ollama (`src/llm.py`). Efeitos na segurança:

- **D1 e limitação 5 resolvidos por completo:** pergunta, schema e SQL não saem mais da máquina.
  A regra de não enviar dados do Oracle à IA continua valendo e testada (`tests/test_sem_dados_na_ia.py`).
- **Trava contra configuração errada:** o `llm.py` recusa `OLLAMA_URL` fora de localhost ou de IP de
  rede privada e modelos `*-cloud` do Ollama, salvo `OLLAMA_PERMITIR_REMOTO=true` no `.env`.
- **C1, limitações 4 e 6 deixam de existir:** sem custo por chamada, sem teto de gasto e sem limite 429.
  O registro de uso (tokens e latência) fica em `dados/uso_llm.csv`.
- **Novo risco operacional:** o modelo roda na CPU. A primeira chamada carrega o modelo e pode levar
  minutos (`OLLAMA_TIMEOUT`, 300 s). A API continua atendendo uma pergunta por vez.
- Os achados abaixo continuam válidos: os guardrails não dependem do modelo usado.

O texto abaixo é a revisão original de 06/10/2026, feita com o Gemini.

Princípio mantido: **nenhuma decisão de segurança depende da IA**. Todas as regras são determinísticas
e o SQL executado é exatamente o SQL validado.

## Achados

### G1. Funções de rede e de objetos internos (alta)

**Reprodução (antes da correção, todos APROVADOS):**

```sql
SELECT HTTPURITYPE('http://x').getclob() FROM dual
SELECT DBURITYPE('/SCOTT/EMP').getclob() FROM dual
SELECT XDBURITYPE('/public').getclob() FROM dual
SELECT uritype.createuri('http://x') FROM dual
SELECT sys_dburigen(segment1) FROM po_headers_all
SELECT owa_util.get_cgi_env('x') FROM dual
SELECT ora_hash(segment1) FROM po_headers_all
```

**Impacto:** o banco de produção poderia abrir conexões HTTP para fora (SSRF e exfiltração de dados)
ou ler objetos fora da whitelist por URI.

**Causa:** só havia lista negra por expressão regular; qualquer função fora dela passava.

**Correção (`guardrails.py` e `config.py`):**
1. Lista negra ampliada: `DBMS_`, `UTL_`, `ORA_`, `CTX_`, `OWA_`, `APEX_`, `HTP.`, `HTF.`, `*URITYPE`,
   `SYS_DBURIGEN`, `SYS_XMLGEN`, `SYS_XMLAGG`, `SYS_CONTEXT`, `USERENV`, `XMLTYPE`, `XMLQUERY`.
2. **Allowlist de funções pela árvore sintática.** O sqlglot reconhece as funções comuns como nós
   tipados (SUM, NVL, TO_CHAR, ADD_MONTHS, LISTAGG, ROW_NUMBER...). Funções que ele não conhece viram
   nós `Anonymous`, e essas só passam se estiverem em `config.FUNCOES_PERMITIDAS`. A mensagem cita a
   função: `função não permitida: HTTPURITYPE`.
3. Chamada de função de pacote ou método (`x.y(...)`) é bloqueada.
4. Identificadores com prefixo proibido são bloqueados também pela árvore, não só pelo texto. Isso fecha
   o caso em que a remoção de strings literais do regex é desalinhada (por exemplo, pela sintaxe
   `q'[...]'` do Oracle).

Na montagem da allowlist foram testadas mais de 80 funções Oracle. Só quatro caem em `Anonymous` na versão
atual do sqlglot (TRUNC com um argumento, RATIO_TO_REPORT, NUMTOYMINTERVAL e NUMTODSINTERVAL). A
allowlist inclui essas quatro e mais as funções Oracle de uso comum, como proteção contra mudanças de
versão do sqlglot.

### G2. Consultas de custo explosivo (alta)

**Reprodução (antes da correção, todos APROVADOS):**

```sql
SELECT LEVEL FROM dual CONNECT BY LEVEL <= 1000000000
WITH r (n) AS (SELECT 1 FROM dual UNION ALL SELECT n + 1 FROM r WHERE n < 1000000000) SELECT n FROM r
SELECT COUNT(*) FROM po_lines_all a, po_lines_all b, po_lines_all c
SELECT * FROM po_headers_all CROSS JOIN po_lines_all
SELECT * FROM po_lines_all a JOIN po_lines_all b ON 1=1
```

A cláusula MODEL era barrada apenas porque o sqlglot não consegue interpretá-la.

**Impacto:** o parâmetro `p_rows` limita as linhas devolvidas, não o trabalho do banco. Uma consulta
dessas pode continuar consumindo o Fusion de produção depois que o cliente desiste.

**Correção:**
- CONNECT BY, cláusula MODEL e CROSS JOIN bloqueados com regra própria
- WITH recursivo bloqueado: só a CTE que referencia a si mesma. WITH comum continua permitido
  (a pergunta 15 do gabarito usa)
- Junção sem `ON`/`USING` (inclusive por vírgula) e `ON` sem nenhuma coluna bloqueados
- No máximo 10 tabelas referenciadas e 4.000 caracteres de SQL (o maior SQL do gabarito tem cerca de 900)
- Regra 16 no `schema_curado.md`: "Use sempre JOIN ... ON explícito. Nunca use junção por vírgula no FROM."
- `BIP_TIMEOUT` padrão reduzido de 120 para 60 segundos

### G3. Funções de tabela (média)

**Reprodução:** `SELECT * FROM XMLTABLE(...)`, `SELECT * FROM JSON_TABLE(...)`,
`SELECT * FROM TABLE(sys_odcivarchar2list('a'))` eram aprovados.

**Correção:** bloqueio pelos nós `XMLTable` e `JSONTable` do sqlglot e por regex de `TABLE(`.

### G4. Dados da sessão (baixa)

`SYS_CONTEXT` e `USERENV` revelavam usuário do banco, IP e sessão. Agora são bloqueados (G1). A
pseudo-coluna `USER` continua permitida: bloqueá-la por texto geraria falso positivo em aliases e o
dado exposto (nome do usuário técnico) é de baixo valor.

### I1. Vazamento de informação em erros (média)

**Reprodução:**
- Uma falha de rede do `requests` aparecia na tela com a URL completa do servidor Fusion
- O `BIPError` repassava até 500 caracteres da resposta do servidor
- O motivo "SQL inválido" trazia detalhes internos do sqlglot e códigos de cor ANSI (`\x1b[4m`)

**Correção (`pipeline.py`):**
- Erro do Oracle: a tela mostra apenas `ORA-NNNNN: mensagem` (o código e o texto continuam visíveis)
- HTTP sem ORA: "O Oracle respondeu com erro HTTP NNN."
- Falta de rede: "Sem conexão com o Oracle. Verifique a rede ou a VPN."
- Tempo esgotado, limite da IA, orçamento: mensagens próprias e claras
- Qualquer outra exceção: "Erro interno. Detalhes no console do servidor."
- O detalhe completo vai para o log do console (`logging`), nunca para a API
- A IA recebe na correção a mensagem já limpa
- Motivos de parse sem códigos ANSI, em uma linha e com no máximo 200 caracteres
- Exceção não tratada na API devolve só "Internal Server Error", sem stack trace (coberto por teste)

### A1. Tamanho de entrada (média)

**Reprodução:** `/validar` aceitava 200 mil caracteres; `/perguntar` aceitava qualquer tamanho, o que
vira tokens e custo no Gemini.

**Correção:** `pergunta` entre 1 e 500 caracteres; `sql` com no máximo 10.000. Fora disso: HTTP 422.

### A2. Concorrência (baixa)

**Correção:** `/perguntar` atende uma pergunta por vez. Se já houver uma em andamento, responde
HTTP 429 com "Já existe uma consulta em andamento. Aguarde o resultado."

### A3. CSRF, CORS e rede (baixa, já protegido)

- POST com `Content-Type: text/plain` (formulário de outro site) recebe 422 e não dispara consulta
- Sem middleware CORS: o navegador bloqueia chamadas JSON vindas de outra origem
- `demo.bat` agora passa `--host 127.0.0.1` explicitamente

### A4. XSS (baixa)

A tela escapa todos os dados exibidos. O único valor sem escape era o `status`, que vem de um
conjunto fixo do servidor. A nova interface escapa também esse valor.

### D1. Dados enviados ao Gemini (média, agora corrigido)

**Nova regra da empresa:** nenhum dado retornado do Oracle pode ser enviado para IA na nuvem. O Gemini
é usado **exclusivamente** para gerar e corrigir SQL.

O que sai da empresa para o Google:
1. O schema curado (nomes de tabelas e colunas, sem dados)
2. A pergunta do usuário
3. Na correção: o SQL que falhou e a primeira linha do erro ORA, com valores entre aspas mascarados

O que **não** sai mais: qualquer linha, valor ou amostra do resultado. Antes, o resumo enviava até 20
linhas ao Gemini (e já tinha sido reduzido de 50).

**Correção:**
- `llm.resumir`, `INSTRUCAO_RESUMO` e as configurações `RESUMIR_RESPOSTA` e `RESUMO_MAX_LINHAS` foram removidos
- A resposta em português agora é montada localmente por `resposta.py`, com regras fixas (sem IA e sem
  rede): 0 linhas, 1 valor, 1 linha com várias colunas, várias linhas (cita o primeiro quando há
  `ORDER BY`) e modo relatório. Valores em R$, inteiros com separador de milhar e datas em dd/mm/aaaa
- `llm.py` expõe só `gerar_sql` e `corrigir_sql`, e nenhuma delas aceita linhas de resultado
- O prompt de geração de SQL não foi alterado, e as avaliações v2 e v3 (86,7% a 93,3% no EX relaxado) foram feitas com esse mesmo prompt

**Teste de segurança:** `tests/test_sem_dados_na_nuvem.py` usa o `llm.py` real com um cliente Gemini
falso que guarda tudo o que receberia. As linhas do Oracle levam marcadores únicos, e o teste falha se
qualquer marcador aparecer em uma chamada ao Gemini, nos fluxos com sucesso, com correção, com erro de
execução e com dados hostis. Outro teste falha se o `llm.py` voltar a expor função que receba dados.

**Erro ORA na correção (mascarado):** a correção automática continua ligada (`TENTATIVAS_CORRECAO=1`),
e o erro passa por `llm.sanitizar_erro` antes de ir ao Gemini:
- fica só a primeira linha, no formato `ORA-NNNNN: mensagem`
- todo trecho entre aspas (simples ou duplas) que **não aparece no SQL enviado** vira `<valor>`, e aspas
  que não fecham até o fim da linha também. Assim passam nomes de colunas e tabelas do próprio SQL, mas
  nenhum valor vindo do banco
- testes em `test_sem_dados_na_nuvem.py`: mascaramento de valores, valores do SQL preservados, descarte
  de linhas extras e um fluxo completo em que o erro cita dados do banco e nada chega ao Gemini

**Risco residual:** um erro ORA que cite um dado do banco **sem aspas** (por exemplo, um número solto)
não seria mascarado. As mensagens ORA mais comuns de SQL gerado (identificador inválido, tabela
inexistente, número inválido) não fazem isso.

**Próximo passo:** usar um modelo local (Ollama) para gerar e corrigir o SQL, eliminando a nuvem por
completo. A pergunta, o schema e o SQL também deixariam de sair da empresa. Exige medir a qualidade do
modelo local contra o `gabarito.json`, porque a taxa de acerto pode cair em relação ao Gemini.

### P1. Prompt injection (baixa)

A pergunta entrava direto no prompt. Antes, dados do Fusion (por exemplo, `COMMENTS`) também chegavam ao
resumo, risco que desapareceu com a remoção do resumo por IA.

**Mitigação:** a pergunta vai delimitada (`<pergunta>`), com instrução para tratá-la como dado. As tags dentro do texto do usuário são removidas para que ele não feche o
bloco antes. O mais importante continua valendo: mesmo que a IA seja convencida, o SQL passa pelos
guardrails determinísticos.

### C1. Teto de custo (média)

**Reprodução:**
- Duas chamadas simultâneas passavam juntas pela verificação do teto
- Uma linha corrompida em `dados/custos_gemini.csv` gerava `ValueError` e toda pergunta falhava

**Correção (`llm.py`):**
- Trava (`threading.Lock`): verificação do teto, chamada e registro do custo acontecem um por vez
- CSV ilegível: nenhuma chamada é feita e a mensagem diz qual registro corrigir (`CustosIlegiveis`).
  `scripts\custos.bat` mostra a mesma mensagem em vez de um stack trace
- Conferido: não existe caminho que chame o Gemini sem passar pelo teto (`gerar_sql` e `corrigir_sql`
  usam `_chamar`)

### R1. SQL com texto em volta e status `sql_invalido`

Antes, se o Gemini respondesse "Aqui está a consulta: SELECT ...", o parse falhava e a pergunta era
marcada como **bloqueada**, o que parecia um bloqueio de segurança.

**Correção:**
- `guardrails.extrair_sql` tira o SQL de dentro do texto (bloco de código ou a partir do primeiro
  SELECT/WITH) e remove frases finais até o SQL ser interpretável
- A extração **nunca descarta** trechos com `;` ou comandos (INSERT, UPDATE, DELETE, DROP...): um
  ataque escondido antes ou depois do SELECT continua chegando à validação e é bloqueado
- SQL que não pode ser interpretado e não tem nenhum motivo de segurança recebe o status
  `sql_invalido` e uma tentativa de correção pela IA. O SQL corrigido passa de novo por todos os guardrails
- Qualquer motivo de segurança, mesmo junto com erro de sintaxe, continua `bloqueado` e definitivo

## Limitações conhecidas

1. **Timeout no banco.** O limite de tempo da consulta dentro do Oracle depende do modelo de dados do
   relatório RunSQL do BI Publisher (`BIP_REPORT_PATH`), que é compartilhado e não pode ser alterado por este
   projeto. O `BIP_TIMEOUT` (60 s) só encerra a espera do cliente; a consulta pode continuar rodando no
   banco. Os bloqueios de G2 reduzem esse risco, mas uma junção legítima e cara continua possível.
2. **Lista de funções depende do sqlglot.** A classificação de funções como `Anonymous` pode mudar
   entre versões. Os testes `test_funcoes_oracle_comuns_aprovadas` e
   `test_sql_referencia_do_gabarito_aprovado` detectam falso bloqueio depois de uma atualização.
3. **Pseudo-coluna USER** continua permitida (ver G4).
4. **Preço dos tokens.** O teto usa `PRECO_INPUT_1M` e `PRECO_OUTPUT_1M` do `.env`. Se esses valores
   não baterem com a tabela atual do Google, o teto não reflete o gasto real.
5. **Nuvem ainda envolvida na geração do SQL.** Pergunta, schema e SQL ainda vão ao Gemini. Próximo
   passo: modelo local (Ollama), ver D1.
6. **Limite 429 do Gemini.** Em caso de limite de requisições, o sistema espera 20 s e tenta de novo
   (até duas vezes). Durante a espera, a consulta fica em andamento.

## Testes

Os casos estão em `tests/` e na bateria de `python src\guardrails.py`:

- `tests/test_guardrails.py`: casos aprovados, todos os ataques acima, 43 funções Oracle legítimas,
  allowlist vinda do `config.py`, extração de SQL (inclusive ataques escondidos em texto) e os
  **15 SQLs de referência do gabarito, que devem continuar aprovados**
- `tests/test_pipeline.py`: `sql_invalido` com e sem correção, bloqueio definitivo, mensagens de erro
  seguras, CSV de custos ilegível e pergunta delimitada no prompt
- `tests/test_resposta.py`: regras fixas da resposta local (0 linhas, 1 valor, várias colunas, `ORDER BY`, relatório)
- `tests/test_sem_dados_na_nuvem.py`: falha se qualquer chamada ao Gemini receber conteúdo do resultado do Oracle
- `tests/test_app.py`: limites de tamanho, CSRF, CORS, uma consulta por vez e ausência de stack trace

Rodar: `scripts\testar.bat`

## Interface

O painel "Testar guardrail", os botões de ataque e o gasto acumulado do Gemini saíram da tela, que agora é voltada ao usuário-chave de compras. A segurança do backend não mudou. O endpoint `/validar` continua para os testes automatizados (`tests/test_app.py`), sem botão na tela. Recusas e bloqueios aparecem com mensagens em linguagem simples, e o SQL gerado fica no painel "Detalhes técnicos", fechado por padrão.
