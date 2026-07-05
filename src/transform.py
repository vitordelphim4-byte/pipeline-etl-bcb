"""Transformação dos dados de população do IBGE em um DataFrame único, tipado e validado."""

import logging
import re

import pandas as pd

logger = logging.getLogger(__name__)

COLUNAS = ["uf_id", "uf_nome", "ano", "populacao"]
COLUNAS_MUNICIPIO = ["municipio_id", "municipio_nome", "uf_sigla", "ano", "populacao"]

# Nome do município vem com a UF embutida, mas o formato varia: "Nome (RO)" ou
# "Nome - RO". O `$` no fim garante que só a UF final é capturada mesmo se o
# nome tiver hífen no meio (ex.: "Embu-Guaçu - SP").
_PADRAO_UF_NO_NOME = re.compile(r"^(.*?)\s*[-(]\s*([A-Z]{2})\)?$")


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


def _localidade_municipio_para_dataframe(localidade: dict) -> pd.DataFrame:
    """Converte um município bruto em DataFrame, separando o nome da UF embutida nele."""
    serie = localidade["serie"]
    if not serie:
        logger.warning("Município %s sem registros para transformar", localidade["localidade"]["id"])
        return pd.DataFrame(columns=COLUNAS_MUNICIPIO)

    nome_bruto = localidade["localidade"]["nome"]
    match = _PADRAO_UF_NO_NOME.match(nome_bruto)
    nome_limpo, uf_sigla = match.groups() if match else (nome_bruto, None)

    df = pd.DataFrame(list(serie.items()), columns=["ano", "populacao"])
    df["municipio_id"] = int(localidade["localidade"]["id"])
    df["municipio_nome"] = nome_limpo
    df["uf_sigla"] = uf_sigla
    return df[COLUNAS_MUNICIPIO]


def _checar_qualidade(df: pd.DataFrame, chave: list[str]) -> pd.DataFrame:
    """Loga e remove registros com valores nulos em `chave`/população e duplicatas de `chave`."""
    nulos = df[chave].isna().any(axis=1) | df["populacao"].isna()
    if nulos.any():
        logger.warning("Removendo %d registro(s) com dado nulo ou inválido", nulos.sum())
        df = df[~nulos]

    duplicados = df.duplicated(subset=chave, keep="last")
    if duplicados.any():
        logger.warning("Removendo %d registro(s) duplicado(s) de %s", duplicados.sum(), chave)
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

    df = _checar_qualidade(df, chave=["uf_id", "ano"])

    df["ano"] = df["ano"].astype(int)
    df["populacao"] = df["populacao"].astype(int)

    df = df[COLUNAS].sort_values(["uf_nome", "ano"]).reset_index(drop=True)
    logger.info("Transformação concluída: %d registros, %d localidade(s)", len(df), df["uf_id"].nunique())
    return df


def transformar_populacao_municipios(localidades_brutas: list[dict]) -> pd.DataFrame:
    """Une os municípios brutos extraídos em um DataFrame único, tipado, sem nulos/duplicatas.

    localidades_brutas: saída de extract.extrair_populacao_municipios().
    Retorna DataFrame com colunas COLUNAS_MUNICIPIO, ordenado por uf_sigla, município e ano.
    """
    df = pd.concat(
        [_localidade_municipio_para_dataframe(loc) for loc in localidades_brutas], ignore_index=True
    )

    df["ano"] = pd.to_numeric(df["ano"], errors="coerce")
    df["populacao"] = pd.to_numeric(df["populacao"], errors="coerce")
    df["municipio_id"] = df["municipio_id"].astype(int)
    df["municipio_nome"] = df["municipio_nome"].astype(str)

    sem_uf = df["uf_sigla"].isna().sum()
    if sem_uf:
        logger.warning("%d registro(s) de município sem UF identificada a partir do nome", sem_uf)

    df = _checar_qualidade(df, chave=["municipio_id", "ano"])

    df["ano"] = df["ano"].astype(int)
    df["populacao"] = df["populacao"].astype(int)

    df = df[COLUNAS_MUNICIPIO].sort_values(["uf_sigla", "municipio_nome", "ano"]).reset_index(drop=True)
    logger.info(
        "Transformação de município concluída: %d registros, %d localidade(s)",
        len(df),
        df["municipio_id"].nunique(),
    )
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
