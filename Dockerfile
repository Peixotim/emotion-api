# 1. Imagem Base
FROM python:3.10-slim

# 2. Variáveis de Ambiente
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# 3. Instalar dependências do sistema (para OpenCV)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       libgl1-mesa-glx \
       libglib2.0-0 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# 4. Definir diretório de trabalho
WORKDIR /app

# 5. Instalar dependências Python
# Copia primeiro o requirements.txt para aproveitar o cache do Docker
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 6. Copiar o restante do código da aplicação
COPY . .

# 7. Comando para iniciar o servidor
# Expõe a porta 8000 (que o uvicorn usará)
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0",