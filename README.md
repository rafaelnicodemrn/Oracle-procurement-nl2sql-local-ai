# Oracle Procurement NL2SQL com IA local

Projeto Integrador II, Engenharia de Software, Uniguaçu. Autor: Rafael Ratti.

Perguntas em português sobre compras viram SQL, passam por guardrails determinísticos e são executadas no Oracle Fusion Procurement Cloud. A resposta é montada localmente, por regras fixas. **A IA roda na própria máquina (Ollama): nenhuma pergunta, schema ou dado sai para IA na nuvem.**

## Objetivo

Permitir que o usuário-chave de compras, sem conhecimento técnico, consulte dados reais do Oracle Fusion Procurement de uma cooperativa agroindustrial do Paraná em linguagem natural, sem depender de relatórios prontos. O projeto também mede a distância entre a acurácia de NL2SQL em benchmarks acadêmicos e em um ambiente corporativo real.

Regra de segurança da empresa: nenhum dado retornado do Oracle pode ser enviado a IA na nuvem. A primeira versão usava o Gemini só para gerar SQL. Desde 15/10/2026 o modelo é local, então nem a pergunta sai da máquina. A regra de não enviar dados do Oracle à IA continua valendo e é coberta por testes.

## Arquitetura

```
Pergunta em português
        │
        ▼
 IA local (Ollama) + schema_curado.md ──► SQL   (camada 1: a IA recusa pedidos destrutivos com SEM_RESPOSTA)
        │
        ▼
 guardrails.py (sqlglot) ─────► aprovado?        (camada 2: validação determinística, não depende da IA)
        │ sim                       │ não → status "bloqueado" com a lista de motivos
        ▼
 bip_client.py ► relatório RunSQL do BI Publisher (SOAP runReport, p_sql e p_rows)
        │
        ▼
 JSON (JSON_DOC) ──► resposta.py (local, sem IA) ──► resposta + tabela + métricas
        ▲
        └── correção automática (1x) se der erro ORA- ou SQL não interpretável (IA local, só com SQL e erro)
```

### Duas camadas de defesa

1. **Camada 1, a IA:** o prompt manda responder `SEM_RESPOSTA` para qualquer pedido que não seja consulta de compras (apagar, alterar, listar senhas e salários etc.). Ela depende do modelo e pode falhar.
2. **Camada 2, os guardrails:** `guardrails.py` valida o SQL sem usar IA. Só SELECT, uma única instrução, whitelist de tabelas em `config.TABELAS_PERMITIDAS`, allowlist de funções, sem `DBMS_`, `UTL_`, `SYS.`, dblink nem `FOR UPDATE`, e limite de linhas pelo parâmetro `p_rows` do BIP, fora do SQL. Um bloqueio é definitivo e não volta para a IA.

Se a camada 1 falhar e a IA gerar um comando perigoso, a camada 2 ainda impede a execução. A interface mostra só a pergunta, a resposta, os dados e, fechado por padrão, o painel "Detalhes técnicos" com o SQL gerado.

## IA local (Ollama)

| Item | Valor padrão | Onde mudar |
|---|---|---|
| Servidor | `http://127.0.0.1:11434` | `OLLAMA_URL` |
| Modelo | `qwen2.5-coder:7b` | `LLM_MODELO` |
| Tempo máximo por chamada | 600 s | `OLLAMA_TIMEOUT` |
| Janela de contexto | 8192 tokens (o prompt com o schema passa de 2.000) | `OLLAMA_NUM_CTX` |
| Modelo carregado na memória | 30 min após a última chamada | `OLLAMA_KEEP_ALIVE` |

- Temperatura 0 e semente fixa, para reduzir a variação do SQL entre execuções
- Trava de segurança: o `llm.py` recusa `OLLAMA_URL` fora de localhost ou de IP de rede privada e modelos `*-cloud` do Ollama. Para usar um servidor interno com nome, defina `OLLAMA_PERMITIR_REMOTO=true`
- Modelos com raciocínio (ex: família qwen3): o bloco `<think>` é removido da resposta; `OLLAMA_THINK=false` desliga o modo pensamento
- Sem GPU dedicada, o modelo roda na CPU. Medição em notebook Intel i5-1335U com 16 GB, Ollama no Docker e `qwen2.5-coder:7b` (15/10/2026):

  | Chamada | Tempo | Tokens (entrada / saída) |
  |---|---|---|
  | Primeira, carregando o modelo | mais de 300 s | 2.059 / 169 |
  | Seguinte, SQL com junções | 78 s | 2.057 / 147 |
  | Seguinte, SQL simples | 18 s | 2.052 / 36 |

  O tempo cresce com o tamanho do SQL gerado (cerca de 2 tokens por segundo). Para mais velocidade, troque para `qwen2.5-coder:3b` e meça a acurácia de novo
