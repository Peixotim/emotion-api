# 1. Imagem Base
# Começamos com uma imagem oficial do Python, versão 3.10, na variante 'slim' (menor).
FROM python:3.10-slim

# 2. Variáveis de Ambiente
# Evita que o Python gere arquivos .pyc, economizando espaço.
ENV PYTHONDONTWRITEBYTECODE 1
# Garante que os logs do Python apareçam imediatamente no terminal do Docker.
ENV PYTHONUNBUFFERED 1

# 3. Instalar dependências do sistema
# O OpenCV (usado pelo DeepFace) precisa de algumas bibliotecas do sistema para funcionar.
# 'apt-get update' atualiza a lista de pacotes.
# 'apt-get install' instala as bibliotecas necessárias.
# '--no-install-recommends' evita instalar pacotes opcionais.
# 'apt-get clean' e 'rm' limpam o cache para manter a imagem final pequena.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       libgl1 \
       libglib2.0-0 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# 4. Definir diretório de trabalho
# Define o diretório padrão dentro do container para os comandos seguintes.
WORKDIR /app

# 5. Instalar dependências Python
# Copiamos apenas o 'requirements.txt' primeiro para aproveitar o cache do Docker.
# Se este arquivo não mudar, o Docker reutilizará a camada de cache desta instalação,
# tornando os builds futuros muito mais rápidos.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 6. Copiar o restante do código da aplicação
# Copia todos os outros arquivos (como main.py) para o diretório de trabalho /app.
COPY . .

# 7. Comando para iniciar o servidor
# Expõe a porta 8000 para que o Docker possa mapeá-la para o host.
EXPOSE 8000
# Define o comando que será executado quando o container iniciar.
# Inicia o servidor Uvicorn, que servirá nossa aplicação FastAPI.
# '--host 0.0.0.0' faz o servidor ser acessível de fora do container.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]