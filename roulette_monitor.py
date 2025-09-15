# -*- coding: utf-8 -*-

import os
import time
import logging
import asyncio
import telegram
import json
import re
from telegram.constants import ParseMode
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# --- CONFIGURAÇÕES ESSENCIAIS ---
TOKEN_BOT = os.environ.get('TOKEN_BOT')
CHAT_ID = os.environ.get('CHAT_ID')
# VARIÁVEIS PARA O LOGIN NO PADRÕES DE CASSINO
PADROES_USER = os.environ.get('PADROES_USER')
PADROES_PASS = os.environ.get('PADROES_PASS')

if not all([TOKEN_BOT, CHAT_ID, PADROES_USER, PADROES_PASS]):
    logging.critical("Todas as variáveis de ambiente (TOKEN_BOT, CHAT_ID, PADROES_USER, PADROES_PASS) devem ser definidas!")
    exit()

URL_LOGIN = 'https://jv.padroesdecassino.com.br/sistema/login'
API_URL = 'https://api.padroesdecassino.com.br/roletabrasileira-brbet.php'
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
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
    
    service = ChromeService() 
    driver = webdriver.Chrome(service=service, options=chrome_options)
    logging.info("Driver do Chrome configurado com sucesso.")
    return driver

def fazer_login(driver):
    """Realiza o login no site para obter uma sessão autenticada."""
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
        
        # Espera por um elemento da página pós-login para confirmar sucesso
        wait.until(EC.presence_of_element_located((By.ID, "menu")))
        logging.info("Login realizado com sucesso!")
        return True

    except Exception as e:
        logging.error(f"Falha no processo de login: {e}")
        return False

def buscar_ultimo_numero_api(driver):
    """Usa a sessão do navegador logado para buscar os dados diretamente da API."""
    global ultimo_numero_encontrado
    try:
        # Usa o driver para ir até a URL da API
        driver.get(API_URL)
        
        # O conteúdo da API é o corpo da página
        api_response_text = driver.find_element(By.TAG_NAME, 'body').text

        # Extrai a lista de dados da variável javascript 'roletaData'
        match = re.search(r"var roletaData = (\[.*?\]);", api_response_text)
        if not match:
            logging.warning("Padrão 'roletaData' não encontrado na resposta da API.")
            return None
            
        json_data = json.loads(match.group(1))

        if not json_data:
            logging.warning("API retornou uma lista de dados vazia.")
            return None

        # O primeiro item da lista é o mais recente
        ultimo_resultado = json_data[0]
        numero_str = ultimo_resultado.get("numero")
        
        if numero_str == ultimo_numero_encontrado:
            return None

        ultimo_numero_encontrado = numero_str
        
        if numero_str is not None and numero_str.isdigit():
            numero = int(numero_str)
            logging.info(f"Número válido encontrado via API: {numero}")
            return numero
        else:
            logging.warning(f"Dado encontrado na API não é um número válido: '{numero_str}'")
            return None

    except Exception as e:
        logging.error(f"Erro ao processar dados da API: {e}")
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
        logging.info(f"Bot '{info_bot.first_name}' (Padrões de Cassino) inicializado com sucesso!")
        await enviar_alerta(bot, f"✅ Bot '{info_bot.first_name}' (Padrões de Cassino) conectado e monitorando!")
    except Exception as e:
        logging.critical(f"Não foi possível conectar ao Telegram. Erro: {e}")
        return

    driver = None
    try:
        driver = configurar_driver()
        
        if not fazer_login(driver):
            raise Exception("O login no Padrões de Cassino falhou.")
        
        while True:
            # USA A NOVA FUNÇÃO DE BUSCA PELA API
            numero = buscar_ultimo_numero_api(driver)
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

