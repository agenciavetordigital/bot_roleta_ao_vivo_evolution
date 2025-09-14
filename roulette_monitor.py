# -*- coding: utf-8 -*-

import os
import time
import logging
import asyncio
import telegram
from telegram.constants import ParseMode
from bs4 import BeautifulSoup

# Importações do Selenium e do Webdriver-Manager
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# --- CONFIGURAÇÕES ESSENCIAIS (VIA VARIÁVEIS DE AMBIENTE) ---
# Estas variáveis devem ser configuradas no painel da Railway
TOKEN_BOT = os.environ.get('TOKEN_BOT')
CHAT_ID = os.environ.get('CHAT_ID')

# --- CONFIGURAÇÕES DO BOT ---
URL_ROLETA = 'https://www.tipminer.com/br/historico/evolution/roleta-ao-vivo'
INTERVALO_VERIFICACAO = 15 # Segundos

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

def configurar_driver_selenium():
    """Configura e retorna uma instância do WebDriver do Selenium."""
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("window-size=1920,1080")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
    
    logging.info("Configurando o driver do Chrome com webdriver-manager...")
    
    # A MUDANÇA PRINCIPAL: O webdriver-manager baixa e gerencia o chromedriver automaticamente
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    
    logging.info("Driver configurado com sucesso.")
    return driver

def buscar_ultimo_numero(driver):
    """Busca o número mais recente da roleta usando Selenium."""
    global ultimo_id_rodada

    try:
        logging.info(f"Acessando a URL: {URL_ROLETA}")
        driver.get(URL_ROLETA)

        # Espera o container de números carregar (até 20 segundos)
        wait = WebDriverWait(driver, 20)
        container_numeros = wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".flex.flex-wrap.gap-2.justify-center"))
        )
        
        # Pega o HTML da página depois que o JavaScript carregou
        html_completo = driver.page_source
        soup = BeautifulSoup(html_completo, 'html.parser')
        
        # Reencontra o elemento no BeautifulSoup para garantir consistência
        container_soup = soup.find('div', class_='flex flex-wrap gap-2 justify-center')
        if not container_soup:
            logging.warning("Não foi possível encontrar o container de números no HTML processado.")
            return None

        primeiro_numero_div = container_soup.find('div')
        if not primeiro_numero_div:
            logging.warning("Não foi possível encontrar a div do último número.")
            return None
            
        id_rodada_atual = str(primeiro_numero_div)
        if id_rodada_atual == ultimo_id_rodada:
            return None # Nenhum número novo, não faz nada

        ultimo_id_rodada = id_rodada_atual
        
        numero_str = primeiro_numero_div.text.strip()
        numero = int(numero_str)
        logging.info(f"Número mais recente encontrado: {numero}")
        return numero

    except (ValueError, TypeError):
        logging.error(f"Não foi possível converter o valor '{numero_str}' para um número inteiro.")
        return None
    except Exception as e:
        logging.error(f"Ocorreu um erro inesperado ao buscar o número: {e}")
        # Tira um print da tela para ajudar a depurar o erro
        try:
            driver.save_screenshot('error_screenshot.png')
            logging.info("Screenshot de erro salvo em 'error_screenshot.png'")
        except Exception as screenshot_error:
            logging.error(f"Falha ao salvar o screenshot de erro: {screenshot_error}")
        return None

async def enviar_alerta(bot, mensagem):
    """Envia uma mensagem para o chat configurado no Telegram."""
    try:
        await bot.send_message(chat_id=CHAT_ID, text=mensagem, parse_mode=ParseMode.MARKDOWN)
        logging.info("Alerta enviado com sucesso!")
    except Exception as e:
        logging.error(f"Erro ao enviar mensagem para o Telegram: {e}")

async def main():
    """Função principal que inicializa o bot e inicia o monitoramento."""
    if not TOKEN_BOT or not CHAT_ID:
        logging.critical("As variáveis de ambiente TOKEN_BOT e CHAT_ID não foram definidas. Encerrando.")
        return

    try:
        bot = telegram.Bot(token=TOKEN_BOT)
        info_bot = await bot.get_me()
        logging.info(f"Bot '{info_bot.first_name}' inicializado com sucesso!")
        await enviar_alerta(bot, "✅ Bot monitor de roleta iniciado com sucesso!")
    except Exception as e:
        logging.critical(f"Não foi possível conectar ao Telegram. Verifique seu token. Erro: {e}")
        return

    driver = None
    try:
        driver = configurar_driver_selenium()
        logging.info("Iniciando monitoramento da roleta...")
        while True:
            numero = buscar_ultimo_numero(driver)
            if numero is not None:
                # Verifica as estratégias se encontrou um número novo
                for nome_estrategia, condicao in ESTRATEGIAS.items():
                    if condicao(numero):
                        mensagem = f"🎯 *Gatilho Encontrado!*\n\n*Estratégia:* {nome_estrategia}\n*Número:* {numero}"
                        await enviar_alerta(bot, mensagem)
            
            await asyncio.sleep(INTERVALO_VERIFICACAO)
    except Exception as e:
        logging.error(f"Um erro crítico ocorreu no loop principal: {e}")
        logging.info("Aguardando 60 segundos antes de tentar novamente...")
        await asyncio.sleep(60)
    finally:
        if driver:
            driver.quit()
        await enviar_alerta(bot, "❌ Bot monitor de roleta foi encerrado.")
        logging.info("Driver do Selenium encerrado.")

if __name__ == '__main__':
    asyncio.run(main())

