# -*- coding: utf-8 -*-
# VERSÃO FINAL COM MÚLTIPLAS ESTRATÉGIAS DE IA

# --- IMPORTAÇÕES ---
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
import pandas as pd
import joblib
import numpy as np

# --- CONFIGURAÇÕES ESSENCIAIS ---
TOKEN_BOT = os.environ.get('TOKEN_BOT')
CHAT_IDS_STR = os.environ.get('CHAT_ID')
URL_APOSTA = os.environ.get('URL_APOSTA')
DATABASE_URL = os.environ.get('DATABASE_URL')

if not all([TOKEN_BOT, CHAT_IDS_STR, URL_APOSTA, DATABASE_URL]):
    logging.critical("ERRO: Todas as variáveis de ambiente devem ser definidas!")
    exit()

CHAT_IDS = [chat_id.strip() for chat_id in CHAT_IDS_STR.split(',')]
INTERVALO_VERIFICACAO_API = 5
MAX_MARTINGALES = 2

# --- CONFIGURAÇÕES DE ESTRATÉGIA ---
GATILHO_ATRASO_DUZIA = 09
NUMEROS_PARA_ANALISE = 80
GATILHO_CONFIANCA_IA_DUZIAS = 0.47
GATILHO_CONFIANCA_IA_TOP5 = 0.28
SEQUENCE_LENGTH_IA_DUZIAS = 15
SEQUENCE_LENGTH_IA_NUMEROS = 20

# --- CONFIGURAÇÕES DE HUMANIZAÇÃO ---
FUSO_HORARIO_BRASIL = pytz.timezone('America/Sao_Paulo')
WORK_MIN_MINUTES = 3 * 60; WORK_MAX_MINUTES = 5 * 60
BREAK_MIN_MINUTES = 25; BREAK_MAX_MINUTES = 45
HORA_TARDE = 12; HORA_NOITE = 18

# --- MODELOS DE IA ---
MODELO_IA_DUZIAS = None
MODELO_IA_NUMEROS = None

# --- FUNÇÕES DE BANCO DE DADOS E PROPRIEDADES ---
def get_db_connection():
    try:
        result = urlparse(DATABASE_URL); conn = psycopg2.connect(database=result.path[1:], user=result.username, password=result.password, host=result.hostname, port=result.port)
        return conn
    except Exception as e: logging.error(f"Erro ao conectar ao PostgreSQL: {e}"); return None

def inicializar_db_postgres():
    conn = get_db_connection()
    if conn is not None:
        try:
            with conn.cursor() as cur: cur.execute('CREATE TABLE IF NOT EXISTS resultados (id SERIAL PRIMARY KEY, numero INTEGER, cor VARCHAR(10), duzia INTEGER, coluna INTEGER, paridade VARCHAR(10), timestamp TIMESTAMPTZ DEFAULT NOW());'); conn.commit()
            logging.info("Banco de dados e tabela 'resultados' verificados.")
        except Exception as e: logging.error(f"Erro ao inicializar a tabela: {e}")
        finally: conn.close()

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
            with conn.cursor() as cur: cur.execute(sql, (numero, cor, duzia, coluna, paridade)); conn.commit()
            logging.info(f"Número {numero} salvo no PostgreSQL.")
        except Exception as e: logging.error(f"Erro ao salvar número no DB: {e}")
        finally: conn.close()

def buscar_numeros_recentes_para_analise(limite=NUMEROS_PARA_ANALISE):
    conn = get_db_connection()
    if conn is None: return []
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT numero FROM resultados ORDER BY id DESC LIMIT %s;", (limite,))
            return [item[0] for item in cur.fetchall()]
    except Exception as e: logging.error(f"Erro ao buscar números recentes: {e}"); return []
    finally: conn.close()
    
