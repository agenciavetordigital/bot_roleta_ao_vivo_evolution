# Usa uma imagem base do Debian com Python
FROM python:3.11-slim-bookworm

# Define variáveis de ambiente para evitar prompts interativos
ENV DEBIAN_FRONTEND=noninteractive

# Atualiza a lista de pacotes e instala o Chromium e o Chromedriver
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    chromium-driver \
    # Limpa o cache para manter a imagem pequena
    && rm -rf /var/lib/apt/lists/*

# Define o diretório de trabalho
WORKDIR /app

# Copia o arquivo de dependências e instala as bibliotecas Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia o script do bot
COPY roulette_monitor.py .

# Define o comando para rodar o bot
CMD ["python", "roulette_monitor.py"]

