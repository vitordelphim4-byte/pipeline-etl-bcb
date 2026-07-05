"""Carga idempotente dos DataFrames de população no banco relacional + export de snapshots CSV."""

import logging
import os
from pathlib import Path

import pandas as pd
from sqlalchemy import (
    Column,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    and_,
    create_engine,
    insert,
    select,
    update,
)
from sqlalchemy.engine import Engine, make_url

logger = logging.getLogger(__name__)

DATABASE_URL_PADRAO = "sqlite:///data/populacao.db"
CSV_PATH = Path("data/populacao.csv")
CSV_PATH_MUNICIPIO = Path("data/populacao_municipio.csv")

metadata = MetaData()

tabela_populacao = Table(
    "populacao",
    metadata,
    Column("uf_id", Integer, nullable=False),
    Column("uf_nome", String, nullable=False),
    Column("ano", Integer, nullable=False),
    Column("populacao", Integer, nullable=False),
    UniqueConstraint("uf_id", "ano", name="uq_populacao_uf_ano"),
)

tabela_populacao_municipio = Table(
    "populacao_municipio",
    metadata,
    Column("municipio_id", Integer, nullable=False),
    Column("municipio_nome", String, nullable=False),
    Column("uf_sigla", String, nullable=True),
    Column("ano", Integer, nullable=False),
    Column("populacao", Integer, nullable=False),
    UniqueConstraint("municipio_id", "ano", name="uq_populacao_municipio_id_ano"),
)


def obter_engine(url: str | None = None) -> Engine:
    """Cria o engine de conexão. Prioridade: argumento > env DATABASE_URL > padrão SQLite local.

    Trocar de banco (ex.: Oracle) não exige mudar código, só a variável DATABASE_URL.
    As duas tabelas (estado e município) vivem no mesmo banco.
    """
    url_final = url or os.environ.get("DATABASE_URL", DATABASE_URL_PADRAO)
    logger.info("Conectando ao banco: %s", make_url(url_final).render_as_string(hide_password=True))
    return create_engine(url_final)


def _upsert(conn, tabela: Table, df: pd.DataFrame, chave: list[str]) -> tuple[int, int]:
    """Insere registros novos e atualiza existentes por `chave`.

    Usa apenas SQL portável (select/insert/update), sem sintaxe de upsert
    específica de um dialeto (ex.: ON CONFLICT não existe no Oracle).
    Retorna (qtd_inserida, qtd_atualizada).
    """
    chaves_existentes = {
        tupla for tupla in conn.execute(select(*[tabela.c[c] for c in chave]))
    }

    inseridos = atualizados = 0
    for bruto in df.to_dict("records"):
        # normaliza escalares numpy (int64/float64) pro tipo nativo do Python
        registro = {k: (v.item() if hasattr(v, "item") else v) for k, v in bruto.items()}
        chave_valores = tuple(registro[c] for c in chave)
        condicao = and_(*[tabela.c[c] == registro[c] for c in chave])

        if chave_valores in chaves_existentes:
            valores_update = {c: v for c, v in registro.items() if c not in chave}
            conn.execute(update(tabela).where(condicao).values(**valores_update))
            atualizados += 1
        else:
            conn.execute(insert(tabela).values(**registro))
            chaves_existentes.add(chave_valores)
            inseridos += 1

    return inseridos, atualizados


def _exportar_csv(engine: Engine, tabela: Table, caminho: Path, ordenar_por: list[str]) -> None:
    """Exporta o histórico completo de uma tabela (não só o lote atual) para CSV versionado no Git."""
    with engine.connect() as conn:
        df_completo = pd.read_sql(
            select(tabela).order_by(*[tabela.c[c] for c in ordenar_por]),
            conn,
        )
    df_completo.to_csv(caminho, index=False)
    logger.info("Snapshot CSV exportado: %s (%d registros)", caminho, len(df_completo))


def carregar(df: pd.DataFrame, url: str | None = None) -> None:
    """Grava a população por estado no banco (upsert idempotente) e exporta o snapshot CSV."""
    Path("data").mkdir(exist_ok=True)
    engine = obter_engine(url)
    metadata.create_all(engine)

    with engine.begin() as conn:
        inseridos, atualizados = _upsert(conn, tabela_populacao, df, chave=["uf_id", "ano"])
    logger.info("Carga (estado) concluída: %d inserido(s), %d atualizado(s)", inseridos, atualizados)

    _exportar_csv(engine, tabela_populacao, CSV_PATH, ordenar_por=["uf_nome", "ano"])


def carregar_municipios(df: pd.DataFrame, url: str | None = None) -> None:
    """Grava a população por município no banco (upsert idempotente) e exporta o snapshot CSV."""
    Path("data").mkdir(exist_ok=True)
    engine = obter_engine(url)
    metadata.create_all(engine)

    with engine.begin() as conn:
        inseridos, atualizados = _upsert(conn, tabela_populacao_municipio, df, chave=["municipio_id", "ano"])
    logger.info("Carga (município) concluída: %d inserido(s), %d atualizado(s)", inseridos, atualizados)

    _exportar_csv(
        engine,
        tabela_populacao_municipio,
        CSV_PATH_MUNICIPIO,
        ordenar_por=["uf_sigla", "municipio_nome", "ano"],
    )


if __name__ == "__main__":
    from src.extract import extrair_populacao, extrair_populacao_municipios
    from src.transform import transformar_populacao, transformar_populacao_municipios

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    carregar(transformar_populacao(extrair_populacao()))
    carregar_municipios(transformar_populacao_municipios(extrair_populacao_municipios()))
    print("Carga finalizada. Rode de novo para confirmar idempotência (0 duplicados, só updates).")
