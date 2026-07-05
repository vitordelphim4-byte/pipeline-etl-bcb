"""Orquestra o pipeline ETL de população do IBGE: extract -> transform -> load.

Roda duas fases independentes (estado e município) que gravam em tabelas
separadas do mesmo banco. Uma falhar não impede a outra de tentar rodar.
"""

import logging
import sys

from src.extract import extrair_populacao, extrair_populacao_municipios
from src.load import carregar, carregar_municipios
from src.transform import transformar_populacao, transformar_populacao_municipios

logger = logging.getLogger(__name__)


def _rodar_fase_estado() -> None:
    logger.info("Fase EXTRACT (estado): início")
    dados_brutos = extrair_populacao()
    logger.info("Fase EXTRACT (estado): fim (%d localidade(s))", len(dados_brutos))

    logger.info("Fase TRANSFORM (estado): início")
    df_limpo = transformar_populacao(dados_brutos)
    logger.info("Fase TRANSFORM (estado): fim (%d registros)", len(df_limpo))

    logger.info("Fase LOAD (estado): início")
    carregar(df_limpo)
    logger.info("Fase LOAD (estado): fim")


def _rodar_fase_municipio() -> None:
    logger.info("Fase EXTRACT (município): início")
    dados_brutos = extrair_populacao_municipios()
    logger.info("Fase EXTRACT (município): fim (%d localidade(s))", len(dados_brutos))

    logger.info("Fase TRANSFORM (município): início")
    df_limpo = transformar_populacao_municipios(dados_brutos)
    logger.info("Fase TRANSFORM (município): fim (%d registros)", len(df_limpo))

    logger.info("Fase LOAD (município): início")
    carregar_municipios(df_limpo)
    logger.info("Fase LOAD (município): fim")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    logger.info("=== Pipeline iniciado ===")
    falhou = False

    for nome, fase in [("estado", _rodar_fase_estado), ("município", _rodar_fase_municipio)]:
        try:
            fase()
        except Exception:
            logger.exception("Pipeline falhou na fase '%s'", nome)
            falhou = True

    if falhou:
        logger.error("=== Pipeline concluído com falha(s) ===")
        sys.exit(1)

    logger.info("=== Pipeline concluído com sucesso ===")


if __name__ == "__main__":
    main()
