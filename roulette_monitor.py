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

# --- CONFIGURAÇÕES ESSENCIAIS ---
TOKEN_BOT = os.environ.get('TOKEN_BOT')
CHAT_ID = os.environ.get('CHAT_ID')
# NOVAS VARIÁVEIS PARA O LOGIN
TIPMINER_USER = os.environ.get('TIPMINER_USER')
TIPMINER_PASS = os.environ.get('TIPMINER_PASS')

if not all([TOKEN_BOT, CHAT_ID, TIPMINER_USER, TIPMINER_PASS]):
    logging.critical("Todas as variáveis de ambiente (TOKEN_BOT, CHAT_ID, TIPMINER_USER, TIPMINER_PASS) devem ser definidas!")
    exit()

URL_ROLETA = 'https://www.tipminer.com/br/historico/evolution/roleta-ao-vivo'
URL_LOGIN = 'https://www.tipminer.com/br/login'
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
    """Configura o driver e o navegador Chrome."""
    logging.info("Configurando o driver e o navegador Chrome...")
    chrome_options = webdriver.ChromeOptions()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920x1080")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
    
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    
    chrome_options.binary_location = "/usr/bin/chromium"
    caminho_driver = "/usr/bin/chromedriver"
    service = ChromeService(executable_path=caminho_driver) 
    
    driver = webdriver.Chrome(service=service, options=chrome_options)
    logging.info("Driver e navegador Chrome configurados com sucesso.")
    return driver

def fazer_login(driver):
    """Navega para a página de login e efetua o login do usuário."""
    try:
        logging.info("Iniciando processo de login no Tipminer...")
        driver.get(URL_LOGIN)
        wait = WebDriverWait(driver, 20)

        email_input = wait.until(EC.presence_of_element_located((By.NAME, "email")))
        email_input.send_keys(TIPMINER_USER)
        logging.info("E-mail preenchido.")

        password_input = driver.find_element(By.NAME, "password")
        password_input.send_keys(TIPMINER_PASS)
        logging.info("Senha preenchida.")

        login_button = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
        login_button.click()
        logging.info("Botão de login clicado.")
        
        # Espera por um redirecionamento, indicando que o login foi processado
        wait.until(EC.url_changes(URL_LOGIN))
        logging.info("Redirecionamento após login detectado.")
        
        # Garante que estamos na página correta
        logging.info("Navegando para a página da roleta para garantir...")
        driver.get(URL_ROLETA)

        # Confirma que o conteúdo da página carregou
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div[data-history-content='true']")))
        logging.info("Login realizado com sucesso! Conteúdo da página de roleta carregado.")
        return True

    except Exception as e:
        logging.error(f"Falha no processo de login: {e}")
        try:
            current_url = driver.current_url
            page_source = driver.page_source
            logging.error(f"URL atual no momento da falha: {current_url}")
            logging.error(f"HTML da página no momento da falha (primeiros 1000 caracteres): {page_source[:1000]}")
        except Exception as debug_e:
            logging.error(f"Erro adicional ao tentar obter informações de depuração: {debug_e}")
        return False

def buscar_ultimo_numero(driver):
    """Busca o número mais recente da roleta usando Selenium."""
    global ultimo_id_rodada
    try:
        # Garante que estamos na página certa antes de cada busca
        if driver.current_url != URL_ROLETA:
            driver.get(URL_ROLETA)
            
        wait = WebDriverWait(driver, 30)
        
        # 1. Encontra o container principal que guarda o histórico
        history_container = wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div[data-history-content='true']"))
        )
        
        # 2. Encontra o container específico dos números
        container_numeros = history_container.find_element(By.CSS_SELECTOR, "div.gap-2")

        # 3. Pega o primeiro 'div' filho, que é sempre o número mais recente
        primeiro_numero_div = container_numeros.find_element(By.XPATH, "./div[1]")
        
        # Usa o HTML interno como um identificador único para a rodada
        id_rodada_atual = primeiro_numero_div.get_attribute('innerHTML')

        if id_rodada_atual == ultimo_id_rodada:
            return None # Número já processado

        ultimo_id_rodada = id_rodada_atual
        
        # 4. Encontra o 'span' DENTRO do 'div' do número mais recente
        numero_span = primeiro_numero_div.find_element(By.TAG_NAME, 'span')
        texto = numero_span.text.strip()
        
        if texto.isdigit() and 0 <= int(texto) <= 36:
            numero = int(texto)
            logging.info(f"Número válido encontrado: {numero}")
            return numero
        else:
            logging.warning(f"Texto encontrado no span não é um número válido: '{texto}'")
            return None

    except Exception as e:
        logging.error(f"Erro ao buscar número com Selenium: {e}")
        # Tira um print da tela para diagnóstico
        try:
            driver.save_screenshot('error_screenshot.png')
            logging.info("Screenshot de erro salvo como 'error_screenshot.png'")
        except Exception as e_ss:
            logging.error(f"Falha ao salvar screenshot: {e_ss}")
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
        logging.info(f"Bot '{info_bot.first_name}' inicializado com sucesso!")
        await enviar_alerta(bot, f"✅ Bot '{info_bot.first_name}' conectado e tentando fazer login...")
    except Exception as e:
        logging.critical(f"Não foi possível conectar ao Telegram. Erro: {e}")
        return

    driver = None
    try:
        driver = configurar_driver()
        
        if not fazer_login(driver):
            await enviar_alerta(bot, "❌ Falha no login do Tipminer. Verifique as credenciais e reinicie o bot.")
            raise Exception("O login no Tipminer falhou.")

        await enviar_alerta(bot, "🔒 Login no Tipminer realizado com sucesso! Iniciando monitoramento.")
        
        while True:
            numero = buscar_ultimo_numero(driver)
            if numero is not None:
                await verificar_estrategias(bot, numero)
            await asyncio.sleep(INTERVALO_VERIFICACAO)
    except Exception as e:
        erro_tratado = str(e).replace("*", "").replace("_", "")
        logging.error(f"Um erro crítico ocorreu no loop principal: {erro_tratado}")
        if bot:
            await enviar_alerta(bot, f"❌ Ocorreu um erro crítico no bot: `{erro_tratado}`")
    finally:
        if driver:
            driver.quit()
        logging.info("Processo principal finalizado.")

if __name__ == '__main__':
    while True:
        try:
            asyncio.run(main())
            logging.info("O programa principal foi encerrado. Reiniciando em 1 minuto.")
        except Exception as e:
            logging.error(f"O processo principal falhou completamente: {e}. Reiniciando em 1 minuto.")
        time.sleep(60)

