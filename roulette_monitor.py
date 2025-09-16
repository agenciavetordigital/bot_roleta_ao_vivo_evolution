# -*- coding: utf-8 -*-

import os
import time
import logging
import asyncio
import random
from datetime import date, datetime, timedelta

import telegram
from telegram.constants import ParseMode
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

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
MAX_MARTINGALES = 2

# --- CONFIGURAÇÕES DE HUMANIZAÇÃO (CICLOS)--- ### NOVO ###
WORK_MIN_MINUTES = 3 * 60  # 3 horas
WORK_MAX_MINUTES = 5 * 60  # 5 horas
BREAK_MIN_MINUTES = 25     # 25 minutos
BREAK_MAX_MINUTES = 45     # 45 minutos
### FIM NOVO ###


# --- LÓGICA DAS ESTRATÉGIAS ---
# (Esta seção continua a mesma, sem alterações)
ROULETTE_WHEEL = [0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23, 10, 5, 24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26]
def get_winners_72(trigger_number):
    try:
        index = ROULETTE_WHEEL.index(trigger_number)
        total_numbers = len(ROULETTE_WHEEL)
        winners = {trigger_number}
        for i in range(1, 5): winners.add(ROULETTE_WHEEL[(index - i + total_numbers) % total_numbers])
        for i in range(1, 5): winners.add(ROULETTE_WHEEL[(index + i) % total_numbers])
        winners.add(0)
        return list(winners)
    except ValueError: return [0, trigger_number]
def get_winners_p2(trigger_number):
    return [0, 1, 2, 5, 6, 8, 9, 10, 12, 13, 14, 16, 17, 19, 20, 23, 24, 26, 27, 28, 30, 31, 32, 34, 35]
ESTRATEGIAS = {
    "Estratégia menos fichas": {"triggers": [2, 12, 17, 16], "filter": [], "get_winners": get_winners_72},
    "Estratégia 95% - Roleta": {"triggers": [3, 4, 7, 11, 15, 18, 21, 22, 25, 29, 33, 36, 26, 27, 28, 30, 31, 32, 34, 35], "filter": [], "get_winners": get_winners_p2}
}


# --- LÓGICA DO BOT ---
# (As funções de lógica do bot, como placar, estado, selenium, telegram, etc.,
# continuam as mesmas da versão refatorada anterior. Cole-as aqui.)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
ultimo_numero_processado = None
numero_anterior = None

def initialize_score():
    score = {"last_check_date": date.today()}
    for name in ESTRATEGIAS:
        score[name] = {"wins_sg": 0, "wins_g1": 0, "wins_g2": 0, "losses": 0}
    return score
daily_score = initialize_score()
active_strategy_state = {}

def reset_strategy_state():
    global active_strategy_state
    active_strategy_state = { "active": False, "strategy_name": "", "martingale_level": 0, "winning_numbers": [], "trigger_number": None, "messages_to_delete": {} }
reset_strategy_state()

def configurar_driver():
    logging.info("Configurando o driver do Chrome...")
    chrome_options = webdriver.ChromeOptions()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
    service = ChromeService()
    driver = webdriver.Chrome(service=service, options=chrome_options)
    logging.info("Driver do Chrome configurado com sucesso.")
    return driver

def fazer_login(driver):
    try:
        logging.info("Iniciando processo de login...")
        driver.get(URL_LOGIN)
        wait = WebDriverWait(driver, 20)
        email_input = wait.until(EC.presence_of_element_located((By.ID, "loginclienteform-email")))
        email_input.send_keys(PADROES_USER)
        password_input = driver.find_element(By.ID, "senha")
        password_input.send_keys(PADROES_PASS)
        login_button = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
        login_button.click()
        wait.until(EC.url_to_be(URL_ROLETA))
        logging.info("Login realizado com sucesso!")
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
        if numero_str == ultimo_numero_processado: return None
        numero_anterior = int(ultimo_numero_processado) if ultimo_numero_processado and ultimo_numero_processado.isdigit() else None
        ultimo_numero_processado = numero_str
        if numero_str.isdigit():
            numero = int(numero_str)
            logging.info(f"✅ Novo número encontrado: {numero} (Anterior: {numero_anterior})")
            return numero
        return None
    except (TimeoutException, NoSuchElementException):
        logging.warning("Elemento do número não encontrado ou demorou para carregar.")
        return None
    except Exception as e:
        logging.error(f"Erro inesperado ao buscar número: {e}")
        return None

