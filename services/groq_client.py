import os
from groq import Groq
from typing import cast

GROQ_MODEL = "llama-3.3-70b-versatile"

SYSTEM_PROMPT = """Você é um assistente de IA avançado, inteligente e direto.

REGRAS DE FORMATAÇÃO (siga sempre):
1. Responda em Português do Brasil.
2. Seja claro, objetivo e bem estruturado.
3. Use markdown para formatação de texto (negrito, listas, títulos).
4. Use blocos de código fenced com linguagem declarada: ```python, ```html, etc.
5. Quando gerar código com nome de arquivo óbvio, adicione comentário na 1ª linha: # filename: app.py

REGRA CRÍTICA — ARTEFATOS (PDF, DOCX, XLSX, CSV, PNG, PPTX):
- SOMENTE sinalize um artefato se o usuário EXPLICITAMENTE pedir para gerar/criar/exportar um arquivo.
- Pesquisar, listar, resumir ou responder perguntas NUNCA deve gerar artefato automaticamente.
- Palavras-chave que autorizam artefato: "gere um PDF", "crie uma planilha", "exporta para Excel",
  "quero um relatório em Word", "salva como PPTX", "gera um arquivo", "cria um documento".
- Quando autorizado, adicione UMA única linha no final da resposta:
  [ARTEFATO: tipo=pdf titulo="Título do arquivo"]

EXEMPLOS:
Usuário pede busca/listagem: responda normalmente, SEM artefato.
Usuário pede "Crie um PDF com esses dados": responda + [ARTEFATO: tipo=pdf titulo="Nome"]
Usuário pede "Exporta para Excel": responda + [ARTEFATO: tipo=xlsx titulo="Nome"]
"""


def get_groq_client() -> Groq:
    """Retorna instância do cliente Groq com a API key do ambiente."""
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY não configurada no ambiente.")
    return Groq(api_key=api_key)


def chat_completion(messages: list[dict], stream: bool = False):
    """
    Chama a API de chat completions da Groq.
    Retorna o objeto de resposta (stream ou completo).
    """
    client = get_groq_client()

    full_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + messages

    return client.chat.completions.create(  # type: ignore
        model=GROQ_MODEL,
        messages=full_messages,  # type: ignore
        stream=stream,
        max_tokens=4096,
        temperature=0.7,
    )