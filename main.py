import cv2
import numpy as np
import base64
import os
import uuid
import datetime
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from contextlib import asynccontextmanager
from sqlalchemy import create_engine, Column, String, DateTime, JSON, Integer, func
from sqlalchemy.orm import sessionmaker, Session, declarative_base
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from deepface import DeepFace
import logging

# Configura o logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Configuração do Banco de Dados (PostgreSQL) ---

# URL de conexão: postgresql://[user]:[password]@[host]:[port]/[database]
# "postgres" é o nome do serviço no docker-compose.yml
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@postgres:5432/emotiondb")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# --- Modelos de Dados (Pydantic) ---

class ImagePayload(BaseModel):
    session_uuid: str
    image_base64: str  # Espera uma string base64 (ex: data:image/jpeg;base64,...)


class SessionResponse(BaseModel):
    session_uuid: str


# --- Modelos do Banco de Dados (SQLAlchemy) ---

class SessionInfo(Base):
    __tablename__ = "sessions"

    session_uuid = Column(String, primary_key=True, index=True)
    ip_address = Column(String)
    country = Column(String)
    state = Column(String)
    startedAt = Column(DateTime(timezone=True), server_default=func.now())


class EmotionLog(Base):
    __tablename__ = "emotions"

    id = Column(Integer, primary_key=True, index=True)
    session_uuid = Column(String, index=True)
    dominant_emotion = Column(String)
    emotions = Column(JSON)  # Tipo JSON nativo do PostgreSQL
    createdAt = Column(DateTime(timezone=True), server_default=func.now())


# --- Lógica de Limpeza (Substituição do TTL) ---

def cleanup_old_emotions():
    """Remove registros de emoções com mais de 30 dias."""
    logger.info("Executando a tarefa de limpeza de emoções antigas...")
    db = SessionLocal()
    try:
        # Define o ponto de corte para 30 dias atrás
        thirty_days_ago = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=30)

        # Deleta registros mais antigos que o ponto de corte
        num_deleted = db.query(EmotionLog).filter(EmotionLog.createdAt < thirty_days_ago).delete(
            synchronize_session=False)
        db.commit()

        if num_deleted > 0:
            logger.info(f"Limpeza concluída: {num_deleted} registros antigos de emoção excluídos.")
        else:
            logger.info("Limpeza concluída: Nenhum registro antigo para excluir.")
    except Exception as e:
        logger.error(f"Erro durante a limpeza de emoções: {e}")
        db.rollback()
    finally:
        db.close()


# --- Ciclo de Vida da Aplicação (Lifespan) ---

scheduler = AsyncIOScheduler(timezone="UTC")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ao iniciar
    logger.info("Iniciando a API e o agendador de limpeza...")

    # Tenta criar as tabelas (seguro para re-executar)
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("Tabelas do banco de dados verificadas/criadas.")
    except Exception as e:
        logger.error(f"Não foi possível conectar ou criar tabelas no banco de dados: {e}")
        # Dependendo da gravidade, você pode querer impedir a inicialização

    # Agenda a limpeza para rodar a cada 24 horas (86400 segundos)
    scheduler.add_job(cleanup_old_emotions, IntervalTrigger(days=1), id="cleanup_job", replace_existing=True)
    scheduler.start()
    logger.info("Agendador de limpeza iniciado, rodará a cada 24 horas.")

    yield

    # Ao desligar
    logger.info("Desligando o agendador...")
    scheduler.shutdown(wait=False)
    logger.info("API desligada.")


# --- Configuração do Aplicativo ---

app = FastAPI(
    title="API de Análise Emocional (PostgreSQL)",
    description="Recebe frames de vídeo, analisa emoções com DeepFace e salva dados no PostgreSQL.",
    lifespan=lifespan  # Adiciona o gerenciador de ciclo de vida
)


# --- Dependência de Sessão do BD ---

