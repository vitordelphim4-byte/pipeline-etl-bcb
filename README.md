# Pipeline ETL — População Estimada por Estado (IBGE)

Pipeline ETL modular que extrai as estimativas anuais de população residente por estado brasileiro, publicadas pelo IBGE (API de Agregados / SIDRA), trata e valida os dados com pandas, e carrega em um banco relacional de forma idempotente. Roda automaticamente via GitHub Actions.

Projeto de portfólio focado em práticas de engenharia de dados: separação em módulos, tratamento de erros, retry, logging estruturado, idempotência e execução agendada na nuvem.

## Dado extraído

Fonte: [API de Agregados do IBGE](https://servicodados.ibge.gov.br/api/docs/agregados?versao=3) (pública, sem autenticação), tabela SIDRA **6579 — População residente estimada**.

| Nível geográfico | Período | Frequência de publicação |
|---|---|---|
| Estado (N3 — 27 Unidades da Federação) | 2001 em diante (com lacunas: 2007, 2010, 2022, 2023 não têm estimativa publicada) | Anual |

## Arquitetura

```mermaid
flowchart LR
    API[("API Agregados<br/>IBGE / SIDRA 6579")] --> EXTRACT["extract.py<br/>(requests + retry)"]
    EXTRACT --> TRANSFORM["transform.py<br/>(pandas: achata série<br/>aninhada, tipagem,<br/>qualidade)"]
    TRANSFORM --> LOAD["load.py<br/>(SQLAlchemy: upsert)"]
    LOAD --> DB[("Banco relacional<br/>SQLite (padrão) / Oracle")]
    LOAD --> CSV[["data/populacao.csv<br/>(snapshot versionado)"]]

    subgraph GHA["GitHub Actions — cron mensal"]
        CRON(["dia 1, 12:00 UTC"]) --> MAIN["main.py"]
    end

    MAIN -.orquestra.-> EXTRACT
    CSV --> COMMIT["commit automático<br/>no repositório"]
```

- **extract.py** — busca a série de população por estado na API de Agregados do IBGE via `requests`, com retry automático (3 tentativas, backoff exponencial) e timeout configurado. A resposta da API é aninhada (uma série de ano→valor por localidade); `extract.py` devolve essa estrutura bruta, sem achatar.
- **transform.py** — usa pandas para achatar a série aninhada em formato tabular (`uf_id`, `uf_nome`, `ano`, `populacao`), tipar como inteiro e checar qualidade (remove nulos e duplicatas de `uf_id`+`ano`).
- **load.py** — grava no banco via SQLAlchemy com upsert idempotente (rodar o pipeline várias vezes não duplica dados) e exporta o histórico completo da tabela para `data/populacao.csv`.
- **main.py** — orquestra as 3 fases com logging de início/fim de cada uma; qualquer exceção é logada com stack trace completo e encerra o processo com código de saída ≠ 0 (o pipeline nunca falha silenciosamente).

## Stack

Python 3.14 · requests · pandas · SQLAlchemy · SQLite · GitHub Actions

## Como rodar localmente

```powershell
# 1. Criar e ativar o ambiente virtual
python -m venv venv
.\venv\Scripts\Activate.ps1

# 2. Instalar dependências
pip install -r requirements.txt

# 3. Rodar o pipeline completo
python main.py
```

Resultado: `data/populacao.db` (SQLite) e `data/populacao.csv` atualizados.

### Trocar de banco

A URL de conexão é lida da variável de ambiente `DATABASE_URL` (padrão: `sqlite:///data/populacao.db`). Para apontar para outro banco (ex.: Oracle), basta definir a variável — nenhum código precisa mudar:

```powershell
$env:DATABASE_URL = "oracle+oracledb://usuario:senha@host:porta/servico"
python main.py
```

## Agendamento

O workflow [`.github/workflows/pipeline.yml`](.github/workflows/pipeline.yml) roda o pipeline automaticamente todo dia 1 de cada mês às 12:00 UTC. Cron mensal (não diário) porque o dado é anual — rodar todo dia seria redundante. Também pode ser disparado manualmente pela aba **Actions** do GitHub (`workflow_dispatch`).

A cada execução, o CSV atualizado é commitado de volta no repositório (só quando há mudança de fato) — o que torna o histórico de execuções agendadas visível diretamente no histórico de commits do Git.

## Decisões técnicas

- **Nível estadual (N3), não municipal (N6)**: a mesma tabela do IBGE também tem dado por município (~5.570 localidades). Optamos por estado (27 localidades) para manter o dataset enxuto; expandir para município é uma mudança pequena e localizada em `extract.py` (só trocar o nível territorial da consulta).
- **Intervalo de anos pedido à API é propositalmente "aberto" (2001-2030)**: a API do IBGE simplesmente omite anos sem dado publicado em vez de dar erro. Isso significa que o pipeline capta automaticamente uma nova estimativa anual assim que o IBGE publicar, sem precisar editar código todo ano.
- **Upsert portável, sem sintaxe específica de dialeto**: em vez de `ON CONFLICT` (SQLite/Postgres apenas, sem equivalente direto no Oracle), o `load.py` verifica chaves existentes e decide entre `INSERT`/`UPDATE` usando apenas SQL padrão do SQLAlchemy Core — garante que a troca de banco via `DATABASE_URL` funcione de fato sem reescrever a lógica de carga.
- **CSV reflete o histórico acumulado da tabela**, não só o lote da execução atual — o snapshot cresce de forma incremental e legível no Git a cada execução agendada.
