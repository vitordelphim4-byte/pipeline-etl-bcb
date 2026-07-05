"""Carga idempotente do DataFrame tratado no banco relacional + export de snapshot CSV."""

import logging
import os
from pathlib import Path

import pandas as pd
from sqlalchemy import (
    Column,
    Date,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    create_engine,
    insert,
    select,
    update,
)
from sqlalchemy.engine import Engine, make_url

logger = logging.getLogger(__name__)

DATABASE_URL_PADRAO = "sqlite:///data/indicadores.db"
CSV_PATH = Path("data/indicadores.csv")

metadata = MetaData()

tabela_indicadores = Table(
    "indicadores",
    metadata,
    Column("codigo_serie", Integer, nullable=False),
    Column("nome_serie", String, nullable=False),
    Column("data", Date, nullable=False),
    Column("valor", Float, nullable=False),
    UniqueConstraint("codigo_serie", "data", name="uq_indicadores_codigo_data"),
)


def obter_engine(url: str | None = None) -> Engine:
    """Cria o engine de conexão. Prioridade: argumento > env DATABASE_URL > padrão SQLite local.

    Trocar de banco (ex.: Oracle) não exige mudar código, só a variável DATABASE_URL.
    """
    url_final = url or os.environ.get("DATABASE_URL", DATABASE_URL_PADRAO)
    logger.info("Conectando ao banco: %s", make_url(url_final).render_as_string(hide_password=True))
    return create_engine(url_final)


def _upsert(conn, df: pd.DataFrame) -> tuple[int, int]:
    """Insere registros novos e atualiza existentes por (codigo_serie, data).

    Usa apenas SQL portável (select/insert/update) para não depender de sintaxe
    de upsert específica de um dialeto (ex.: ON CONFLICT do SQLite/Postgres não existe no Oracle).
    Retorna (qtd_inserida, qtd_atualizada).
    """
    tabela = tabela_indicadores
    chaves_existentes = {
        (codigo, data) for codigo, data in conn.execute(select(tabela.c.codigo_serie, tabela.c.data))
    }

    inseridos = atualizados = 0
    for registro in df.to_dict("records"):
        codigo = int(registro["codigo_serie"])
        data = registro["data"].date()
        valor = float(registro["valor"])
        nome = str(registro["nome_serie"])
        chave = (codigo, data)

        if chave in chaves_existentes:
            conn.execute(
                update(tabela)
                .where((tabela.c.codigo_serie == codigo) & (tabela.c.data == data))
                .values(nome_serie=nome, valor=valor)
            )
            atualizados += 1
        else:
            conn.execute(insert(tabela).values(codigo_serie=codigo, nome_serie=nome, data=data, valor=valor))
            chaves_existentes.add(chave)
            inseridos += 1

    return inseridos, atualizados


def _exportar_csv(engine: Engine) -> None:
    """Exporta o histórico completo da tabela (não só o lote da execução atual) para CSV versionado no Git."""
    with engine.connect() as conn:
        df_completo = pd.read_sql(
            select(tabela_indicadores).order_by(tabela_indicadores.c.codigo_serie, tabela_indicadores.c.data),
            conn,
        )
    df_completo.to_csv(CSV_PATH, index=False)
    logger.info("Snapshot CSV exportado: %s (%d registros)", CSV_PATH, len(df_completo))


def carregar(df: pd.DataFrame, url: str | None = None) -> None:
    """Grava o DataFrame no banco (upsert idempotente) e exporta o snapshot CSV."""
    Path("data").mkdir(exist_ok=True)
    engine = obter_engine(url)
    metadata.create_all(engine)

    with engine.begin() as conn:
        inseridos, atualizados = _upsert(conn, df)
    logger.info("Carga concluída: %d inserido(s), %d atualizado(s)", inseridos, atualizados)

    _exportar_csv(engine)


if __name__ == "__main__":
    from src.extract import extrair_todas_series
    from src.transform import transformar_series

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    carregar(transformar_series(extrair_todas_series()))
    print("Carga finalizada. Rode de novo para confirmar idempotência (0 duplicados, só updates).")
