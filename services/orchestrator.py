import os
from services.groq_client import chat_completion
from services.response_parser import parse_response, Chunk, ArtifactIntent


def _web_search(question: str) -> list[dict]:
    """Busca via Tavily se a chave estiver configurada."""
    api_key = os.getenv("TAVILY_API_KEY", "")
    if not api_key or api_key == "tvly-xxx":
        return []

    q = question.strip()
    if not q:
        print("[Tavily] Ignorando busca web: consulta vazia")
        return []

    try:
        from tavily import TavilyClient
        from tavily.errors import BadRequestError, InvalidAPIKeyError, UsageLimitExceededError

        client = TavilyClient(api_key=api_key)
        resp = client.search(query=q, search_depth="basic", max_results=5)
        return resp.get("results", [])
    except BadRequestError as e:
        print(f"[Tavily] Bad Request: {e}. query={q!r}")
        return []
    except InvalidAPIKeyError:
        print("[Tavily] API key inválida ou expirada. Verifique TAVILY_API_KEY.")
        return []
    except UsageLimitExceededError as e:
        print(f"[Tavily] Limite de requisições excedido: {e}")
        return []
    except Exception as e:
        print(f"[Tavily] Erro inesperado: {e}. query={q!r}")
        return []


def build_web_context(results: list[dict]) -> str:
    """Formata os resultados de busca como contexto para o prompt."""
    if not results:
        return ""
    lines = ["**Contexto web (fontes recentes):**"]
    for i, r in enumerate(results, 1):
        lines.append(f"[{i}] {r.get('title','')} — {r.get('url','')}\n{r.get('content','')[:300]}")
    return "\n\n".join(lines)


def process_chat(
    messages: list[dict],
    use_web: bool = False,
) -> dict:
    """
    Fluxo principal (sem streaming):
    1. Opcionalmente faz busca web
    2. Injeta contexto no último user message
    3. Chama Groq
    4. Parseia a resposta
    5. Retorna JSON estruturado
    """
    augmented = list(messages)

    # Busca web — injeta contexto na última mensagem do usuário
    web_sources = []
    if use_web:
        last_user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        web_results = _web_search(last_user)
        if web_results:
            web_sources = [
                {"id": i+1, "title": r.get("title",""), "url": r.get("url","")}
                for i, r in enumerate(web_results)
            ]
            context = build_web_context(web_results)
            # Adiciona contexto como mensagem de sistema temporária
            augmented = list(messages)
            augmented[-1] = {
                "role": "user",
                "content": f"{context}\n\n---\n\n{messages[-1]['content']}"
            }

    # Chama Groq (modo não-stream)
    response = chat_completion(augmented, stream=False)
    raw_text = response.choices[0].message.content or ""

    # Parseia chunks e artefatos
    chunks, artifact_intents = parse_response(raw_text)

    return _build_response(chunks, artifact_intents, web_sources, raw_text)


def process_chat_stream(messages: list[dict], use_web: bool = False):
    """
    Versão streaming: retorna generator de texto bruto.
    O frontend recebe chunks SSE e reconstrói o texto.
    """
    augmented = list(messages)

    if use_web:
        last_user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        web_results = _web_search(last_user)
        if web_results:
            context = build_web_context(web_results)
            augmented[-1] = {
                "role": "user",
                "content": f"{context}\n\n---\n\n{messages[-1]['content']}"
            }

    stream = chat_completion(augmented, stream=True)
    for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta


def _build_response(
    chunks: list[Chunk],
    artifact_intents: list[ArtifactIntent],
    web_sources: list[dict],
    raw: str,
) -> dict:
    """Constrói o payload JSON de resposta para o frontend."""
    from services.groq_client import GROQ_MODEL

    return {
        "message": "",
        "chunks": [
            {
                "type": c.type,
                "content": c.content,
                "language": c.language,
                "filename": c.filename,
            }
            for c in chunks
        ],
        "artifacts": [
            {
                "type": a.type,
                "title": a.title,
                "status": "ready_to_generate",
            }
            for a in artifact_intents
        ],
        "sources": web_sources,
        "meta": {
            "model": GROQ_MODEL,
            "streamed": False,
            "raw_length": len(raw),
        },
    }
