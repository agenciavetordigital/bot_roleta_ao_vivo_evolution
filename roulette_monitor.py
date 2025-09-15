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
    logging.critical("Todas as variáveis de ambiente (TOKEN_BOT, CHAT_ID, PADROES_USER, PADROES_PASS, URL_APOSTA) devem ser definidas!")
    exit()

CHAT_IDS = [chat_id.strip() for chat_id in CHAT_IDS_STR.split(',')]

URL_ROLETA = 'https://jv.padroesdecassino.com.br/sistema/roletabrasileira'
URL_LOGIN = 'https://jv.padroesdecassino.com.br/sistema/login'
INTERVALO_VERIFICACAO = 3

# --- LÓGICA DAS ESTRATÉGIAS ---
ROULETTE_WHEEL = [0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8,
                  23, 10, 5, 24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12,
                  35, 3, 26]

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
    return [0, 1, 2, 5, 6, 8, 9, 10, 12, 13, 14, 16, 17, 19, 20,
            23, 24, 26, 27, 28, 30, 31, 32, 34, 35]

ESTRATEGIAS = {
    "Estratégia do 72": {"triggers": [2, 12, 17, 16], "filter": [], "get_winners": get_winners_72},
    "Estratégia P2 - Roleta": {"triggers": [3, 4, 7, 11, 15, 18, 21, 22,
                                           25, 29, 33, 36, 26, 27, 28,
                                           30, 31, 32, 34, 35],
                               "filter": [], "get_winners": get_winners_p2}
}

# --- LÓGICA DO BOT ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
ultimo_numero_processado = None
numero_anterior = None 

def initialize_score():
    score = {"last_check_date": date.today()}
    for name in ESTRATEGIAS:
        score[name] = {"wins_sg": 0, "wins_g1": 0, "wins_g2": 0, "losses": 0}
    return score

daily_score = initialize_score()

active_strategy_state = {
    "active": False, "strategy_name": "", "martingale_level": 0,
    "winning_numbers": [], "trigger_number": None, "messages": {}
}

# --- Health check variables ---
last_health_check_date = None
sent_good_night = False

def configurar_driver():
    logging.info("Configurando o driver do Chrome...")
    chrome_options = webdriver.ChromeOptions()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
    service = ChromeService() 
    driver = webdriver.Chrome(service=service, options=chrome_options)
    logging.info("Driver do Chrome configurado com sucesso.")
    return driver

def fazer_login(driver):
    try:
        logging.info("Iniciando processo de login no Padrões de Cassino...")
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

def format_score_message():
    messages = ["📊 *Placar do Dia* 📊"]
    for name, score in daily_score.items():
        if name != "last_check_date":
            wins_str = f"SG: {score['wins_sg']} | G1: {score['wins_g1']} | G2: {score['wins_g2']}"
            messages.append(f"*{name}*:\n`    `✅ `{wins_str}`\n`    `❌ `{score['losses']}`")
    return "\n\n".join(messages)

async def send_message_to_all(bot, text, **kwargs):
    sent_messages = {}
    for chat_id in CHAT_IDS:
        try:
            message = await bot.send_message(chat_id=chat_id, text=text, **kwargs)
            sent_messages[chat_id] = message
        except Exception as e:
            logging.error(f"Erro ao enviar mensagem para o chat_id {chat_id}: {e}")
    return sent_messages

# --- Health check (Bom dia / Boa noite) ---
async def check_bot_health(bot):
    global last_health_check_date, sent_good_night
    now = datetime.now()
    today = now.date()

    # Bom dia (apenas 1x por dia, ao virar a data)
    if last_health_check_date != today:
        last_health_check_date = today
        sent_good_night = False  # reseta para o novo dia
        await send_message_to_all(bot, "🌞 Bom dia! Estou online e a postos.")

    # Boa noite (apenas 1x por dia, após 20h)
    if now.hour >= 20 and not sent_good_night:
        sent_good_night = True
        await send_message_to_all(bot, "🌙 Boa noite! Continuo online e monitorando.")

