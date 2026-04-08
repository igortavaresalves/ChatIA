import re
from dataclasses import dataclass, field


@dataclass
class Chunk:
    type: str           # "text" | "code"
    content: str
    language: str = ""
    filename: str = ""


@dataclass
class ArtifactIntent:
    type: str           # pdf | docx | xlsx | csv | png | pptx
    title: str
    status: str = "pending"


# Mapa de heurísticas para inferir linguagem quando não declarada
LANG_HINTS: dict[str, list[str]] = {
    "python":     ["def ", "import ", "print(", "class ", "if __name__"],
    "javascript": ["const ", "let ", "var ", "function ", "=>", "console.log"],
    "typescript": ["interface ", ": string", ": number", ": boolean", "as const"],
    "html":       ["<!DOCTYPE", "<html", "<div", "<body", "<head"],
    "css":        ["{", "}", "px;", "color:", "margin:", "padding:"],
    "csharp":     ["using ", "namespace ", "public class", "static void"],
    "react":      ["jsx", "useState", "useEffect", "return (", "<>"],
    "markdown":   ["# ", "## ", "- [ ]", "**", "__"],
}

# Regex para bloco de código fenced: ```lang\n...```
CODE_BLOCK_RE = re.compile(r"```(\w*)\n?([\s\S]*?)```", re.MULTILINE)

# Regex para sinalização de artefato: [ARTEFATO: tipo=pdf titulo="..."]
ARTIFACT_RE = re.compile(
    r'\[ARTEFATO:\s*tipo=(\w+)\s+titulo="([^"]+)"\]', re.IGNORECASE
)

# Regex para extrair filename de comentário na primeira linha do código
FILENAME_RE = re.compile(r"^(?:#|//|<!--)\s*filename:\s*(.+?)\s*(?:-->)?$", re.MULTILINE)


def infer_language(code: str) -> str:
    """Tenta inferir a linguagem de um bloco de código por heurísticas."""
    scores: dict[str, int] = {lang: 0 for lang in LANG_HINTS}
    for lang, hints in LANG_HINTS.items():
        for hint in hints:
            if hint in code:
                scores[lang] += 1
    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] > 0 else "text"


def extract_filename(code: str) -> str:
    """Extrai nome de arquivo de um comentário na primeira linha do código."""
    match = FILENAME_RE.search(code[:200])
    return match.group(1).strip() if match else ""


def parse_response(raw: str) -> tuple[list[Chunk], list[ArtifactIntent]]:
    """
    Recebe o texto bruto da LLM e retorna:
    - lista de Chunks (text e code intercalados)
    - lista de ArtifactIntents detectadas
    """
    chunks: list[Chunk] = []
    artifact_intents: list[ArtifactIntent] = []

    # 1. Detecta intenções de artefato
    for match in ARTIFACT_RE.finditer(raw):
        artifact_intents.append(ArtifactIntent(
            type=match.group(1).lower(),
            title=match.group(2),
        ))
    # Remove marcações de artefato do texto
    clean = ARTIFACT_RE.sub("", raw).strip()

    # 2. Divide texto e blocos de código
    last_end = 0
    for match in CODE_BLOCK_RE.finditer(clean):
        # Texto antes do bloco
        before = clean[last_end:match.start()].strip()
        if before:
            chunks.append(Chunk(type="text", content=before))

        lang = match.group(1).strip().lower() or ""
        code = match.group(2)

        # Infere linguagem se não declarada
        if not lang:
            lang = infer_language(code)

        filename = extract_filename(code)

        chunks.append(Chunk(
            type="code",
            content=code.strip(),
            language=lang,
            filename=filename,
        ))
        last_end = match.end()

    # Texto remanescente após último bloco
    remainder = clean[last_end:].strip()
    if remainder:
        chunks.append(Chunk(type="text", content=remainder))

    # Se não houve nenhum chunk, retorna o texto limpo como único chunk
    if not chunks:
        chunks.append(Chunk(type="text", content=clean))

    return chunks, artifact_intents
