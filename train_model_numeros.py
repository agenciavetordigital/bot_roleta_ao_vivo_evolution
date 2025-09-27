# train_model_numeros.py (versão 3.0 - Com Features Agregadas)
import os
import pandas as pd
import joblib
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score
import psycopg2
from urllib.parse import urlparse
from scipy.stats import entropy

# --- CONFIGURAÇÕES ---
DATABASE_URL = os.environ.get('DATABASE_URL')
SEQUENCE_LENGTH = 15
ANALYSIS_WINDOW = 50 # Janela para calcular features estatísticas

# --- FUNÇÕES AUXILIARES ---
def get_db_connection():
    try:
        result = urlparse(DATABASE_URL)
        conn = psycopg2.connect(database=result.path[1:], user=result.username, password=result.password, host=result.hostname, port=result.port)
        return conn
    except Exception: return None

def get_properties(numero):
    if numero == 0: return 'Verde', 0, 0, 'N/A'
    cor = 'Vermelho' if numero in [1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36] else 'Preto'
    duzia = 1 if 1 <= numero <= 12 else 2 if 13 <= numero <= 24 else 3
    coluna = 3 if numero % 3 == 0 else numero % 3
    paridade = 'Par' if numero % 2 == 0 else 'Ímpar'
    return cor, duzia, coluna, paridade

# --- LÓGICA PRINCIPAL DE TREINAMENTO ---
def train_and_save_model():
    print("Iniciando treinamento do modelo v3 (com Features Agregadas)...")
    conn = get_db_connection()
    if not conn: print("Falha ao conectar ao DB. Abortando."); return
    try:
        df = pd.read_sql("SELECT numero FROM resultados ORDER BY id ASC", conn)
        print(f"Total de {len(df)} giros carregados.")
    finally:
        conn.close()

    if len(df) < 200:
        print(f"Dados insuficientes (< 200). Abortando."); return

    print("Criando features e alvos...")
    df['duzia'] = df['numero'].apply(lambda x: get_properties(x)[1])
    df['cor_preto'] = df['numero'].apply(lambda x: 1 if get_properties(x)[0] == 'Preto' else 0)
    df['paridade_par'] = df['numero'].apply(lambda x: 1 if get_properties(x)[3] == 'Par' else 0)
    
    # Features de sequência (Lag)
    for i in range(1, SEQUENCE_LENGTH + 1):
        df[f'numero_lag_{i}'] = df['numero'].shift(i)
        df[f'duzia_lag_{i}'] = df['duzia'].shift(i)
        
    # Novas Features Estatísticas Agregadas
    # Usamos uma janela de 50 giros anteriores para calcular as estatísticas
    rolling_window = df['numero'].shift(1).rolling(window=ANALYSIS_WINDOW)
    
    # 1. Entropia
    df['feature_entropy'] = rolling_window.apply(lambda x: entropy(pd.Series(x).value_counts(normalize=True)), raw=False)
    # 2. Números Únicos
    df['feature_unique_count'] = rolling_window.apply(lambda x: len(pd.unique(x)), raw=False)

    df['target'] = df['numero']
    df.dropna(inplace=True)

    if df.empty:
        print("Nenhum dado restante após preparação. Abortando."); return

    features = [col for col in df.columns if 'lag' in col or 'feature' in col]
    X = df[features]; y = df['target']
    
    if len(y.unique()) < 37:
        print(f"Atenção: Apenas {len(y.unique())} números únicos encontrados. Treinando com o disponível.")

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)
    
    print("Treinando o modelo RandomForestClassifier v3...")
    model = RandomForestClassifier(n_estimators=100, max_depth=15, random_state=42, class_weight='balanced', min_samples_leaf=3, n_jobs=-1)
    model.fit(X_train, y_train)
    
    accuracy = accuracy_score(y_test, model.predict(X_test))
    print(f"Acurácia do modelo v3 (Top 1): {accuracy:.2%}")
    
    # Salvamos o modelo e a lista de features que ele espera
    model_data = {'model': model, 'features': features}
    joblib.dump(model_data, 'modelo_numeros.pkl')
    print("Modelo de Números v3 salvo como 'modelo_numeros.pkl'")

if __name__ == '__main__':
    train_and_save_model()