- Uso registrado em `dados/uso_llm.csv` (tokens e latência). Custo por chamada: zero

## Resultados da avaliação

Medições feitas com a versão em nuvem (`gemini-3.5-flash-lite`), até 1 correção automática. Dois critérios: **EX estrito** (mesmas linhas, ignorando ordem e nome de coluna) e **EX relaxado** (aceita colunas a mais).

| Avaliação | Perguntas | EX estrito | EX relaxado |
|---|---|---|---|
| v1, conjunto de ajuste (06/10) | 15 | 60,0% | 66,7% |
| v2, conjunto de ajuste (06/10) | 15 | 66,7% | 93,3% |
| v3, conjunto de ajuste (07/10) | 15 | 60,0% | 86,7% |
| Conjunto de teste separado, 3 repetições (14/10) | 20 | 88,3% (85,0 a 90,0) | 96,7% (95,0 a 100,0) |

No conjunto de teste: latência média de 3,3 s (1,4 s da IA e 1,9 s do Oracle), cerca de 2.400 tokens por pergunta e 5 de 6 ataques em linguagem natural contidos pela camada 1. Todos os SQLs maliciosos da bateria de testes são bloqueados pela camada 2.

**Próximo passo:** rodar `scripts\avaliar_conjunto.bat` com o modelo local e comparar acurácia e latência com a linha de base do Gemini.

## Dados que ficam fora do Git

O repositório não contém dados da empresa. Ficam só na máquina local (ver `.gitignore`):

- `.env` com usuário, senha, host do Fusion e caminho do relatório
- `avaliacao/gabarito.json` e `avaliacao/gabarito_teste.json`, que citam fornecedores, compradores e itens reais. O formato está em `avaliacao/gabarito_exemplo.json`
- `avaliacao/resultados/`, `dados/`, a apresentação e os documentos com valores reais (revisão do gabarito, roteiro da demo e checklist de testes manuais)

Sem os gabaritos reais, os testes que dependem deles são pulados e os demais usam o exemplo.

## Limitações conhecidas

- **Sobreajuste ao conjunto de ajuste:** as regras 17 a 19 do schema nasceram dos erros da v1. Por isso existe o conjunto de teste separado, congelado antes da primeira execução
- **Variação do SQL entre execuções:** mesmo com temperatura 0, o SQL gerado pode mudar. A avaliação repetida mostra a variação real
- **Timeout do RunSQL compartilhado:** o relatório BIP tem timeout próprio (`BIP_TIMEOUT`, 60 s). Consultas pesadas podem falhar por tempo, e a API atende uma pergunta por vez
- **Desempenho na CPU:** o modelo local é mais lento que a API em nuvem. A acurácia precisa ser medida de novo para cada modelo
- **Escopo:** só Procurement, níveis 1 a 3. Sourcing (`PON_*`) e requisições (`POR_*`) ficam como extensão futura
- **Colunas extras e EX estrito:** o EX estrito penaliza respostas corretas com colunas além das do gabarito

## Estrutura do projeto

```
Oracle-procurement-nl2sql-local-ai\
  README.md, requirements.txt, .env.example, .gitignore, CLAUDE.md
  demo.bat                    sobe a tela da demo
  src\
    app.py                    API FastAPI e entrega da tela
    pipeline.py               orquestração e métricas
    llm.py                    IA local via Ollama (só gera e corrige SQL) e registro de uso
    guardrails.py             validação determinística do SQL
    bip_client.py             chamada SOAP ao BI Publisher
    config.py                 configuração, whitelist e caminhos
    resposta.py               resposta em português, sem IA
    recursos\schema_curado.md schema enviado à IA
    static\index.html         tela (HTML, CSS e JS puros, sem build)
  tests\                      testes automatizados com mocks (sem IA nem Oracle)
  avaliacao\                  avaliar.py, avaliar_conjunto.py, validar_gabarito.py e gabarito_exemplo.json
  scripts\                    atalhos .bat, uso_ia.py e explorar.py
  docs\                       revisão de segurança
```

