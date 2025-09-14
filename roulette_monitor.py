# -*- coding: utf-8 -*-
import requests
from bs4 import BeautifulSoup
import time
import telegram
import logging
import asyncio
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

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

# --- LOGGING ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
ultimo_id_rodada = None

# --- FUNÇÃO PARA BUSCAR O NÚMERO ---
def buscar_ultimo_numero(driver):
    global ultimo_id_rodada
    try:
        wait = WebDriverWait(driver, 30)
        history_container = wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div[data-history-content='true']"))
        )

        spans = history_container.find_elements(By.TAG_NAME, 'span')

        # Loga todos os spans capturados
        logging.info("Capturados os seguintes spans no histórico:")
        for span in spans:
            logging.info(f"→ '{span.text.strip()}'")

        for span in spans:
            texto = span.text.strip()

            # Filtro reforçado: só aceita dígitos, até 2 caracteres
            if not texto.isdigit() or len(texto) > 2:
                continue

            numero = int(texto)

            # Garante que é número válido da roleta (0–36)
            if 0 <= numero <= 36:
                if texto == ultimo_id_rodada:
                    return None
                ultimo_id_rodada = texto
                logging.info(f"Número mais recente encontrado: {numero}")
                return numero

        logging.warning("Nenhum número válido de roleta encontrado no histórico.")
        return None

    except Exception as e:
        logging.error(f"Erro ao buscar número com Selenium: {e}")
        return None

# --- FUNÇÕES DO BOT ---
async def verificar_estrategias(bot, numero):
    if numero is None:
        return
    for nome_estrategia, condicao in ESTRATEGIAS.items():
        try:
            if condicao(numero):
                mensagem = (
                    f"🎯 Gatilho Encontrado! 🎯\n\n"
                    f"Estratégia: *{nome_estrategia}*\n"
                    f"Número Sorteado: *{numero}*"
                )
                logging.info(f"Estratégia '{nome_estrategia}' ativada → enviando alerta")
                await enviar_alerta(bot, mensagem)
        except Exception as e:
            logging.error(f"Erro na estratégia '{nome_estrategia}': {e}")

async def enviar_alerta(bot, mensagem):
    try:
        await bot.send_message(
            chat_id=CHAT_ID,
            text=mensagem,
            parse_mode=telegram.ParseMode.MARKDOWN
        )
        logging.info("✅ Alerta enviado com sucesso!")
    except Exception as e:
        logging.error(f"Erro ao enviar alerta: {e}")

# --- LOOP PRINCIPAL ---
async def main():
    try:
        bot = telegram.Bot(token=TOKEN_BOT)
        info_bot = await bot.get_me()
        logging.info(f"Bot '{info_bot.first_name}' inicializado com sucesso!")
        await enviar_alerta(bot, "✅ Bot monitor de roleta iniciado com sucesso!")
    except Exception as e:
        logging.critical(f"Erro ao conectar com Telegram: {e}")
        return

    logging.info("Iniciando monitoramento da roleta...")

    options = webdriver.ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    driver = webdriver.Chrome(options=options)

    driver.get(URL_ROLETA)

    while True:
        try:
            numero = buscar_ultimo_numero(driver)
            if numero is not None:
                await verificar_estrategias(bot, numero)
            await asyncio.sleep(INTERVALO_VERIFICACAO)
        except KeyboardInterrupt:
            logging.info("Monitoramento interrompido pelo usuário.")
            await enviar_alerta(bot, "❌ Bot monitor encerrado manualmente.")
            break
        except Exception as e:
            logging.error(f"Erro crítico no loop principal: {e}")
            logging.info("⏳ Aguardando 60 segundos antes de tentar novamente...")
            await asyncio.sleep(60)

if __name__ == '__main__':
    asyncio.run(main())
