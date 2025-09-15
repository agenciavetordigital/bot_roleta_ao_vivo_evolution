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
from datetime import date

# --- CONFIGURAÇÕES ESSENCIAIS ---
TOKEN_BOT = os.environ.get('TOKEN_BOT')
CHAT_ID = os.environ.get('CHAT_ID')
PADROES_USER = os.environ.get('PADROES_USER')
PADROES_PASS = os.environ.get('PADROES_PASS')
URL_APOSTA = os.environ.get('URL_APOSTA')

if not all([TOKEN_BOT, CHAT_ID, PADROES_USER, PADROES_PASS, URL_APOSTA]):
    logging.critical("Todas as variáveis de ambiente (TOKEN_BOT, CHAT_ID, PADROES_USER, PADROES_PASS, URL_APOSTA) devem ser definidas!")
    exit()

URL_ROLETA = 'https://jv.padroesdecassino.com.br/sistema/roletabrasileira'
URL_LOGIN = 'https://jv.padroesdecassino.com.br/sistema/login'
INTERVALO_VERIFICACAO = 3

# --- LÓGICA DA ESTRATÉGIA ---
ROULETTE_WHEEL = [0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23, 10, 5, 24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26]

def get_winning_numbers(trigger_number):
    """
    Calcula os números da aposta: o 0, o gatilho e seus 8 vizinhos (4 para cada lado).
    """
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

ESTRATEGIAS = {
    "Estratégia do 72": [2, 7, 12, 17, 22, 27, 32, 11, 16, 25, 34],
}

# --- LÓGICA DO BOT ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
ultimo_numero_encontrado = None

# --- PLACAR DIÁRIO E ESTADO DA ESTRATÉGIA ---
daily_score = {
    "wins": 0,
    "losses": 0,
    "last_check_date": date.today()
}
active_strategy_state = {
    "active": False,
    "strategy_name": "",
    "martingale_level": 0,
    "winning_numbers": [],
    "trigger_number": None,
    "message_ids": [] # NOVO: Para guardar os IDs das mensagens a apagar
}

def configurar_driver():
    """Configura e retorna uma instância do driver do Chrome."""
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
    """Navega para a página de login e efetua o login do usuário."""
    try:
        logging.info("Iniciando processo de login no Padrões de Cassino...")
        driver.get(URL_LOGIN)
        wait = WebDriverWait(driver, 20)

        email_input = wait.until(EC.presence_of_element_located((By.ID, "loginclienteform-email")))
        email_input.send_keys(PADROES_USER)
        logging.info("E-mail preenchido.")

        password_input = driver.find_element(By.ID, "senha")
        password_input.send_keys(PADROES_PASS)
        logging.info("Senha preenchida.")
        
        login_button = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
        login_button.click()
        logging.info("Botão de login clicado.")
        
        wait.until(EC.url_to_be(URL_ROLETA))
        logging.info("Login realizado com sucesso! Redirecionado para a página da roleta.")
        return True
    except Exception as e:
        logging.error(f"Falha no processo de login: {e}")
        return False

def buscar_ultimo_numero(driver):
    """Busca o número mais recente da roleta de forma otimizada."""
    global ultimo_numero_encontrado
    try:
        wait = WebDriverWait(driver, 10)
        container_recente = wait.until(EC.presence_of_element_located((By.ID, "dados")))
        ultimo_numero_div = container_recente.find_element(By.CSS_SELECTOR, "div:last-child")
        numero_str = ultimo_numero_div.text.strip()
        
        if numero_str == ultimo_numero_encontrado:
            return None 

        ultimo_numero_encontrado = numero_str
        
        if numero_str.isdigit():
            numero = int(numero_str)
            logging.info(f"✅ Novo número encontrado: {numero}")
            return numero
        else:
            logging.warning(f"Texto encontrado não é um número válido: '{numero_str}'")
            return None
    except Exception:
        logging.warning("Não foi possível buscar o último número. A página pode estar carregando.")
        return None

async def enviar_e_registrar_alerta(bot, mensagem):
    """Envia uma mensagem e guarda o seu ID."""
    global active_strategy_state
    try:
        sent_message = await bot.send_message(chat_id=CHAT_ID, text=mensagem, parse_mode=ParseMode.MARKDOWN)
        active_strategy_state["message_ids"].append(sent_message.message_id)
        logging.info("Alerta enviado e ID registrado com sucesso!")
    except Exception as e:
        logging.error(f"Erro ao enviar mensagem para o Telegram: {e}")

async def apagar_mensagens_anteriores(bot):
    """Apaga todas as mensagens guardadas na memória da estratégia."""
    global active_strategy_state
    logging.info(f"Apagando {len(active_strategy_state['message_ids'])} mensagens anteriores...")
    for msg_id in active_strategy_state["message_ids"]:
        try:
            await bot.delete_message(chat_id=CHAT_ID, message_id=msg_id)
        except Exception as e:
            logging.warning(f"Não foi possível apagar a mensagem {msg_id}. Pode já ter sido apagada. Erro: {e}")
    active_strategy_state["message_ids"] = []

