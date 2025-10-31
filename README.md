# 🚀 API de Análise Emocional

Esta é a API de backend para o projeto de Dashboard Emocional. Construída em Python com FastAPI, esta API é responsável por:

1.  Receber frames de vídeo (imagens base64) de um cliente frontend.
2.  Analisar esses frames em tempo real usando a biblioteca `DeepFace` para detetar emoções.
3.  Salvar os dados da sessão e os resultados da análise numa base de dados PostgreSQL.
4.  Excluir automaticamente os dados de emoção após 30 dias para garantir a privacidade.

Este projeto é totalmente containerizado com Docker.

---

## ✨ Funcionalidades Principais

* **API Robusta:** Construída com [FastAPI](https://fastapi.tiangolo.com/) para alta performance.
* **Análise de IA:** Utiliza o `DeepFace` com backend `OpenCV` para uma análise de emoções rápida e eficiente.
* **Base de Dados SQL:** Persiste todos os dados num servidor [PostgreSQL](https://www.postgresql.org/) robusto, gerido pelo [SQLAlchemy](https://www.sqlalchemy.org/).
* **Privacidade Primeiro:** Uma tarefa agendada (`APScheduler`) corre diariamente para apagar todos os registos de emoção com mais de 30 dias.
* **Totalmente Containerizado:** Configuração de "um comando" (`docker-compose up`) para iniciar a API e a Base de Dados.

## 🛠️ Tecnologias Utilizadas

| Tecnologia | Propósito |
| :--- | :--- |
| 🐳 **Docker & Docker Compose** | Orquestração de containers |
| 🐍 **Python 3.10** | Linguagem principal |
| 🚀 **FastAPI** | Framework da API |
| 🐘 **PostgreSQL 15** | Base de dados relacional |
| 🧱 **SQLAlchemy** | ORM para interagir com o PostgreSQL |
| 🧠 **DeepFace** | Biblioteca de análise facial e de emoções |
| 🕒 **APScheduler** | Agendador da tarefa de limpeza (TTL) |

---

## 🏎️ Como Iniciar (Guia Rápido)

Siga estes passos para ter o backend a rodar localmente.

### Pré-requisitos

* [Docker](https://www.docker.com/products/docker-desktop/)
* [Docker Compose](https://docs.docker.com/compose/install/) (geralmente já vem com o Docker Desktop)

### 1. Estrutura de Ficheiros

Certifique-se de que a sua pasta de backend contém os 4 ficheiros seguintes:
    emotion-api/ 
        ├── 📄 main.py 
        ├── 🐳 Dockerfile
        ├── ⚙️ docker-compose.yml 
        └── 📋 requirements.txt


### 2. Iniciar os Serviços

1.  Abra um terminal na pasta `emotion-api/`.
2.  Execute o comando para construir as imagens e iniciar os containers:

    ```bash
    docker-compose up --build
    ```

3.  A API estará agora a rodar e acessível em `http://localhost:8000`.
4.  A base de dados PostgreSQL estará acessível na porta `5433` (para evitar conflitos com a porta `5432` padrão).

### 🚨 Troubleshooting (Resolução de Problemas)

* **Erro: `address already in use` na porta `5432`**
    * **Causa:** Você já tem um serviço PostgreSQL a rodar na sua máquina local.
    * **Solução:** O ficheiro `docker-compose.yml` que criámos já resolve isto! Ele está configurado para usar a porta **5433** do seu computador. Se mesmo assim tiver um conflito, pode alterar esta linha no `docker-compose.yml`:
        ```yaml
        ports:
          - "5433:5432" # Altere "5433" para qualquer outra porta livre (ex: "5434:5432")
        ```

---

## 📖 Endpoints da API

A API expõe os seguintes endpoints (disponíveis em `http://localhost:8000/docs`):

### `GET /`
* **Descrição:** Verificação de "saúde" da API.
* **Resposta (200 OK):**
    ```json
    { "status": "API de Análise Emocional (PostgreSQL) está online." }
    ```

### `POST /start-session`
* **Descrição:** Inicia uma nova sessão de utilizador e retorna um UUID único.
* **Resposta (200 OK):**
    ```json
    { "session_uuid": "algum-uuid-unico-aqui" }
    ```

### `POST /analyze-emotion`
* **Descrição:** Recebe um frame de vídeo e o UUID da sessão, analisa-o e guarda o resultado.
* **Corpo da Requisição (JSON):**
    ```json
    {
      "session_uuid": "o-uuid-recebido-antes",
      "image_base64": "data:image/jpeg;base64,iVBORw0KGgo..."
    }
    ```
* **Resposta (200 OK):**
    ```json
    {
      "dominant_emotion": "happy",
      "emotions": {
        "angry": 0.01,
        "disgust": 0.0,
        "fear": 0.12,
        "happy": 95.5,
        "sad": 1.2,
        "surprise": 0.1,
        "neutral": 3.07
      }
    }
    ```