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

# --- LÓGICA DAS ESTRATÉGIAS ---
ROULETTE_WHEEL = [0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23, 10, 5, 24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26]

def get_winners_72(trigger_number):
    """
    Calcula os números da aposta para a Estratégia do 72: o 0, o gatilho e seus 8 vizinhos.
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

def get_winners_p2(trigger_number):
    """
    Retorna a lista fixa de números para a Estratégia P2.
    """
    return [0, 1, 2, 5, 6, 8, 9, 10, 12, 13, 14, 16, 17, 19, 20, 23, 24, 26, 27, 28, 30, 31, 32, 34, 35]

ESTRATEGIAS = {
    "Estratégia do 72": {
        "triggers": [2, 7, 12, 17, 22, 27, 32, 11, 16, 25, 34],
        "filter": [],  # Sem filtro avançado para esta estratégia
        "get_winners": get_winners_72
    },
    "Estratégia P2 - Roleta": {
        "triggers": [3, 4, 7, 11, 15, 18, 21, 22, 25, 29, 33, 36, 26, 27, 28, 30, 31, 32, 34, 35],
        "filter": [], # Filtro removido conforme solicitado
        "get_winners": get_winners_p2
    }
}

# --- LÓGICA DO BOT ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
ultimo_numero_processado = None
numero_anterior = None # Para a filtragem avançada

# --- PLACAR DIÁRIO E ESTADO DA ESTRATÉGIA ---
def initialize_score():
    score = {"last_check_date": date.today()}
    for name in ESTRATEGIAS:
        score[name] = {"wins": 0, "losses": 0}
    return score

daily_score = initialize_score()

active_strategy_state = {
    "active": False,
    "strategy_name": "",
    "martingale_level": 0,
    "winning_numbers": [],
    "trigger_number": None,
    "trigger_message_id": None,
    "martingale_message_ids": []
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
    """Busca o número mais recente da roleta de forma otimizada."""
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
        else:
            return None
    except Exception:
        logging.warning("Não foi possível buscar o último número. A página pode estar carregando.")
        return None

def format_score_message():
    """Formata a mensagem do placar para todas as estratégias."""
    messages = ["*Placar do Dia:*"]
    for name, score in daily_score.items():
        if name != "last_check_date":
            messages.append(f"*{name}*: ✅ {score['wins']} x ❌ {score['losses']}")
    return "\n".join(messages)

async def apagar_mensagens_da_jogada(bot):
    """Apaga a mensagem de gatilho e as de martingale."""
    global active_strategy_state
    messages_to_delete = active_strategy_state.get("martingale_message_ids", [])
    if active_strategy_state.get("trigger_message_id"):
        messages_to_delete.append(active_strategy_state["trigger_message_id"])
    for msg_id in messages_to_delete:
        try:
            await bot.delete_message(chat_id=CHAT_ID, message_id=msg_id)
        except Exception as e:
            logging.warning(f"Não foi possível apagar a mensagem {msg_id}. Erro: {e}")

async def apagar_mensagens_de_martingale(bot):
    """Apaga apenas as mensagens de martingale."""
    global active_strategy_state
    for msg_id in active_strategy_state["martingale_message_ids"]:
        try:
            await bot.delete_message(chat_id=CHAT_ID, message_id=msg_id)
        except Exception as e:
            logging.warning(f"Não foi possível apagar a mensagem {msg_id}. Erro: {e}")
    active_strategy_state["martingale_message_ids"] = []

async def check_and_reset_daily_score(bot):
    """Verifica se o dia mudou e reseta o placar se necessário."""
    global daily_score
    today = date.today()
    if daily_score["last_check_date"] != today:
        logging.info(f"Novo dia detectado! Resetando o placar.")
        
        summary_title = f"Resumo do dia {daily_score['last_check_date'].strftime('%d/%m/%Y')}:"
        final_scores = format_score_message().replace("*Placar do Dia:*", "*Placar Final:*")
        
        await bot.send_message(chat_id=CHAT_ID, text=f"{summary_title}\n{final_scores}", parse_mode=ParseMode.MARKDOWN)

        daily_score = initialize_score()
        await bot.send_message(chat_id=CHAT_ID, text="Placar diário zerado. Bom dia e boas apostas!")

async def processar_numero(bot, numero):
    """Verifica o número, gerencia o estado da estratégia e envia alertas."""
    global active_strategy_state, daily_score, numero_anterior

    if numero is None:
        return

    await check_and_reset_daily_score(bot)
    placar_formatado = format_score_message()

    # Se uma estratégia já está ativa, processa o resultado
    if active_strategy_state["active"]:
        strategy_name = active_strategy_state["strategy_name"]
        is_win = numero in active_strategy_state["winning_numbers"]
        
        if is_win:
            await apagar_mensagens_da_jogada(bot)
            daily_score[strategy_name]["wins"] += 1
            placar_final_formatado = format_score_message()
            mensagem = f"✅ Paga Roleta ✅\n\n*Estratégia: {strategy_name}*\nGatilho: *{active_strategy_state['trigger_number']}* | Saiu: *{numero}*\n\n{placar_final_formatado}"
            await bot.send_message(chat_id=CHAT_ID, text=mensagem, parse_mode=ParseMode.MARKDOWN)
            active_strategy_state = {"active": False, "trigger_message_id": None, "martingale_message_ids": []}
        else:
            await apagar_mensagens_de_martingale(bot)
            active_strategy_state["martingale_level"] += 1
            level = active_strategy_state["martingale_level"]
            
            if level <= 2:
                mensagem = (f"❌ Roleta Safada ❌\n\n*Estratégia: {strategy_name}*\n"
                            f"Gatilho: *{active_strategy_state['trigger_number']}* | Saiu: *{numero}*\n\n"
                            f"Entrar no *{level}º Martingale*\n\n{placar_formatado}")
                sent_message = await bot.send_message(chat_id=CHAT_ID, text=mensagem, parse_mode=ParseMode.MARKDOWN)
                active_strategy_state["martingale_message_ids"].append(sent_message.message_id)
            else:
                await apagar_mensagens_da_jogada(bot)
                daily_score[strategy_name]["losses"] += 1
                placar_final_formatado = format_score_message()
                mensagem = (f"❌ Roleta Safada ❌\n\n*Estratégia: {strategy_name}*\n"
                            f"Loss final no 2º Martingale.\n"
                            f"Gatilho: *{active_strategy_state['trigger_number']}* | Saiu: *{numero}*\n\n{placar_final_formatado}")
                await bot.send_message(chat_id=CHAT_ID, text=mensagem, parse_mode=ParseMode.MARKDOWN)
                active_strategy_state = {"active": False, "trigger_message_id": None, "martingale_message_ids": []}
    # Se nenhuma estratégia está ativa, procura por um novo gatilho
    else:
        for name, details in ESTRATEGIAS.items():
            if numero in details["triggers"]:
                # Verifica a filtragem avançada
                if details["filter"] and numero_anterior in details["filter"]:
                    logging.info(f"Gatilho {numero} para '{name}' ignorado. Número anterior ({numero_anterior}) está no filtro.")
                    continue

                winning_numbers = details["get_winners"](numero)
                mensagem = (f"🎯 Gatilho Encontrado! 🎯\n\n"
                            f"Estratégia: *{name}*\n"
                            f"Número Gatilho: *{numero}*\n\n"
                            f"Apostar em: `{', '.join(map(str, sorted(winning_numbers)))}`\n\n"
                            f"{placar_formatado}\n\n"
                            f"[Fazer Aposta]({URL_APOSTA})")
                sent_message = await bot.send_message(chat_id=CHAT_ID, text=mensagem, parse_mode=ParseMode.MARKDOWN)
                
                active_strategy_state = {
                    "active": True, "strategy_name": name, "martingale_level": 0,
                    "winning_numbers": winning_numbers, "trigger_number": numero,
                    "trigger_message_id": sent_message.message_id,
                    "martingale_message_ids": []
                }
                break # Sai do loop para não ativar outra estratégia ao mesmo tempo

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

