# Usa uma imagem base do Python, super leve
FROM python:3.11-slim

# Define o diretório de trabalho dentro do container
WORKDIR /app

# Copia o arquivo de dependências
COPY requirements.txt .

# Instala as dependências
RUN pip install --no-cache-dir -r requirements.txt

# Copia o script do bot
COPY roulette_monitor.py .

# Define o comando para rodar o bot quando o container iniciar
CMD ["python", "roulette_monitor.py"]

