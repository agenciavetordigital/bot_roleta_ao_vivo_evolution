# -*- coding: utf-8 -*-

import os
import time
import logging
import asyncio
import random
from datetime import date, datetime, timedelta, time as dt_time
import pytz

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

# --- CONFIGURAÇÕES DE HUMANIZAÇÃO E HORA ---
FUSO_HORARIO_BRASIL = pytz.timezone('America/Sao_Paulo')
WORK_MIN_MINUTES = 3 * 60; WORK_MAX_MINUTES = 5 * 60
BREAK_MIN_MINUTES = 25; BREAK_MAX_MINUTES = 45
HORA_TARDE = 12; HORA_NOITE = 18

# --- LÓGICA DAS ESTRATÉGIAS ---
STRATEGY_MENOS_FICHAS_NEIGHBORS = { 2: [15, 19, 4, 21, 2, 25, 17, 34, 6], 7: [9, 22, 18, 29, 7, 28, 12, 35, 3], 12: [18, 29, 7, 28, 12, 35, 3, 26, 0], 17: [4, 21, 2, 25, 17, 34, 6, 27, 13], 22: [20, 14, 31, 9, 22, 18, 29, 7, 28], 27: [25, 17, 34, 6, 27, 13, 36, 11, 30], 32: [35, 3, 26, 0, 32, 15, 19, 4, 21], 11: [6, 27, 13, 36, 11, 30, 8, 23, 10], 16: [23, 10, 5, 24, 16, 33, 1, 20, 14], 25: [19, 4, 21, 2, 25, 17, 34, 6, 27], 34: [21, 2, 25, 17, 34, 6, 27, 13, 36]}
def get_winners_menos_fichas(trigger_number):
    winners = STRATEGY_MENOS_FICHAS_NEIGHBORS.get(trigger_number, [])
    if 0 not in winners: winners.append(0)
    return winners
ESTRATEGIAS = { "Estratégia Menos Fichas": { "triggers": list(STRATEGY_MENOS_FICHAS_NEIGHBORS.keys()), "filter": [], "get_winners": get_winners_menos_fichas }}

# --- LÓGICA DO BOT ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
ultimos_numeros_processados = []
numero_anterior = None
daily_play_history = []

daily_messages_sent = {}
def reset_daily_messages_tracker():
    global daily_messages_sent
    daily_messages_sent = {"tarde": False, "noite": False}
reset_daily_messages_tracker()

def initialize_score():
    score = {"last_check_date": datetime.now(FUSO_HORARIO_BRASIL).date()}
    for name in ESTRATEGIAS:
        score[name] = {"wins_sg": 0, "wins_g1": 0, "wins_g2": 0, "losses": 0}
    return score
daily_score = initialize_score()
active_strategy_state = {}
def reset_strategy_state():
    global active_strategy_state
    active_strategy_state = { "active": False, "strategy_name": "", "martingale_level": 0, "winning_numbers": [], "trigger_number": None, "play_message_ids": {} }
reset_strategy_state()
def configurar_driver():
    logging.info("Configurando o driver do Chrome...")
    chrome_options = webdriver.ChromeOptions(); chrome_options.add_argument("--headless"); chrome_options.add_argument("--no-sandbox"); chrome_options.add_argument("--disable-dev-shm-usage"); chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
    service = ChromeService(); driver = webdriver.Chrome(service=service, options=chrome_options); logging.info("Driver do Chrome configurado com sucesso.")
    return driver
def fazer_login(driver):
    try:
        logging.info("Iniciando processo de login..."); driver.get(URL_LOGIN); wait = WebDriverWait(driver, 20)
        email_input = wait.until(EC.presence_of_element_located((By.ID, "loginclienteform-email"))); email_input.send_keys(PADROES_USER)
        password_input = driver.find_element(By.ID, "senha"); password_input.send_keys(PADROES_PASS)
        login_button = driver.find_element(By.CSS_SELECTOR, "button[type='submit']"); login_button.click()
        wait.until(EC.url_to_be(URL_ROLETA)); logging.info("Login realizado com sucesso!")
        return True
    except Exception as e:
        logging.error(f"Falha no processo de login: {e}"); return False
