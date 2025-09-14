# -*- coding: utf-8 -*-

import os
import time
import logging
import asyncio
import telegram
import httpx
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

INTERVALO_VERIFICACAO = 10

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

def obter_cookies_de_login():
    """Usa o Selenium para fazer login e retorna os cookies de sessão."""
    driver = None
    try:
        logging.info("Configurando o driver do Chrome para obter cookies...")
        chrome_options = webdriver.ChromeOptions()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        
        # REMOVIDO: Deixar o Selenium encontrar o navegador automaticamente
        # chrome_options.binary_location = "/usr/bin/chromium" 
        
        caminho_driver = "/usr/bin/chromedriver"
        service = ChromeService(executable_path=caminho_driver)
        driver = webdriver.Chrome(service=service, options=chrome_options)
        
        logging.info("Iniciando processo de login no Tipminer...")
        driver.get(URL_LOGIN)
        wait = WebDriverWait(driver, 20)

        email_input = wait.until(EC.presence_of_element_located((By.NAME, "email")))
        email_input.send_keys(TIPMINER_USER)
        
        password_input = driver.find_element(By.NAME, "password")
        password_input.send_keys(TIPMINER_PASS)
        
        login_button = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
        login_button.click()
        
        wait.until(EC.url_changes(URL_LOGIN))
        logging.info("Login realizado com sucesso! Capturando cookies...")
        
        cookies_selenium = driver.get_cookies()
        cookies_httpx = {cookie['name']: cookie['value'] for cookie in cookies_selenium}
        
        return cookies_httpx
    finally:
        if driver:
            driver.quit()

async def buscar_ultimo_numero(client):
    """Busca o número mais recente da roleta na API usando os cookies de sessão."""
    global ultimo_id_rodada
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Referer': 'https://www.tipminer.com/br/historico/evolution/roleta-ao-vivo'
        }
        response = await client.get(API_URL, headers=headers, timeout=15)
        response.raise_for_status()
        data = response.json()

        if not data or not isinstance(data, list) or len(data) == 0:
            logging.warning("API retornou uma resposta vazia ou em formato inesperado, mesmo com login.")
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
        logging.error(f"Erro ao processar dados da API: {e}")
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
        logging.info(f"Bot '{info_bot.first_name}' (Híbrido) inicializado com sucesso!")
        await enviar_alerta(bot, f"✅ Bot '{info_bot.first_name}' (Híbrido) conectado. Tentando fazer login...")
    except Exception as e:
        logging.critical(f"Não foi possível conectar ao Telegram. Erro: {e}")
        return

    try:
        session_cookies = obter_cookies_de_login()
        if not session_cookies:
            raise Exception("Não foi possível obter os cookies de sessão.")
        
        await enviar_alerta(bot, "🔒 Login no Tipminer realizado com sucesso! Iniciando monitoramento da API.")
        
        async with httpx.AsyncClient(cookies=session_cookies) as client:
            while True:
                numero = await buscar_ultimo_numero(client)
                if numero is not None:
                    await verificar_estrategias(bot, numero)
                await asyncio.sleep(INTERVALO_VERIFICACAO)

    except Exception as e:
        logging.error(f"Um erro crítico ocorreu: {e}")
        if bot:
            await enviar_alerta(bot, f"❌ Ocorreu um erro crítico no bot: {e}")
        logging.info("O programa será reiniciado em 1 minuto.")
        await asyncio.sleep(60)

if __name__ == '__main__':
    asyncio.run(main())
