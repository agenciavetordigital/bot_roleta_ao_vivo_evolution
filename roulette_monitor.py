# -*- coding: utf-8 -*-

# --- IMPORTAÇÕES PADRÃO E DE LIBS ---
import os
import time
import logging
import asyncio
import random
from datetime import datetime, timedelta, time as dt_time
import pytz
import requests
import telegram
from telegram.constants import ParseMode
import psycopg2
from urllib.parse import urlparse

# --- CONFIGURAÇÕES ESSENCIAIS ---
TOKEN_BOT = os.environ.get('TOKEN_BOT')
CHAT_IDS_STR = os.environ.get('CHAT_ID')
URL_APOSTA = os.environ.get('URL_APOSTA')
DATABASE_URL = os.environ.get('DATABASE_URL')

# Validação crítica das variáveis de ambiente
if not all([TOKEN_BOT, CHAT_IDS_STR, URL_APOSTA, DATABASE_URL]):
    logging.critical("ERRO: Todas as variáveis de ambiente devem ser definidas: TOKEN_BOT, CHAT_ID, URL_APOSTA, DATABASE_URL!")
    exit()

CHAT_IDS = [chat_id.strip() for chat_id in CHAT_IDS_STR.split(',')]

INTERVALO_VERIFICACAO_API = 5
MAX_MARTINGALES = 2

# --- CONFIGURAÇÕES DE HUMANIZAÇÃO E HORA ---
FUSO_HORARIO_BRASIL = pytz.timezone('America/Sao_Paulo')
WORK_MIN_MINUTES = 3 * 60; WORK_MAX_MINUTES = 5 * 60
BREAK_MIN_MINUTES = 25; BREAK_MAX_MINUTES = 45
HORA_TARDE = 12; HORA_NOITE = 18

# --- FUNÇÕES DE BANCO DE DADOS POSTGRESQL ---
def get_db_connection():
    try:
        result = urlparse(DATABASE_URL)
        conn = psycopg2.connect(database=result.path[1:], user=result.username, password=result.password, host=result.hostname, port=result.port)
        return conn
    except (Exception, psycopg2.Error) as error:
        logging.error(f"Erro ao conectar ao PostgreSQL: {error}")
        return None