def buscar_ultimo_numero(driver):
    global ultimos_numeros_processados, numero_anterior
    try:
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "dados")))
        js_script = "return Array.from(document.querySelectorAll('#dados div')).map(el => el.innerText.trim());"
        numeros_atuais_str = driver.execute_script(js_script); numeros_atuais_str = [num for num in numeros_atuais_str if num.isdigit()]
        if not numeros_atuais_str or numeros_atuais_str == ultimos_numeros_processados: return None
        novo_numero_str = numeros_atuais_str[-1]
        if len(ultimos_numeros_processados) > 0:
            numero_anterior_str = ultimos_numeros_processados[-1]
            if numero_anterior_str.isdigit(): numero_anterior = int(numero_anterior_str)
        ultimos_numeros_processados = numeros_atuais_str
        if novo_numero_str.isdigit():
            numero = int(novo_numero_str); logging.info(f"✅ Novo giro detectado: {numero} (Anterior: {numero_anterior})")
            return numero
        return None
    except (TimeoutException, NoSuchElementException): logging.warning("Elemento dos números não encontrado ou demorou para carregar."); return None
    except Exception as e: logging.error(f"Erro inesperado ao buscar número: {e}"); return None
def calculate_streaks_for_period(start_time, end_time):
    plays_in_period = [p['result'] for p in daily_play_history if start_time <= p['time'].time() < end_time]
    if not plays_in_period: return {"max_wins": 0, "max_losses": 0}
    max_wins, current_wins = 0, 0; max_losses, current_losses = 0, 0
    for result in plays_in_period:
        if result == 'win': current_wins += 1; current_losses = 0
        else: current_losses += 1; current_wins = 0
        if current_wins > max_wins: max_wins = current_wins
        if current_losses > max_losses: max_losses = current_losses
    return {"max_wins": max_wins, "max_losses": max_losses}
def format_score_message(title="📊 *Placar do Dia* 📊"):
    messages = [title]; overall_wins, overall_losses = 0, 0
    for name, score in daily_score.items():
        if name == "last_check_date": continue
        strategy_wins = score['wins_sg'] + score['wins_g1'] + score['wins_g2']; strategy_losses = score['losses']
        overall_wins += strategy_wins; overall_losses += strategy_losses
        total_plays = strategy_wins + strategy_losses
        accuracy = (strategy_wins / total_plays * 100) if total_plays > 0 else 0
        wins_str = f"SG: {score['wins_sg']} | G1: {score['wins_g1']} | G2: {score['wins_g2']}"
        messages.append(f"*{name}* (Assertividade: {accuracy:.1f}%)\n`   `✅ `{wins_str}`\n`   `❌ `{strategy_losses}`")
    total_overall_plays = overall_wins + overall_losses
    overall_accuracy = (overall_wins / total_overall_plays * 100) if total_overall_plays > 0 else 0
    messages.insert(1, f"📈 *Assertividade Geral: {overall_accuracy:.1f}%*")
    return "\n\n".join(messages)
async def send_message_to_all(bot, text, **kwargs):
    for chat_id in CHAT_IDS:
        try: await bot.send_message(chat_id=chat_id, text=text, **kwargs)
        except Exception as e: logging.error(f"Erro ao enviar mensagem para o chat_id {chat_id}: {e}")
async def send_and_track_play_message(bot, text, **kwargs):
    sent_messages = {}; 
    for chat_id in CHAT_IDS:
        try: message = await bot.send_message(chat_id=chat_id, text=text, **kwargs); sent_messages[chat_id] = message
        except Exception as e: logging.error(f"Erro ao enviar mensagem para o chat_id {chat_id}: {e}")
    for chat_id, message in sent_messages.items(): active_strategy_state["play_message_ids"][chat_id] = message.message_id
async def edit_play_messages(bot, new_text, **kwargs):
    for chat_id, message_id in active_strategy_state["play_message_ids"].items():
        try: await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=new_text, **kwargs)
        except Exception as e: logging.warning(f"Não foi possível editar a msg {message_id} do chat {chat_id}: {e}")
async def check_and_reset_daily_score(bot):
    global daily_score, daily_play_history
    today_br = datetime.now(FUSO_HORARIO_BRASIL).date()
    if daily_score.get("last_check_date") != today_br:
        logging.info("Novo dia detectado! Enviando relatório e resetando o placar.")
        yesterday_str = daily_score.get("last_check_date", "dia anterior").strftime('%d/%m/%Y')
        summary_title = f"📈 *Relatório Final do Dia {yesterday_str}* 📈"
        final_scores = format_score_message(title=summary_title)
        streaks = calculate_streaks_for_period(dt_time.min, dt_time.max)
        streak_report = (f"\n\n*Resumo do Dia:*\n"
                         f"Sequência Máx. de Vitórias: *{streaks['max_wins']}* ✅\n"
                         f"Sequência Máx. de Derrotas: *{streaks['max_losses']}* ❌")
        await send_message_to_all(bot, final_scores + streak_report, parse_mode=ParseMode.MARKDOWN)
        daily_score = initialize_score()
        daily_play_history.clear()
        reset_daily_messages_tracker()
        await send_message_to_all(bot, "☀️ Bom dia! Um novo dia de análises está começando. Boa sorte a todos!")