# --- FUNÇÕES DE MACHINE LEARNING ---
def carregar_modelos_ia():
    global MODELO_IA_DUZIAS, MODELO_IA_NUMEROS
    try:
        MODELO_IA_DUZIAS = joblib.load('modelo_duzias.pkl')
        logging.info("🧠 Modelo de IA (Dúzias) carregado com sucesso!")
    except FileNotFoundError:
        logging.warning("Arquivo 'modelo_duzias.pkl' não encontrado. Estratégia correspondente desativada.")
    except Exception as e:
        logging.error(f"Erro ao carregar o modelo de Dúzias: {e}")

    try:
        MODELO_IA_NUMEROS = joblib.load('modelo_numeros.pkl')
        logging.info("🧠 Modelo de IA (Números) carregado com sucesso!")
    except FileNotFoundError:
        logging.warning("Arquivo 'modelo_numeros.pkl' não encontrado. Estratégia correspondente desativada.")
    except Exception as e:
        logging.error(f"Erro ao carregar o modelo de Números: {e}")

def analisar_ia_duzias(numeros_recentes):
    if MODELO_IA_DUZIAS is None or len(numeros_recentes) < SEQUENCE_LENGTH_IA_DUZIAS: return None, 0
    try:
        dados_sequencia = numeros_recentes[:SEQUENCE_LENGTH_IA_DUZIAS]
        features_dict = {}
        for i, numero in enumerate(dados_sequencia):
            _, duzia, _, _ = get_properties(numero)
            features_dict[f'duzia_lag_{i+1}'] = duzia
        df_features = pd.DataFrame([features_dict])
        predicao = MODELO_IA_DUZIAS.predict(df_features)[0]
        probabilidades = MODELO_IA_DUZIAS.predict_proba(df_features)[0]
        indice_predicao = list(MODELO_IA_DUZIAS.classes_).index(predicao)
        confianca = probabilidades[indice_predicao]
        return int(predicao), confianca
    except Exception as e: logging.error(f"Erro na análise com IA de Dúzias: {e}"); return None, 0

def analisar_ia_top5(numeros_recentes):
    if MODELO_IA_NUMEROS is None or len(numeros_recentes) < SEQUENCE_LENGTH_IA_NUMEROS: return None, 0
    try:
        dados_sequencia = numeros_recentes[:SEQUENCE_LENGTH_IA_NUMEROS]
        features_dict = {}
        for i, numero in enumerate(dados_sequencia):
            cor, duzia, _, paridade = get_properties(numero)
            features_dict[f'numero_lag_{i+1}'] = numero; features_dict[f'duzia_lag_{i+1}'] = duzia
            features_dict[f'cor_preto_lag_{i+1}'] = 1 if cor == 'Preto' else 0
            features_dict[f'paridade_par_lag_{i+1}'] = 1 if paridade == 'Par' else 0
        df_features = pd.DataFrame([features_dict])
        probabilidades = MODELO_IA_NUMEROS.predict_proba(df_features)[0]
        classes = MODELO_IA_NUMEROS.classes_
        prob_map = {classes[i]: probabilidades[i] for i in range(len(classes))}
        top_5_numeros = sorted(prob_map, key=prob_map.get, reverse=True)[:5]
        confianca_somada = sum(prob_map[num] for num in top_5_numeros)
        return top_5_numeros, confianca_somada
    except Exception as e: logging.error(f"Erro na análise com IA de Números: {e}"); return None, 0

# --- LÓGICA DAS ESTRATÉGIAS ---
DUZIAS = { 1: list(range(1, 13)), 2: list(range(13, 25)), 3: list(range(25, 37)) }

# --- LÓGICA DO BOT ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
ultimo_numero_processado_api, numero_anterior_estrategia, daily_play_history, daily_messages_sent, active_strategy_state = None, None, [], {}, {}

def reset_daily_messages_tracker(): global daily_messages_sent; daily_messages_sent = {"tarde": False, "noite": False}

def initialize_score():
    score = {"last_check_date": datetime.now(FUSO_HORARIO_BRASIL).date()}
    all_strategies = ["Estratégia Atraso de Dúzias", "Estratégia IA Dúzias", "Estratégia IA Top 5 Números"]
    for name in all_strategies: score[name] = {"wins_sg": 0, "wins_g1": 0, "wins_g2": 0, "losses": 0}
    return score
