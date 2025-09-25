# train_model.py
import os
import pandas as pd
import joblib
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score
import psycopg2
from urllib.parse import urlparse

# --- CONFIGURAÇÕES ---
DATABASE_URL = os.environ.get('DATABASE_URL')
SEQUENCE_LENGTH = 10  # Usaremos os últimos 10 números para prever o próximo

# --- FUNÇÕES AUXILIARES ---
def get_db_connection():
    try:
        result = urlparse(DATABASE_URL)
        conn = psycopg2.connect(database=result.path[1:], user=result.username, password=result.password, host=result.hostname, port=result.port)
        return conn
    except Exception as e:
        print(f"Erro ao conectar ao DB: {e}")
        return None

def get_properties(numero):
    if numero == 0: return 'Verde', 0, 0, 'N/A'
    cor = 'Vermelho' if numero in [1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36] else 'Preto'
    duzia = 1 if 1 <= numero <= 12 else 2 if 13 <= numero <= 24 else 3
    coluna = 3 if numero % 3 == 0 else numero % 3
    paridade = 'Par' if numero % 2 == 0 else 'Ímpar'
    return cor, duzia, coluna, paridade

# --- LÓGICA PRINCIPAL DE TREINAMENTO ---
def train_and_save_model():
    print("Iniciando o processo de treinamento do modelo de IA...")
    
    # 1. Carregar dados do banco de dados
    conn = get_db_connection()
    if not conn:
        print("Falha ao conectar ao banco de dados. Abortando.")
        return
        
    print("Carregando dados do PostgreSQL...")
    try:
        df = pd.read_sql("SELECT numero FROM resultados ORDER BY id ASC", conn)
        print(f"Total de {len(df)} giros carregados.")
    finally:
        conn.close()

    if len(df) < 100:
        print("Dados insuficientes para treinamento (< 100 giros). Abortando.")
        return

    # 2. Engenharia de Features
    print("Criando features e alvos...")
    df['duzia'] = df['numero'].apply(lambda x: get_properties(x)[1])
    
    # Criar sequências de features (ex: duzia_lag_1, duzia_lag_2, etc.)
    for i in range(1, SEQUENCE_LENGTH + 1):
        df[f'duzia_lag_{i}'] = df['duzia'].shift(i)

    # O alvo (target) é a dúzia do giro atual
    df['target'] = df['duzia']
    
    df.dropna(inplace=True)
    df = df[df['target'] != 0] # Ignorar o número 0 como um alvo válido para dúzias

    if df.empty:
        print("Nenhum dado restante após a preparação. Abortando.")
        return

    # 3. Preparar dados para o modelo
    features = [col for col in df.columns if 'lag' in col]
    X = df[features]
    y = df['target']
    
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)
    
    print(f"Tamanho do conjunto de treino: {len(X_train)} | Teste: {len(X_test)}")

    # 4. Treinar o modelo
    print("Treinando o modelo RandomForestClassifier...")
    model = RandomForestClassifier(n_estimators=150, random_state=42, class_weight='balanced', min_samples_leaf=5)
    model.fit(X_train, y_train)
    
    # 5. Avaliar o modelo
    predictions = model.predict(X_test)
    accuracy = accuracy_score(y_test, predictions)
    print(f"Acurácia do modelo no conjunto de teste: {accuracy:.2%}")
    
    # 6. Salvar o modelo treinado
    print("Salvando o modelo em 'modelo_ia.pkl'...")
    joblib.dump(model, 'modelo_ia.pkl')
    print("Modelo salvo com sucesso!")

if __name__ == '__main__':
    train_and_save_model()