def get_db():
    """Fornece uma sessão de banco de dados para a rota."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# --- Configuração de CORS ---
# Permite que seu frontend (ex: localhost:3000) se comunique com este backend (ex: localhost:8000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Em produção, restrinja isso! (ex: "http://seu-dominio.com")
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Funções Auxiliares ---

def decode_base64_image(base64_str: str):
    """Decodifica uma string base64 (com ou sem prefixo) para uma imagem OpenCV."""
    try:
        # Remove o prefixo (ex: "data:image/jpeg;base64,")
        if "," in base64_str:
            _, encoded = base64_str.split(",", 1)
        else:
            encoded = base64_str

        # Decodifica
        img_data = base64.b64decode(encoded)

        # Converte para um array numpy
        nparr = np.frombuffer(img_data, np.uint8)

        # Converte para uma imagem OpenCV
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if img is None:
            raise ValueError("Não foi possível decodificar a imagem. Os dados podem estar corrompidos.")
        return img
    except Exception as e:
        logger.error(f"Erro ao decodificar base64: {e}")
        return None


# --- Rotas da API ---

@app.get("/")
def read_root():
    return {"status": "API de Análise Emocional (PostgreSQL) está online."}


@app.post("/start-session", response_model=SessionResponse)
def start_session(request: Request, db: Session = Depends(get_db)):
    """
    Registra o início de uma nova sessão de usuário.
    Salva IP, UUID da sessão no PostgreSQL.
    """
    session_uuid = str(uuid.uuid4())

    # Tenta obter o IP real, considerando proxies (comum em produção)
    user_ip = request.headers.get("X-Forwarded-For", request.client.host)

    # Lógica de GeoIP (a implementar com serviço externo, ex: MaxMind)
    user_country = "Desconhecido"
    user_state = "Desconhecido"

    try:
        new_session = SessionInfo(
            session_uuid=session_uuid,
            ip_address=user_ip,
            country=user_country,
            state=user_state,
            startedAt=datetime.datetime.now(datetime.timezone.utc)  # Garante UTC
        )
        db.add(new_session)
        db.commit()

        logger.info(f"Nova sessão iniciada: {session_uuid} para IP: {user_ip}")
        return SessionResponse(session_uuid=session_uuid)

    except Exception as e:
        db.rollback()
        logger.error(f"Erro ao criar sessão: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao criar sessão: {e}")


@app.post("/analyze-emotion")
async def analyze_emotion(payload: ImagePayload, db: Session = Depends(get_db)):
    """
    Recebe um frame (base64) e o UUID da sessão, analisa a emoção
    e salva o resultado no banco de dados.
    """

    # 1. Decodificar a imagem
    img = decode_base64_image(payload.image_base64)
    if img is None:
        raise HTTPException(status_code=400, detail="Formato de imagem base64 inválido ou corrompido.")

    # 2. Analisar Emoção com DeepFace
    try:
        # enforce_detection=False: Não lança erro se nenhum rosto for encontrado.
        analysis = DeepFace.analyze(
            img_path=img,
            actions=['emotion'],
            enforce_detection=False,
            detector_backend='opencv'  # 'opencv' é mais rápido, 'ssd' ou 'mtcnn' são mais precisos
        )

        # DeepFace retorna uma lista; pegamos o primeiro rosto detectado
        if not analysis or not isinstance(analysis, list) or 'dominant_emotion' not in analysis[0]:
            logger.warning(f"Nenhum rosto detectado na análise para sessão {payload.session_uuid}")
            return {"dominant_emotion": "Nenhum rosto detectado", "emotions": {}}

        result = analysis[0]
        dominant_emotion = result['dominant_emotion']
        emotions = result['emotion']  # Dicionário com todas as emoções

        # 3. Salvar resultado no Banco de Dados
        new_emotion_log = EmotionLog(
            session_uuid=payload.session_uuid,
            dominant_emotion=dominant_emotion,
            emotions=emotions,  # SQLAlchemy lida com a serialização JSON
            createdAt=datetime.datetime.now(datetime.timezone.utc)  # Garante UTC
        )
        db.add(new_emotion_log)
        db.commit()

        # 4. Retornar para o Frontend
        return {
            "dominant_emotion": dominant_emotion,
            "emotions": emotions
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Erro na análise do DeepFace ou gravação no BD: {e}")
        raise HTTPException(status_code=500, detail=f"Erro interno na análise: {e}")


# --- Execução (para debug local) ---
if __name__ == "__main__":
    import uvicorn

    logger.warning("Iniciando servidor localmente (sem lifespan/agendador)...")
    logger.warning("Use 'uvicorn main:app --reload' para testar com o lifespan.")

    # Garante que tabelas existem para debug local
    try:
        Base.metadata.create_all(bind=engine)
    except Exception as e:
        logger.error(f"Não foi possível conectar ao BD no modo debug: {e}")

    uvicorn.run(app, host="0.0.0.0", port=8000)