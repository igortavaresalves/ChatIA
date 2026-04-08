"""
Serviço para detecção, persistência e gerenciamento de artefatos de código gerados durante conversas.

Este módulo implementa a lógica para:
- Detectar blocos de código em respostas
- Classificar linguagem e mapear para extensões
- Persistir artefatos com versionamento
- Atualizar artefatos existentes
- Preparar arquivos para download
"""

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional
from pathlib import Path
import tempfile
import os


@dataclass
class CodeArtifact:
    """Representa um artefato de código detectado na conversa."""
    id: str
    conversation_id: str
    message_id: str
    filename: str
    extension: str
    language: str
    content: str
    checksum: str
    version: int = 1
    status: str = "detected"  # detected, draft, updated, replaced, ready_for_download
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    replaced_by: Optional[str] = None
    is_final: bool = False
    belongs_to_project: bool = True
    purpose: str = ""
    dependencies: List[str] = field(default_factory=list)


# Armazenamento em memória para artefatos (em produção, usar banco de dados)
_artifacts_store: Dict[str, Dict[str, CodeArtifact]] = {}  # conversation_id -> {filename -> artifact}


# Mapeamento de linguagem para extensão
LANGUAGE_EXT_MAP = {
    "python": ".py",
    "html": ".html",
    "css": ".css",
    "javascript": ".js",
    "typescript": ".ts",
    "tsx": ".tsx",
    "jsx": ".jsx",
    "json": ".json",
    "yaml": ".yml",
    "xml": ".xml",
    "markdown": ".md",
    "sql": ".sql",
    "bash": ".sh",
    "powershell": ".ps1",
    "csharp": ".cs",
    "cpp": ".cpp",
    "c": ".c",
    "java": ".java",
    "kotlin": ".kt",
    "swift": ".swift",
    "go": ".go",
    "rust": ".rs",
    "php": ".php",
    "ruby": ".rb",
    "dart": ".dart",
    "r": ".R",
    "scala": ".scala",
    "lua": ".lua",
    "dockerfile": "Dockerfile",  # nome fixo
    "requirements": "requirements.txt",  # nome fixo
    "package_json": "package.json",  # nome fixo
    "tsconfig": "tsconfig.json",  # nome fixo
    "env_example": ".env.example",  # nome fixo
}

# Heurísticas para inferir linguagem
LANGUAGE_HINTS = {
    "python": [r"def ", r"import ", r"print\(", r"class ", r"if __name__"],
    "javascript": [r"const ", r"let ", r"var ", r"function ", r"=>\s*\{", r"console\.log"],
    "typescript": [r"interface ", r": string", r": number", r": boolean", r"as const"],
    "html": [r"<!DOCTYPE", r"<html", r"<div", r"<body"],
    "css": [r"\{", r"\}", r"px;", r"color:", r"margin:", r"padding:"],
    "csharp": [r"using ", r"namespace ", r"public class"],
    "java": [r"public class", r"import java\.", r"System\.out"],
    "cpp": [r"#include", r"int main", r"std::"],
    "c": [r"#include <", r"int main", r"printf"],
    "go": [r"package ", r"func ", r"import \("],
    "rust": [r"fn ", r"let ", r"use ", r"println!"],
    "php": [r"<?php", r"echo ", r"function "],
    "ruby": [r"def ", r"puts ", r"class ", r"require "],
    "dart": [r"void main", r"import 'dart:", r"class "],
    "kotlin": [r"fun ", r"val ", r"var ", r"class "],
    "swift": [r"func ", r"let ", r"var ", r"class "],
    "r": [r"<-", r"print\(", r"library\("],
    "scala": [r"object ", r"def ", r"class ", r"import "],
    "lua": [r"function ", r"print\(", r"local "],
    "bash": [r"#!/bin/bash", r"echo ", r"if \[", r"for "],
    "powershell": [r"Write-Host", r"Get-", r"Set-", r"function "],
    "sql": [r"SELECT ", r"INSERT ", r"UPDATE ", r"CREATE TABLE"],
    "json": [r"\{.*\}", r"\".*\":", r"\[.*\]"],
    "yaml": [r"^\s*[\w\-]+:\s", r"^\s*-\s", r"^\w+:\s*$"],
    "xml": [r"<\?xml", r"<[^>]+>", r"</[^>]+>"],
    "markdown": [r"^# ", r"^\*\*.*\*\*", r"^\[.*\]\(.*\)"],
    "dockerfile": [r"FROM ", r"RUN ", r"COPY ", r"CMD "],
}