daily_score = initialize_score()

def reset_strategy_state():
    global active_strategy_state
    active_strategy_state = { "active": False, "strategy_name": "", "martingale_level": 0, "winning_numbers": [], "trigger_number": None, "play_message_ids": {}, "trigger_info": "" }
reset_daily_messages_tracker(); reset_strategy_state()

def buscar_ultimo_numero_api():
    global ultimo_numero_processado_api, numero_anterior_estrategia
    try:
        cache_buster = int(time.time() * 1000); url = f"https://api.jogosvirtual.com/jsons/historico_roletabrasileira.json?_={cache_buster}"
        response = requests.get(url, timeout=10); response.raise_for_status(); dados = response.json()
        lista_de_numeros = dados.get('baralhos', {}).get('0', [])
        if not lista_de_numeros: return None, None
        valor_bruto = lista_de_numeros[-1]
        if valor_bruto is None: return None, None
        try: novo_numero = int(valor_bruto)
        except (ValueError, TypeError): return None, None
        if novo_numero != ultimo_numero_processado_api:
            logging.info(f"✅ Novo giro detectado via API: {novo_numero} (Anterior: {ultimo_numero_processado_api})")
            numero_anterior_estrategia = ultimo_numero_processado_api; ultimo_numero_processado_api = novo_numero
            return novo_numero, numero_anterior_estrategia
        return None, None
    except Exception as e: logging.error(f"Erro em buscar_ultimo_numero_api: {e}"); return None, None

async def processar_numero(bot, numero, numero_anterior):
    if numero is None: return
    salvar_numero_postgres(numero)
    await check_and_reset_daily_score(bot)
    if active_strategy_state["active"]: await handle_active_strategy(bot, numero)
    else: await check_for_new_triggers(bot, numero, numero_anterior)

def analisar_atraso_duzias(numeros_recentes):
    if len(numeros_recentes) < GATILHO_ATRASO_DUZIA: return None, 0
    atrasos = {1: -1, 2: -1, 3: -1}
    for i, numero in enumerate(numeros_recentes):
        _, duzia, _, _ = get_properties(numero)
        if duzia in atrasos and atrasos[duzia] == -1: atrasos[duzia] = i
        if all(v != -1 for v in atrasos.values()): break
    for duzia in atrasos:
        if atrasos[duzia] == -1: atrasos[duzia] = len(numeros_recentes)
    duzia_atrasada = max(atrasos, key=atrasos.get)
    return duzia_atrasada, atrasos[duzia_atrasada]

def format_score_message(title="📊 *Placar do Dia* 📊"):
    messages = [title]; overall_wins, overall_losses = 0, 0
    for name, score in daily_score.items():
        if name == "last_check_date" or not isinstance(score, dict): continue
        strategy_wins = score.get('wins_sg', 0) + score.get('wins_g1', 0) + score.get('wins_g2', 0); strategy_losses = score.get('losses', 0)
        overall_wins += strategy_wins; overall_losses += strategy_losses; total_plays = strategy_wins + strategy_losses
        accuracy = (strategy_wins / total_plays * 100) if total_plays > 0 else 0
        wins_str = f"SG: {score.get('wins_sg', 0)} | G1: {score.get('wins_g1', 0)} | G2: {score.get('wins_g2', 0)}"
        messages.append(f"*{name}* (Assertividade: {accuracy:.1f}%)\n`   `✅ `{wins_str}`\n`   `❌ `{strategy_losses}`")
    total_overall_plays = overall_wins + overall_losses
    overall_accuracy = (overall_wins / total_overall_plays * 100) if total_overall_plays > 0 else 0
    messages.insert(1, f"📈 *Assertividade Geral: {overall_accuracy:.1f}%*")
    return "\n\n".join(messages)

