# Usa uma imagem base do Debian com Python
FROM python:3.11-slim-bookworm

# Define o diretório de trabalho
WORKDIR /app

# Copia o arquivo de dependências e instala as bibliotecas Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia o script do bot
COPY roulette_monitor.py .

# Define o comando para rodar o bot
CMD ["python", "roulette_monitor.py"]

