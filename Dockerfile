# Usamos uma imagem base oficial do Python com o sistema Debian (Bookworm)
FROM python:3.11-slim-bookworm

# Definimos o diretório de trabalho dentro do container
WORKDIR /app

# Atualizamos a lista de pacotes e instalamos as dependências do sistema
# wget e unzip são necessários para baixar o Chrome e o chromedriver
RUN apt-get update && apt-get install -y \
    wget \
    unzip \
    # Dependências essenciais para o Chrome rodar em modo headless
    libglib2.0-0 \
    libnss3 \
    libgconf-2-4 \
    libfontconfig1 \
    libx11-6 \
    libx11-xcb1 \
    libxcb1 \
    libxcomposite1 \
    libxcursor1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxi6 \
    libxrandr2 \
    libxrender1 \
    libxss1 \
    libxtst6 \
    ca-certificates \
    fonts-liberation \
    libappindicator3-1 \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libatspi2.0-0 \
    libcairo2 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libpango-1.0-0 \
    libnspr4 \
    --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Baixamos e instalamos o Google Chrome
RUN wget -q https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
    && dpkg -i google-chrome-stable_current_amd64.deb \
    || apt-get -fy install \
    && rm google-chrome-stable_current_amd64.deb

# Baixamos e instalamos o Chromedriver
RUN wget -q https://storage.googleapis.com/chrome-for-testing-public/125.0.6422.78/linux64/chromedriver-linux64.zip \
    && unzip chromedriver-linux64.zip \
    && mv chromedriver-linux64/chromedriver /usr/bin/chromedriver \
    && rm chromedriver-linux64.zip \
    && rm -rf chromedriver-linux64

# Copiamos o arquivo de dependências do Python e as instalamos
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiamos o script do bot
COPY roulette_monitor.py .

# Comando para iniciar o bot quando o container rodar
CMD ["python", "roulette_monitor.py"]
