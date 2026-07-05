"""Transformação das séries brutas do BCB em um único DataFrame limpo e validado."""

import logging

import pandas as pd

logger = logging.getLogger(__name__)

COLUNAS = ["codigo_serie", "nome_serie", "data", "valor"]


def _serie_para_dataframe(serie: dict) -> pd.DataFrame:
    """Converte uma série bruta ({"codigo_serie", "nome_serie", "dados"}) em DataFrame."""
    if not serie["dados"]:
        logger.warning("Série %s sem registros para transformar", serie["codigo_serie"])
        return pd.DataFrame(columns=COLUNAS)

    df = pd.DataFrame(serie["dados"])
    df["codigo_serie"] = serie["codigo_serie"]
    df["nome_serie"] = serie["nome_serie"]
    return df[COLUNAS]


def _checar_qualidade(df: pd.DataFrame) -> pd.DataFrame:
    """Loga e remove registros com data/valor nulo e duplicatas de (codigo_serie, data)."""
    nulos = df["data"].isna() | df["valor"].isna()
    if nulos.any():
        logger.warning("Removendo %d registro(s) com data/valor nulo ou inválido", nulos.sum())
        df = df[~nulos]

    duplicados = df.duplicated(subset=["codigo_serie", "data"], keep="last")
    if duplicados.any():
        logger.warning("Removendo %d registro(s) duplicado(s) de (codigo_serie, data)", duplicados.sum())
        df = df[~duplicados]

    return df


def transformar_series(series_brutas: list[dict]) -> pd.DataFrame:
    """Une as séries brutas extraídas em um DataFrame único, tipado, sem nulos/duplicatas.

    series_brutas: saída de extract.extrair_todas_series().
    Retorna DataFrame com colunas COLUNAS, ordenado por codigo_serie e data.
    """
    df = pd.concat([_serie_para_dataframe(s) for s in series_brutas], ignore_index=True)

    df["data"] = pd.to_datetime(df["data"], format="%d/%m/%Y", errors="coerce")
    df["valor"] = pd.to_numeric(df["valor"], errors="coerce")
    df["codigo_serie"] = df["codigo_serie"].astype(int)
    df["nome_serie"] = df["nome_serie"].astype(str)

    df = _checar_qualidade(df)

    df = df[COLUNAS].sort_values(["codigo_serie", "data"]).reset_index(drop=True)
    logger.info("Transformação concluída: %d registros, %d série(s)", len(df), df["codigo_serie"].nunique())
    return df


if __name__ == "__main__":
    from src.extract import extrair_todas_series

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    df_final = transformar_series(extrair_todas_series())

    print(df_final.dtypes)
    print(df_final.head())
    print(df_final.tail())
    print("Total de registros:", len(df_final))

    assert df_final["data"].notna().all(), "há datas nulas no resultado final"
    assert df_final["valor"].notna().all(), "há valores nulos no resultado final"
    assert not df_final.duplicated(subset=["codigo_serie", "data"]).any(), "há duplicatas no resultado final"
    print("Checagens de qualidade OK")