async def check_and_reset_daily_score(bot):
    """Verifica se o dia mudou e reseta o placar se necessário."""
    global daily_score
    today = date.today()
    if daily_score["last_check_date"] != today:
        logging.info(f"Novo dia detectado! Resetando o placar de {daily_score['last_check_date']} para {today}.")
        
        yesterday_score_msg = (f"Resumo do dia {daily_score['last_check_date'].strftime('%d/%m/%Y')}:\n"
                               f"Placar Final: ✅ {daily_score['wins']} x ❌ {daily_score['losses']}")
        await bot.send_message(chat_id=CHAT_ID, text=yesterday_score_msg) # Envia sem registrar para não ser apagada

        daily_score = {"wins": 0, "losses": 0, "last_check_date": today}
        await bot.send_message(chat_id=CHAT_ID, text="Placar diário zerado. Bom dia e boas apostas!")

async def processar_numero(bot, numero):
    """Verifica o número, gerencia o estado da estratégia e envia alertas."""
    global active_strategy_state, daily_score

    if numero is None:
        return

    await check_and_reset_daily_score(bot)
    placar_atual = f"Placar do Dia: ✅ {daily_score['wins']} x ❌ {daily_score['losses']}"

    if active_strategy_state["active"]:
        is_win = numero in active_strategy_state["winning_numbers"]
        
        await apagar_mensagens_anteriores(bot) # Limpa o chat antes de enviar o resultado

        if is_win:
            daily_score["wins"] += 1
            placar_final = f"Placar do Dia: ✅ {daily_score['wins']} x ❌ {daily_score['losses']}"
            mensagem = f"✅ Paga Roleta ✅\n\nGatilho: *{active_strategy_state['trigger_number']}* | Saiu: *{numero}*\n\n{placar_final}"
            await bot.send_message(chat_id=CHAT_ID, text=mensagem, parse_mode=ParseMode.MARKDOWN)
            active_strategy_state = {"active": False, "message_ids": []}
        else:
            active_strategy_state["martingale_level"] += 1
            level = active_strategy_state["martingale_level"]
            
            if level <= 2:
                mensagem = (f"❌ Roleta Safada ❌\n\n"
                            f"Gatilho: *{active_strategy_state['trigger_number']}* | Saiu: *{numero}*\n\n"
                            f"Entrar no *{level}º Martingale*\n\n{placar_atual}")
                await enviar_e_registrar_alerta(bot, mensagem) # Re-envia e guarda o ID
            else:
                daily_score["losses"] += 1
                placar_final = f"Placar do Dia: ✅ {daily_score['wins']} x ❌ {daily_score['losses']}"
                mensagem = (f"❌ Roleta Safada ❌\n\n"
                            f"Loss final no 2º Martingale.\n"
                            f"Gatilho: *{active_strategy_state['trigger_number']}* | Saiu: *{numero}*\n\n{placar_final}")
                await bot.send_message(chat_id=CHAT_ID, text=mensagem, parse_mode=ParseMode.MARKDOWN)
                active_strategy_state = {"active": False, "message_ids": []}
    else:
        for name, triggers in ESTRATEGIAS.items():
            if numero in triggers:
                winning_numbers = get_winning_numbers(numero)
                active_strategy_state = {
                    "active": True, "strategy_name": name, "martingale_level": 0,
                    "winning_numbers": winning_numbers, "trigger_number": numero,
                    "message_ids": [] # Zera a lista de mensagens
                }
                mensagem = (f"🎯 Gatilho Encontrado! 🎯\n\n"
                            f"Estratégia: *{name}*\n"
                            f"Número Gatilho: *{numero}*\n\n"
                            f"Apostar em: `{', '.join(map(str, sorted(winning_numbers)))}`\n\n"
                            f"{placar_atual}\n\n"
                            f"[Fazer Aposta]({URL_APOSTA})")
                await enviar_e_registrar_alerta(bot, mensagem)
                break

async def main():
    """Função principal."""
    bot = None
    try:
        bot = telegram.Bot(token=TOKEN_BOT)
        info_bot = await bot.get_me()
        logging.info(f"Bot '{info_bot.first_name}' (Padrões de Cassino) inicializado com sucesso!")
        await bot.send_message(chat_id=CHAT_ID, text=f"✅ Bot '{info_bot.first_name}' (Padrões de Cassino) conectado e monitorando!")
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
        if bot:
            await bot.send_message(chat_id=CHAT_ID, text=f"❌ Ocorreu um erro crítico no bot: {str(e)}")
    finally:
        if driver:
            driver.quit()
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

