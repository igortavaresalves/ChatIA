const state = {
  history:   [],
  streaming: false,
  useWeb:    false,
  theme:     localStorage.getItem("theme") || "dark",
};

document.addEventListener("DOMContentLoaded", () => {
  applyTheme(state.theme);
  bindEvents();
  checkHealth();
});

function bindEvents() {
  document.getElementById("send-btn").addEventListener("click", sendMessage);
  document.getElementById("user-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  });
  document.getElementById("user-input").addEventListener("input", (e) => autoResize(e.target));
  document.getElementById("theme-btn").addEventListener("click", toggleTheme);
  document.getElementById("web-toggle").addEventListener("click", toggleWeb);
  document.getElementById("new-chat-btn").addEventListener("click", newChat);
  document.querySelectorAll(".chip").forEach(c => {
    c.addEventListener("click", () => {
      document.getElementById("user-input").value = c.dataset.prompt;
      autoResize(document.getElementById("user-input"));
      sendMessage();
    });
  });
}

async function checkHealth() {
  try {
    const res  = await fetch("/health");
    const data = await res.json();
    const dot  = document.getElementById("model-dot");
    if (data.groq_configured) {
      dot.style.background = "var(--accent-2)";
      dot.style.boxShadow  = "0 0 6px var(--accent-2)";
    } else {
      dot.style.background = "var(--danger)";
      document.getElementById("model-name").textContent = "API key não configurada";
    }
  } catch (e) { console.warn("Health check falhou:", e); }
}

async function sendMessage() {
  if (state.streaming) return;

  const input = document.getElementById("user-input");
  const text  = input.value.trim();
  if (!text) return;

  input.value = "";
  input.style.height = "auto";
  document.getElementById("send-btn").disabled = true;
  state.streaming = true;

  document.getElementById("empty-state")?.remove();
  state.history.push({ role: "user", content: text });
  appendUserMessage(text);

  const aiBlock = appendAiBlock();

  try {
    await streamAndRender(aiBlock);
  } catch (err) {
    showError(aiBlock, err.message);
  } finally {
    state.streaming = false;
    document.getElementById("send-btn").disabled = false;
    input.focus();
  }
}

async function streamAndRender(aiBlock) {
  const loadingEl = aiBlock.querySelector(".thinking-row");

  const res = await fetch("/chat", {
    method:  "POST",
    headers: { "Content-Type": "application/json" },
    body:    JSON.stringify({
      messages: state.history,
      use_web:  state.useWeb,
      stream:   true,
    }),
  });

  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || "Erro no servidor");
  }

  /* Fase 1 — streaming visual */
  const streamEl = document.createElement("div");
  streamEl.className = "chunk-text streaming";
  streamEl.style.minHeight = "40px";
  loadingEl.replaceWith(streamEl);

  const reader  = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer  = "";
  let rawText = "";

  outer: while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop();

    for (const line of lines) {
      if (!line.startsWith("data: ")) continue;
      const data = line.slice(6).trim();
      if (data === "[DONE]") break outer;
      try {
        const evt = JSON.parse(data);
        if (evt.token) {
          rawText += evt.token;
          streamEl.innerHTML = renderMarkdownText(rawText);
          scrollToBottom();
        }
      } catch {}
    }
  }

  streamEl.classList.remove("streaming");

  /* Fase 2 — parse local do rawText completo */
  const { chunks, artifacts } = parseRawLocally(rawText);
  const cleanText = rawText.replace(/\[ARTEFATO:[^\]]+\]/gi, "").trim();
  state.history.push({ role: "assistant", content: cleanText });

  const container = document.createDocumentFragment();

  for (const chunk of chunks) {
    if (chunk.type === "text" && chunk.content.trim()) {
      const el = document.createElement("div");
      el.className = "chunk-text";
      el.innerHTML = renderMarkdownText(chunk.content);
      container.appendChild(el);
    } else if (chunk.type === "code") {
      container.appendChild(renderCodeBlock(chunk));
    }
  }

  if (artifacts.length) {
    const codeContent = chunks
      .filter(c => c.type === "code")
      .map(c => c.content)
      .join("\n\n");
    const artifactContent = codeContent || cleanText;
    container.appendChild(renderArtifactsPanel(artifacts, artifactContent));
  }

  streamEl.replaceWith(container);
  scrollToBottom();
}