# Nomes fixos por convenção
FIXED_NAMES = {
    "package.json": "package_json",
    "tsconfig.json": "tsconfig",
    "Dockerfile": "dockerfile",
    "requirements.txt": "requirements",
    ".env.example": "env_example",
}


def infer_language(code: str) -> str:
    """Infere a linguagem do código baseado em heurísticas."""
    scores = {lang: 0 for lang in LANGUAGE_HINTS}
    for lang, hints in LANGUAGE_HINTS.items():
        for hint in hints:
            if re.search(hint, code, re.IGNORECASE | re.MULTILINE):
                scores[lang] += 1
    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] > 0 else "text"


def resolve_filename_and_extension(language: str, suggested_filename: str = "", content: str = "") -> tuple[str, str]:
    """Resolve nome do arquivo e extensão baseado na linguagem e contexto."""
    # Se filename sugerido, usar ele
    if suggested_filename:
        # Verificar se é nome fixo
        if suggested_filename in FIXED_NAMES:
            lang_key = FIXED_NAMES[suggested_filename]
            ext = LANGUAGE_EXT_MAP.get(lang_key, "")
            return suggested_filename, ext
        else:
            # Usar extensão baseada na linguagem
            ext = LANGUAGE_EXT_MAP.get(language, ".txt")
            return suggested_filename, ext

    # Inferir nome baseado na linguagem
    if language == "html":
        filename = "index.html"
    elif language == "css":
        filename = "styles.css"
    elif language == "javascript":
        filename = "script.js"
    elif language == "typescript":
        filename = "app.ts"
    elif language == "python":
        filename = "main.py"
    elif language == "csharp":
        filename = "Program.cs"
    elif language == "java":
        filename = "Main.java"
    elif language == "go":
        filename = "main.go"
    elif language == "rust":
        filename = "main.rs"
    elif language == "dart":
        filename = "main.dart"
    elif language == "kotlin":
        filename = "Main.kt"
    elif language == "swift":
        filename = "main.swift"
    elif language == "php":
        filename = "index.php"
    elif language == "ruby":
        filename = "main.rb"
    elif language == "r":
        filename = "script.R"
    elif language == "scala":
        filename = "Main.scala"
    elif language == "lua":
        filename = "main.lua"
    elif language == "bash":
        filename = "script.sh"
    elif language == "powershell":
        filename = "script.ps1"
    elif language == "sql":
        filename = "query.sql"
    elif language == "json":
        filename = "data.json"
    elif language == "yaml":
        filename = "config.yml"
    elif language == "xml":
        filename = "data.xml"
    elif language == "markdown":
        filename = "README.md"
    else:
        filename = f"code{LANGUAGE_EXT_MAP.get(language, '.txt')}"

    ext = LANGUAGE_EXT_MAP.get(language, ".txt")
    return filename, ext


def detect_code_artifacts(chunks: List, conversation_id: str, message_id: str) -> List[CodeArtifact]:
    """Detecta artefatos de código nos chunks e os cria/persiste."""
    artifacts = []
    for chunk in chunks:
        if chunk.type == "code" and chunk.content.strip():
            language = chunk.language or infer_language(chunk.content)
            if language == "text":
                continue  # Ignorar texto simples

            filename, extension = resolve_filename_and_extension(language, chunk.filename, chunk.content)
            checksum = hashlib.md5(chunk.content.encode()).hexdigest()

            # Verificar se já existe artefato similar
            existing = get_artifact_by_filename(conversation_id, filename)
            if existing:
                # Atualizar se conteúdo diferente
                if existing.checksum != checksum:
                    update_artifact(existing.id, chunk.content, message_id)
                    existing = get_artifact_by_id(existing.id)
                artifacts.append(existing)
            else:
                # Criar novo
                artifact = create_artifact(
                    conversation_id=conversation_id,
                    message_id=message_id,
                    filename=filename,
                    extension=extension,
                    language=language,
                    content=chunk.content,
                    purpose=f"Código {language}",
                )
                artifacts.append(artifact)

    return artifacts


