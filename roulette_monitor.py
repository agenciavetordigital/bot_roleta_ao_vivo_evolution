# -*- coding: utf-8 -*-

import os
import time
import logging
import asyncio
import telegram
import httpx  # Biblioteca moderna para chamadas de API
from telegram.constants import ParseMode

# --- CONFIGURAÇÕES ESSENCIAIS ---
TOKEN_BOT = os.environ.get('TOKEN_BOT')
CHAT_ID = os.environ.get('CHAT_ID')

# A URL da API que você encontrou!
API_URL = "https://www.tipminer.com/api/v3/history/roulette/0194b473-1738-70dd-84a9-f1ddd4f00678?limit=200&subject=filter&timezone=America%2FSao_Paulo"

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
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'application/json',
            'Referer': 'https://www.tipminer.com/br/historico/evolution/roleta-ao-vivo' # Adicionado para simular um acesso legítimo
        }
        response = await client.get(API_URL, headers=headers, timeout=15)
        response.raise_for_status()

        data = response.json()

        if not data or not isinstance(data, list) or len(data) == 0:
            logging.warning("API retornou uma resposta vazia ou em formato inesperado.")
            return None

        # O primeiro item da lista é o mais recente
        ultima_rodada = data[0]
        id_rodada_atual = ultima_rodada.get("id")

        if id_rodada_atual == ultimo_id_rodada:
            return None  # Já processado

        ultimo_id_rodada = id_rodada_atual
        numero_str = ultima_rodada.get("result")

        if numero_str is not None and numero_str.isdigit():
            numero = int(numero_str)
            logging.info(f"Número válido encontrado na API: {numero}")
            return numero
        else:
            logging.warning(f"Resultado inválido ou não numérico na API: '{numero_str}'")
            return None

    except httpx.HTTPStatusError as e:
        logging.error(f"Erro ao acessar a API: Status {e.response.status_code}. A URL pode ter mudado ou o acesso foi bloqueado.")
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
        logging.info(f"Bot '{info_bot.first_name}' (API Final) inicializado com sucesso!")
        await enviar_alerta(bot, f"✅ Bot '{info_bot.first_name}' (API Final) conectado e monitorando.")
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

