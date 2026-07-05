"""Transformação dos dados de população do IBGE em um DataFrame único, tipado e validado."""

import logging

import pandas as pd

logger = logging.getLogger(__name__)

COLUNAS = ["uf_id", "uf_nome", "ano", "populacao"]


def _localidade_para_dataframe(localidade: dict) -> pd.DataFrame:
    """Converte uma localidade bruta ({"localidade": {...}, "serie": {"ano": "valor"}}) em DataFrame."""
    serie = localidade["serie"]
    if not serie:
        logger.warning("Localidade %s sem registros para transformar", localidade["localidade"]["id"])
        return pd.DataFrame(columns=COLUNAS)

    df = pd.DataFrame(list(serie.items()), columns=["ano", "populacao"])
    df["uf_id"] = int(localidade["localidade"]["id"])
    df["uf_nome"] = localidade["localidade"]["nome"]
    return df[COLUNAS]


def _checar_qualidade(df: pd.DataFrame) -> pd.DataFrame:
    """Loga e remove registros com ano/população nulos e duplicatas de (uf_id, ano)."""
    nulos = df["ano"].isna() | df["populacao"].isna()
    if nulos.any():
        logger.warning("Removendo %d registro(s) com ano/população nulo ou inválido", nulos.sum())
        df = df[~nulos]

    duplicados = df.duplicated(subset=["uf_id", "ano"], keep="last")
    if duplicados.any():
        logger.warning("Removendo %d registro(s) duplicado(s) de (uf_id, ano)", duplicados.sum())
        df = df[~duplicados]

    return df


def transformar_populacao(localidades_brutas: list[dict]) -> pd.DataFrame:
    """Une as localidades brutas extraídas em um DataFrame único, tipado, sem nulos/duplicatas.

    localidades_brutas: saída de extract.extrair_populacao().
    Retorna DataFrame com colunas COLUNAS, ordenado por uf_nome e ano.
    """
    df = pd.concat([_localidade_para_dataframe(loc) for loc in localidades_brutas], ignore_index=True)

    df["ano"] = pd.to_numeric(df["ano"], errors="coerce")
    df["populacao"] = pd.to_numeric(df["populacao"], errors="coerce")
    df["uf_id"] = df["uf_id"].astype(int)
    df["uf_nome"] = df["uf_nome"].astype(str)

    df = _checar_qualidade(df)

    df["ano"] = df["ano"].astype(int)
    df["populacao"] = df["populacao"].astype(int)

    df = df[COLUNAS].sort_values(["uf_nome", "ano"]).reset_index(drop=True)
    logger.info("Transformação concluída: %d registros, %d localidade(s)", len(df), df["uf_id"].nunique())
    return df


if __name__ == "__main__":
    from src.extract import extrair_populacao

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    df_final = transformar_populacao(extrair_populacao())

    print(df_final.dtypes)
    print(df_final.head())
    print(df_final.tail())
    print("Total de registros:", len(df_final))

    assert df_final["ano"].notna().all(), "há anos nulos no resultado final"
    assert df_final["populacao"].notna().all(), "há população nula no resultado final"
    assert not df_final.duplicated(subset=["uf_id", "ano"]).any(), "há duplicatas no resultado final"
    print("Checagens de qualidade OK")