def create_artifact(conversation_id: str, message_id: str, filename: str, extension: str,
                   language: str, content: str, purpose: str = "") -> CodeArtifact:
    """Cria um novo artefato."""
    artifact_id = f"{conversation_id}_{filename}_{datetime.now().isoformat()}"
    checksum = hashlib.md5(content.encode()).hexdigest()

    artifact = CodeArtifact(
        id=artifact_id,
        conversation_id=conversation_id,
        message_id=message_id,
        filename=filename,
        extension=extension,
        language=language,
        content=content,
        checksum=checksum,
        purpose=purpose,
        status="ready_for_download",
        is_final=True,
    )

    if conversation_id not in _artifacts_store:
        _artifacts_store[conversation_id] = {}
    _artifacts_store[conversation_id][filename] = artifact

    return artifact


def update_artifact(artifact_id: str, new_content: str, message_id: str) -> CodeArtifact:
    """Atualiza um artefato existente."""
    artifact = get_artifact_by_id(artifact_id)
    if not artifact:
        raise ValueError(f"Artefato {artifact_id} não encontrado")

    old_checksum = artifact.checksum
    new_checksum = hashlib.md5(new_content.encode()).hexdigest()

    if old_checksum == new_checksum:
        return artifact  # Sem mudanças

    # Marcar anterior como substituído
    artifact.status = "replaced"
    artifact.replaced_by = f"{artifact_id}_v{artifact.version + 1}"
    artifact.is_final = False

    # Criar nova versão
    new_artifact = CodeArtifact(
        id=f"{artifact.id}_v{artifact.version + 1}",
        conversation_id=artifact.conversation_id,
        message_id=message_id,
        filename=artifact.filename,
        extension=artifact.extension,
        language=artifact.language,
        content=new_content,
        checksum=new_checksum,
        version=artifact.version + 1,
        status="ready_for_download",
        is_final=True,
        purpose=artifact.purpose,
        belongs_to_project=artifact.belongs_to_project,
        dependencies=artifact.dependencies,
    )

    _artifacts_store[artifact.conversation_id][artifact.filename] = new_artifact
    return new_artifact


def get_artifact_by_id(artifact_id: str) -> Optional[CodeArtifact]:
    """Busca artefato por ID."""
    for conv_artifacts in _artifacts_store.values():
        for artifact in conv_artifacts.values():
            if artifact.id == artifact_id:
                return artifact
    return None


def get_artifact_by_filename(conversation_id: str, filename: str) -> Optional[CodeArtifact]:
    """Busca artefato por filename em uma conversa."""
    conv_artifacts = _artifacts_store.get(conversation_id, {})
    return conv_artifacts.get(filename)


def get_conversation_artifacts(conversation_id: str) -> List[CodeArtifact]:
    """Retorna todos os artefatos finais de uma conversa."""
    conv_artifacts = _artifacts_store.get(conversation_id, {})
    return [art for art in conv_artifacts.values() if art.is_final]


def generate_file(artifact: CodeArtifact) -> str:
    """Gera arquivo temporário para download."""
    path = os.path.join(tempfile.gettempdir(), f"{artifact.filename}")
    with open(path, "w", encoding="utf-8") as f:
        f.write(artifact.content)
    return path


def get_mime_type(extension: str) -> str:
    """Retorna MIME type baseado na extensão."""
    mime_map = {
        ".py": "text/x-python",
        ".html": "text/html",
        ".css": "text/css",
        ".js": "application/javascript",
        ".ts": "application/typescript",
        ".tsx": "application/typescript",
        ".jsx": "application/javascript",
        ".json": "application/json",
        ".yml": "application/x-yaml",
        ".xml": "application/xml",
        ".md": "text/markdown",
        ".sql": "application/sql",
        ".sh": "application/x-shellscript",
        ".ps1": "application/x-powershell",
        ".cs": "text/x-csharp",
        ".cpp": "text/x-c++src",
        ".c": "text/x-csrc",
        ".java": "text/x-java-source",
        ".kt": "text/x-kotlin",
        ".swift": "text/x-swift",
        ".go": "text/x-go",
        ".rs": "text/x-rust",
        ".php": "application/x-php",
        ".rb": "text/x-ruby",
        ".dart": "application/dart",
        ".R": "text/x-rsrc",
        ".scala": "text/x-scala",
        ".lua": "text/x-lua",
    }
    return mime_map.get(extension, "text/plain")