async def send_message_to_all(bot, text, **kwargs):
    for chat_id in CHAT_IDS:
        try: await bot.send_message(chat_id=chat_id, text=text, **kwargs)
        except Exception as e: logging.error(f"Erro ao enviar mensagem para {chat_id}: {e}")

async def send_and_track_play_message(bot, text, **kwargs):
    sent_messages = {}
    for chat_id in CHAT_IDS:
        try: message = await bot.send_message(chat_id=chat_id, text=text, **kwargs); sent_messages[chat_id] = message
        except Exception as e: logging.error(f"Erro ao enviar mensagem para {chat_id}: {e}")
    for chat_id, message in sent_messages.items(): active_strategy_state["play_message_ids"][chat_id] = message.message_id

async def edit_play_messages(bot, new_text, **kwargs):
    for chat_id, message_id in active_strategy_state["play_message_ids"].items():
        try: await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=new_text, **kwargs)
        except Exception as e: logging.warning(f"Não foi possível editar msg {message_id} do chat {chat_id}: {e}")

async def check_and_reset_daily_score(bot):
    global daily_score, daily_play_history
    today_br = datetime.now(FUSO_HORARIO_BRASIL).date()
    if daily_score.get("last_check_date") != today_br:
        logging.info("Novo dia detectado! Enviando relatório e resetando placar.")
        yesterday_str = daily_score.get("last_check_date", "dia anterior").strftime('%d/%m/%Y'); final_scores = format_score_message(title=f"📈 *Relatório Final do Dia {yesterday_str}* 📈")
        streaks = calculate_streaks_for_period(dt_time.min, dt_time.max); streak_report = f"\n\n*Resumo do Dia:*\nSequência Máx. de Vitórias: *{streaks['max_wins']}* ✅\nSequência Máx. de Derrotas: *{streaks['max_losses']}* ❌"
        await send_message_to_all(bot, final_scores + streak_report, parse_mode=ParseMode.MARKDOWN)
        daily_score = initialize_score(); daily_play_history.clear(); reset_daily_messages_tracker()
        await send_message_to_all(bot, "☀️ Bom dia! Um novo dia de análises está começando.")

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
    name = active_strategy_state['strategy_name']; winning_numbers = active_strategy_state['winning_numbers']; trigger_info = active_strategy_state.get('trigger_info', '')
    if name == "Estratégia Atraso de Dúzias":
        return (f"🎯 *Gatilho Estatístico Encontrado!* 🎯\n\n🎲 *Estratégia: {name}*\n"
                f"📈 *Análise: Dúzia {active_strategy_state['trigger_number']} está atrasada há {trigger_info} rodadas!*\n\n"
                f"💰 *Apostar na Dúzia {active_strategy_state['trigger_number']} e no Zero:*\n`{', '.join(map(str, sorted(winning_numbers)))}`")
    if name == "Estratégia IA Dúzias":
        return (f"🤖 *Sinal de IA (Dúzias)!* 🤖\n\n🎲 *Estratégia: {name}*\n"
                f"🧠 *Análise do Modelo: Dúzia {active_strategy_state['trigger_number']} com {trigger_info:.1%} de confiança!*\n\n"
                f"💰 *Apostar na Dúzia {active_strategy_state['trigger_number']} e no Zero:*\n`{', '.join(map(str, sorted(winning_numbers)))}`")
    if name == "Estratégia IA Top 5 Números":
        return (f"🤖 *Sinal de IA (Top 5)!* 🤖\n\n🎲 *Estratégia: {name}*\n"
                f"🧠 *Análise do Modelo: Confiança de {trigger_info:.1%} nos seguintes números!*\n\n"
                f"💰 *Apostar em (Top 5 + Zero):*\n`{', '.join(map(str, sorted(winning_numbers)))}`")
    return ""

