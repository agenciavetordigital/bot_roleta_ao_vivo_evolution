# Usa uma imagem base oficial do Python
FROM python:3.11-slim

# Define o diretório de trabalho no container
WORKDIR /app

# Instala dependências do sistema essenciais
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    ca-certificates \
    --no-install-recommends

# Atualiza a lista de pacotes e instala o NAVEGADOR Chromium e o DRIVER correspondente
RUN apt-get update \
    && apt-get install -y \
    chromium \
    chromium-driver \
    --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Copia o arquivo de dependências
COPY requirements.txt .

# Instala as dependências do Python
RUN pip install --no-cache-dir -r requirements.txt

# Copia o código da aplicação
COPY roulette_monitor.py .

# Define o comando para rodar a aplicação
CMD ["python", "roulette_monitor.py"]

