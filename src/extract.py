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

NIVEL_MUNICIPIO = "N6[all]"
TIMEOUT_MUNICIPIO_SEGUNDOS = 60  # respostas de município demoram mais (~5.571 localidades)
# A API responde 500 se pedir todos os anos de uma vez para todos os municípios
# (testado: 7 anos ok, 16 anos quebra). Buscar em janelas menores evita o erro.
JANELA_ANOS_MUNICIPIO = 5


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


def _buscar_periodo(
    periodos: str,
    nivel: str,
    timeout: int,
    sessao: requests.Session | None = None,
) -> list[dict]:
    """Faz uma chamada à API de Agregados do IBGE para um período/nível específicos.

    Retorna a lista bruta "series" por localidade:
    [{"localidade": {"id", "nome", ...}, "serie": {"2001": "valor", ...}}, ...]
    """
    sessao = sessao or _criar_sessao()
    url = BASE_URL.format(agregado=AGREGADO, periodos=periodos, variavel=VARIAVEL)

    logger.info("Extraindo população do IBGE (tabela %s, período %s, nível %s)", AGREGADO, periodos, nivel)
    try:
        resposta = sessao.get(url, params={"localidades": nivel}, timeout=timeout)
        resposta.raise_for_status()
        payload = resposta.json()
    except requests.exceptions.RequestException:
        logger.error("Falha ao extrair população do IBGE (período %s) após %d tentativas", periodos, TOTAL_RETRIES + 1)
        raise

    if not payload:
        # Lista vazia: a API responde assim quando o período pedido não tem
        # nenhum dado publicado ainda (ex.: janela totalmente no futuro).
        logger.info("Nenhum dado publicado para o período %s", periodos)
        return []

    try:
        return payload[0]["resultados"][0]["series"]
    except (IndexError, KeyError, TypeError) as exc:
        raise ValueError(f"Resposta inesperada da API do IBGE: {payload!r}") from exc


def extrair_populacao(
    periodos: str = PERIODO_PADRAO,
    nivel: str = NIVEL_TERRITORIAL,
) -> list[dict]:
    """Busca a população estimada por estado no IBGE (tabela SIDRA 6579)."""
    series = _buscar_periodo(periodos, nivel, TIMEOUT_SEGUNDOS)
    logger.info("População extraída com sucesso: %d localidade(s)", len(series))
    return series


def _janelas_de_anos(inicio: int, fim: int, tamanho: int) -> list[tuple[int, int]]:
    """Quebra o intervalo [inicio, fim] em janelas contíguas de até `tamanho` anos."""
    janelas = []
    ano = inicio
    while ano <= fim:
        fim_janela = min(ano + tamanho - 1, fim)
        janelas.append((ano, fim_janela))
        ano = fim_janela + 1
    return janelas


def extrair_populacao_municipios(
    ano_inicial: int = 2001,
    ano_final: int = 2030,
    janela: int = JANELA_ANOS_MUNICIPIO,
) -> list[dict]:
    """Busca população estimada por município (nível N6) no IBGE (tabela SIDRA 6579).

    Busca em janelas de `janela` anos (ver JANELA_ANOS_MUNICIPIO) e mescla os
    resultados por localidade, já que a API não aceita todos os anos de uma vez
    para os ~5.571 municípios. Retorna a mesma estrutura de extrair_populacao().
    """
    sessao = _criar_sessao()
    por_localidade: dict[str, dict] = {}

    for ini, fim in _janelas_de_anos(ano_inicial, ano_final, janela):
        series = _buscar_periodo(f"{ini}-{fim}", NIVEL_MUNICIPIO, TIMEOUT_MUNICIPIO_SEGUNDOS, sessao=sessao)
        for item in series:
            loc_id = item["localidade"]["id"]
            if loc_id not in por_localidade:
                por_localidade[loc_id] = {"localidade": item["localidade"], "serie": {}}
            por_localidade[loc_id]["serie"].update(item["serie"])

    logger.info("População por município extraída com sucesso: %d localidade(s)", len(por_localidade))
    return list(por_localidade.values())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    dados = extrair_populacao()
    print(f"{len(dados)} localidades (estado) extraídas")
    print(dados[0])
