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
# A MUDANÇA ESTRATÉGICA: Importa o gerenciador de drivers
from webdriver_manager.chrome import ChromeDriverManager

# --- CONFIGURAÇÕES ESSENCIAIS ---
TOKEN_BOT = os.environ.get('TOKEN_BOT')
CHAT_ID = os.environ.get('CHAT_ID')
TIPMANAGER_USER = os.environ.get('TIPMANAGER_USER')
TIPMANAGER_PASS = os.environ.get('TIPMANAGER_PASS')

if not all([TOKEN_BOT, CHAT_ID, TIPMANAGER_USER, TIPMANAGER_PASS]):
    logging.critical("As variáveis de ambiente TOKEN_BOT, CHAT_ID, TIPMANAGER_USER e TIPMANAGER_PASS devem ser definidas!")
    exit()

URL_ROLETA = 'https://app.tipmanager.net/casino-bot/roulette/last-results'
URL_LOGIN = 'https://app.tipmanager.net/auth/login'
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

def configurar_driver():
    """Configura e retorna uma instância do driver do Chrome."""
    logging.info("Configurando o driver do Chrome...")
    chrome_options = webdriver.ChromeOptions()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920x1080")
    
    # A MUDANÇA ESTRATÉGICA: O webdriver-manager encontra o Chrome e baixa o driver compatível.
    # Não precisamos mais especificar o caminho do binário.
    service = ChromeService(ChromeDriverManager().install())
    
    driver = webdriver.Chrome(service=service, options=chrome_options)
    logging.info("Driver do Chrome configurado com sucesso.")
    return driver

def fazer_login(driver):
    """Navega para a página de login e efetua o login do usuário."""
    try:
        logging.info("Iniciando processo de login no app.tipmanager.net...")
        driver.get(URL_LOGIN)
        wait = WebDriverWait(driver, 20)

        email_input = wait.until(EC.presence_of_element_located((By.NAME, "email")))
        email_input.send_keys(TIPMANAGER_USER)
        
        password_input = driver.find_element(By.NAME, "password")
        password_input.send_keys(TIPMANAGER_PASS)
        
        login_button = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
        login_button.click()
        
        # Espera por um elemento que só aparece após o login bem-sucedido
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "nav[aria-label='Main']")))
        logging.info("Login realizado com sucesso!")
        return True
    except Exception as e:
        logging.error(f"Falha no processo de login: {e}")
        return False

async def buscar_ultimo_numero(driver):
    """Busca o número mais recente da roleta usando a sessão logada."""
    global ultimo_numero_encontrado
    try:
        driver.get(URL_ROLETA)
        wait = WebDriverWait(driver, 30)
        
        # Seletor CSS mais específico para o container dos resultados
        history_container = wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div[class*='LastResults_container']"))
        )
        
        # Encontra o primeiro div dentro do container, que é o número mais recente
        primeiro_numero_div = history_container.find_element(By.XPATH, "./div[1]")
        
        # Pega o texto do span dentro deste div
        numero_span = primeiro_numero_div.find_element(By.TAG_NAME, 'span')
        numero_str = numero_span.text.strip()
        
        if numero_str == ultimo_numero_encontrado:
            return None

        ultimo_numero_encontrado = numero_str
        
        if numero_str.isdigit():
            numero = int(numero_str)
            logging.info(f"Número válido encontrado: {numero}")
            return numero
        else:
            logging.warning(f"Texto encontrado não é um número válido: '{numero_str}'")
            return None

    except Exception as e:
        logging.error(f"Erro ao buscar número com Selenium: {e}")
        return None

async def verificar_estrategias(bot, numero):
    """Verifica o número e envia alertas."""
    if numero is None:
        return
    for nome_estrategia, condicao in ESTRATEGIAS.items():
        if condicao(numero):
            mensagem = f"🎯 Gatilho Encontrado! 🎯\n\nEstratégia: *{nome_estrategia}*\nNúmero Sorteado: *{numero}*"
            logging.info(f"Condição da estratégia '{nome_estrategia}' atendida. Enviando alerta...")
            await enviar_alerta(bot, mensagem)

async def enviar_alerta(bot, mensagem):
    """Envia uma mensagem para o Telegram."""
    try:
        await bot.send_message(chat_id=CHAT_ID, text=mensagem, parse_mode=ParseMode.MARKDOWN)
        logging.info("Alerta enviado com sucesso!")
    except Exception as e:
        logging.error(f"Erro ao enviar mensagem para o Telegram: {e}")

async def main():
    """Função principal."""
    bot = None
    try:
        bot = telegram.Bot(token=TOKEN_BOT)
        info_bot = await bot.get_me()
        logging.info(f"Bot '{info_bot.first_name}' (TipManager) inicializado com sucesso!")
        await enviar_alerta(bot, f"✅ Bot '{info_bot.first_name}' (TipManager) conectado. Tentando fazer login...")
    except Exception as e:
        logging.critical(f"Não foi possível conectar ao Telegram. Erro: {e}")
        return

    driver = None
    try:
        driver = configurar_driver()
        
        if not fazer_login(driver):
            raise Exception("O login no TipManager falhou.")
        
        await enviar_alerta(bot, "🔒 Login no TipManager realizado com sucesso! Iniciando monitoramento.")
        
        while True:
            numero = await buscar_ultimo_numero(driver)
            if numero is not None:
                await verificar_estrategias(bot, numero)
            await asyncio.sleep(INTERVALO_VERIFICACAO)

    except Exception as e:
        logging.error(f"Um erro crítico ocorreu: {e}")
        if bot:
            await enviar_alerta(bot, f"❌ Ocorreu um erro crítico no bot: {str(e)}")
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

