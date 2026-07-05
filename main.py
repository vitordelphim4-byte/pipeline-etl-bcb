"""Orquestra o pipeline ETL de população do IBGE: extract -> transform -> load."""

import logging
import sys

from src.extract import extrair_populacao
from src.load import carregar
from src.transform import transformar_populacao

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    try:
        logger.info("=== Pipeline iniciado ===")

        logger.info("Fase EXTRACT: início")
        dados_brutos = extrair_populacao()
        logger.info("Fase EXTRACT: fim (%d localidade(s))", len(dados_brutos))

        logger.info("Fase TRANSFORM: início")
        df_limpo = transformar_populacao(dados_brutos)
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
