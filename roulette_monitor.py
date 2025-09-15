# -*- coding: utf-8 -*-

import os
import time
import logging
import asyncio
import telegram
import httpx
import json
from telegram.constants import ParseMode

# --- CONFIGURAÇÕES ESSENCIAIS ---
TOKEN_BOT = os.environ.get('TOKEN_BOT')
CHAT_ID = os.environ.get('CHAT_ID')

if not all([TOKEN_BOT, CHAT_ID]):
    logging.critical("As variáveis de ambiente TOKEN_BOT e CHAT_ID devem ser definidas!")
    exit()

# A URL DA API QUE VOCÊ DESCOBRIU!
API_URL = 'https://api.padroesdecassino.com.br/roletabrasileira-brbet.php'
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

async def buscar_ultimo_numero(client):
    """Busca o número mais recente da roleta diretamente da API."""
    global ultimo_numero_encontrado
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = await client.get(API_URL, headers=headers, timeout=10)
        response.raise_for_status() # Lança um erro se a resposta não for 200 OK

        # O conteúdo vem como texto JS "var numeros = [...]", então precisamos extrair o JSON
        text_content = response.text
        start_index = text_content.find('[')
        end_index = text_content.rfind(']') + 1
        
        if start_index == -1 or end_index == 0:
            logging.warning("Não foi possível encontrar o array de números na resposta da API.")
            return None

        json_str = text_content[start_index:end_index]
        numeros = json.loads(json_str)

        if not numeros:
            logging.warning("API retornou uma lista de números vazia.")
            return None

        # O número mais recente é o primeiro da lista
        numero_atual = int(numeros[0])
        
        if numero_atual == ultimo_numero_encontrado:
            return None

        ultimo_numero_encontrado = numero_atual
        logging.info(f"Número válido encontrado via API: {numero_atual}")
        return numero_atual

    except httpx.RequestError as e:
        logging.error(f"Erro de rede ao acessar a API: {e}")
        return None
    except (json.JSONDecodeError, IndexError, ValueError) as e:
        logging.error(f"Erro ao processar os dados da API: {e}")
        logging.error(f"Resposta recebida: {response.text[:200]}") # Mostra o início da resposta para depuração
        return None
    except Exception as e:
        logging.error(f"Ocorreu um erro inesperado ao buscar número da API: {e}")
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
        logging.info(f"Bot '{info_bot.first_name}' (API Padrões de Cassino) inicializado com sucesso!")
        await enviar_alerta(bot, f"✅ Bot '{info_bot.first_name}' (API Padrões de Cassino) conectado e monitorando!")
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
                if bot:
                    await enviar_alerta(bot, f"❌ Ocorreu um erro crítico no bot: {str(e)}")
                logging.info("Aguardando 60 segundos antes de tentar novamente...")
                await asyncio.sleep(60)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Bot encerrado pelo usuário.")
    except Exception as e:
        logging.error(f"O processo principal falhou completamente: {e}.")

