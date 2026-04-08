import csv
import os
import re
import tempfile
from datetime import datetime
from typing import cast
from openpyxl.worksheet.worksheet import Worksheet


def _clean_markdown(text: str) -> str:
    """Remove marcações markdown para texto limpo em documentos."""
    text = re.sub(r'\[ARTEFATO:[^\]]+\]', '', text)   # remove tags de artefato
    text = re.sub(r'```[\w]*\n?[\s\S]*?```', '', text) # remove blocos de código
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)       # bold -> texto
    text = re.sub(r'\*(.+?)\*',     r'\1', text)        # itálico -> texto
    text = re.sub(r'^#{1,3} (.+)$', r'\1', text, flags=re.MULTILINE)  # headers
    text = re.sub(r'^[-*] ',        '• ',  text, flags=re.MULTILINE)  # bullets
    return text.strip()


def _split_paragraphs(text: str) -> list[str]:
    """Divide o conteúdo em parágrafos não-vazios."""
    return [p.strip() for p in text.split('\n') if p.strip()]


def _tmp_path(title: str, ext: str) -> str:
    """Gera caminho seguro em /tmp."""
    safe = re.sub(r'[^\w\s-]', '', title).strip().replace(' ', '_')[:40]
    return os.path.join(tempfile.gettempdir(), f"{safe}.{ext}")


def generate_docx(title: str, content: str = "") -> str:
    from docx import Document
    from docx.shared import Pt, RGBColor, Cm
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    doc = Document()

    # Margens
    for section in doc.sections:
        section.top_margin    = Cm(2.5)
        section.bottom_margin = Cm(2.5)
        section.left_margin   = Cm(3)
        section.right_margin  = Cm(2.5)

    # Título
    heading = doc.add_heading(title, level=1)
    heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
    if heading.runs:
        heading.runs[0].font.color.rgb = RGBColor(0x1a, 0x1a, 0x2e)

    # Data
    date_p = doc.add_paragraph(f"Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    date_p.runs[0].font.size = Pt(9)
    date_p.runs[0].font.color.rgb = RGBColor(0x88, 0x88, 0x88)
    doc.add_paragraph("")

    # Conteúdo real da resposta
    body = _clean_markdown(content) if content.strip() else title
    for line in _split_paragraphs(body):
        p = doc.add_paragraph(line)
        p.runs[0].font.size = Pt(11) if p.runs else None

    path = _tmp_path(title, "docx")
    doc.save(path)
    return path


def generate_pdf(title: str, content: str = "") -> str:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable

    path = _tmp_path(title, "pdf")
    doc  = SimpleDocTemplate(
        path, pagesize=A4,
        leftMargin=2.5*cm, rightMargin=2.5*cm,
        topMargin=2.5*cm,  bottomMargin=2.5*cm,
    )

    styles     = getSampleStyleSheet()
    title_st   = ParagraphStyle("T", parent=styles["Title"],
                                fontSize=18, textColor=colors.HexColor("#1a1a2e"),
                                spaceAfter=6, alignment=1)
    date_st    = ParagraphStyle("D", parent=styles["Normal"],
                                fontSize=9,  textColor=colors.HexColor("#888888"),
                                spaceAfter=4, alignment=1)
    body_st    = ParagraphStyle("B", parent=styles["Normal"],
                                fontSize=11, leading=18,
                                textColor=colors.HexColor("#222222"),
                                spaceAfter=4)
    bullet_st  = ParagraphStyle("BL", parent=body_st,
                                leftIndent=16, bulletIndent=4)

    def esc(s):
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    story = [
        Paragraph(esc(title), title_st),
        Paragraph(f"Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M')}", date_st),
        Spacer(1, 0.3*cm),
        HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cccccc")),
        Spacer(1, 0.4*cm),
    ]

    # Conteúdo real — usa o texto da resposta da LLM
    body = _clean_markdown(content) if content.strip() else title
    for line in _split_paragraphs(body):
        if line.startswith("•"):
            story.append(Paragraph(esc(line), bullet_st))
        else:
            story.append(Paragraph(esc(line), body_st))
        story.append(Spacer(1, 0.15*cm))

    doc.build(story)
    return path


def generate_xlsx(title: str, content: str = "") -> str:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = cast(Worksheet, wb.active)
    ws.title = title[:31]

    # Título
    ws["A1"] = title
    ws["A1"].font = Font(bold=True, size=14, color="1a1a2e")
    ws["A2"] = f"Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M')}"
    ws["A2"].font = Font(italic=True, size=9, color="888888")
    ws.merge_cells("A1:E1")
    ws.merge_cells("A2:E2")

    # Se o conteúdo tem linhas com estrutura de lista, tenta montar tabela
    lines = _split_paragraphs(_clean_markdown(content)) if content.strip() else []

    header_fill = PatternFill("solid", fgColor="1a1a2e")
    header_font = Font(bold=True, color="FFFFFF")

    if lines:
        # Cabeçalho simples
        ws.cell(row=4, column=1, value="#").fill   = header_fill
        ws.cell(row=4, column=1).font              = header_font
        ws.cell(row=4, column=2, value="Conteúdo").fill = header_fill
        ws.cell(row=4, column=2).font              = header_font

        for i, line in enumerate(lines, start=5):
            ws.cell(row=i, column=1, value=i-4)
            ws.cell(row=i, column=2, value=line)
            if i % 2 == 0:
                for col in [1, 2]:
                    ws.cell(row=i, column=col).fill = PatternFill("solid", fgColor="f0f4ff")

        ws.column_dimensions["A"].width = 6
        ws.column_dimensions["B"].width = 80
    else:
        # Sem conteúdo estruturado: tabela de exemplo
        headers = ["#", "Item", "Valor", "Status", "Data"]
        for col, h in enumerate(headers, 1):
            c = ws.cell(row=4, column=col, value=h)
            c.fill = header_fill; c.font = header_font
            c.alignment = Alignment(horizontal="center")
        sample = [
            [1, "Item A", "R$ 1.200,00", "Ativo",    "01/04/2026"],
            [2, "Item B", "R$ 850,00",   "Pendente", "02/04/2026"],
        ]
        for ri, row in enumerate(sample, 5):
            for ci, val in enumerate(row, 1):
                ws.cell(row=ri, column=ci, value=val).alignment = Alignment(horizontal="center")
        for col in range(1, 6):
            ws.column_dimensions[get_column_letter(col)].width = 18

    path = _tmp_path(title, "xlsx")
    wb.save(path)
    return path


def generate_csv(title: str, content: str = "") -> str:
    path  = _tmp_path(title, "csv")
    lines = _split_paragraphs(_clean_markdown(content)) if content.strip() else []

    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["#", "Conteúdo"])
        if lines:
            for i, line in enumerate(lines, 1):
                writer.writerow([i, line])
        else:
            writer.writerow([1, title])
    return path