# --- Estratégias e gatilhos ---
async def processar_numero(bot, numero):
    global active_strategy_state, daily_score
    if numero is None: 
        return

    # checar reset diário e mensagens de saúde
    await check_bot_health(bot)

    placar_formatado = format_score_message()
    if active_strategy_state["active"]:
        strategy_name = active_strategy_state["strategy_name"]
        is_win = numero in active_strategy_state["winning_numbers"]
        if is_win:
            win_level = active_strategy_state["martingale_level"]
            if win_level == 0:
                daily_score[strategy_name]["wins_sg"] += 1
                win_type_message = "Vitória sem Gale!"
            else:
                daily_score[strategy_name][f"wins_g{win_level}"] += 1
                win_type_message = f"Vitória no {win_level}º Martingale"
            mensagem = (f"✅ Paga Roleta ✅\n\n"
                        f"*{win_type_message}*\n"
                        f"_Estratégia: {strategy_name}_\n"
                        f"Gatilho: *{active_strategy_state['trigger_number']}* | Saiu: *{numero}*\n\n"
                        f"{format_score_message()}")
            await send_message_to_all(bot, mensagem, parse_mode=ParseMode.MARKDOWN)
            active_strategy_state = {"active": False, "messages": {}}
        else:
            active_strategy_state["martingale_level"] += 1
            level = active_strategy_state["martingale_level"]
            if level <= 2:
                mensagem = (f"❌ Roleta Safada ❌\n\n"
                            f"_Estratégia: {strategy_name}_\n"
                            f"Gatilho: *{active_strategy_state['trigger_number']}* | Saiu: *{numero}*\n\n"
                            f"➡️ Entrar no *{level}º Martingale*\n\n"
                            f"{placar_formatado}")
                await send_message_to_all(bot, mensagem, parse_mode=ParseMode.MARKDOWN)
            else:
                daily_score[strategy_name]["losses"] += 1
                mensagem = (f"❌ Loss Final ❌\n\n"
                            f"_Estratégia: {strategy_name}_\n"
                            f"Gatilho: *{active_strategy_state['trigger_number']}* | Saiu: *{numero}*\n\n"
                            f"{format_score_message()}")
                await send_message_to_all(bot, mensagem, parse_mode=ParseMode.MARKDOWN)
                active_strategy_state = {"active": False, "messages": {}}
    else:
        for name, details in ESTRATEGIAS.items():
            if numero in details["triggers"]:
                winning_numbers = details["get_winners"](numero)
                mensagem = (f"🎯 *Gatilho Encontrado!* 🎯\n\n"
                            f"🎲 *Estratégia: {name}*\n"
                            f"🔢 *Número Gatilho: {numero}*\n\n"
                            f"💰 *Apostar em:*\n`{', '.join(map(str, sorted(winning_numbers)))}`\n\n"
                            f"{placar_formatado}\n\n"
                            f"[🔗 Fazer Aposta]({URL_APOSTA})")
                await send_message_to_all(bot, mensagem, parse_mode=ParseMode.MARKDOWN)
                active_strategy_state = {"active": True, "strategy_name": name, "martingale_level": 0,
                                         "winning_numbers": winning_numbers, "trigger_number": numero, "messages": {}}
                break

# --- Main ---
async def main():
    bot = None
    try:
        bot = telegram.Bot(token=TOKEN_BOT)
        info_bot = await bot.get_me()
        logging.info(f"Bot '{info_bot.first_name}' (Padrões de Cassino) inicializado com sucesso!")

        # Notificação de reinicialização
        await send_message_to_all(bot, "⚠️ Atenção: Tive um problema e fui reiniciado, mas já estou de volta ao trabalho.")

    except Exception as e:
        logging.critical(f"Não foi possível conectar ao Telegram. Erro: {e}")
        return
    driver = None
    try:
        driver = configurar_driver()
        if not fazer_login(driver): 
            raise Exception("O login no Padrões de Cassino falhou.")
        while True:
            numero = buscar_ultimo_numero(driver)
            await processar_numero(bot, numero)
            await asyncio.sleep(INTERVALO_VERIFICACAO)
    except Exception as e:
        logging.error(f"Um erro crítico ocorreu: {e}")
    finally:
        if driver: driver.quit()
        logging.info("Driver do Selenium encerrado.")
        logging.info("O programa principal foi encerrado. Reiniciando em 1 minuto.")
        await asyncio.sleep(60)

if __name__ == '__main__':
    while True:
        try:
            asyncio.run(main())
        except Exception as e:
            logging.error(f"O processo principal falhou completamente: {e}. Reiniciando em 1 minuto.")
            time.sleep(60)
