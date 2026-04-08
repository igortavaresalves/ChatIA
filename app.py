import json
import os
import uuid
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()  # carrega .env

from services.orchestrator import process_chat, process_chat_stream
from services.artifact_service import generate_artifact, get_mime_type, GENERATORS
from services.code_artifact_service import generate_file, get_mime_type as get_code_mime_type

app = FastAPI(title="AI Chat", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve arquivos estáticos (HTML, CSS, JS)
static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


class Message(BaseModel):
    role: str       # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    messages: list[Message]
    use_web: bool = False
    stream: bool = False


class ArtifactRequest(BaseModel):
    type: str       # pdf | docx | xlsx | csv | png | pptx
    title: str
    content: str = ""


@app.get("/")
async def index():
    """Serve a página principal do chat."""
    return FileResponse(str(static_dir / "index.html"))


@app.get("/health")
async def health():
    """Endpoint de health check."""
    groq_ok  = bool(os.getenv("GROQ_API_KEY"))
    tavily_ok = bool(os.getenv("TAVILY_API_KEY"))
    return {
        "status": "ok",
        "groq_configured": groq_ok,
        "tavily_configured": tavily_ok,
        "supported_artifacts": list(GENERATORS.keys()),
    }


@app.post("/chat")
async def chat(req: ChatRequest):
    """
    Endpoint principal de chat.
    - stream=False: retorna JSON estruturado com chunks e artefatos
    - stream=True: retorna SSE com texto bruto (frontend parseia ao final)
    """
    messages = [m.model_dump() for m in req.messages]

    if req.stream:
        # Streaming SSE: envia texto bruto token a token
        def generate():
            for token in process_chat_stream(messages, use_web=req.use_web):
                yield f"data: {json.dumps({'token': token})}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # Modo não-stream: retorna JSON completo
    result = process_chat(messages, use_web=req.use_web)
    return JSONResponse(result)


@app.post("/artifact/generate")
async def artifact_generate(req: ArtifactRequest):
    """
    Gera um artefato real (DOCX, PDF, XLSX, CSV, PNG, PPTX, ou arquivos de código) e
    retorna o arquivo para download direto.
    """
    from services.code_artifact_service import LANGUAGE_EXT_MAP

    # Verificar se é tipo de código
    if req.type in LANGUAGE_EXT_MAP:
        # Criar artefato de código temporário
        from services.code_artifact_service import create_artifact
        artifact = create_artifact(
            conversation_id="temp",
            message_id="temp",
            filename=req.title,
            extension=LANGUAGE_EXT_MAP[req.type],
            language=req.type,
            content=req.content,
        )
        file_path = generate_file(artifact)
        mime = get_code_mime_type(artifact.extension)
    elif req.type in GENERATORS:
        file_path = generate_artifact(req.type, req.title, req.content)
        mime = get_mime_type(req.type)
    else:
        raise HTTPException(400, f"Tipo não suportado: {req.type}")

    filename = Path(file_path).name

    return FileResponse(
        path=file_path,
        media_type=mime,
        filename=filename,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/artifact/types")
async def artifact_types():
    """Lista os tipos de artefato suportados."""
    from services.code_artifact_service import LANGUAGE_EXT_MAP
    code_types = list(LANGUAGE_EXT_MAP.keys())
    return {"types": list(GENERATORS.keys()) + code_types}
