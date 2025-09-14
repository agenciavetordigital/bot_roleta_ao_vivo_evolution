# -*- coding: utf-8 -*-

import os
import time
import logging
import asyncio
import telegram
import httpx  # Biblioteca moderna para chamadas de API
from telegram.constants import ParseMode
from datetime import datetime
import pytz  # Para fuso horário

# --- CONFIGURAÇÕES ESSENCIAIS ---
TOKEN_BOT = os.environ.get('TOKEN_BOT')
CHAT_ID = os.environ.get('CHAT_ID')

# O ID da roleta, extraído da URL que você encontrou
ROULETTE_ID = "0194b473-1738-70dd-84a9-f1ddd4f00678"
BASE_API_URL = f"https://www.tipminer.com/api/v3/types-per-hour/roulette/{ROULETTE_ID}/"

if not all([TOKEN_BOT, CHAT_ID]):
    logging.critical("As variáveis de ambiente (TOKEN_BOT, CHAT_ID) devem ser definidas!")
    exit()

INTERVALO_VERIFICACAO = 10  # Podemos verificar mais rápido agora

# --- ESTRATÉGIAS DE ALERTA ---
ESTRATEGIAS = {
    "Estratégia Vizinhos do Zero": lambda num: num in [0, 2, 3, 4, 7, 12, 15, 18, 19, 21, 22, 25, 26, 28, 29, 32, 35],
    "Estratégia Terceiro Final": lambda num: num % 10 in [3, 6, 9] and num not in [0],
    "Estratégia Número 7": lambda num: num == 7,
    "Estratégia Primeira Dúzia": lambda num: 1 <= num <= 12,
    "Estratégia Coluna 1": lambda num: num % 3 == 1 and num != 0,
}

# --- LÓGICA DO BOT (API) ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
ultimo_id_rodada = None


async def buscar_ultimo_numero(client):
    """Busca o número mais recente da roleta na API."""
    global ultimo_id_rodada
    try:
        # Gera a data atual no fuso horário de São Paulo
        tz = pytz.timezone('America/Sao_Paulo')
        now = datetime.now(tz)
        data_hoje = now.strftime('%Y-%m-%d')

        # Constrói a URL da API dinamicamente
        api_url_dinamica = f"{BASE_API_URL}{data_hoje}?timezone=America/Sao_Paulo"

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'application/json',
        }
        response = await client.get(api_url_dinamica, headers=headers, timeout=10)
        response.raise_for_status()

        data = response.json()

        # Encontra a rodada mais recente nos dados retornados pela API
        ultima_rodada = None
        # Itera das horas mais recentes para as mais antigas para encontrar a última jogada
        for hora in range(now.hour, -1, -1):
            hora_str = f"{hora:02d}"  # Formata a hora como "01", "02", etc.
            rodadas_na_hora = data.get(hora_str)

            if rodadas_na_hora and isinstance(rodadas_na_hora, list) and len(rodadas_na_hora) > 0:
                # Pega a última rodada da lista (a mais recente desta hora)
                ultima_rodada = rodadas_na_hora[-1]
                break  # Encontramos a hora mais recente com dados

        if not ultima_rodada:
            logging.warning("Nenhuma rodada encontrada nos dados da API para o dia de hoje.")
            return None

        # O ID da rodada na API v3 é um número inteiro
        id_rodada_atual = ultima_rodada.get("id")

        if id_rodada_atual == ultimo_id_rodada:
            return None  # Já processado

        ultimo_id_rodada = id_rodada_atual
        # Na nova API, o resultado numérico está no campo "type"
        numero = ultima_rodada.get("type")

        if numero is not None and isinstance(numero, int):
            logging.info(f"Número válido encontrado na API: {numero}")
            return numero
        else:
            logging.warning(f"Resultado inválido ou não numérico na API: '{numero}'")
            return None

    except httpx.RequestError as e:
        logging.error(f"Erro ao acessar a API: {e}")
        return None
    except Exception as e:
        logging.error(f"Erro ao processar dados da API: {e}")
        return None

async def verificar_estrategias(bot, numero):
    """Verifica o número contra a lista de estratégias e envia alertas."""
    if numero is None:
        return
    for nome_estrategia, condicao in ESTRATEGIAS.items():
        if condicao(numero):
            mensagem = f"🎯 Gatilho Encontrado! 🎯\n\nEstratégia: *{nome_estrategia}*\nNúmero Sorteado: *{numero}*"
            logging.info(f"Condição da estratégia '{nome_estrategia}' atendida. Enviando alerta...")
            await enviar_alerta(bot, mensagem)


async def enviar_alerta(bot, mensagem):
    """Envia uma mensagem para o chat configurado no Telegram."""
    try:
        await bot.send_message(chat_id=CHAT_ID, text=mensagem, parse_mode=ParseMode.MARKDOWN)
        logging.info("Alerta enviado com sucesso!")
    except Exception as e:
        logging.error(f"Erro ao enviar mensagem para o Telegram: {e}")


async def main():
    """Função principal que inicializa o bot e inicia o monitoramento."""
    bot = None
    try:
        bot = telegram.Bot(token=TOKEN_BOT)
        info_bot = await bot.get_me()
        logging.info(f"Bot '{info_bot.first_name}' (API) inicializado com sucesso!")
        await enviar_alerta(bot, f"✅ Bot '{info_bot.first_name}' (API) conectado e monitorando.")
    except Exception as e:
        logging.critical(f"Não foi possível conectar ao Telegram. Erro: {e}")
        return

    async with httpx.AsyncClient() as client:
        while True:
            try:
                numero = await buscar_ultimo_numero(client)
                if numero is not None:
                    await verificar_estrategias(bot, numero)
                await asyncio.sleep(INTERVALO_VERIFICACAO)
            except Exception as e:
                logging.error(f"Um erro crítico ocorreu no loop principal: {e}")
                await asyncio.sleep(60)

if __name__ == '__main__':
    asyncio.run(main())