function parseRawLocally(raw) {
  const chunks    = [];
  const artifacts = [];
  const usedNames = new Set();

  const artifactRe = /\[ARTEFATO:\s*tipo=(\w+)\s+titulo="([^"]+)"\]/gi;
  let m;
  while ((m = artifactRe.exec(raw)) !== null) {
    artifacts.push({ type: m[1].toLowerCase(), title: m[2], content: "" });
    usedNames.add(m[2]);
  }

  const clean   = raw.replace(/\[ARTEFATO:[^\]]+\]/gi, "").trim();
  const codeRe  = /```(\w*)\n?([\s\S]*?)```/g;
  let lastEnd   = 0;
  let codeMatch;

  while ((codeMatch = codeRe.exec(clean)) !== null) {
    const before = clean.slice(lastEnd, codeMatch.index).trim();
    if (before) chunks.push({ type: "text", content: before });

    const lang = codeMatch[1].trim().toLowerCase() || inferLang(codeMatch[2]);
    const code = codeMatch[2].trim();
    const suggested = extractFilename(code);
    const filename = uniqueFilename(resolveFilename(lang, suggested), usedNames);

    chunks.push({ type: "code", language: lang, content: code, filename });
    artifacts.push({ type: lang, title: filename, content: code });
    lastEnd = codeRe.lastIndex;
  }

  const remainder = clean.slice(lastEnd).trim();
  if (remainder) chunks.push({ type: "text", content: remainder });
  if (!chunks.length) chunks.push({ type: "text", content: clean });

  return { chunks, artifacts };
}

function inferLang(code) {
  const hints = {
    python:     ["def ", "import ", "print(", "class ", "if __name__"],
    javascript: ["const ", "let ", "var ", "function ", "=>", "console.log"],
    typescript: ["interface ", ": string", ": number", "as const"],
    html:       ["<!DOCTYPE", "<html", "<div", "<body"],
    css:        ["margin:", "padding:", "color:", "font-size:"],
    csharp:     ["using ", "namespace ", "public class"],
  };
  let best = "text", bestScore = 0;
  for (const [lang, patterns] of Object.entries(hints)) {
    const score = patterns.filter(p => code.includes(p)).length;
    if (score > bestScore) { bestScore = score; best = lang; }
  }
  return best;
}

function resolveFilename(language, suggested = "") {
  if (suggested) return suggested;
  switch (language) {
    case "html": return "index.html";
    case "css": return "styles.css";
    case "javascript": return "script.js";
    case "typescript": return "app.ts";
    case "tsx": return "app.tsx";
    case "jsx": return "app.jsx";
    case "python": return "main.py";
    case "bash": return "script.sh";
    case "powershell": return "script.ps1";
    case "csharp": return "Program.cs";
    case "java": return "Main.java";
    case "cpp": return "main.cpp";
    case "c": return "main.c";
    case "go": return "main.go";
    case "rust": return "main.rs";
    case "php": return "index.php";
    case "ruby": return "main.rb";
    case "dart": return "main.dart";
    case "kotlin": return "Main.kt";
    case "swift": return "main.swift";
    default: return `code.${language || "txt"}`;
  }
}

function uniqueFilename(base, used) {
  if (!used.has(base)) {
    used.add(base);
    return base;
  }
  const dot = base.lastIndexOf(".");
  const name = dot >= 0 ? base.slice(0, dot) : base;
  const ext = dot >= 0 ? base.slice(dot) : "";
  let counter = 1;
  let candidate;
  do {
    candidate = `${name}-${counter}${ext}`;
    counter += 1;
  } while (used.has(candidate));
  used.add(candidate);
  return candidate;
}

