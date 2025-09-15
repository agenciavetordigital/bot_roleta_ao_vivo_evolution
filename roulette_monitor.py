import os
import time
import logging
import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import StaleElementReferenceException

# ==============================
# CONFIGURAÇÕES
# ==============================
TELEGRAM_TOKEN = "COLOQUE_SEU_TOKEN_AQUI"
CHAT_ID = "COLOQUE_SEU_CHAT_ID_AQUI"
URL_LOGIN = "https://www.tipminer.com/br/login"
URL_ROLETA = "https://www.tipminer.com/br/historico/evolution/roleta-ao-vivo"
USUARIO = "COLOQUE_SEU_EMAIL"
SENHA = "COLOQUE_SUA_SENHA"

# ==============================
# LOGGING
# ==============================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# ==============================
# ESTADO GLOBAL
# ==============================
ultimo_numero_encontrado = None
prev_snapshot = []

# ==============================
# FUNÇÕES AUXILIARES
# ==============================
def enviar_telegram(msg: str):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg})
    except Exception as e:
        logging.error(f"Erro ao enviar mensagem para Telegram: {e}")


def login(driver):
    """Realiza login no Tipminer"""
    driver.get(URL_LOGIN)
    wait = WebDriverWait(driver, 20)
    try:
        usuario_input = wait.until(EC.presence_of_element_located((By.NAME, "email")))
        senha_input = driver.find_element(By.NAME, "password")
        botao = driver.find_element(By.CSS_SELECTOR, "button[type=submit]")

        usuario_input.send_keys(USUARIO)
        senha_input.send_keys(SENHA)
        botao.click()

        wait.until(EC.url_contains("/br"))
        logging.info("✅ Login realizado com sucesso!")
    except Exception as e:
        logging.error(f"Erro no login: {e}")


def buscar_ultimo_numero(driver):
    """
    Heurística robusta para encontrar o último número:
    1) procura por elementos com classes/atributos que indiquem 'current/active/latest'
    2) compara snapshot atual vs anterior para encontrar a diferença
    3) fallback em posições óbvias (primeiro/último)
    """
    global ultimo_numero_encontrado, prev_snapshot

    MAX_RETRIES = 3
    for attempt in range(MAX_RETRIES):
        try:
            if driver.current_url != URL_ROLETA:
                driver.get(URL_ROLETA)
            else:
                driver.refresh()

            wait = WebDriverWait(driver, 20)
            elements = wait.until(
                EC.presence_of_all_elements_located((By.CSS_SELECTOR, "#dados div, #dados span"))
            )

            snapshot = []
            element_attrs = []
            for el in elements:
                try:
                    txt = el.text.strip()
                except StaleElementReferenceException:
                    raise
                cls = (el.get_attribute("class") or "")
                data_current = el.get_attribute("data-current") or el.get_attribute("data-last") or ""
                snapshot.append(txt)
                element_attrs.append((txt, cls, data_current))

            logging.info("🔎 Debug: snapshot atual (#dados): %s", snapshot[:20])  # só mostra os primeiros 20

            candidate = None
            used_heuristic = None

            # HEURÍSTICA 1: marcador
            for i, (txt, cls, data_attr) in enumerate(element_attrs):
                lcls = cls.lower()
                if data_attr:
                    if txt.isdigit() and 0 <= int(txt) <= 36:
                        candidate = txt
                        used_heuristic = f"marker-data-attr(index={i})"
                        break
                if any(k in lcls for k in ("active", "current", "latest", "recent", "last", "is-active", "selected")):
                    if txt.isdigit() and 0 <= int(txt) <= 36:
                        candidate = txt
                        used_heuristic = f"marker-class('{cls}',index={i})"
                        break

            # HEURÍSTICA 2: diff snapshot
            if candidate is None and prev_snapshot:
                if snapshot != prev_snapshot:
                    minlen = min(len(snapshot), len(prev_snapshot))
                    idx_diff = None
                    for idx in range(minlen):
                        if snapshot[idx] != prev_snapshot[idx]:
                            idx_diff = idx
                            break
                    if idx_diff is None and len(snapshot) > len(prev_snapshot):
                        idx_diff = len(prev_snapshot)

                    if idx_diff is not None:
                        cand_txt = snapshot[idx_diff]
                        if cand_txt.isdigit() and 0 <= int(cand_txt) <= 36:
                            candidate = cand_txt
                            used_heuristic = f"snapshot-diff(index={idx_diff})"

            # HEURÍSTICA 3: fallback
            if candidate is None and snapshot:
                for pos_name, idx in (("first", 0), ("last", -1)):
                    cand_txt = snapshot[idx]
                    if cand_txt.isdigit() and 0 <= int(cand_txt) <= 36:
                        if cand_txt != ultimo_numero_encontrado:
                            candidate = cand_txt
                            used_heuristic = f"fallback-{pos_name}"
                            break

            prev_snapshot = snapshot

            if candidate:
                logging.info(f"Heurística usada: {used_heuristic} -> candidato: {candidate}")
                if candidate == ultimo_numero_encontrado:
                    return None
                ultimo_numero_encontrado = candidate
                return int(candidate)

            logging.warning("Nenhum candidato válido encontrado.")
            return None

        except StaleElementReferenceException:
            logging.warning("StaleElementReferenceException — tentativa %d/%d", attempt + 1, MAX_RETRIES)
            time.sleep(0.5)
            continue
        except Exception as e:
            logging.error(f"Erro inesperado em buscar_ultimo_numero: {e}")
            return None

    logging.error("Falha após %d tentativas", MAX_RETRIES)
    return None


# ==============================
# MAIN
# ==============================
def main():
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")

    driver = webdriver.Chrome(options=chrome_options)
    login(driver)

    while True:
        numero = buscar_ultimo_numero(driver)
        if numero is not None:
            msg = f"🎰 Último número da roleta: {numero}"
            enviar_telegram(msg)
            logging.info(f"➡️ Enviado para Telegram: {msg}")
        time.sleep(10)


if __name__ == "__main__":
    main()
