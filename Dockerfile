# Usa uma imagem base do Debian com Python
FROM python:3.11-slim-bookworm

# Instala dependências do sistema necessárias para o Chromium rodar
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    chromium-driver \
    && rm -rf /var/lib/apt/lists/*

# Define o diretório de trabalho
WORKDIR /app

# Copia e instala as dependências do Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia o script do bot
COPY roulette_monitor.py .

# Define o comando para rodar o bot
CMD ["python", "roulette_monitor.py"]

