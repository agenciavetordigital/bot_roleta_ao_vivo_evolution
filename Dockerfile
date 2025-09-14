# Usa uma imagem base oficial do Python
FROM python:3.11-slim

# Define o diretório de trabalho no container
WORKDIR /app

# Instala dependências do sistema essenciais para adicionar novos repositórios e para o Chrome
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    ca-certificates \
    --no-install-recommends

# MÉTODO MODERNO E CORRETO PARA ADICIONAR A CHAVE DO GOOGLE CHROME
# Baixa a chave, converte para o formato GPG e salva no diretório correto
RUN wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /usr/share/keyrings/google-chrome-keyring.gpg

# Adiciona o repositório do Google Chrome, apontando para a chave que acabamos de salvar
RUN echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome-keyring.gpg] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google-chrome.list

# Atualiza a lista de pacotes e instala o Chrome e o Chromedriver
RUN apt-get update \
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

