"""Extração de séries temporais da API SGS do Banco Central do Brasil."""

import logging
from datetime import datetime, timedelta

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

logger = logging.getLogger(__name__)

BASE_URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados"
TIMEOUT_SEGUNDOS = 15
TOTAL_RETRIES = 2  # + 1ª tentativa = 3 tentativas no total
BACKOFF_FACTOR = 1  # espera crescente entre tentativas (~1s, 2s, ...)

# A API do SGS exige dataInicial/dataFinal para séries diárias (código 1) e limita
# a janela a 10 anos. Usado como padrão em extrair_todas_series quando não informado.
JANELA_PADRAO_DIAS = 730  # ~2 anos

# Séries do SGS a extrair: código -> nome legível
SERIES: dict[int, str] = {
    1: "Dólar americano (venda)",
    433: "IPCA - variação mensal",
    432: "Meta Selic definida pelo Copom",
}


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


def extrair_serie(
    codigo: int,
    data_inicial: str | None = None,
    data_final: str | None = None,
    sessao: requests.Session | None = None,
) -> list[dict]:
    """Busca uma série do SGS pelo código. Retorna a lista de registros brutos da API.

    data_inicial/data_final, se informados, devem estar no formato dd/MM/yyyy.
    """
    sessao_local = sessao or _criar_sessao()
    url = BASE_URL.format(codigo=codigo)
    params = {"formato": "json"}
    if data_inicial:
        params["dataInicial"] = data_inicial
    if data_final:
        params["dataFinal"] = data_final

    logger.info("Extraindo série %s (params=%s)", codigo, params)
    try:
        resposta = sessao_local.get(url, params=params, timeout=TIMEOUT_SEGUNDOS)
        resposta.raise_for_status()
        dados = resposta.json()
    except requests.exceptions.RequestException:
        logger.error("Falha ao extrair série %s após %d tentativas", codigo, TOTAL_RETRIES + 1)
        raise

    if not isinstance(dados, list):
        raise ValueError(f"Resposta inesperada da API para série {codigo}: {dados!r}")

    logger.info("Série %s extraída com sucesso: %d registros", codigo, len(dados))
    return dados


def extrair_todas_series(
    data_inicial: str | None = None,
    data_final: str | None = None,
) -> list[dict]:
    """Extrai todas as séries definidas em SERIES.

    Se as datas não forem informadas, usa janela padrão dos últimos ~2 anos
    (JANELA_PADRAO_DIAS), necessária para a série diária (código 1) funcionar.
    Retorna lista de dicts: {"codigo_serie", "nome_serie", "dados"} (dados = JSON bruto da API).
    """
    if data_final is None:
        data_final = datetime.now().strftime("%d/%m/%Y")
    if data_inicial is None:
        data_inicial = (datetime.now() - timedelta(days=JANELA_PADRAO_DIAS)).strftime("%d/%m/%Y")

    sessao = _criar_sessao()
    resultado = []
    for codigo, nome in SERIES.items():
        dados = extrair_serie(codigo, data_inicial, data_final, sessao=sessao)
        resultado.append({"codigo_serie": codigo, "nome_serie": nome, "dados": dados})
    return resultado


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    for serie in extrair_todas_series():
        print(serie["codigo_serie"], serie["nome_serie"], "->", len(serie["dados"]), "registros")
