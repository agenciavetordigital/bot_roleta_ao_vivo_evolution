# train_model_duzias.py
import os
import pandas as pd
import joblib
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score
import psycopg2
from urllib.parse import urlparse

DATABASE_URL = os.environ.get('DATABASE_URL')
SEQUENCE_LENGTH = 10

def get_db_connection():
    try:
        result = urlparse(DATABASE_URL)
        conn = psycopg2.connect(database=result.path[1:], user=result.username, password=result.password, host=result.hostname, port=result.port)
        return conn
    except Exception: return None

def get_properties(numero):
    if numero == 0: return 'Verde', 0
    duzia = 1 if 1 <= numero <= 12 else 2 if 13 <= numero <= 24 else 3
    return 'Color', duzia

def train_model():
    print("Iniciando treinamento do modelo de DÚZIAS...")
    conn = get_db_connection()
    if not conn: print("Falha ao conectar ao DB. Abortando."); return
    try:
        df = pd.read_sql("SELECT numero FROM resultados ORDER BY id ASC", conn)
        print(f"Total de {len(df)} giros carregados para o modelo de dúzias.")
    finally:
        conn.close()

    if len(df) < 100:
        print("Dados insuficientes (< 100). Abortando."); return

    df['duzia'] = df['numero'].apply(lambda x: get_properties(x)[1])
    for i in range(1, SEQUENCE_LENGTH + 1):
        df[f'duzia_lag_{i}'] = df['duzia'].shift(i)
    df['target'] = df['duzia']
    df.dropna(inplace=True)
    df = df[df['target'] != 0]

    if df.empty:
        print("Nenhum dado restante após preparação. Abortando."); return

    features = [col for col in df.columns if 'lag' in col]
    X = df[features]; y = df['target']
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)
    
    model = RandomForestClassifier(n_estimators=150, random_state=42, class_weight='balanced', min_samples_leaf=5)
    model.fit(X_train, y_train)
    
    accuracy = accuracy_score(y_test, model.predict(X_test))
    print(f"Acurácia do modelo de Dúzias: {accuracy:.2%}")
    
    joblib.dump(model, 'modelo_duzias.pkl')
    print("Modelo de Dúzias salvo como 'modelo_duzias.pkl'")

if __name__ == '__main__':
    train_model()
