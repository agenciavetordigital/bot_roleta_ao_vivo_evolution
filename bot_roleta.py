# -*- coding: utf-8 -*-

import requests
from bs4 import BeautifulSoup
import time
import telegram
from telegram.constants import ParseMode
import logging
import asyncio

# --- CONFIGURAÇÕES ESSENCIAIS ---
TOKEN_BOT = "8453600984:AAFn7thSXwu4BHLwleZnnrNp_qN3FoDftV4"
CHAT_ID = 1354332413
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
ultimo_id_rodada = None

def buscar_ultimo_numero():
    """Busca o número mais recente da roleta no site."""
    global ultimo_id_rodada
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        # Conexão direta, sem necessidade de proxy no Replit
        response = requests.get(URL_ROLETA, headers=headers, timeout=10)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'html.parser')
        container_numeros = soup.find('div', class_='flex flex-wrap gap-2 justify-center')
        if not container_numeros:
            logging.warning("Não foi possível encontrar o container de números no site.")
            return None, None

        primeiro_numero_div = container_numeros.find('div')
        if not primeiro_numero_div:
            logging.warning("Não foi possível encontrar a div do último número.")
            return None, None
            
        id_rodada_atual = str(primeiro_numero_div)
        if id_rodada_atual == ultimo_id_rodada:
            return None, None

        ultimo_id_rodada = id_rodada_atual
        
        numero_str = primeiro_numero_div.text.strip()
        numero = int(numero_str)
        logging.info(f"Número mais recente encontrado: {numero}")
        return numero, id_rodada_atual

    except requests.exceptions.RequestException as e:
        logging.error(f"Erro ao acessar a URL: {e}")
        return None, None
    except (ValueError, TypeError) as e:
        logging.error(f"Não foi possível converter o valor para um número inteiro. Detalhe: {e}")
        return None, None
    except Exception as e:
        logging.error(f"Ocorreu um erro inesperado ao buscar o número: {e}")
        return None, None

async def verificar_estrategias(bot, numero):
    """Verifica o número contra a lista de estratégias e envia alertas."""
    if numero is None:
        return

    for nome_estrategia, condicao in ESTRATEGIAS.items():
        try:
            if condicao(numero):
                mensagem = f"🎯 Gatilho Encontrado! 🎯\n\nEstratégia: *{nome_estrategia}*\nNúmero Sorteado: *{numero}*"
                logging.info(f"Condição da estratégia '{nome_estrategia}' atendida. Enviando alerta...")
                await enviar_alerta(bot, mensagem)
        except Exception as e:
            logging.error(f"Erro ao processar a estratégia '{nome_estrategia}': {e}")

async def enviar_alerta(bot, mensagem):
    """Envia uma mensagem para o chat configurado no Telegram."""
    try:
        await bot.send_message(
            chat_id=CHAT_ID,
            text=mensagem,
            parse_mode=ParseMode.MARKDOWN
        )
        logging.info("Alerta enviado com sucesso!")
    except telegram.error.TelegramError as e:
        logging.error(f"Erro ao enviar mensagem para o Telegram: {e}")
    except Exception as e:
        logging.error(f"Ocorreu um erro inesperado ao enviar o alerta: {e}")

async def main():
    """Função principal que inicializa o bot e inicia o monitoramento."""
    try:
        bot = telegram.Bot(token=TOKEN_BOT)
        info_bot = await bot.get_me()
        logging.info(f"Bot '{info_bot.first_name}' inicializado com sucesso!")
        await enviar_alerta(bot, "✅ Bot monitor de roleta iniciado com sucesso!")
    except Exception as e:
        logging.critical(f"Não foi possível conectar ao Telegram. Verifique seu token. Erro: {e}")
        return

    logging.info("Iniciando monitoramento da roleta...")
    while True:
        try:
            numero, _ = buscar_ultimo_numero()
            if numero is not None:
                await verificar_estrategias(bot, numero)
            
            await asyncio.sleep(INTERVALO_VERIFICACAO)

        except KeyboardInterrupt:
            logging.info("Monitoramento interrompido pelo usuário.")
            await enviar_alerta(bot, "❌ Bot monitor de roleta foi encerrado.")
            break
        except Exception as e:
            logging.error(f"Um erro crítico ocorreu no loop principal: {e}")
            logging.info("Aguardando 60 segundos antes de tentar novamente...")
            await asyncio.sleep(60)

if __name__ == '__main__':
    asyncio.run(main())

