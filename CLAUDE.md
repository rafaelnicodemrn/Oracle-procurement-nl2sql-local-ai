# CLAUDE.md: Oracle Procurement NL2SQL com IA local (PI2)

## O que é
Projeto acadêmico (Projeto Integrador II, Engenharia de Software, Uniguaçu) de Rafael Ratti. Sistema que responde perguntas em português sobre compras usando dados reais do Oracle Fusion Procurement Cloud de uma cooperativa agroindustrial do Paraná.

Fluxo: pergunta → IA local (Ollama) gera SQL (com `schema_curado.md`) → `guardrails.py` valida (sqlglot) → `bip_client.py` executa no Fusion via SOAP `runReport` no relatório RunSQL do BI Publisher (`BIP_REPORT_PATH`) → JSON → `resposta.py` monta a resposta localmente, sem IA. **Nenhum dado do Oracle pode ir para a IA**: ela recebe só pergunta, schema e SQL.

## Ambiente
- Windows, PowerShell, Python 3.12 em `.venv` (rodar sempre `.venv\Scripts\python.exe`, sem activate)
- IA local: Ollama em `http://127.0.0.1:11434`, modelo padrão `qwen2.5-coder:7b` (`LLM_MODELO` no `.env`). Nesta máquina o instalador do Ollama é bloqueado pela política da empresa: o Ollama roda no Docker Desktop (container `ollama`, criado por `scripts\iniciar_ollama_docker.bat`)
- Atalhos: `demo.bat` na raiz (uvicorn na porta 8000, com `--app-dir src`) e, em `scripts\`, `testar_ia.bat`, `perguntar.bat`, `avaliar.bat`, `uso_ia.bat`, `testar.bat`, `testar_conexao.bat`
- Dependências em `requirements.txt`. Não adicionar dependências pesadas; o Ollama é chamado por HTTP com `requests`. Frontend sem build (HTML, CSS e JS puros em `src/static/`)
- Repositório Git público: https://github.com/rafaelnicodemrn/Oracle-procurement-nl2sql-local-ai

## Regras obrigatórias
1. **Nunca ler, exibir, copiar ou alterar o arquivo `.env`.** Ele contém a senha e o host do Fusion. Use `.env.example` como referência.
2. **Nunca chamar o Fusion/BIP sem pedir permissão antes.** Cada chamada atinge o ambiente da empresa. A IA local não tem custo, mas ocupa a CPU: avise antes de rodar avaliações longas. Testes automatizados devem usar mocks (veja `tests/conftest.py`, que bloqueia `llm._post` e `requests`).
3. **Não enfraquecer os guardrails.** Qualquer mudança em `guardrails.py` deve manter ou endurecer as regras: só SELECT, uma instrução, whitelist de tabelas em `config.TABELAS_PERMITIDAS`, sem DBMS_/UTL_/SYS./dblink/FOR UPDATE, limite de linhas pelo parâmetro `p_rows`.
4. **Não mudar o contrato do BIP** (envelope SOAP, nomes `p_sql` e `p_rows`, extração de `JSON_DOC`). Foi validado empiricamente e é frágil.
5. **Não editar `src/recursos/schema_curado.md` nem os gabaritos em `avaliacao/`** sem pedir. Eles definem a avaliação acadêmica.
6. Manter compatibilidade com o formato de resposta de `pipeline.Resultado` (a tela e os avaliadores dependem dele).
7. Textos de interface e documentação em português do Brasil, linguagem direta, **sem travessões (—)**.
8. **Nada de dados da empresa no Git.** Nomes de fornecedores, compradores, valores, resultados de avaliação, host e caminho do relatório ficam fora do versionamento (veja `.gitignore`). Antes de cada commit, confira `git status` e o diff. A empresa é citada só como "cooperativa agroindustrial do Paraná".
9. Antes de mudanças grandes, mostre o plano. Antes de alterar um arquivo importante, crie uma cópia em `C:\Programas\Python\Oracle-procurement-nl2sql-local-ai_removidos\backups_<data>\`. Nunca deixe backups dentro do projeto.

## Arquivos
- Código em `src\` (módulos com imports simples; `config.BASE_DIR` é a raiz do projeto e o `.env` fica na raiz)
- `src/config.py`: configuração, whitelist e caminhos
- `src/bip_client.py`: chamada SOAP ao BIP
- `src/guardrails.py`: validação determinística do SQL (rode `.venv\Scripts\python.exe src\guardrails.py` para a bateria de testes)
- `src/llm.py`: IA local via Ollama (somente geração e correção de SQL), trava contra endereço remoto e registro de uso em `dados/uso_llm.csv`
- `src/pipeline.py`: orquestração e métricas
- `src/resposta.py`: resposta em português por regras fixas, sem IA
- `src/app.py` + `src/static/index.html`: API e tela da demo
- `avaliacao/avaliar.py` e `avaliacao/avaliar_conjunto.py`: avaliação contra os gabaritos locais (geram `avaliacao/resultados/`, fora do Git)
- `scripts/explorar.py`: SELECT avulso no Fusion