def format_score_message():
    messages = ["📊 *Placar do Dia* 📊"]
    for name, score in daily_score.items():
        if name != "last_check_date":
            wins_str = f"SG: {score['wins_sg']} | G1: {score['wins_g1']} | G2: {score['wins_g2']}"
            messages.append(f"*{name}*:\n`   `✅ `{wins_str}`\n`   `❌ `{score['losses']}`")
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

async def send_and_track_message(bot, text, **kwargs):
    sent_messages = await send_message_to_all(bot, text, **kwargs)
    for chat_id, message in sent_messages.items():
        if chat_id not in active_strategy_state["messages_to_delete"]:
            active_strategy_state["messages_to_delete"][chat_id] = []
        active_strategy_state["messages_to_delete"][chat_id].append(message.message_id)

async def delete_all_play_messages(bot):
    messages_to_delete = active_strategy_state.get("messages_to_delete", {})
    for chat_id, message_ids in messages_to_delete.items():
        for message_id in message_ids:
            try: await bot.delete_message(chat_id=chat_id, message_id=message_id)
            except Exception: logging.warning(f"Não foi possível apagar a msg {message_id} do chat {chat_id}.")

async def check_and_reset_daily_score(bot):
    global daily_score
    today = date.today()
    if daily_score["last_check_date"] != today:
        logging.info("Novo dia detectado! Resetando o placar.")
        summary_title = f"Resumo do dia {daily_score['last_check_date'].strftime('%d/%m/%Y')}:"
        final_scores = format_score_message().replace("*Placar do Dia*", "*Placar Final*")
        await send_message_to_all(bot, f"{summary_title}\n{final_scores}", parse_mode=ParseMode.MARKDOWN)
        daily_score = initialize_score()
        await send_message_to_all(bot, "Placar diário zerado. Bom dia e boas apostas!")

async def handle_win(bot, final_number):
    await delete_all_play_messages(bot)
    strategy_name = active_strategy_state["strategy_name"]
    win_level = active_strategy_state["martingale_level"]
    if win_level == 0:
        daily_score[strategy_name]["wins_sg"] += 1; win_type_message = "Vitória sem Gale!"
    else:
        daily_score[strategy_name][f"wins_g{win_level}"] += 1; win_type_message = f"Vitória no {win_level}º Martingale"
    mensagem = (f"✅ Paga Roleta ✅\n\n*{win_type_message}*\n_Estratégia: {strategy_name}_\nGatilho: *{active_strategy_state['trigger_number']}* | Saiu: *{final_number}*\n\n{format_score_message()}")
    await send_message_to_all(bot, mensagem, parse_mode=ParseMode.MARKDOWN)
    reset_strategy_state()

async def handle_loss(bot, final_number):
    await delete_all_play_messages(bot)
    strategy_name = active_strategy_state["strategy_name"]
    daily_score[strategy_name]["losses"] += 1
    mensagem = (f"❌ Loss Final ❌\n\n_Estratégia: {strategy_name}_\nGatilho: *{active_strategy_state['trigger_number']}* | Saiu: *{final_number}*\n\n{format_score_message()}")
    await send_message_to_all(bot, mensagem, parse_mode=ParseMode.MARKDOWN)
    reset_strategy_state()

async def handle_martingale(bot, current_number):
    strategy_name = active_strategy_state["strategy_name"]
    level = active_strategy_state["martingale_level"]
    mensagem = (f"❌ Roleta Safada ❌\n\n_Estratégia: {strategy_name}_\nGatilho: *{active_strategy_state['trigger_number']}* | Saiu: *{current_number}*\n\n➡️ Entrar no *{level}º Martingale*\n\n{format_score_message()}")
    await send_and_track_message(bot, mensagem, parse_mode=ParseMode.MARKDOWN)

async def handle_active_strategy(bot, numero):
    if numero in active_strategy_state["winning_numbers"]: await handle_win(bot, numero)
    else:
        active_strategy_state["martingale_level"] += 1
        if active_strategy_state["martingale_level"] <= MAX_MARTINGALES: await handle_martingale(bot, numero)
        else: await handle_loss(bot, numero)

