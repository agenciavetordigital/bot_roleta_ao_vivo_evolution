# -*- coding: utf-8 -*-

import os
import time
import logging
import asyncio
import telegram
import json
from telegram.constants import ParseMode
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# --- CONFIGURAÇÕES ESSENCIAIS ---
TOKEN_BOT = os.environ.get('TOKEN_BOT')
CHAT_ID = os.environ.get('CHAT_ID')
TIPMINER_USER = os.environ.get('TIPMINER_USER')
TIPMINER_PASS = os.environ.get('TIPMINER_PASS')

API_URL = "https://www.tipminer.com/api/v3/history/roulette/0194b473-1788-70dd-84a9-f1ddd4f00678?limit=200&subject=filter&timezone=America%2FSao_Paulo"
URL_LOGIN = 'https://www.tipminer.com/br/login'

if not all([TOKEN_BOT, CHAT_ID, TIPMINER_USER, TIPMINER_PASS]):
    logging.critical("Todas as variáveis de ambiente (TOKEN_BOT, CHAT_ID, TIPMINER_USER, TIPMINER_PASS) devem ser definidas!")
    exit()

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
    """Configura e retorna uma instância do driver do Chrome."""
    logging.info("Configurando o driver do Chrome...")
    chrome_options = webdriver.ChromeOptions()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    
    caminho_driver = "/usr/bin/chromedriver"
    service = ChromeService(executable_path=caminho_driver)
    driver = webdriver.Chrome(service=service, options=chrome_options)
    logging.info("Driver do Chrome configurado com sucesso.")
    return driver

def fazer_login(driver):
    """Navega para a página de login e efetua o login do usuário."""
    try:
        logging.info("Iniciando processo de login no Tipminer...")
        driver.get(URL_LOGIN)
        wait = WebDriverWait(driver, 20)

        email_input = wait.until(EC.presence_of_element_located((By.NAME, "email")))
        email_input.send_keys(TIPMINER_USER)
        
        password_input = driver.find_element(By.NAME, "password")
        password_input.send_keys(TIPMINER_PASS)
        
        login_button = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
        login_button.click()
        
        # Espera por um elemento da página principal para confirmar o login
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "nav[aria-label='Main']")))
        logging.info("Login realizado com sucesso!")
        return True
    except Exception as e:
        logging.error(f"Falha no processo de login: {e}")
        return False

async def buscar_ultimo_numero(driver):
    """Usa a sessão logada do Selenium para buscar os dados da API."""
    global ultimo_id_rodada
    try:
        # Usa JavaScript para fazer a requisição à API dentro do navegador já logado
        script_fetch = f"""
            return fetch('{API_URL}')
                .then(response => response.json())
                .catch(error => ({{'error': error.toString()}}));
        """
        data = driver.execute_script(script_fetch)

        if 'error' in data or not data or not isinstance(data, list) or len(data) == 0:
            logging.warning(f"API retornou uma resposta vazia ou com erro: {data.get('error', 'Formato inesperado')}")
            return None

        ultima_rodada = data[0]
        id_rodada_atual = ultima_rodada.get("id")

        if id_rodada_atual == ultimo_id_rodada:
            return None

        ultimo_id_rodada = id_rodada_atual
        numero_str = ultima_rodada.get("result")
        
        if numero_str is not None and numero_str.isdigit():
            numero = int(numero_str)
            logging.info(f"Número válido encontrado na API: {numero}")
            return numero
        else:
            logging.warning(f"Resultado inválido ou não numérico na API: '{numero_str}'")
            return None
    except Exception as e:
        logging.error(f"Erro ao buscar dados da API via Selenium: {e}")
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
        logging.info(f"Bot '{info_bot.first_name}' (Final) inicializado com sucesso!")
        await enviar_alerta(bot, f"✅ Bot '{info_bot.first_name}' (Final) conectado. Tentando fazer login...")
    except Exception as e:
        logging.critical(f"Não foi possível conectar ao Telegram. Erro: {e}")
        return

    driver = None
    try:
        driver = configurar_driver()
        
        if not fazer_login(driver):
            raise Exception("O login no Tipminer falhou.")
        
        await enviar_alerta(bot, "🔒 Login no Tipminer realizado com sucesso! Iniciando monitoramento.")
        
        while True:
            numero = await buscar_ultimo_numero(driver)
            if numero is not None:
                await verificar_estrategias(bot, numero)
            await asyncio.sleep(INTERVALO_VERIFICACAO)

    except Exception as e:
        logging.error(f"Um erro crítico ocorreu: {e}")
        if bot:
            await enviar_alerta(bot, f"❌ Ocorreu um erro crítico no bot: {e}")
    finally:
        if driver:
            driver.quit()
        logging.info("Driver do Selenium encerrado.")
        logging.info("O programa será reiniciado em 1 minuto.")
        await asyncio.sleep(60)

if __name__ == '__main__':
    asyncio.run(main())

