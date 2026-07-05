"""Carga idempotente do DataFrame de população no banco relacional + export de snapshot CSV."""

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
    create_engine,
    insert,
    select,
    update,
)
from sqlalchemy.engine import Engine, make_url

logger = logging.getLogger(__name__)

DATABASE_URL_PADRAO = "sqlite:///data/populacao.db"
CSV_PATH = Path("data/populacao.csv")

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


def obter_engine(url: str | None = None) -> Engine:
    """Cria o engine de conexão. Prioridade: argumento > env DATABASE_URL > padrão SQLite local.

    Trocar de banco (ex.: Oracle) não exige mudar código, só a variável DATABASE_URL.
    """
    url_final = url or os.environ.get("DATABASE_URL", DATABASE_URL_PADRAO)
    logger.info("Conectando ao banco: %s", make_url(url_final).render_as_string(hide_password=True))
    return create_engine(url_final)


def _upsert(conn, df: pd.DataFrame) -> tuple[int, int]:
    """Insere registros novos e atualiza existentes por (uf_id, ano).

    Usa apenas SQL portável (select/insert/update), sem sintaxe de upsert
    específica de um dialeto (ex.: ON CONFLICT não existe no Oracle).
    Retorna (qtd_inserida, qtd_atualizada).
    """
    tabela = tabela_populacao
    chaves_existentes = {
        (uf_id, ano) for uf_id, ano in conn.execute(select(tabela.c.uf_id, tabela.c.ano))
    }

    inseridos = atualizados = 0
    for registro in df.to_dict("records"):
        uf_id = int(registro["uf_id"])
        ano = int(registro["ano"])
        populacao = int(registro["populacao"])
        uf_nome = str(registro["uf_nome"])
        chave = (uf_id, ano)

        if chave in chaves_existentes:
            conn.execute(
                update(tabela)
                .where((tabela.c.uf_id == uf_id) & (tabela.c.ano == ano))
                .values(uf_nome=uf_nome, populacao=populacao)
            )
            atualizados += 1
        else:
            conn.execute(insert(tabela).values(uf_id=uf_id, uf_nome=uf_nome, ano=ano, populacao=populacao))
            chaves_existentes.add(chave)
            inseridos += 1

    return inseridos, atualizados


def _exportar_csv(engine: Engine) -> None:
    """Exporta o histórico completo da tabela (não só o lote da execução atual) para CSV versionado no Git."""
    with engine.connect() as conn:
        df_completo = pd.read_sql(
            select(tabela_populacao).order_by(tabela_populacao.c.uf_nome, tabela_populacao.c.ano),
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
    from src.extract import extrair_populacao
    from src.transform import transformar_populacao

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    carregar(transformar_populacao(extrair_populacao()))
    print("Carga finalizada. Rode de novo para confirmar idempotência (0 duplicados, só updates).")