def inicializar_db_postgres():
    conn = get_db_connection()
    if conn is not None:
        try:
            with conn.cursor() as cur:
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS resultados (
                        id SERIAL PRIMARY KEY, numero INTEGER, cor VARCHAR(10), duzia INTEGER,
                        coluna INTEGER, paridade VARCHAR(10), timestamp TIMESTAMPTZ DEFAULT NOW()
                    );
                ''')
                conn.commit()
            logging.info("Banco de dados e tabela 'resultados' verificados/criados com sucesso.")
        except (Exception, psycopg2.DatabaseError) as error:
            logging.error(f"Erro ao inicializar a tabela: {error}")
        finally:
            conn.close()

def get_properties(numero):
    if numero == 0: return 'Verde', 0, 0, 'N/A'
    cor = 'Vermelho' if numero in [1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36] else 'Preto'
    duzia = 1 if 1 <= numero <= 12 else 2 if 13 <= numero <= 24 else 3
    coluna = 3 if numero % 3 == 0 else numero % 3
    paridade = 'Par' if numero % 2 == 0 else 'Ímpar'
    return cor, duzia, coluna, paridade

def salvar_numero_postgres(numero):
    cor, duzia, coluna, paridade = get_properties(numero)
    sql = "INSERT INTO resultados(numero, cor, duzia, coluna, paridade) VALUES(%s, %s, %s, %s, %s);"
    conn = get_db_connection()
    if conn is not None:
        try:
            with conn.cursor() as cur:
                cur.execute(sql, (numero, cor, duzia, coluna, paridade))
                conn.commit()
            logging.info(f"Número {numero} salvo no banco de dados PostgreSQL.")
        except (Exception, psycopg2.DatabaseError) as error:
            logging.error(f"Erro ao salvar número no DB: {error}")
        finally:
            conn.close()

# --- LÓGICA DAS ESTRATÉGIAS ---
STRATEGY_MENOS_FICHAS_NEIGHBORS = { 2: [15, 19, 4, 21, 2, 25, 17, 34, 6], 7: [9, 22, 18, 29, 7, 28, 12, 35, 3], 12: [18, 29, 7, 28, 12, 35, 3, 26, 0], 17: [4, 21, 2, 25, 17, 34, 6, 27, 13], 22: [20, 14, 31, 9, 22, 18, 29, 7, 28], 27: [25, 17, 34, 6, 27, 13, 36, 11, 30], 32: [35, 3, 26, 0, 32, 15, 19, 4, 21], 11: [6, 27, 13, 36, 11, 30, 8, 23, 10], 16: [23, 10, 5, 24, 16, 33, 1, 20, 14], 25: [19, 4, 21, 2, 25, 17, 34, 6, 27], 34: [21, 2, 25, 17, 34, 6, 27, 13, 36]}
def get_winners_menos_fichas(trigger_number):
    winners = STRATEGY_MENOS_FICHAS_NEIGHBORS.get(trigger_number, [])
    if 0 not in winners: winners.append(0)
    return winners
ESTRATEGIAS = { "Estratégia Menos Fichas": { "triggers": list(STRATEGY_MENOS_FICHAS_NEIGHBORS.keys()), "filter": [], "get_winners": get_winners_menos_fichas }}

# --- LÓGICA DO BOT ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
ultimo_numero_processado_api = None
numero_anterior_estrategia = None
daily_play_history = []
daily_messages_sent = {}
active_strategy_state = {}

def reset_daily_messages_tracker():
    global daily_messages_sent
    daily_messages_sent = {"tarde": False, "noite": False}

def initialize_score():
    score = {"last_check_date": datetime.now(FUSO_HORARIO_BRASIL).date()}
    for name in ESTRATEGIAS:
        score[name] = {"wins_sg": 0, "wins_g1": 0, "wins_g2": 0, "losses": 0}
    return score

daily_score = initialize_score()

def reset_strategy_state():
    global active_strategy_state
    active_strategy_state = { "active": False, "strategy_name": "", "martingale_level": 0, "winning_numbers": [], "trigger_number": None, "play_message_ids": {} }

reset_daily_messages_tracker()
reset_strategy_state()

def buscar_ultimo_numero_api():
    global ultimo_numero_processado_api, numero_anterior_estrategia
    try:
        # Log para sabermos o estado antes da chamada
        logging.info(f"[DEBUG] Iniciando busca. Estado atual: ultimo_numero_processado_api = {ultimo_numero_processado_api}")

        cache_buster = int(time.time() * 1000)
        url = f"https://api.jogosvirtual.com/jsons/historico_roletabrasileira.json?_={cache_buster}"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        dados = response.json()

        # --- LOG DE DEPURAÇÃO MAIS IMPORTANTE ---
        # Vamos imprimir exatamente o que a API nos retornou
        logging.info(f"[DEBUG] Dados brutos recebidos da API: {dados}")
        
        if not dados:
            return None, None

        lista_de_numeros = dados.get('baralhos', {}).get('0', [])
        if not lista_de_numeros: return None, None
        valor_bruto = lista_de_numeros[0]
        
        if valor_bruto is None: return None, None
        
        try:
            novo_numero = int(valor_bruto)
        except (ValueError, TypeError):
            return None, None
            
        if novo_numero != ultimo_numero_processado_api:
            logging.info(f"✅ Novo giro detectado via API: {novo_numero} (Anterior: {ultimo_numero_processado_api})")
            numero_anterior_estrategia = ultimo_numero_processado_api
            ultimo_numero_processado_api = novo_numero
            return novo_numero, numero_anterior_estrategia
        
        return None, None
    except requests.exceptions.RequestException as e:
        logging.error(f"Erro ao fazer requisição para a API: {e}")
        return None, None
    except Exception as e:
        logging.error(f"Erro inesperado em buscar_ultimo_numero_api: {e}")
        return None, None

async def processar_numero(bot, numero, numero_anterior):
    if numero is None: return
    salvar_numero_postgres(numero)
    await check_and_reset_daily_score(bot)
    if active_strategy_state["active"]:
        await handle_active_strategy(bot, numero)
    else:
        await check_for_new_triggers(bot, numero, numero_anterior)

# (O restante do código é idêntico e não precisa de alterações)
def calculate_streaks_for_period(start_time, end_time):
    plays_in_period = [p['result'] for p in daily_play_history if start_time <= p['time'].time() < end_time]
    if not plays_in_period: return {"max_wins": 0, "max_losses": 0}
    max_wins, current_wins, max_losses, current_losses = 0, 0, 0, 0
    for result in plays_in_period:
        if result == 'win': current_wins += 1; current_losses = 0
        else: current_losses += 1; current_wins = 0
        if current_wins > max_wins: max_wins = current_wins
        if current_losses > max_losses: max_losses = current_losses
    return {"max_wins": max_wins, "max_losses": max_losses}

def format_score_message(title="📊 *Placar do Dia* 📊"):
    messages = [title]; overall_wins, overall_losses = 0, 0
    for name, score in daily_score.items():
        if name == "last_check_date": continue
        strategy_wins = score['wins_sg'] + score['wins_g1'] + score['wins_g2']; strategy_losses = score['losses']
        overall_wins += strategy_wins; overall_losses += strategy_losses
        total_plays = strategy_wins + strategy_losses
        accuracy = (strategy_wins / total_plays * 100) if total_plays > 0 else 0
        wins_str = f"SG: {score['wins_sg']} | G1: {score['wins_g1']} | G2: {score['wins_g2']}"
        messages.append(f"*{name}* (Assertividade: {accuracy:.1f}%)\n`   `✅ `{wins_str}`\n`   `❌ `{strategy_losses}`")
    total_overall_plays = overall_wins + overall_losses
    overall_accuracy = (overall_wins / total_overall_plays * 100) if total_overall_plays > 0 else 0
    messages.insert(1, f"📈 *Assertividade Geral: {overall_accuracy:.1f}%*")
    return "\n\n".join(messages)

async def send_message_to_all(bot, text, **kwargs):
    for chat_id in CHAT_IDS:
        try: await bot.send_message(chat_id=chat_id, text=text, **kwargs)
        except Exception as e: logging.error(f"Erro ao enviar mensagem para o chat_id {chat_id}: {e}")

async def send_and_track_play_message(bot, text, **kwargs):
    sent_messages = {}
    for chat_id in CHAT_IDS:
        try:
            message = await bot.send_message(chat_id=chat_id, text=text, **kwargs)
            sent_messages[chat_id] = message
        except Exception as e: logging.error(f"Erro ao enviar mensagem para o chat_id {chat_id}: {e}")
    for chat_id, message in sent_messages.items():
        active_strategy_state["play_message_ids"][chat_id] = message.message_id

async def edit_play_messages(bot, new_text, **kwargs):
    for chat_id, message_id in active_strategy_state["play_message_ids"].items():
        try: await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=new_text, **kwargs)
        except Exception as e: logging.warning(f"Não foi possível editar a msg {message_id} do chat {chat_id}: {e}")

async def check_and_reset_daily_score(bot):
    global daily_score, daily_play_history
    today_br = datetime.now(FUSO_HORARIO_BRASIL).date()
    if daily_score.get("last_check_date") != today_br:
        logging.info("Novo dia detectado! Enviando relatório e resetando o placar.")
        yesterday_str = daily_score.get("last_check_date", "dia anterior").strftime('%d/%m/%Y')
        final_scores = format_score_message(title=f"📈 *Relatório Final do Dia {yesterday_str}* 📈")
        streaks = calculate_streaks_for_period(dt_time.min, dt_time.max)
        streak_report = f"\n\n*Resumo do Dia:*\nSequência Máx. de Vitórias: *{streaks['max_wins']}* ✅\nSequência Máx. de Derrotas: *{streaks['max_losses']}* ❌"
        await send_message_to_all(bot, final_scores + streak_report, parse_mode=ParseMode.MARKDOWN)
        daily_score = initialize_score()
        daily_play_history.clear()
        reset_daily_messages_tracker()
        await send_message_to_all(bot, "☀️ Bom dia! Um novo dia de análises está começando. Boa sorte a todos!")

async def check_and_send_period_messages(bot):
    global daily_messages_sent
    now_br = datetime.now(FUSO_HORARIO_BRASIL)
    if now_br.hour >= HORA_TARDE and not daily_messages_sent.get("tarde"):
        logging.info("Enviando mensagem do período da tarde.")
        partial_score = format_score_message(title="📊 *Placar Parcial (Manhã)* 📊")
        streaks = calculate_streaks_for_period(dt_time.min, dt_time(hour=11, minute=59, second=59))
        streak_report = f"\n\nSequência Máx. de Vitórias: *{streaks['max_wins']}* ✅\nSequência Máx. de Derrotas: *{streaks['max_losses']}* ❌"
        message = f"☀️ Período da tarde iniciando!\n\nNossa parcial da **MANHÃ** foi:\n{partial_score}{streak_report}"
        await send_message_to_all(bot, message, parse_mode=ParseMode.MARKDOWN)
        daily_messages_sent["tarde"] = True
    if now_br.hour >= HORA_NOITE and not daily_messages_sent.get("noite"):
        logging.info("Enviando mensagem do período da noite.")
        partial_score = format_score_message(title="📊 *Placar Parcial (Tarde)* 📊")
        streaks = calculate_streaks_for_period(dt_time(hour=12), dt_time(hour=17, minute=59, second=59))
        streak_report = f"\n\nSequência Máx. de Vitórias (Tarde): *{streaks['max_wins']}* ✅\nSequência Máx. de Derrotas (Tarde): *{streaks['max_losses']}* ❌"
        message = f"🌙 Período da noite iniciando!\n\nNossa parcial da **TARDE** foi:\n{partial_score}{streak_report}"
        await send_message_to_all(bot, message, parse_mode=ParseMode.MARKDOWN)
        daily_messages_sent["noite"] = True

def build_base_signal_message():
    name = active_strategy_state['strategy_name']; numero = active_strategy_state['trigger_number']; winning_numbers = active_strategy_state['winning_numbers']
    return (f"🎯 *Gatilho Encontrado!* 🎯\n\n🎲 *Estratégia: {name}*\n🔢 *Número Gatilho: {numero}*\n\n💰 *Apostar em:*\n`{', '.join(map(str, sorted(winning_numbers)))}`\n\n[🔗 Fazer Aposta]({URL_APOSTA})")

async def handle_win(bot, final_number):
    daily_play_history.append({'time': datetime.now(FUSO_HORARIO_BRASIL), 'result': 'win'})
    strategy_name = active_strategy_state["strategy_name"]; win_level = active_strategy_state["martingale_level"]
    if win_level == 0: daily_score[strategy_name]["wins_sg"] += 1; win_type_message = "Vitória sem Gale!"
    else: daily_score[strategy_name][f"wins_g{win_level}"] += 1; win_type_message = f"Vitória no {win_level}º Martingale"
    mensagem_final = (f"✅ *VITÓRIA!*\n\n*{win_type_message}*\n_Estratégia: {strategy_name}_\nGatilho: *{active_strategy_state['trigger_number']}* | Saiu: *{final_number}*\n\n{format_score_message()}")
    await edit_play_messages(bot, mensagem_final, parse_mode=ParseMode.MARKDOWN); reset_strategy_state()

async def handle_loss(bot, final_number):
    daily_play_history.append({'time': datetime.now(FUSO_HORARIO_BRASIL), 'result': 'loss'})
    strategy_name = active_strategy_state["strategy_name"]; daily_score[strategy_name]["losses"] += 1
    mensagem_final = (f"❌ *LOSS!*\n\n_Estratégia: {strategy_name}_\nGatilho: *{active_strategy_state['trigger_number']}* | Saiu: *{final_number}*\n\n{format_score_message()}")
    await edit_play_messages(bot, mensagem_final, parse_mode=ParseMode.MARKDOWN); reset_strategy_state()

async def handle_martingale(bot, current_number):
    level = active_strategy_state["martingale_level"]; base_message = build_base_signal_message()
    mensagem_editada = (f"{base_message}\n\n------------------------------------\n⏳ *Análise: Entrar no {level}º Martingale...*\nO número *{current_number}* não pagou.")
    await edit_play_messages(bot, mensagem_editada, parse_mode=ParseMode.MARKDOWN)

async def handle_active_strategy(bot, numero):
    if numero in active_strategy_state["winning_numbers"]: await handle_win(bot, numero)
    else:
        active_strategy_state["martingale_level"] += 1
        if active_strategy_state["martingale_level"] <= MAX_MARTINGALES: await handle_martingale(bot, numero)
        else: await handle_loss(bot, numero)

async def check_for_new_triggers(bot, numero, numero_anterior):
    for name, details in ESTRATEGIAS.items():
        if numero in details["triggers"]:
            if details.get("filter") and numero_anterior is not None and numero_anterior in details["filter"]:
                logging.info(f"Gatilho {numero} ignorado para '{name}' devido ao filtro com número anterior {numero_anterior}.")
                continue
            winning_numbers = details["get_winners"](numero)
            active_strategy_state.update({ "active": True, "strategy_name": name, "winning_numbers": winning_numbers, "trigger_number": numero })
            mensagem = f"{build_base_signal_message()}\n\n---\n{format_score_message()}"
            await send_and_track_play_message(bot, mensagem, parse_mode=ParseMode.MARKDOWN)
            break

async def work_session(bot):
    work_duration_minutes = random.randint(WORK_MIN_MINUTES, WORK_MAX_MINUTES)
    session_end_time = datetime.now(FUSO_HORARIO_BRASIL) + timedelta(minutes=work_duration_minutes)
    logging.info(f"Iniciando nova sessão de trabalho (API) que durará {work_duration_minutes // 60}h e {work_duration_minutes % 60}min.")
    await send_message_to_all(bot, f"Monitoramento de ciclos (API) previsto para durar *{work_duration_minutes // 60}h e {work_duration_minutes % 60}min*.", parse_mode=ParseMode.MARKDOWN)
    while datetime.now(FUSO_HORARIO_BRASIL) < session_end_time:
        await check_and_send_period_messages(bot)
        numero, numero_anterior = buscar_ultimo_numero_api()
        await processar_numero(bot, numero, numero_anterior)
        await asyncio.sleep(INTERVALO_VERIFICACAO_API)
    logging.info("Sessão de trabalho (API) concluída. Preparando para a pausa.")

async def supervisor():
    bot = telegram.Bot(token=TOKEN_BOT)
    try:
        await send_message_to_all(bot, f"🤖 Monitoramento Roleta Online (API Mode)!\nIniciando gerenciamento de ciclos.")
    except Exception as e:
        logging.critical(f"Não foi possível conectar ao Telegram para a mensagem inicial: {e}")
    while True:
        try:
            await work_session(bot)
            break_duration_minutes = random.randint(BREAK_MIN_MINUTES, BREAK_MAX_MINUTES)
            logging.info(f"Iniciando pausa de {break_duration_minutes} minutos.")
            await send_message_to_all(bot, f"⏸️ Pausa programada para manutenção.\nDuração: *{break_duration_minutes} minutos*.", parse_mode=ParseMode.MARKDOWN)
            await asyncio.sleep(break_duration_minutes * 60)
            logging.info("Pausa finalizada. Iniciando nova sessão de trabalho.")
            await send_message_to_all(bot, f"✅ Sistema operante novamente!")
        except Exception as e:
            import traceback
            tb_str = traceback.format_exc()
            logging.critical(f"O processo supervisor falhou! Erro: {e}\nTraceback:\n{tb_str}")
            await asyncio.sleep(60)

if __name__ == '__main__':
    logging.info("Verificando e inicializando o banco de dados PostgreSQL...")
    inicializar_db_postgres()
    try:
        asyncio.run(supervisor())
    except KeyboardInterrupt:
        logging.info("Bot encerrado manualmente.")
    except Exception as e:
        logging.critical(f"Erro fatal no supervisor: {e}")