async def check_and_send_period_messages(bot):
    global daily_messages_sent
    now_br = datetime.now(FUSO_HORARIO_BRASIL)
    if now_br.hour >= HORA_TARDE and not daily_messages_sent.get("tarde"):
        logging.info("Enviando mensagem do período da tarde.")
        partial_title = "📊 *Placar Parcial (Manhã)* 📊"
        partial_score = format_score_message(title=partial_title)
        streaks = calculate_streaks_for_period(dt_time.min, dt_time(hour=11, minute=59, second=59))
        streak_report = (f"\n\nSequência Máx. de Vitórias: *{streaks['max_wins']}* ✅\n"
                         f"Sequência Máx. de Derrotas: *{streaks['max_losses']}* ❌")
        message = f"☀️ Período da tarde iniciando!\n\nNossa parcial da **MANHÃ** foi:\n{partial_score}{streak_report}"
        await send_message_to_all(bot, message, parse_mode=ParseMode.MARKDOWN)
        daily_messages_sent["tarde"] = True
    if now_br.hour >= HORA_NOITE and not daily_messages_sent.get("noite"):
        logging.info("Enviando mensagem do período da noite.")
        partial_title = "📊 *Placar Parcial (Tarde)* 📊"
        partial_score = format_score_message(title=partial_title)
        streaks = calculate_streaks_for_period(dt_time(hour=12), dt_time(hour=17, minute=59, second=59))
        streak_report = (f"\n\nSequência Máx. de Vitórias (Tarde): *{streaks['max_wins']}* ✅\n"
                         f"Sequência Máx. de Derrotas (Tarde): *{streaks['max_losses']}* ❌")
        message = f"🌙 Período da noite iniciando!\n\nNossa parcial da **TARDE** foi:\n{partial_score}{streak_report}"
        await send_message_to_all(bot, message, parse_mode=ParseMode.MARKDOWN)
        daily_messages_sent["noite"] = True

def build_base_signal_message():
    name = active_strategy_state['strategy_name']; numero = active_strategy_state['trigger_number']; winning_numbers = active_strategy_state['winning_numbers']
    return (f"🎯 *Gatilho Encontrado!* 🎯\n\n🎲 *Estratégia: {name}*\n🔢 *Número Gatilho: {numero}*\n\n💰 *Apostar em:*\n`{', '.join(map(str, sorted(winning_numbers)))}`\n\n[🔗 Fazer Aposta]({URL_APOSTA})")
async def handle_win(bot, final_number):
    global daily_play_history
    # ### CORREÇÃO APLICADA AQUI ###
    daily_play_history.append({'time': datetime.now(FUSO_HORARIO_BRASIL), 'result': 'win'})
    strategy_name = active_strategy_state["strategy_name"]; win_level = active_strategy_state["martingale_level"]
    if win_level == 0: daily_score[strategy_name]["wins_sg"] += 1; win_type_message = "Vitória sem Gale!"
    else: daily_score[strategy_name][f"wins_g{win_level}"] += 1; win_type_message = f"Vitória no {win_level}º Martingale"
    mensagem_final = (f"✅ *VITÓRIA!*\n\n*{win_type_message}*\n_Estratégia: {strategy_name}_\nGatilho: *{active_strategy_state['trigger_number']}* | Saiu: *{final_number}*\n\n{format_score_message()}")
    await edit_play_messages(bot, mensagem_final, parse_mode=ParseMode.MARKDOWN); reset_strategy_state()
async def handle_loss(bot, final_number):
    global daily_play_history
    # ### CORREÇÃO APLICADA AQUI ###
    daily_play_history.append({'time': datetime.now(FUSO_HORARIO_BRASIL), 'result': 'loss'})
    strategy_name = active_strategy_state["strategy_name"]; daily_score[strategy_name]["losses"] += 1
    mensagem_final = (f"❌ *LOSS!*\n\n_Estratégia: {strategy_name}_\nGatilho: *{active_strategy_state['trigger_number']}* | Saiu: *{final_number}*\n\n{format_score_message()}")
    await edit_play_messages(bot, mensagem_final, parse_mode=ParseMode.MARKDOWN); reset_strategy_state()