## Instalação (Windows)

1. Suba o Ollama. Há dois caminhos:

   - **Instalador nativo:** instale em https://ollama.com/download e rode `ollama pull qwen2.5-coder:7b`
   - **Docker** (para máquinas em que o instalador é bloqueado): com o Docker Desktop instalado, rode `scripts\iniciar_ollama_docker.bat`. Ele cria o container `ollama` com a porta 11434 aberta só para a própria máquina (`127.0.0.1`), reinício automático e volume para os modelos, e baixa o `qwen2.5-coder:7b`. Para outro modelo: `scripts\iniciar_ollama_docker.bat qwen2.5-coder:3b`

2. Instale o projeto:

   ```powershell
   cd Oracle-procurement-nl2sql-local-ai
   py -3.12 -m venv .venv
   .venv\Scripts\python.exe -m pip install -r requirements.txt
   copy .env.example .env
   notepad .env
   ```

   No `.env`, preencha `BIP_HOST`, `BIP_REPORT_PATH`, `BIP_USER` e `BIP_PASS`. O `.env` guarda segredos e não é versionado.

3. Confira a IA local com `scripts\testar_ia.bat` (gera um SQL de exemplo, sem acessar o Oracle).

## Como rodar

| Atalho | O que faz |
|---|---|
| `demo.bat` | Sobe a tela em http://127.0.0.1:8000 e abre o navegador quando `/health` responder |
| `scripts\iniciar_ollama_docker.bat` | Sobe o Ollama no Docker e baixa o modelo (alternativa ao instalador) |
| `scripts\testar_ia.bat` | Confere o Ollama e o modelo e gera um SQL de exemplo (não acessa o Oracle) |
| `scripts\testar_conexao.bat` | Testa a conexão com o Fusion (1 chamada ao BIP) |
| `scripts\testar.bat` | Roda os testes automatizados, sem IA nem Oracle |
| `scripts\perguntar.bat` | Pergunta pelo terminal (usa IA local e Oracle) |
| `scripts\avaliar.bat` | Avaliação no conjunto de ajuste (usa IA local e Oracle) |
| `scripts\avaliar_conjunto.bat` | Avaliação repetida no conjunto de teste separado |
| `scripts\validar_gabarito.bat` | Valida a estrutura de um gabarito antes de avaliar |
| `scripts\uso_ia.bat` | Mostra chamadas, tokens e latência média da IA local |
| `scripts\explorar.bat` | Executa um SELECT avulso no Fusion |
| `scripts\instalar.bat` | Apaga e recria o `.venv` e instala as dependências |

Modo de demonstração offline, sem IA nem Oracle:

```powershell
$env:DEMO_OFFLINE = "true"
.venv\Scripts\python.exe -m uvicorn app:app --app-dir src --host 127.0.0.1 --port 8000
```

As respostas são simuladas nos status ok, bloqueado, sql_invalido e erro_execucao. A validação de segurança continua real nesse modo, porque a camada 2 é local.

## Decisões de projeto

- Nenhum dado do Oracle vai para a IA: ela só gera e corrige SQL, e a resposta é montada em `resposta.py`. Um teste falha se uma chamada à IA receber conteúdo do resultado
- IA local via Ollama, com trava contra endereço remoto e modelos de nuvem
- Limite de linhas aplicado pelo parâmetro `p_rows` do BIP, fora do SQL gerado pela IA
- Bloqueio de guardrail é definitivo; erro de execução (ORA-) ou SQL não interpretável recebe 1 tentativa de correção
- Uma consulta por vez (HTTP 429 se houver outra em andamento)
- Item com centenas de organizações: filtro por subconsulta em `EGP_SYSTEM_ITEMS_B`, nunca join direto
- Categorias filtradas por `LANGUAGE = 'PTB'`; compradores por `NAME_TYPE = 'GLOBAL'` e vigência
- Host do Fusion e caminho do relatório só no `.env`