async def handle_win(bot, final_number):
    daily_play_history.append({'time': datetime.now(FUSO_HORARIO_BRASIL), 'result': 'win'})
    strategy_name = active_strategy_state["strategy_name"]; win_level = active_strategy_state["martingale_level"]
    if win_level == 0: daily_score[strategy_name]["wins_sg"] += 1; win_type_message = "Vitória sem Gale!"
    else: daily_score[strategy_name][f"wins_g{win_level}"] += 1; win_type_message = f"Vitória no {win_level}º Martingale"
    trigger_display = active_strategy_state.get('trigger_number', 'N/A')
    mensagem_final = (f"✅ *VITÓRIA!*\n\n*{win_type_message}*\n_Estratégia: {strategy_name}_\n_Gatilho: {trigger_display}_\nSaiu: *{final_number}*\n\n{format_score_message()}")
    await edit_play_messages(bot, mensagem_final, parse_mode=ParseMode.MARKDOWN); reset_strategy_state()

async def handle_loss(bot, final_number):
    daily_play_history.append({'time': datetime.now(FUSO_HORARIO_BRASIL), 'result': 'loss'})
    strategy_name = active_strategy_state["strategy_name"]; daily_score[strategy_name]["losses"] += 1
    trigger_display = active_strategy_state.get('trigger_number', 'N/A')
    mensagem_final = (f"❌ *LOSS!*\n\n_Estratégia: {strategy_name}_\n_Gatilho: {trigger_display}_\nSaiu: *{final_number}*\n\n{format_score_message()}")
    await edit_play_messages(bot, mensagem_final, parse_mode=ParseMode.MARKDOWN); reset_strategy_state()

async def handle_martingale(bot, current_number):
    level = active_strategy_state["martingale_level"]; base_message = build_base_signal_message()
    mensagem_editada = (f"{base_message}\n\n------------------------------------\n⏳ *Análise: Entrar no {level}º Martingale...*\nO número *{current_number}* não pagou.")
    await edit_play_messages(bot, mensagem_editada, parse_mode=ParseMode.MARKDOWN)

async def handle_active_strategy(bot, numero):
    _, duzia_do_numero, _, _ = get_properties(numero); winning_numbers = active_strategy_state["winning_numbers"]
    is_win = numero in winning_numbers
    if active_strategy_state['strategy_name'] == "Estratégia IA Dúzias":
        is_win = duzia_do_numero == active_strategy_state['trigger_number'] and numero != 0

    if is_win: await handle_win(bot, numero)
    else:
        active_strategy_state["martingale_level"] += 1
        if active_strategy_state["martingale_level"] <= MAX_MARTINGALES: await handle_martingale(bot, numero)
        else: await handle_loss(bot, numero)

async def check_for_new_triggers(bot, numero, numero_anterior):
    max_len = max(NUMEROS_PARA_ANALISE, SEQUENCE_LENGTH_IA_DUZIAS, SEQUENCE_LENGTH_IA_NUMEROS)
    numeros_recentes = buscar_numeros_recentes_para_analise(max_len)
    
    top_5, conf_top5 = analisar_ia_top5(numeros_recentes)
    if top_5 is not None and conf_top5 >= GATILHO_CONFIANCA_IA_TOP5:
        logging.info(f"Gatilho IA Top 5! Confiança: {conf_top5:.1%}. Números: {top_5}")
        winning_numbers = top_5
        if 0 not in winning_numbers: winning_numbers.append(0)
        active_strategy_state.update({"active": True, "strategy_name": "Estratégia IA Top 5 Números", "winning_numbers": winning_numbers, "trigger_number": ", ".join(map(str,sorted(top_5))), "trigger_info": conf_top5 })
    
    elif MODELO_IA_DUZIAS:
        duzia_ia, conf_duzia = analisar_ia_duzias(numeros_recentes)
        if duzia_ia is not None and conf_duzia >= GATILHO_CONFIANCA_IA_DUZIAS:
            logging.info(f"Gatilho IA Dúzias! Dúzia {duzia_ia} com {conf_duzia:.1%} de confiança.")
            winning_numbers = DUZIAS[duzia_ia].copy()
            if 0 not in winning_numbers: winning_numbers.append(0)
            active_strategy_state.update({"active": True, "strategy_name": "Estratégia IA Dúzias", "winning_numbers": winning_numbers, "trigger_number": duzia_ia, "trigger_info": conf_duzia })

    else:
        duzia_atrasada, atraso = analisar_atraso_duzias(numeros_recentes)
        if atraso >= GATILHO_ATRASO_DUZIA:
            logging.info(f"Gatilho Atraso de Dúzia! Dúzia {duzia_atrasada} a {atraso} rodadas.")
            winning_numbers = DUZIAS[duzia_atrasada].copy(); winning_numbers.append(0)
            active_strategy_state.update({"active": True, "strategy_name": "Estratégia Atraso de Dúzias", "winning_numbers": winning_numbers, "trigger_number": duzia_atrasada, "trigger_info": atraso })

    if active_strategy_state["active"]:
        mensagem = f"{build_base_signal_message()}\n\n[🔗 Fazer Aposta]({URL_APOSTA})\n---\n{format_score_message()}"
        await send_and_track_play_message(bot, mensagem, parse_mode=ParseMode.MARKDOWN)