function extractFilename(code) {
  const m = code.match(/^(?:#|\/\/|<!--)\s*filename:\s*(.+?)(?:\s*-->)?$/m);
  return m ? m[1].trim() : "";
}

function appendUserMessage(text) {
  const el = document.createElement("div");
  el.className = "msg-block";
  el.innerHTML = `<div class="msg-user">${escHtml(text)}</div>`;
  chatInner().appendChild(el);
  scrollToBottom();
}

function appendAiBlock() {
  const block = document.createElement("div");
  block.className = "msg-block";
  block.innerHTML = `
    <div class="msg-ai">
      <div class="ai-header">Assistente</div>
      <div class="thinking-row">
        <div class="dots"><span></span><span></span><span></span></div>
        <span>${state.useWeb ? "Pesquisando e pensando…" : "Pensando…"}</span>
      </div>
    </div>`;
  chatInner().appendChild(block);
  scrollToBottom();
  return block.querySelector(".msg-ai");
}

function renderSources(sources) {
  const wrap = document.createElement("div");
  wrap.className = "sources-wrap";
  wrap.innerHTML = `<div class="sources-label">Fontes</div><div class="sources-strip"></div>`;
  const strip = wrap.querySelector(".sources-strip");
  for (const s of sources) {
    const a = document.createElement("a");
    a.className = "source-pill";
    a.href = s.url; a.target = "_blank"; a.rel = "noopener";
    a.innerHTML = `<img src="https://www.google.com/s2/favicons?domain=${encodeURIComponent(s.url)}&sz=16" alt="" onerror="this.style.display='none'" />${escHtml(s.title.slice(0, 40))}`;
    strip.appendChild(a);
  }
  return wrap;
}

function renderCodeBlock(chunk) {
  const langExtMap = {
    python:"py", javascript:"js", typescript:"ts", html:"html",
    css:"css", csharp:"cs", react:"jsx", markdown:"md",
    json:"json", bash:"sh", sql:"sql", text:"txt"
  };
  const ext         = langExtMap[chunk.language] || chunk.language || "txt";
  const displayName = chunk.filename || `codigo.${ext}`;

  const wrap = document.createElement("div");
  wrap.className = "chunk-code";

  const header = document.createElement("div");
  header.className = "code-header";
  header.innerHTML = `
    <span class="code-lang">${escHtml(chunk.language || "text")}</span>
    <span class="code-filename">${escHtml(displayName)}</span>
    <div class="code-actions">
      <button class="code-btn copy-btn">Copiar</button>
      <button class="code-btn download-code-btn">Baixar</button>
    </div>`;

  // <pre> preserva indentação e quebras de linha nativamente
  const pre = document.createElement("pre");
  pre.className   = "code-body";
  pre.textContent = chunk.content;

  wrap.appendChild(header);
  wrap.appendChild(pre);

  header.querySelector(".copy-btn").addEventListener("click", async (e) => {
    await navigator.clipboard.writeText(chunk.content);
    const btn = e.currentTarget;
    btn.textContent = "Copiado";
    btn.classList.add("copied");
    setTimeout(() => { btn.textContent = "Copiar"; btn.classList.remove("copied"); }, 1800);
  });

  header.querySelector(".download-code-btn").addEventListener("click", () => {
    const blob = new Blob([chunk.content], { type: "text/plain" });
    triggerDownload(blob, displayName);
  });

  return wrap;
}

const ARTIFACT_ICONS = {
  pdf:"PDF", docx:"DOCX", xlsx:"XLSX", csv:"CSV", png:"PNG", pptx:"PPTX", py:"PY",
  python:"PY", javascript:"JS", typescript:"TS", html:"HTML", css:"CSS",
  csharp:"CS", java:"JAVA", cpp:"CPP", c:"C", go:"GO", rust:"RS",
  php:"PHP", ruby:"RB", dart:"DART", kotlin:"KT", swift:"SWIFT",
  bash:"SH", powershell:"PS", sql:"SQL", json:"JSON", yaml:"YML",
  xml:"XML", markdown:"MD",
};

function renderArtifactsPanel(artifacts, content) {
  const panel = document.createElement("div");
  panel.className = "artifacts-panel";
  panel.innerHTML = `
    <div class="artifacts-header">Arquivos disponíveis para download</div>
    <div class="artifacts-grid"></div>`;
  const grid = panel.querySelector(".artifacts-grid");

  for (const art of artifacts) {
    const card = document.createElement("div");
    card.className = "artifact-card";
    const icon = ARTIFACT_ICONS[art.type] || "FILE";
    card.innerHTML = `
      <div class="artifact-icon" style="background:var(--bg-4)">${icon}</div>
      <div class="artifact-info">
        <div class="artifact-title">${escHtml(art.title)}</div>
        <div class="artifact-meta">${art.type.toUpperCase()}</div>
      </div>
      <button class="artifact-download-btn" title="Gerar e baixar">Baixar</button>`;

    const btn = card.querySelector(".artifact-download-btn");
    // Usa o content específico do artefato se disponível, senão o geral
    const artifactContent = art.content || content;
    btn.addEventListener("click", () => downloadArtifact(art.type, art.title, artifactContent, btn));
    grid.appendChild(card);
  }

  return panel;
}

async function downloadArtifact(type, title, content, btn) {
  if (btn.classList.contains("loading")) return;
  btn.classList.add("loading");
  btn.textContent = "…";

  try {
    const res = await fetch("/artifact/generate", {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({ type, title, content }),
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Erro ao gerar arquivo");
    }

    const blob     = await res.blob();
    const filename = `${title.replace(/[^a-zA-Z0-9 _-]/g, "").trim()}.${type}`;
    triggerDownload(blob, filename);

    btn.textContent      = "Pronto";
    btn.style.background = "var(--accent-2)";
    btn.style.color      = "#000";
    setTimeout(() => {
      btn.textContent      = "Baixar";
      btn.style.background = "";
      btn.style.color      = "";
      btn.classList.remove("loading");
    }, 2500);

  } catch (err) {
    btn.textContent      = "Erro";
    btn.style.background = "var(--danger)";
    btn.style.color      = "#fff";
    console.error("Erro download artefato:", err);
    setTimeout(() => {
      btn.textContent      = "Baixar";
      btn.style.background = "";
      btn.style.color      = "";
      btn.classList.remove("loading");
    }, 2500);
  }
}

function triggerDownload(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a   = document.createElement("a");
  a.href = url; a.download = filename;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(url); a.remove(); }, 1000);
}

function renderMarkdownText(raw) {
  const codeBlocks = [];

  // Passo 1: extrai blocos de código e substitui por tokens únicos
  // Feito ANTES de qualquer escape — protege indentação e quebras de linha
  let safe = raw.replace(/```(\w*)\n?([\s\S]*?)```/g, (_, lang, code) => {
    const token = `CODEBLOCK_${codeBlocks.length}_END`;
    const codeLang = (lang || "").trim().toLowerCase() || inferLang(code);
    const ext = {
      python:"py", javascript:"js", typescript:"ts", html:"html",
      css:"css", csharp:"cs", react:"jsx", json:"json", bash:"sh", sql:"sql"
    }[codeLang] || codeLang || "txt";
    const escapedCode = code
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
    codeBlocks.push(
      `<div class="chunk-code" style="margin:8px 0">` +
        `<div class="code-header">` +
          `<span class="code-lang">${escHtml(codeLang || "text")}</span>` +
          `<span class="code-filename">codigo.${ext}</span>` +
        `</div>` +
        `<pre class="code-body">${escapedCode}</pre>` +
      `</div>`
    );
    return token;
  });

  // Passo 2: transforma APENAS o texto restante
  // Os tokens não contêm & < > então o escape não os afeta
  safe = safe
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\[ARTEFATO:[^\]]+\]/gi, "")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g,     "<em>$1</em>")
    .replace(/`([^`]+)`/g,     "<code>$1</code>")
    .replace(/^### (.+)$/gm,   "<h3>$1</h3>")
    .replace(/^## (.+)$/gm,    "<h2>$1</h2>")
    .replace(/^# (.+)$/gm,     "<h1>$1</h1>")
    .replace(/^[-*] (.+)$/gm,  "<li>$1</li>")
    .replace(/^\d+\. (.+)$/gm, "<li>$1</li>")
    .replace(/(<li>[\s\S]+?<\/li>)/g, "<ul>$1</ul>")
    .replace(/<\/ul>\s*<ul>/g, "")
    .replace(/\n\n+/g, "</p><p>")
    .replace(/\n/g,    "<br/>")
    .replace(/^(.+)$/, "<p>$1</p>");

  // Passo 3: reinsere os blocos de código
  safe = safe.replace(/CODEBLOCK_(\d+)_END/g, (_, i) => codeBlocks[+i]);

  return safe;
}

function showError(container, msg) {
  const el = document.createElement("div");
  el.className = "chunk-text";
  el.innerHTML = `<span style="color:var(--danger)">${escHtml(msg)}</span>`;
  const loading = container.querySelector(".thinking-row");
  loading ? loading.replaceWith(el) : container.appendChild(el);
}

function autoResize(el) {
  el.style.height = "auto";
  el.style.height = Math.min(el.scrollHeight, 160) + "px";
}

function scrollToBottom() {
  const area = document.getElementById("chat-area");
  area.scrollTo({ top: area.scrollHeight, behavior: "smooth" });
}

function chatInner() { return document.getElementById("chat-inner"); }
function escHtml(s)  { const d = document.createElement("div"); d.textContent = s; return d.innerHTML; }

function applyTheme(t) {
  document.documentElement.setAttribute("data-theme", t);
  document.getElementById("theme-btn").textContent = t === "dark" ? "Sol" : "Lua";
  localStorage.setItem("theme", t);
}
function toggleTheme() {
  state.theme = state.theme === "dark" ? "light" : "dark";
  applyTheme(state.theme);
}

function toggleWeb() {
  state.useWeb = !state.useWeb;
  const btn = document.getElementById("web-toggle");
  btn.classList.toggle("on", state.useWeb);
  btn.querySelector("span:last-child").textContent = `Web ${state.useWeb ? "ON" : "OFF"}`;
}

function newChat() {
  state.history = [];
  const inner = chatInner();
  inner.innerHTML = `
    <div class="empty-state" id="empty-state">
      <div class="empty-icon"></div>
      <h2>Como posso ajudar?</h2>
      <p>Pergunte qualquer coisa. Posso escrever código, gerar documentos, analisar dados e muito mais.</p>
      <div class="suggestion-chips">
        <div class="chip" data-prompt="Escreva um script Python para ler um CSV e gerar um gráfico de barras">Gerar gráfico Python</div>
        <div class="chip" data-prompt="Crie um relatório PDF com resumo executivo sobre vendas do trimestre">Relatório PDF</div>
        <div class="chip" data-prompt="Monte uma planilha Excel com dados de estoque de 5 produtos">Planilha Excel</div>
        <div class="chip" data-prompt="Crie uma apresentação PPTX de 3 slides sobre inteligência artificial">Apresentação PPTX</div>
      </div>
    </div>`;
  inner.querySelectorAll(".chip").forEach(c => {
    c.addEventListener("click", () => {
      document.getElementById("user-input").value = c.dataset.prompt;
      autoResize(document.getElementById("user-input"));
      sendMessage();
    });
  });
}