import base64
import datetime
import logging
import os
import uuid
from contextlib import asynccontextmanager
from typing import Dict, Any

import cv2
import numpy as np
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from deepface import DeepFace
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, Column, String, DateTime, JSON, Integer, func
from sqlalchemy.orm import sessionmaker, Session, DeclarativeBase

# --- Configuração de Logging ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# --- Configuração do Banco de Dados (PostgreSQL) ---
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@postgres:5432/emotiondb")
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


# --- Modelos de Dados (Pydantic para validação da API) ---
class ImagePayload(BaseModel):
    session_uuid: str = Field(..., description="O UUID da sessão do usuário.")
    image_base64: str = Field(..., description="O frame do vídeo em formato string base64.")


class SessionResponse(BaseModel):
    session_uuid: str


class EmotionAnalysisResponse(BaseModel):
    dominant_emotion: str
    emotions: Dict[str, float]


# --- Modelos do Banco de Dados (SQLAlchemy para tabelas) ---
class SessionInfo(Base):
    __tablename__ = "sessions"
    session_uuid = Column(String, primary_key=True, index=True)
    ip_address = Column(String, nullable=True)
    country = Column(String, nullable=True)
    state = Column(String, nullable=True)
    startedAt = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class EmotionLog(Base):
    __tablename__ = "emotions"
    id = Column(Integer, primary_key=True, index=True)
    session_uuid = Column(String, index=True, nullable=False)
    dominant_emotion = Column(String, nullable=False)
    emotions = Column(JSON, nullable=False)
    createdAt = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


# --- Lógica de Limpeza de Dados ---
def cleanup_old_emotions():
    logger.info("Executando a tarefa de limpeza de emoções antigas...")
    db = SessionLocal()
    try:
        thirty_days_ago = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=30)
        num_deleted = db.query(EmotionLog).filter(EmotionLog.createdAt < thirty_days_ago).delete(
            synchronize_session=False)
        db.commit()
        if num_deleted > 0:
            logger.info(f"Limpeza concluída: {num_deleted} registros antigos de emoção excluídos.")
        else:
            logger.info("Limpeza concluída: Nenhum registro antigo para excluir.")
    except Exception as e:
        logger.error(f"Erro durante a tarefa de limpeza de emoções: {e}")
        db.rollback()
    finally:
        db.close()


# --- Ciclo de Vida da Aplicação (Lifespan) ---
scheduler = AsyncIOScheduler(timezone="UTC")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Iniciando a API...")
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("Tabelas do banco de dados verificadas/criadas com sucesso.")
    except Exception as e:
        logger.error(f"FATAL: Não foi possível conectar ao banco de dados na inicialização: {e}")

    scheduler.add_job(cleanup_old_emotions, IntervalTrigger(days=1), id="cleanup_job", replace_existing=True)
    scheduler.start()
    logger.info("Agendador de limpeza de dados iniciado.")

    yield

    logger.info("Desligando a API...")
    scheduler.shutdown(wait=False)
    logger.info("Agendador desligado.")


# --- Configuração da Aplicação FastAPI ---
app = FastAPI(
    title="API de Análise Emocional",
    description="Processa frames de vídeo para análise de emoções e salva os dados no PostgreSQL.",
    version="1.0.0",
    lifespan=lifespan
)


# --- Dependência de Sessão do Banco de Dados ---
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# --- Configuração de CORS (Cross-Origin Resource Sharing) ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# --- Funções Auxiliares ---
def decode_base64_image(base64_str: str) -> np.ndarray | None:
    try:
        if "," in base64_str:
            _, encoded = base64_str.split(",", 1)
        else:
            encoded = base64_str
        img_data = base64.b64decode(encoded)
        nparr = np.frombuffer(img_data, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("Falha ao decodificar dados da imagem.")
        return img
    except Exception as e:
        logger.error(f"Erro ao decodificar imagem base64: {e}")
        return None


# --- Rotas da API ---
@app.get("/", summary="Health Check")
def read_root() -> Dict[str, str]:
    return {"status": "API de Análise Emocional (PostgreSQL) está online."}


@app.post("/start-session", response_model=SessionResponse, summary="Inicia uma nova sessão")
def start_session(request: Request, db: Session = Depends(get_db)):
    session_uuid = str(uuid.uuid4())
    user_ip = request.headers.get("X-Forwarded-For", request.client.host)

    try:
        new_session = SessionInfo(
            session_uuid=session_uuid,
            ip_address=user_ip,
            country="Desconhecido",
            state="Desconhecido"
        )
        db.add(new_session)
        db.commit()
        logger.info(f"Nova sessão iniciada: {session_uuid} para IP: {user_ip}")
        return SessionResponse(session_uuid=session_uuid)
    except Exception as e:
        db.rollback()
        logger.error(f"Falha ao criar sessão no banco de dados: {e}")
        raise HTTPException(status_code=500, detail="Erro interno ao tentar criar a sessão.")


@app.post("/analyze-emotion", response_model=EmotionAnalysisResponse, summary="Analisa a emoção de uma imagem")
async def analyze_emotion(payload: ImagePayload, db: Session = Depends(get_db)):
    img = decode_base64_image(payload.image_base64)
    if img is None:
        raise HTTPException(status_code=400, detail="Imagem base64 inválida ou corrompida.")

    try:
        analysis_result = DeepFace.analyze(
            img_path=img,
            actions=['emotion'],
            enforce_detection=False,
            detector_backend='opencv'
        )

        if not isinstance(analysis_result, list) or not analysis_result:
            logger.warning(f"DeepFace retornou um resultado inesperado para a sessão {payload.session_uuid}")
            return {"dominant_emotion": "Nenhum rosto detectado", "emotions": {}}

        first_face = analysis_result[0]
        dominant_emotion = first_face.get('dominant_emotion')
        emotions = first_face.get('emotion')

        if not dominant_emotion or not emotions:
            logger.warning(f"Nenhum rosto detectado na análise para a sessão {payload.session_uuid}")
            return {"dominant_emotion": "Nenhum rosto detectado", "emotions": {}}

        # *** INÍCIO DA CORREÇÃO ***
        # Converte os valores de np.float32 para float padrão do Python
        emotions_serializable = {key: float(value) for key, value in emotions.items()}
        # *** FIM DA CORREÇÃO ***

        new_emotion_log = EmotionLog(
            session_uuid=payload.session_uuid,
            dominant_emotion=dominant_emotion,
            emotions=emotions_serializable  # <-- Usa o dicionário corrigido
        )
        db.add(new_emotion_log)
        db.commit()

        # Retorna o dicionário corrigido para o frontend também
        return EmotionAnalysisResponse(dominant_emotion=dominant_emotion, emotions=emotions_serializable)

    except Exception as e:
        db.rollback()
        logger.error(f"Erro na análise do DeepFace ou gravação no BD para sessão {payload.session_uuid}: {e}",
                     exc_info=True)  # Adicionado exc_info=True para um log mais completo
        raise HTTPException(status_code=500, detail="Erro interno durante a análise da emoção.")


# --- Bloco de Execução para Debug Local ---
if __name__ == "__main__":
    import uvicorn

    logger.warning("Iniciando servidor em modo de debug local. O agendador não será executado.")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)