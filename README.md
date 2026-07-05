# Pipeline ETL — População Estimada (IBGE)

Pipeline ETL modular que extrai as estimativas anuais de população residente — por estado e por município — publicadas pelo IBGE (API de Agregados / SIDRA), trata e valida os dados com pandas, e carrega em um banco relacional de forma idempotente. Roda automaticamente via GitHub Actions.

Projeto de portfólio focado em práticas de engenharia de dados: separação em módulos, tratamento de erros, retry, logging estruturado, idempotência e execução agendada na nuvem.

## Dado extraído

Fonte: [API de Agregados do IBGE](https://servicodados.ibge.gov.br/api/docs/agregados?versao=3) (pública, sem autenticação), tabela SIDRA **6579 — População residente estimada**.

| Nível geográfico | Localidades | Período | Frequência de publicação |
|---|---|---|---|
| Estado (N3) | 27 Unidades da Federação | 2001 em diante (lacunas: 2007, 2010, 2022, 2023) | Anual |
| Município (N6) | ~5.571 municípios | 2001 em diante (mesmas lacunas + gaps pontuais por município) | Anual |

Os dois níveis são tabelas separadas (`populacao` e `populacao_municipio`) no mesmo banco — misturar as duas num único total contaria a população nacional em dobro.

## Arquitetura

```mermaid
flowchart LR
    API[("API Agregados<br/>IBGE / SIDRA 6579")] --> EXTRACT["extract.py<br/>(requests + retry)"]
    EXTRACT --> TRANSFORM["transform.py<br/>(pandas: achata série<br/>aninhada, tipagem,<br/>qualidade)"]
    TRANSFORM --> LOAD["load.py<br/>(SQLAlchemy: upsert)"]
    LOAD --> DB[("Banco relacional<br/>SQLite (padrão) / Oracle<br/>tabelas: populacao,<br/>populacao_municipio")]
    LOAD --> CSV[["data/populacao.csv<br/>data/populacao_municipio.csv"]]

    subgraph GHA["GitHub Actions — cron mensal"]
        CRON(["dia 1, 12:00 UTC"]) --> MAIN["main.py"]
    end

    MAIN -.orquestra estado + município.-> EXTRACT
    CSV --> COMMIT["commit automático<br/>no repositório"]
```

- **extract.py** — busca a população na API de Agregados do IBGE via `requests`, com retry automático (3 tentativas, backoff exponencial) e timeout configurado. Para município, a API rejeita (erro 500) pedir todos os anos de uma vez para as ~5.571 localidades — a busca é feita em janelas de 5 anos e mesclada por localidade. A resposta da API é aninhada (série de ano→valor por localidade); `extract.py` devolve essa estrutura bruta, sem achatar.
- **transform.py** — usa pandas para achatar a série aninhada em formato tabular, tipar como inteiro e checar qualidade (remove nulos e duplicatas pela chave natural). Para município, também separa a UF (embutida no nome vindo da API, ex.: `"Nome (RO)"` ou `"Nome - RO"`) numa coluna própria (`uf_sigla`), senão não dá pra agrupar município por estado no dashboard.
- **load.py** — grava no banco via SQLAlchemy com upsert idempotente (rodar o pipeline várias vezes não duplica dados) e exporta o histórico completo de cada tabela para CSV.
- **main.py** — orquestra as duas fases (estado, município), cada uma com logging de início/fim de extract/transform/load. As fases são independentes: se uma falhar, a outra ainda tenta rodar; qualquer exceção é logada com stack trace completo e o processo termina com código de saída ≠ 0 (o pipeline nunca falha silenciosamente).

## Stack

Python 3.14 · requests · pandas · SQLAlchemy · SQLite · GitHub Actions

## Como rodar localmente

```powershell
# 1. Criar e ativar o ambiente virtual
python -m venv venv
.\venv\Scripts\Activate.ps1

# 2. Instalar dependências
pip install -r requirements.txt

# 3. Rodar o pipeline completo (estado + município)
python main.py
```

Resultado: `data/populacao.db` (SQLite, tabelas `populacao` e `populacao_municipio`), `data/populacao.csv` e `data/populacao_municipio.csv` atualizados.

### Trocar de banco

A URL de conexão é lida da variável de ambiente `DATABASE_URL` (padrão: `sqlite:///data/populacao.db`). Para apontar para outro banco (ex.: Oracle), basta definir a variável — nenhum código precisa mudar:

```powershell
$env:DATABASE_URL = "oracle+oracledb://usuario:senha@host:porta/servico"
python main.py
```

## Agendamento

O workflow [`.github/workflows/pipeline.yml`](.github/workflows/pipeline.yml) roda o pipeline automaticamente todo dia 1 de cada mês às 12:00 UTC. Cron mensal (não diário) porque o dado é anual — rodar todo dia seria redundante. Também pode ser disparado manualmente pela aba **Actions** do GitHub (`workflow_dispatch`).

A cada execução, os CSVs atualizados são commitados de volta no repositório (só quando há mudança de fato) — o que torna o histórico de execuções agendadas visível diretamente no histórico de commits do Git.

## Decisões técnicas

- **Município (N6) em tabela separada da de estado (N3)**: mesma tabela-fonte do IBGE, mas níveis geográficos diferentes não podem conviver na mesma tabela sem um marcador de nível — do contrário, somar a coluna `populacao` sem filtrar conta o Brasil mais de uma vez.
- **Extração de município em janelas de anos**: a API do IBGE responde erro 500 ao pedir todos os anos de uma vez para as ~5.571 localidades (testado: 7 anos funciona, 16 anos quebra). `extract.py` busca em janelas de 5 anos e mescla os resultados por localidade — o resto do pipeline não percebe a diferença.
- **UF extraída do nome do município via regex, não de um campo dedicado**: a API não devolve a UF separada para município, só embutida no nome (formato inconsistente entre chamadas: `"Nome (RO)"` numa consulta pontual, `"Nome - RO"` na consulta em lote). O regex usado ancora no fim da string para não confundir com hífens que façam parte do nome real do município (ex.: "Embu-Guaçu").
- **Intervalo de anos pedido à API é propositalmente "aberto" (fim no futuro)**: a API do IBGE simplesmente omite anos sem dado publicado em vez de dar erro (e retorna lista vazia se a janela pedida não tiver dado nenhum). Isso significa que o pipeline capta automaticamente uma nova estimativa anual assim que o IBGE publicar, sem precisar editar código todo ano.
- **Upsert portável, sem sintaxe específica de dialeto**: em vez de `ON CONFLICT` (SQLite/Postgres apenas, sem equivalente direto no Oracle), o `load.py` verifica chaves existentes e decide entre `INSERT`/`UPDATE` usando apenas SQL padrão do SQLAlchemy Core — a mesma função de upsert atende as duas tabelas (estado e município), parametrizada pela chave natural de cada uma.
- **CSV reflete o histórico acumulado de cada tabela**, não só o lote da execução atual — o snapshot cresce de forma incremental e legível no Git a cada execução agendada.
