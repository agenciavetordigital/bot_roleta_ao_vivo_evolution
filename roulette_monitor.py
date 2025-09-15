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
from datetime import datetime

# --- CONFIGURAÇÕES ESSENCIAIS ---
TOKEN_BOT = os.environ.get('TOKEN_BOT')
CHAT_ID = os.environ.get('CHAT_ID')
PADROES_USER = os.environ.get('PADROES_USER')
PADROES_PASS = os.environ.get('PADROES_PASS')

if not all([TOKEN_BOT, CHAT_ID, PADROES_USER, PADROES_PASS]):
    logging.critical("Todas as variáveis de ambiente devem ser definidas!")
    exit()

URL_ROLETA = 'https://jv.padroesdecassino.com.br/sistema/roletabrasileira'
URL_LOGIN = 'https://jv.padroesdecassino.com.br/sistema/login'
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
last_health_check_date = None
last_goodnight_date = None

def configurar_driver():
    chrome_options = webdriver.ChromeOptions()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
    service = ChromeService()
    driver = webdriver.Chrome(service=service, options=chrome_options)
    return driver

def fazer_login(driver):
    try:
        driver.get(URL_LOGIN)
        wait = WebDriverWait(driver, 20)

        email_input = wait.until(EC.presence_of_element_located((By.ID, "loginclienteform-email")))
        email_input.send_keys(PADROES_USER)

        password_input = driver.find_element(By.ID, "senha")
        password_input.send_keys(PADROES_PASS)

        login_button = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
        login_button.click()
        
        wait.until(EC.url_contains("sistema"))
        logging.info("Login realizado com sucesso!")
        return True

    except Exception as e:
        logging.error(f"Falha no processo de login: {e}")
        return False

def buscar_ultimo_numero(driver):
    global ultimo_numero_encontrado
    try:
        if driver.current_url != URL_ROLETA:
            driver.get(URL_ROLETA)
        else:
            driver.refresh()

        wait = WebDriverWait(driver, 20)
        container = wait.until(EC.presence_of_element_located((By.ID, "dados")))

        primeiro_item = container.find_element(By.XPATH, "./*")
        numero_str = primeiro_item.text.strip()

        if not numero_str.isdigit():
            logging.warning(f"Texto encontrado não é número válido: '{numero_str}'")
            return None

        if numero_str == ultimo_numero_encontrado:
            return None

        ultimo_numero_encontrado = numero_str
        numero = int(numero_str)
        logging.info(f"Número válido encontrado: {numero}")
        return numero

    except Exception as e:
        logging.error(f"Erro ao buscar número: {e}")
        return None

async def verificar_estrategias(bot, numero):
    if numero is None:
        return
    for nome_estrategia, condicao in ESTRATEGIAS.items():
        if condicao(numero):
            mensagem = f"🎯 Gatilho Encontrado! 🎯\n\nEstratégia: *{nome_estrategia}*\nNúmero Sorteado: *{numero}*"
            await enviar_alerta(bot, mensagem)

async def enviar_alerta(bot, mensagem):
    try:
        await bot.send_message(chat_id=CHAT_ID, text=mensagem, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logging.error(f"Erro ao enviar mensagem: {e}")

# --- NOVO: checagem de saúde ---
async def check_bot_health(bot):
    global last_health_check_date, last_goodnight_date
    now = datetime.now()
    today = now.date()

    # Bom dia (primeira execução do dia)
    if last_health_check_date != today:
        last_health_check_date = today
        await enviar_alerta(bot, "🌞 Bom dia! Estou online e a postos.")

    # Boa noite (após 20h, uma vez por dia)
    if now.hour >= 20 and last_goodnight_date != today:
        last_goodnight_date = today
        await enviar_alerta(bot, "🌙 Boa noite! Continuo rodando em segundo plano.")

async def main():
    bot = telegram.Bot(token=TOKEN_BOT)
    info_bot = await bot.get_me()
    logging.info(f"Bot '{info_bot.first_name}' inicializado com sucesso!")

    # 🚨 Mensagem de reinicialização
    await enviar_alerta(bot, "⚠️ Atenção: Tive um problema e fui reiniciado, mas já estou de volta ao trabalho.")

    driver = configurar_driver()
    
    if not fazer_login(driver):
        await enviar_alerta(bot, "❌ Falha no login. Verifique credenciais.")
        return
    
    while True:
        numero = buscar_ultimo_numero(driver)
        if numero is not None:
            await verificar_estrategias(bot, numero)

        # checagem diária de saúde
        await check_bot_health(bot)

        await asyncio.sleep(INTERVALO_VERIFICACAO)

if __name__ == '__main__':
    while True:
        try:
            asyncio.run(main())
        except Exception as e:
            logging.error(f"Falha crítica: {e}. Reiniciando em 1 minuto.")
            time.sleep(60)
