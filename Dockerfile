# Usa uma imagem base oficial do Python
FROM python:3.11-slim

# Define o diretório de trabalho no container
WORKDIR /app

# Instala o wget e dependências do sistema para o Chrome, incluindo o comando 'which'
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    which \
    --no-install-recommends

# Baixa e instala a versão estável mais recente do Google Chrome
RUN wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | apt-key add - \
    && echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update \
    && apt-get install -y \
    google-chrome-stable \
    chromedriver \
    --no-install-recommends \
    && apt-get purge -y --auto-remove wget \
    && rm -rf /var/lib/apt/lists/*

# A MUDANÇA ESTRATÉGICA: Encontra o caminho do executável do Chrome e o armazena em uma variável de ambiente
ENV CHROME_BINARY_PATH=$(which google-chrome-stable)

# Copia o arquivo de dependências
COPY requirements.txt .

# Instala as dependências do Python
RUN pip install --no-cache-dir -r requirements.txt

# Copia o código da aplicação
COPY roulette_monitor.py .

# Define o comando para rodar a aplicação
CMD ["python", "roulette_monitor.py"]

