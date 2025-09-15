# -*- coding: utf-8 -*-

import os
import time
import logging
import asyncio
import telegram
import json
import random
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from datetime import date, datetime, timedelta

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
HISTORICO_FILE = 'historico.json'

# --- TIMER DE PAUSA ALEATÓRIO ---
MIN_EXECUCAO_HORAS = 3
MAX_EXECUCAO_HORAS = 6
MIN_PAUSA_MINUTOS = 25
MAX_PAUSA_MINUTOS = 45

# --- ESTRATÉGIAS ---
ROULETTE_WHEEL = [0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27,
                  13, 36, 11, 30, 8, 23, 10, 5, 24, 16, 33, 1,
                  20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26]

def get_winners_72(trigger_number):
    try:
        index = ROULETTE_WHEEL.index(trigger_number)
        total_numbers = len(ROULETTE_WHEEL)
        winners = {trigger_number}
        for i in range(1, 5):
            winners.add(ROULETTE_WHEEL[(index - i + total_numbers) % total_numbers])
            winners.add(ROULETTE_WHEEL[(index + i) % total_numbers])
        winners.add(0)
        return list(winners)
    except ValueError:
        return [0, trigger_number]

def get_winners_p2(trigger_number):
    return [0, 1, 2, 5, 6, 8, 9, 10, 12, 13, 14, 16, 17, 19,
            20, 23, 24, 26, 27, 28, 30, 31, 32, 34, 35]

ESTRATEGIAS = {
    "Estratégia menos fichas": {"triggers": [2, 12, 17, 16],
                                "filter": [], "get_winners": get_winners_72},
    "Estratégia 95% - Roleta": {"triggers": [3, 4, 7, 11, 15, 18, 21,
                                             22, 25, 29, 33, 36,
                                             26, 27, 28, 30, 31, 32, 34, 35],
                                "filter": [], "get_winners": get_winners_p2}
}

# --- LÓGICA DO BOT ---
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

ultimo_numero_processado = None
numero_anterior = None

