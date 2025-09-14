# -*- coding: utf-8 -*-

import os
import time
import logging
import asyncio
import telegram
from telegram.constants import ParseMode
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# --- CONFIGURAÇÕES ESSENCIAIS ---
TOKEN_BOT = os.environ.get('TOKEN_BOT')
CHAT_ID = os.environ.get('CHAT_ID')

if not TOKEN_BOT or not CHAT_ID:
    logging.critical("As variáveis de ambiente TOKEN_BOT e CHAT_ID devem ser definidas!")
    exit()

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

def configurar_driver():
    """Configura o driver e o navegador Chrome, especificando os caminhos dos executáveis."""
    logging.info("Configurando o driver e o navegador Chrome com caminhos explícitos...")
    chrome_options = webdriver.ChromeOptions()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920x1080")
    
    # A MUDANÇA FINAL: Especificamos o caminho para o NAVEGADOR.
    chrome_options.binary_location = "/usr/bin/google-chrome"
    
    caminho_driver = "/usr/bin/chromedriver"
    service = ChromeService(executable_path=caminho_driver) 
    
    driver = webdriver.Chrome(service=service, options=chrome_options)
    logging.info("Driver e navegador Chrome configurados com sucesso.")
    return driver

def buscar_ultimo_numero(driver):
    """Busca o número mais recente da roleta usando Selenium."""
    global ultimo_id_rodada
    try:
        driver.get(URL_ROLETA)
        wait = WebDriverWait(driver, 20)
        container_numeros = wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div.flex.flex-wrap.gap-2.justify-center"))
        )
        primeiro_numero_div = container_numeros.find_element(By.TAG_NAME, 'div')
        id_rodada_atual = primeiro_numero_div.get_attribute('innerHTML')

        if id_rodada_atual == ultimo_id_rodada:
            return None

        ultimo_id_rodada = id_rodada_atual
        numero_str = primeiro_numero_div.text.strip()
        numero = int(numero_str)
        logging.info(f"Número mais recente encontrado: {numero}")
        return numero
    except Exception as e:
        logging.error(f"Erro ao buscar número com Selenium: {e}")
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
        logging.info(f"Bot '{info_bot.first_name}' inicializado com sucesso!")
        await enviar_alerta(bot, f"✅ Bot '{info_bot.first_name}' conectado e monitorando!")
    except Exception as e:
        logging.critical(f"Não foi possível conectar ao Telegram. Erro: {e}")
        return

    driver = None
    try:
        driver = configurar_driver()
        logging.info("Iniciando monitoramento da roleta...")
        while True:
            numero = buscar_ultimo_numero(driver)
            if numero is not None:
                await verificar_estrategias(bot, numero)
            await asyncio.sleep(INTERVALO_VERIFICACAO)
    except Exception as e:
        # Tratamento do erro de formatação do Telegram
        erro_tratado = str(e).replace("*", "").replace("_", "")
        logging.error(f"Um erro crítico ocorreu no loop principal: {erro_tratado}")
        if bot:
            await enviar_alerta(bot, f"❌ Ocorreu um erro crítico no bot: `{erro_tratado}`")
    finally:
        if driver:
            driver.quit()
        logging.info("Processo principal finalizado.")

if __name__ == '__main__':
    while True:
        try:
            asyncio.run(main())
            logging.info("O programa principal foi encerrado. Reiniciando em 1 minuto.")
        except Exception as e:
            logging.error(f"O processo principal falhou completamente: {e}. Reiniciando em 1 minuto.")
        time.sleep(60)