async def handle_martingale(bot, current_number):
    level = active_strategy_state["martingale_level"]; base_message = build_base_signal_message()
    mensagem_editada = (f"{base_message}\n\n------------------------------------\n⏳ *Análise: Entrar no {level}º Martingale...*\nO número *{current_number}* não pagou.")
    await edit_play_messages(bot, mensagem_editada, parse_mode=ParseMode.MARKDOWN)
async def handle_active_strategy(bot, numero):
    if numero in active_strategy_state["winning_numbers"]: await handle_win(bot, numero)
    else:
        active_strategy_state["martingale_level"] += 1
        if active_strategy_state["martingale_level"] <= MAX_MARTINGALES: await handle_martingale(bot, numero)
        else: await handle_loss(bot, numero)
async def check_for_new_triggers(bot, numero):
    for name, details in ESTRATEGIAS.items():
        if numero in details["triggers"]:
            if details.get("filter") and numero_anterior is not None and numero_anterior in details["filter"]:
                logging.info(f"Gatilho {numero} ignorado para '{name}' devido ao filtro com número anterior {numero_anterior}."); continue
            winning_numbers = details["get_winners"](numero)
            active_strategy_state.update({ "active": True, "strategy_name": name, "winning_numbers": winning_numbers, "trigger_number": numero })
            mensagem = f"{build_base_signal_message()}\n\n---\n{format_score_message()}"
            await send_and_track_play_message(bot, mensagem, parse_mode=ParseMode.MARKDOWN); break
async def processar_numero(bot, numero):
    if numero is None: return
    await check_and_reset_daily_score(bot)
    if active_strategy_state["active"]: await handle_active_strategy(bot, numero)
    else: await check_for_new_triggers(bot, numero)
async def work_session(bot):
    work_duration_minutes = random.randint(WORK_MIN_MINUTES, WORK_MAX_MINUTES)
    session_end_time = datetime.now(FUSO_HORARIO_BRASIL) + timedelta(minutes=work_duration_minutes)
    logging.info(f"Iniciando uma nova sessão de trabalho que durará {work_duration_minutes // 60}h e {work_duration_minutes % 60}min.")
    await send_message_to_all(bot, f"Monitoramento de ciclos previsto para durar *{work_duration_minutes // 60}h e {work_duration_minutes % 60}min*.", parse_mode=ParseMode.MARKDOWN)
    driver = None
    try:
        driver = configurar_driver()
        if not fazer_login(driver): raise Exception("O login falhou.")
        while datetime.now(FUSO_HORARIO_BRASIL) < session_end_time:
            await check_and_send_period_messages(bot)
            numero = buscar_ultimo_numero(driver)
            await processar_numero(bot, numero)
            await asyncio.sleep(INTERVALO_VERIFICACAO)
        logging.info("Sessão de trabalho concluída. Preparando para a pausa.")
    except Exception as e:
        logging.error(f"Um erro crítico ocorreu na sessão de trabalho: {e}")
    finally:
        if driver: driver.quit(); logging.info("Driver do Selenium encerrado para a pausa.")

async def supervisor():
    bot = telegram.Bot(token=TOKEN_BOT)
    try: await send_message_to_all(bot, f"🤖 Monitoramento Roleta Online!\nIniciando gerenciamento de ciclos.")
    except Exception as e: logging.critical(f"Não foi possível conectar ao Telegram para a mensagem inicial: {e}")
    while True:
        try:
            await work_session(bot)
            break_duration_minutes = random.randint(BREAK_MIN_MINUTES, BREAK_MAX_MINUTES)
            logging.info(f"Iniciando pausa de {break_duration_minutes} minutos.")
            await send_message_to_all(bot, f"⏸️ Pausa programada para manutenção das estratégias.\nDuração: *{break_duration_minutes} minutos*.", parse_mode=ParseMode.MARKDOWN)
            await asyncio.sleep(break_duration_minutes * 60)
            logging.info("Pausa finalizada. Iniciando nova sessão de trabalho.")
            await send_message_to_all(bot, f"✅ Estratégias atualizadas, sistema operante novamente!")
        except Exception as e:
            logging.critical(f"O processo supervisor falhou: {e}. Reiniciando o ciclo em 60 segundos."); await asyncio.sleep(60)

if __name__ == '__main__':
    try: asyncio.run(supervisor())
    except KeyboardInterrupt: logging.info("Bot encerrado manualmente.")
    except Exception as e: logging.critical(f"Erro fatal no supervisor: {e}")