async def check_for_new_triggers(bot, numero):
    for name, details in ESTRATEGIAS.items():
        if numero in details["triggers"]:
            if details.get("filter") and numero_anterior in details["filter"]:
                logging.info(f"Gatilho {numero} ignorado para '{name}' devido ao filtro.")
                continue
            winning_numbers = details["get_winners"](numero)
            active_strategy_state.update({ "active": True, "strategy_name": name, "winning_numbers": winning_numbers, "trigger_number": numero })
            mensagem = (f"🎯 *Gatilho Encontrado!* 🎯\n\n🎲 *Estratégia: {name}*\n🔢 *Número Gatilho: {numero}*\n\n💰 *Apostar em:*\n`{', '.join(map(str, sorted(winning_numbers)))}`\n\n{format_score_message()}\n\n[🔗 Fazer Aposta]({URL_APOSTA})")
            await send_and_track_message(bot, mensagem, parse_mode=ParseMode.MARKDOWN)
            break

async def processar_numero(bot, numero):
    if numero is None: return
    await check_and_reset_daily_score(bot)
    if active_strategy_state["active"]: await handle_active_strategy(bot, numero)
    else: await check_for_new_triggers(bot, numero)


# --- EXECUÇÃO PRINCIPAL (representa uma SESSÃO DE TRABALHO) ---
async def main():
    bot = telegram.Bot(token=TOKEN_BOT)

    # --- LÓGICA DA SESSÃO DE TRABALHO --- ### NOVO ###
    work_duration_minutes = random.randint(WORK_MIN_MINUTES, WORK_MAX_MINUTES)
    session_end_time = datetime.now() + timedelta(minutes=work_duration_minutes)
    
    logging.info(f"Iniciando uma nova sessão de trabalho que durará {work_duration_minutes // 60}h e {work_duration_minutes % 60}min.")
    await send_message_to_all(bot, f"☀️ *Sessão de trabalho iniciada!*\nO bot ficará ativo por aproximadamente *{work_duration_minutes // 60}h e {work_duration_minutes % 60}min*.", parse_mode=ParseMode.MARKDOWN)
    
    driver = None
    try:
        driver = configurar_driver()
        if not fazer_login(driver):
            raise Exception("O login falhou.")
        
        while datetime.now() < session_end_time:
            numero = buscar_ultimo_numero(driver)
            await processar_numero(bot, numero)
            await asyncio.sleep(INTERVALO_VERIFICACAO)
        
        # Fim do loop de trabalho
        logging.info("Sessão de trabalho concluída. Preparando para a pausa.")
        await send_message_to_all(bot, "⏱️ Sessão de trabalho finalizada. O bot entrará em pausa para um café. ☕", parse_mode=ParseMode.MARKDOWN)

    except Exception as e:
        logging.error(f"Um erro crítico ocorreu na sessão de trabalho: {e}")
    finally:
        if driver:
            driver.quit()
            logging.info("Driver do Selenium encerrado para a pausa.")


# --- SUPERVISOR (gerencia os ciclos de TRABALHO e PAUSA) ---
if __name__ == '__main__':
    # Mensagem de inicialização única
    try:
        bot = telegram.Bot(token=TOKEN_BOT)
        asyncio.run(send_message_to_all(bot, f"✅ Bot supervisor iniciado com sucesso! Gerenciando ciclos de trabalho e pausa."))
    except Exception as e:
        logging.critical(f"Não foi possível conectar ao Telegram para a mensagem inicial: {e}")

    while True:
        try:
            # Executa uma sessão de trabalho completa
            asyncio.run(main()) 

            # Lógica da Pausa
            break_duration_minutes = random.randint(BREAK_MIN_MINUTES, BREAK_MAX_MINUTES)
            logging.info(f"Iniciando pausa de {break_duration_minutes} minutos.")
            time.sleep(break_duration_minutes * 60)
            logging.info("Pausa finalizada. Iniciando nova sessão de trabalho.")

        except Exception as e:
            logging.critical(f"O processo supervisor falhou: {e}. Reiniciando o ciclo em 60 segundos.")
            time.sleep(60)
