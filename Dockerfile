# Usa uma imagem base oficial do Python
FROM python:3.11-slim

# Define o diretório de trabalho no container
WORKDIR /app

# Instala dependências do sistema para o Chrome
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    --no-install-recommends

# Baixa e instala a versão estável mais recente do Google Chrome e o Chromedriver
RUN wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | apt-key add - \
    && echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update \
    && apt-get install -y \
    google-chrome-stable \
    chromedriver \
    --no-install-recommends \
    && apt-get purge -y --auto-remove wget \
    && rm -rf /var/lib/apt/lists/*

# Copia o arquivo de dependências
COPY requirements.txt .

# Instala as dependências do Python
RUN pip install --no-cache-dir -r requirements.txt

# Copia o código da aplicação
COPY roulette_monitor.py .

# Define o comando para rodar a aplicação
CMD ["python", "roulette_monitor.py"]