# --- BANCO DE DADOS ---
def load_history():
    if os.path.exists(HISTORICO_FILE):
        try:
            with open(HISTORICO_FILE, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError:
            return {}
    return {}

def save_history(history):
    with open(HISTORICO_FILE, 'w') as f:
        json.dump(history, f, indent=4)

# --- PLACAR ---
def initialize_score():
    score = {"last_check_date": date.today().isoformat()}
    for name in ESTRATEGIAS:
        score[name] = {"wins_sg": 0, "wins_g1": 0, "wins_g2": 0, "losses": 0}
    return score

daily_score = initialize_score()
active_strategy_state = {"active": False, "messages": {}}

# --- NOTIFICAÇÕES DE SAÚDE ---
last_good_morning = None
last_good_night = None

async def check_health_messages(bot):
    global last_good_morning, last_good_night
    now = datetime.now()

    if now.hour < 12 and (last_good_morning is None or last_good_morning != date.today()):
        await send_message_to_all(bot, "🌞 Bom dia! Estou online e a postos.")
        last_good_morning = date.today()

    if now.hour >= 20 and (last_good_night is None or last_good_night != date.today()):
        await send_message_to_all(bot, "🌙 Boa noite! O bot segue em funcionamento.")
        last_good_night = date.today()

# --- SELENIUM ---
def configurar_driver():
    logging.info("Configurando o driver do Chrome...")
    chrome_options = webdriver.ChromeOptions()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
    service = ChromeService()
    driver = webdriver.Chrome(service=service, options=chrome_options)
    logging.info("Driver do Chrome configurado com sucesso.")
    return driver

def fazer_login(driver):
    try:
        logging.info("Iniciando processo de login...")
        driver.get(URL_LOGIN)
        wait = WebDriverWait(driver, 20)
        email_input = wait.until(
            EC.presence_of_element_located((By.ID, "loginclienteform-email"))
        )
        email_input.send_keys(PADROES_USER)
        password_input = driver.find_element(By.ID, "senha")
        password_input.send_keys(PADROES_PASS)
        driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
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
        container_recente = wait.until(
            EC.presence_of_element_located((By.ID, "dados"))
        )
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
        logging.warning("Não foi possível buscar o último número.")
        return None

# --- MENSAGENS ---
def format_score_message(score_data, title="📊 *Placar do Dia* 📊"):
    messages = [title]
    for name, score in score_data.items():
        if name != "last_check_date":
            total_wins = score['wins_sg'] + score['wins_g1'] + score['wins_g2']
            total_plays = total_wins + score['losses']
            win_rate = (total_wins / total_plays * 100) if total_plays > 0 else 0

            wins_str = f"SG: {score['wins_sg']} | G1: {score['wins_g1']} | G2: {score['wins_g2']}"
            messages.append(
                f"*{name}*:\n`    `✅ `{wins_str}` (`{win_rate:.1f}%`)\n`    `❌ `{score['losses']}`"
            )
    return "\n\n".join(messages)

async def send_message_to_all(bot, text, **kwargs):
    for chat_id in CHAT_IDS:
        try:
            await bot.send_message(chat_id=chat_id, text=text, **kwargs)
        except Exception as e:
            logging.error(f"Erro ao enviar mensagem para o chat_id {chat_id}: {e}")

# --- COMANDO /relatorio ---
async def relatorio_command(update, context):
    try:
        args = context.args
        if not args:
            await update.message.reply_text(
                "Por favor, especifique o dia. Ex: `/relatorio ontem` ou `/relatorio 2025-09-14`",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        target_day_str = args[0].lower()
        history = load_history()
        target_date = None

        if target_day_str == "ontem":
            target_date = (date.today() - timedelta(days=1)).isoformat()
        else:
            try:
                datetime.strptime(target_day_str, "%Y-%m-%d")
                target_date = target_day_str
            except ValueError:
                await update.message.reply_text(
                    "Formato de data inválido. Use AAAA-MM-DD.", parse_mode=ParseMode.MARKDOWN
                )
                return

        if target_date in history:
            score_data = history[target_date]
            report_title = f"📜 Relatório do dia {date.fromisoformat(target_date).strftime('%d/%m/%Y')}:"
            report_message = format_score_message(score_data, title=report_title)
            await update.message.reply_text(report_message, parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text(f"Nenhum dado encontrado para o dia {target_date}.", parse_mode=ParseMode.MARKDOWN)

    except Exception as e:
        logging.error(f"Erro no comando /relatorio: {e}")
        await update.message.reply_text("⚠️ Ocorreu um erro ao processar o relatório.", parse_mode=ParseMode.MARKDOWN)

# --- RESET DO PLACAR ---
async def check_and_reset_daily_score(bot):
    global daily_score
    today_str = date.today().isoformat()
    if daily_score["last_check_date"] != today_str:
        logging.info(f"Novo dia detectado! Salvando placar e resetando.")
        history = load_history()
        history[daily_score["last_check_date"]] = daily_score
        save_history(history)
        summary_title = f"Resumo do dia {date.fromisoformat(daily_score['last_check_date']).strftime('%d/%m/%Y')}:"
        final_scores = format_score_message(daily_score, title="*Placar Final:*")
        await send_message_to_all(bot, f"{summary_title}\n{final_scores}", parse_mode=ParseMode.MARKDOWN)
        daily_score = initialize_score()
        await send_message_to_all(bot, "🌞 Placar diário zerado. Bom dia e boas apostas!")

# --- PROCESSAR NÚMERO ---
async def processar_numero(bot, numero):
    if numero is None:
        return
    await check_and_reset_daily_score(bot)
    await check_health_messages(bot)

# --- LOOP PRINCIPAL ---
async def monitor_loop(bot):
    while True:
        tempo_execucao_segundos = random.randint(MIN_EXECUCAO_HORAS * 3600,
                                                 MAX_EXECUCAO_HORAS * 3600)
        tempo_pausa_minutos = random.randint(MIN_PAUSA_MINUTOS, MAX_PAUSA_MINUTOS)
        tempo_pausa_segundos = tempo_pausa_minutos * 60

        driver = None
        start_time = time.time()
        try:
            driver = configurar_driver()
            if not fazer_login(driver):
                await send_message_to_all(bot, "❌ Falha crítica no login. Tentando novamente em 1 minuto.")
                await asyncio.sleep(60)
                continue  # volta ao início sem pausa longa

            await send_message_to_all(bot, "✅ Bot conectado e monitorando! ⚠️ Reinicialização detectada.")

            while time.time() - start_time < tempo_execucao_segundos:
                numero = buscar_ultimo_numero(driver)
                await processar_numero(bot, numero)
                await asyncio.sleep(INTERVALO_VERIFICACAO)

            logging.info(f"Atingido o tempo de execução. Iniciando pausa de {tempo_pausa_minutos} minutos.")
            await send_message_to_all(bot, f"⏳ Pausa programada. Retorno em {tempo_pausa_minutos} minutos.")

        except Exception as e:
            logging.error(f"Erro no loop de monitoramento: {e}")
            await send_message_to_all(bot, f"🚨 Erro crítico: {e}. Reiniciando em 1 minuto.")
            await asyncio.sleep(60)

        finally:
            if driver:
                driver.quit()
                logging.info("Driver do Selenium encerrado.")

        # Só pausa após o ciclo
        await asyncio.sleep(tempo_pausa_segundos)
        await send_message_to_all(bot, "⚙️ Pausa concluída. Retomando monitoramento.")

# --- MAIN ---
async def main():
    global daily_score
    history = load_history()
    today_str = date.today().isoformat()
    if today_str in history:
        daily_score = history[today_str]
        logging.info("Placar de hoje carregado do histórico.")
    else:
        daily_score = initialize_score()

    application = Application.builder().token(TOKEN_BOT).build()
    application.add_handler(CommandHandler("relatorio", relatorio_command))

    await application.initialize()
    asyncio.create_task(monitor_loop(application.bot))
    await application.run_polling()
    await application.shutdown()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bot encerrado pelo usuário.")
    except Exception as e:
        logging.error(f"O processo principal falhou completamente: {e}.")
