"""Extração de dados demográficos do IBGE (API de Agregados / SIDRA)."""

import logging

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

logger = logging.getLogger(__name__)

BASE_URL = (
    "https://servicodados.ibge.gov.br/api/v3/agregados/{agregado}"
    "/periodos/{periodos}/variaveis/{variavel}"
)
TIMEOUT_SEGUNDOS = 20
TOTAL_RETRIES = 2  # + 1ª tentativa = 3 tentativas no total
BACKOFF_FACTOR = 1  # espera crescente entre tentativas (~1s, 2s, ...)

AGREGADO = 6579  # tabela SIDRA: População residente estimada
VARIAVEL = 9324  # variável: População residente estimada (pessoas)
NIVEL_TERRITORIAL = "N3[all]"  # N3 = Unidades da Federação (estados)

# Intervalo de anos pedido à API. Fim propositalmente no futuro: a API do IBGE
# simplesmente omite anos sem dado publicado (testado com 2001-2030), então não
# é preciso editar essa constante toda vez que o IBGE divulgar uma nova estimativa.
PERIODO_PADRAO = "2001-2030"


def _criar_sessao() -> requests.Session:
    """Cria sessão HTTP com retry automático (backoff exponencial) em falhas transitórias."""
    sessao = requests.Session()
    retry = Retry(
        total=TOTAL_RETRIES,
        backoff_factor=BACKOFF_FACTOR,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    sessao.mount("https://", HTTPAdapter(max_retries=retry))
    return sessao


def extrair_populacao(
    periodos: str = PERIODO_PADRAO,
    nivel: str = NIVEL_TERRITORIAL,
) -> list[dict]:
    """Busca a população estimada por estado no IBGE (tabela SIDRA 6579).

    Retorna a lista bruta de séries por localidade, no formato original da API:
    [{"localidade": {"id", "nome", ...}, "serie": {"2001": "valor", ...}}, ...]
    """
    url = BASE_URL.format(agregado=AGREGADO, periodos=periodos, variavel=VARIAVEL)
    sessao = _criar_sessao()

    logger.info("Extraindo população do IBGE (tabela %s, período %s, nível %s)", AGREGADO, periodos, nivel)
    try:
        resposta = sessao.get(url, params={"localidades": nivel}, timeout=TIMEOUT_SEGUNDOS)
        resposta.raise_for_status()
        payload = resposta.json()
    except requests.exceptions.RequestException:
        logger.error("Falha ao extrair população do IBGE após %d tentativas", TOTAL_RETRIES + 1)
        raise

    try:
        series = payload[0]["resultados"][0]["series"]
    except (IndexError, KeyError, TypeError) as exc:
        raise ValueError(f"Resposta inesperada da API do IBGE: {payload!r}") from exc

    logger.info("População extraída com sucesso: %d localidade(s)", len(series))
    return series


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    dados = extrair_populacao()
    print(f"{len(dados)} localidades extraídas")
    print(dados[0])
