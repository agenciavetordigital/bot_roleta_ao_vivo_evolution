# -*- coding: utf-8 -*-

import os
import time
import logging
import asyncio
import telegram
from telegram.constants import ParseMode
import cloudscraper # A nossa nova ferramenta anti-CAPTCHA
from bs4 import BeautifulSoup

# --- CONFIGURAÇÕES ESSENCIAIS ---
TOKEN_BOT = os.environ.get('TOKEN_BOT')
CHAT_ID = os.environ.get('CHAT_ID')

if not all([TOKEN_BOT, CHAT_ID]):
    logging.critical("As variáveis de ambiente TOKEN_BOT e CHAT_ID devem ser definidas!")
    exit()

# Voltamos para a URL original do TipMiner, que é pública
URL_ROLETA = 'https://www.tipminer.com/br/historico/evolution/roleta-ao-vivo'
INTERVALO_VERIFICACAO = 15

# --- ESTRATÉGIAS DE ALERTA ---
ESTRATEGIAS = {
    "Estratégia Vizinhos do Zero": lambda num: num in [0, 2, 3, 4, 7, 12, 15, 18, 19, 21, 22, 25, 26, 28, 29, 32, 35],
    "Estratégia Terceiro Final": lambda num: num % 10 in [3, 6, 9] and num not in [0],
    "Estratégia Número 7": lambda num: num == 7,
    "Estratégia Primeira Dúzia": lambda num: 1 <= num <= 12,
    "Estratégia Coluna 1": lambda num: num % 3 == 1 and num != 0,
}

# --- LÓGICA DO BOT ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
ultimo_numero_encontrado = None
scraper = cloudscraper.create_scraper() # Cria uma instância do nosso "navegador" especial

def buscar_ultimo_numero():
    """Busca o número mais recente da roleta usando o cloudscraper."""
    global ultimo_numero_encontrado
    try:
        response = scraper.get(URL_ROLETA)
        response.raise_for_status() # Garante que a requisição foi bem-sucedida
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        container_numeros = soup.find('div', class_='flex flex-wrap gap-2 justify-center')
        if not container_numeros:
            logging.warning("Container de números não encontrado. O site pode ter mudado.")
            return None

        primeiro_numero_div = container_numeros.find('div')
        if not primeiro_numero_div:
            logging.warning("Div do primeiro número não encontrada.")
            return None
            
        numero_str = primeiro_numero_div.text.strip()
        
        if numero_str == ultimo_numero_encontrado:
            return None

        ultimo_numero_encontrado = numero_str
        
        if numero_str.isdigit():
            numero = int(numero_str)
            logging.info(f"Número válido encontrado: {numero}")
            return numero
        else:
            logging.warning(f"Texto encontrado não é um número válido: '{numero_str}'")
            return None

    except Exception as e:
        logging.error(f"Erro ao buscar número: {e}")
        return None

async def verificar_estrategias(bot, numero):
    """Verifica o número e envia alertas."""
    if numero is None:
        return
    for nome_estrategia, condicao in ESTRATEGIAS.items():
        if condicao(numero):
            mensagem = f"🎯 Gatilho Encontrado! 🎯\n\nEstratégia: *{nome_estrategia}*\nNúmero Sorteado: *{numero}*"
            logging.info(f"Condição da estratégia '{nome_estrategia}' atendida. Enviando alerta...")
            await enviar_alerta(bot, mensagem)

async def enviar_alerta(bot, mensagem):
    """Envia uma mensagem para o Telegram."""
    try:
        await bot.send_message(chat_id=CHAT_ID, text=mensagem, parse_mode=ParseMode.MARKDOWN)
        logging.info("Alerta enviado com sucesso!")
    except Exception as e:
        logging.error(f"Erro ao enviar mensagem para o Telegram: {e}")

async def main():
    """Função principal."""
    bot = None
    try:
        bot = telegram.Bot(token=TOKEN_BOT)
        info_bot = await bot.get_me()
        logging.info(f"Bot '{info_bot.first_name}' (Cloudscraper) inicializado com sucesso!")
        await enviar_alerta(bot, f"✅ Bot '{info_bot.first_name}' (Cloudscraper) conectado e monitorando!")
    except Exception as e:
        logging.critical(f"Não foi possível conectar ao Telegram. Erro: {e}")
        return

    while True:
        try:
            numero = buscar_ultimo_numero()
            if numero is not None:
                await verificar_estrategias(bot, numero)
            await asyncio.sleep(INTERVALO_VERIFICACAO)
        except Exception as e:
            logging.error(f"Um erro crítico ocorreu no loop principal: {e}")
            await asyncio.sleep(60) # Espera mais tempo em caso de erro grave

if __name__ == '__main__':
    asyncio.run(main())

