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
from datetime import date, datetime

# --- CONFIGURAÇÕES ESSENCIAIS ---
TOKEN_BOT = os.environ.get('TOKEN_BOT')
CHAT_IDS_STR = os.environ.get('CHAT_ID')
PADROES_USER = os.environ.get('PADROES_USER')
PADROES_PASS = os.environ.get('PADROES_PASS')
URL_APOSTA = os.environ.get('URL_APOSTA')

if not all([TOKEN_BOT, CHAT_IDS_STR, PADROES_USER, PADROES_PASS, URL_APOSTA]):
    logging.critical("Todas as variáveis de ambiente devem ser definidas!")
    exit()

CHAT_IDS = [chat_id.strip() for chat_id in CHAT_IDS_STR.split(',')]

URL_ROLETA = 'https://jv.padroesdecassino.com.br/sistema/roletabrasileira'
URL_LOGIN = 'https://jv.padroesdecassino.com.br/sistema/login'
INTERVALO_VERIFICACAO = 3

# --- LÓGICA DAS ESTRATÉGIAS ---
ROULETTE_WHEEL = [0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11,
                  30, 8, 23, 10, 5, 24, 16, 33, 1, 20, 14, 31, 9, 22, 18,
                  29, 7, 28, 12, 35, 3, 26]

def get_winners_72(trigger_number):
    try:
        index = ROULETTE_WHEEL.index(trigger_number)
        total_numbers = len(ROULETTE_WHEEL)
        winners = {trigger_number}
        for i in range(1, 5):
            winners.add(ROULETTE_WHEEL[(index - i + total_numbers) % total_numbers])
        for i in range(1, 5):
            winners.add(ROULETTE_WHEEL[(index + i) % total_numbers])
        winners.add(0)
        return list(winners)
    except ValueError:
        return [0, trigger_number]

def get_winners_p2(trigger_number):
    return [0, 1, 2, 5, 6, 8, 9, 10, 12, 13, 14, 16, 17, 19, 20, 23, 24,
            26, 27, 28, 30, 31, 32, 34, 35]

ESTRATEGIAS = {
    "Estratégia do 72": {
        "triggers": [2, 12, 17, 16], "filter": [], "get_winners": get_winners_72},
    "Estratégia P2 - Roleta": {
        "triggers": [3, 4, 7, 11, 15, 18, 21, 22, 25, 29, 33, 36,
                     26, 27, 28, 30, 31, 32, 34, 35],
        "filter": [], "get_winners": get_winners_p2}
}

# --- LÓGICA DO BOT ---
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

ultimo_numero_processado = None
numero_anterior = None

# variáveis para notificações de saúde
last_health_check_date = None
last_goodnight_date = None

# --- PLACAR DIÁRIO ---
def initialize_score():
    score = {"last_check_date": date.today()}
    for name in ESTRATEGIAS:
        score[name] = {"wins_sg": 0, "wins_g1": 0, "wins_g2": 0, "losses": 0}
    return score

daily_score = initialize_score()

def format_score_message():
    messages = ["📊 *Placar do Dia* 📊"]
    for name, score in daily_score.items():
        if name != "last_check_date":
            wins_str = f"SG: {score['wins_sg']} | G1: {score['wins_g1']} | G2: {score['wins_g2']}"
            messages.append(f"*{name}*:\n`    `✅ `{wins_str}`\n`    `❌ `{score['losses']}`")
    return "\n\n".join(messages)

# --- Selenium ---
def configurar_driver():
    chrome_options = webdriver.ChromeOptions()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                "AppleWebKit/537.36 (KHTML, like Gecko) "
                                "Chrome/91.0.4472.124 Safari/537.36")
    service = ChromeService()
    return webdriver.Chrome(service=service, options=chrome_options)

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
        wait.until(EC.url_to_be(URL_ROLETA))
        logging.info("Login realizado com sucesso! Redirecionado para a página da roleta.")
        return True
    except Exception as e:
        logging.error(f"Falha no processo de login: {e}")
        return False

def buscar_ultimo_numero(driver):
    global ultimo_numero_processado, numero_anterior
    try:
        wait = WebDriverWait(driver, 10)
        container_recente = wait.until(EC.presence_of_element_located((By.ID, "dados")))
        ultimo_numero_div = container_recente.find_element(By.CSS_SELECTOR, "div:last-child")
        numero_str = ultimo_numero_div.text.strip()
        if numero_str == ultimo_numero_processado:
            return None
        numero_anterior = int(ultimo_numero_processado) if ultimo_numero_processado and ultimo_numero_processado.isdigit() else None
        ultimo_numero_processado = numero_str
        if numero_str.isdigit():
            numero = int(numero_str)
            logging.info(f"✅ Novo número encontrado: {numero} (Anterior: {numero_anterior})")
            return numero
        return None
    except Exception:
        logging.warning("Não foi possível buscar o último número. A página pode estar carregando.")
        return None

# --- Funções auxiliares de mensagens ---
async def send_message_to_all(bot, text, **kwargs):
    for chat_id in CHAT_IDS:
        try:
            await bot.send_message(chat_id=chat_id, text=text, **kwargs)
        except Exception as e:
            logging.error(f"Erro ao enviar mensagem para o chat_id {chat_id}: {e}")

# --- Notificações de saúde ---
async def check_bot_health(bot):
    global last_health_check_date, last_goodnight_date, daily_score
    now = datetime.now()
    today = now.date()

    # Bom dia + resumo do dia anterior
    if last_health_check_date != today:
        last_health_check_date = today
        summary_title = f"📊 Resumo do dia {daily_score['last_check_date'].strftime('%d/%m/%Y')}:"
        final_scores = format_score_message().replace("*Placar do Dia*", "*Placar Final*")
        await send_message_to_all(bot, f"{summary_title}\n{final_scores}", parse_mode=ParseMode.MARKDOWN)
        daily_score = initialize_score()
        await send_message_to_all(bot, "🌞 Bom dia! Estou online e a postos. Placar diário zerado.")

    # Boa noite
    if now.hour >= 20 and last_goodnight_date != today:
        last_goodnight_date = today
        await send_message_to_all(bot, "🌙 Boa noite! Continuo rodando em segundo plano.")

# --- Processamento das estratégias ---
async def processar_numero(bot, numero):
    # Aqui mantém a lógica de estratégias do seu código
    pass

async def main():
    bot = telegram.Bot(token=TOKEN_BOT)
    info_bot = await bot.get_me()
    logging.info(f"Bot '{info_bot.first_name}' inicializado com sucesso!")

    # 🚨 Reinicialização
    await send_message_to_all(bot, "⚠️ Atenção: Tive um problema e fui reiniciado, mas já estou de volta ao trabalho.")

    driver = configurar_driver()
    if not fazer_login(driver):
        await send_message_to_all(bot, "❌ Falha no login. Verifique credenciais.")
        return

    while True:
        numero = buscar_ultimo_numero(driver)
        await processar_numero(bot, numero)

        # checagem de saúde
        await check_bot_health(bot)

        await asyncio.sleep(INTERVALO_VERIFICACAO)

if __name__ == '__main__':
    while True:
        try:
            asyncio.run(main())
        except Exception as e:
            logging.error(f"Falha crítica: {e}. Reiniciando em 1 minuto.")
            time.sleep(60)
