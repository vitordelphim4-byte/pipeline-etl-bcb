"""Orquestra o pipeline ETL de indicadores do Banco Central: extract -> transform -> load."""

import logging
import sys

from src.extract import extrair_todas_series
from src.load import carregar
from src.transform import transformar_series

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    try:
        logger.info("=== Pipeline iniciado ===")

        logger.info("Fase EXTRACT: início")
        dados_brutos = extrair_todas_series()
        logger.info("Fase EXTRACT: fim (%d série(s))", len(dados_brutos))

        logger.info("Fase TRANSFORM: início")
        df_limpo = transformar_series(dados_brutos)
        logger.info("Fase TRANSFORM: fim (%d registros)", len(df_limpo))

        logger.info("Fase LOAD: início")
        carregar(df_limpo)
        logger.info("Fase LOAD: fim")

        logger.info("=== Pipeline concluído com sucesso ===")
    except Exception:
        logger.exception("Pipeline falhou")
        sys.exit(1)


if __name__ == "__main__":
    main()
