# Pipeline ETL — Indicadores Econômicos (Banco Central do Brasil)

Pipeline ETL modular que extrai indicadores econômicos publicados pelo Banco Central do Brasil (API SGS), trata e valida os dados com pandas, e carrega em um banco relacional de forma idempotente. Roda diariamente de forma automatizada via GitHub Actions.

Projeto de portfólio focado em práticas de engenharia de dados: separação em módulos, tratamento de erros, retry, logging estruturado, idempotência e execução agendada na nuvem.

## Indicadores extraídos

Fonte: [API SGS do Banco Central](https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados?formato=json) (pública, sem autenticação).

| Código | Indicador | Periodicidade |
|---|---|---|
| 1 | Dólar americano (venda) | Diária |
| 433 | IPCA — variação mensal (%) | Mensal |
| 432 | Meta Selic definida pelo Copom (% a.a.) | Diária |

## Arquitetura

```mermaid
flowchart LR
    API[("API SGS<br/>Banco Central")] --> EXTRACT["extract.py<br/>(requests + retry)"]
    EXTRACT --> TRANSFORM["transform.py<br/>(pandas: tipagem,<br/>schema, qualidade)"]
    TRANSFORM --> LOAD["load.py<br/>(SQLAlchemy: upsert)"]
    LOAD --> DB[("Banco relacional<br/>SQLite (padrão) / Oracle")]
    LOAD --> CSV[["data/indicadores.csv<br/>(snapshot versionado)"]]

    subgraph GHA["GitHub Actions — cron diário"]
        CRON(["21:00 UTC<br/>(18:00 BRT)"]) --> MAIN["main.py"]
    end

    MAIN -.orquestra.-> EXTRACT
    CSV --> COMMIT["commit automático<br/>no repositório"]
```

- **extract.py** — busca as 3 séries na API do SGS via `requests`, com retry automático (3 tentativas, backoff exponencial) para falhas transitórias e timeout configurado. Loga cada chamada.
- **transform.py** — usa pandas para tipar (`data` → datetime, `valor` → float), padronizar o schema (`codigo_serie`, `nome_serie`, `data`, `valor`) e checar qualidade (remove nulos e duplicatas de `codigo_serie`+`data`).
- **load.py** — grava no banco via SQLAlchemy com upsert idempotente (rodar o pipeline várias vezes não duplica dados) e exporta o histórico completo da tabela para `data/indicadores.csv`.
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

Resultado: `data/indicadores.db` (SQLite) e `data/indicadores.csv` atualizados.

### Trocar de banco

A URL de conexão é lida da variável de ambiente `DATABASE_URL` (padrão: `sqlite:///data/indicadores.db`). Para apontar para outro banco (ex.: Oracle), basta definir a variável — nenhum código precisa mudar:

```powershell
$env:DATABASE_URL = "oracle+oracledb://usuario:senha@host:porta/servico"
python main.py
```

## Agendamento

O workflow [`.github/workflows/pipeline.yml`](.github/workflows/pipeline.yml) roda o pipeline automaticamente todo dia às 21:00 UTC (18:00 no horário de Brasília), após o fechamento diário do câmbio (PTAX) e a divulgação do SGS. Também pode ser disparado manualmente pela aba **Actions** do GitHub (`workflow_dispatch`).

A cada execução, o CSV atualizado é commitado de volta no repositório (só quando há mudança de fato) — o que torna o histórico de execuções agendadas visível diretamente no histórico de commits do Git.

## Decisões técnicas

- **Janela de extração de 2 anos por padrão**: a API do SGS exige `dataInicial`/`dataFinal` para séries diárias (limite máximo de 10 anos por consulta). Reprocessar 2 anos a cada execução é redundante em volume, mas seguro: a carga é idempotente, então reprocessar não duplica nem corrompe dados já gravados.
- **Upsert portável, sem sintaxe específica de dialeto**: em vez de `ON CONFLICT` (SQLite/Postgres apenas, sem equivalente direto no Oracle), o `load.py` verifica chaves existentes e decide entre `INSERT`/`UPDATE` usando apenas SQL padrão do SQLAlchemy Core — garante que a troca de banco via `DATABASE_URL` funcione de fato sem reescrever a lógica de carga.
- **CSV reflete o histórico acumulado da tabela**, não só o lote da execução atual — o snapshot cresce de forma incremental e legível no Git a cada execução agendada.