async def work_session(bot):
    work_duration_minutes = random.randint(WORK_MIN_MINUTES, WORK_MAX_MINUTES)
    session_end_time = datetime.now(FUSO_HORARIO_BRASIL) + timedelta(minutes=work_duration_minutes)
    logging.info(f"Iniciando nova sessão Boot Venon que durará {work_duration_minutes // 60}h e {work_duration_minutes % 60}min.")
    await send_message_to_all(bot, f"Monitoramento de ciclos previsto para durar *{work_duration_minutes // 60}h e {work_duration_minutes % 60}min*.", parse_mode=ParseMode.MARKDOWN)
    while datetime.now(FUSO_HORARIO_BRASIL) < session_end_time:
        await check_and_send_period_messages(bot) # <-- CORREÇÃO AQUI
        numero, numero_anterior = buscar_ultimo_numero_api()
        if numero is not None: await processar_numero(bot, numero, numero_anterior)
        await asyncio.sleep(INTERVALO_VERIFICACAO_API)
    logging.info("Sessão de trabalho Boot Venon concluída.")

async def supervisor():
    bot = telegram.Bot(token=TOKEN_BOT)
    try: await send_message_to_all(bot, f"🤖 Monitoramento Roleta Online Boot Venon!\nIniciando gerenciamento de ciclos.")
    except Exception as e: logging.critical(f"Não foi possível conectar ao Telegram na inicialização: {e}")
    while True:
        try:
            # await check_and_send_period_messages(bot) <-- REMOVIDO DAQUI
            await work_session(bot)
            break_duration_minutes = random.randint(BREAK_MIN_MINUTES, BREAK_MAX_MINUTES)
            logging.info(f"Iniciando pausa de {break_duration_minutes} minutos.")
            await send_message_to_all(bot, f"⏸️ Pausa programada para manutenção Boot Venon.\nDuração: *{break_duration_minutes} minutos*.", parse_mode=ParseMode.MARKDOWN)
            await asyncio.sleep(break_duration_minutes * 60)
            logging.info("Pausa finalizada. Iniciando nova sessão.")
            await send_message_to_all(bot, f"✅ Sistema operante novamente! Boot Venon Online")
        except Exception as e:
            import traceback; tb_str = traceback.format_exc()
            logging.critical(f"O processo supervisor falhou! Erro: {e}\nTraceback:\n{tb_str}"); await asyncio.sleep(60)

if __name__ == '__main__':
    logging.info("Verificando e inicializando o banco de dados PostgreSQL...")
    inicializar_db_postgres()
    logging.info("Carregando modelos de Inteligência Artificial...")
    carregar_modelos_ia()
    try: asyncio.run(supervisor())
    except KeyboardInterrupt: logging.info("Bot encerrado manualmente.")
    except Exception as e: logging.critical(f"Erro fatal no supervisor: {e}")