def generate_png(title: str, content: str = "") -> str:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # Tenta extrair números do conteúdo para plotar valores reais
    numbers = re.findall(r'R\$\s*([\d.,]+)', content)
    values  = []
    for n in numbers[:8]:
        try:
            values.append(float(n.replace(".", "").replace(",", ".")))
        except ValueError:
            pass

    if not values:
        values = [4200, 3800, 5100, 4700, 6200, 5800]

    labels  = [f"Item {i+1}" for i in range(len(values))]
    colors_ = ["#6c8ef7"] * len(values)
    if values:
        colors_[values.index(max(values))] = "#4ade80"

    fig, ax = plt.subplots(figsize=(10, 6))
    fig.patch.set_facecolor("#0d0f14")
    ax.set_facecolor("#13161e")

    ax.bar(labels, values, color=colors_, width=0.55, zorder=3)
    ax.set_title(title, color="white", fontsize=14, fontweight="bold", pad=14)
    ax.set_ylabel("Valor (R$)", color="#9ca3af", fontsize=10)
    ax.tick_params(colors="#9ca3af")
    for spine in ax.spines.values():
        spine.set_color("#252a38")
    ax.yaxis.grid(True, color="#252a38", linestyle="--", alpha=0.6, zorder=0)
    ax.set_axisbelow(True)

    for bar in ax.patches:
        bbox = bar.get_bbox()  # type: ignore
        ax.text(bbox.x0 + bbox.width/2, bbox.y1 + max(values)*0.01,
                f"R$ {bbox.height:,.0f}", ha="center", va="bottom",
                color="white", fontsize=8)

    plt.tight_layout()
    path = _tmp_path(title, "png")
    plt.savefig(path, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close()
    return path


def generate_pptx(title: str, content: str = "") -> str:
    from pptx import Presentation
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor
    from pptx.enum.text import PP_ALIGN

    prs = Presentation()
    prs.slide_width  = Inches(13.33)
    prs.slide_height = Inches(7.5)

    DARK   = RGBColor(0x0d, 0x0f, 0x14)
    ACCENT = RGBColor(0x6c, 0x8e, 0xf7)
    WHITE  = RGBColor(0xFF, 0xFF, 0xFF)
    GRAY   = RGBColor(0x9c, 0xa3, 0xaf)

    def _bg(slide):
        fill = slide.background.fill
        fill.solid()
        fill.fore_color.rgb = DARK

    def _txt(slide, text, l, t, w, h, size, bold=False, color=WHITE, align=PP_ALIGN.LEFT):
        tb = slide.shapes.add_textbox(Inches(l), Inches(t), Inches(w), Inches(h))
        tf = tb.text_frame; tf.word_wrap = True
        p  = tf.paragraphs[0]; p.alignment = align
        run = p.add_run(); run.text = text
        run.font.size = Pt(size); run.font.bold = bold; run.font.color.rgb = color

    # Slide 1 — Capa
    s1 = prs.slides.add_slide(prs.slide_layouts[6])
    _bg(s1)
    _txt(s1, title, 1, 2.8, 11.33, 1.4, 36, bold=True, color=ACCENT, align=PP_ALIGN.CENTER)
    _txt(s1, f"Gerado em {datetime.now().strftime('%d/%m/%Y')}", 1, 4.4, 11.33, 0.6, 13, color=GRAY, align=PP_ALIGN.CENTER)

    # Slide 2 — Conteúdo real da resposta
    body  = _clean_markdown(content) if content.strip() else "Conteúdo da apresentação."
    lines = _split_paragraphs(body)
    # Divide em blocos de ~12 linhas por slide
    chunk_size = 12
    for slide_idx, i in enumerate(range(0, max(len(lines), 1), chunk_size)):
        block = lines[i:i+chunk_size]
        s = prs.slides.add_slide(prs.slide_layouts[6])
        _bg(s)
        subtitle = f"Slide {slide_idx + 2}" if len(lines) > chunk_size else "Detalhes"
        _txt(s, subtitle, 0.8, 0.4, 11, 0.7, 22, bold=True, color=ACCENT)
        _txt(s, "\n".join(block), 0.8, 1.3, 11.5, 5.5, 16, color=WHITE)

    # Slide final
    sf = prs.slides.add_slide(prs.slide_layouts[6])
    _bg(sf)
    _txt(sf, "Obrigado!", 1, 3.2, 11.33, 1, 32, bold=True, color=WHITE, align=PP_ALIGN.CENTER)

    path = _tmp_path(title, "pptx")
    prs.save(path)
    return path


def generate_py(title: str, content: str = "") -> str:
    """Gera um arquivo Python simples com o conteúdo fornecido."""
    path = _tmp_path(title, "py")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content.strip())
    return path


GENERATORS = {
    "docx": generate_docx,
    "pdf":  generate_pdf,
    "xlsx": generate_xlsx,
    "csv":  generate_csv,
    "png":  generate_png,
    "pptx": generate_pptx,
    "py":   generate_py,
}

MIME_TYPES = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf":  "application/pdf",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv":  "text/csv",
    "png":  "image/png",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "py":   "text/x-python",
}


def generate_artifact(artifact_type: str, title: str, content: str = "") -> str:
    generator = GENERATORS.get(artifact_type.lower())
    if not generator:
        raise ValueError(f"Tipo não suportado: {artifact_type}. Use: {list(GENERATORS.keys())}")
    return generator(title, content)


def get_mime_type(artifact_type: str) -> str:
    return MIME_TYPES.get(artifact_type.lower(), "application/octet-stream")