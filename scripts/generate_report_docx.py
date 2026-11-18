"""Build docs/PROJECT_REPORT.docx from docs/PROJECT_REPORT.md.

Run with the bundled Python (python-docx + Pillow):

    <bundled python> scripts/generate_report_docx.py
"""

from __future__ import annotations

import re
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / 'docs'
SOURCE = DOCS / 'PROJECT_REPORT.md'
OUTPUT = DOCS / 'PROJECT_REPORT.docx'

GREEN = RGBColor(36, 92, 70)
GREEN_DARK = RGBColor(22, 61, 48)
MUTED = RGBColor(110, 120, 114)
INK = RGBColor(29, 41, 37)


def shade(cell, hex_color: str):
    properties = cell._tc.get_or_add_tcPr()
    shading = OxmlElement('w:shd')
    shading.set(qn('w:val'), 'clear')
    shading.set(qn('w:color'), 'auto')
    shading.set(qn('w:fill'), hex_color)
    properties.append(shading)


def set_cell_margins(table, top=40, bottom=40, left=70, right=70):
    table_properties = table._tbl.tblPr
    margins = OxmlElement('w:tblCellMar')
    for name, value in (('top', top), ('left', left), ('bottom', bottom), ('right', right)):
        node = OxmlElement(f'w:{name}')
        node.set(qn('w:w'), str(value))
        node.set(qn('w:type'), 'dxa')
        margins.append(node)
    table_properties.append(margins)


def add_page_number_footer(section):
    footer = section.footer
    paragraph = footer.paragraphs[0]
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = paragraph.add_run('Rukomeza Market - Project Report   |   Page ')
    run.font.size = Pt(8)
    run.font.color.rgb = MUTED
    fld = OxmlElement('w:fldSimple')
    fld.set(qn('w:instr'), 'PAGE')
    paragraph._p.append(fld)
    run = paragraph.add_run(' of ')
    run.font.size = Pt(8)
    run.font.color.rgb = MUTED
    fld = OxmlElement('w:fldSimple')
    fld.set(qn('w:instr'), 'NUMPAGES')
    paragraph._p.append(fld)


def add_toc(document, section_titles):
    for index, title in enumerate(section_titles, start=1):
        paragraph = document.add_paragraph()
        paragraph.paragraph_format.space_after = Pt(3)
        run = paragraph.add_run(title)
        run.font.size = Pt(10)
        run.font.color.rgb = INK
    note = document.add_paragraph()
    note_run = note.add_run('Each numbered section starts on a new page in the body of the report.')
    note_run.italic = True
    note_run.font.size = Pt(8)
    note_run.font.color.rgb = MUTED


def style_document(document):
    normal = document.styles['Normal']
    normal.font.name = 'Calibri'
    normal.font.size = Pt(10.5)
    normal.font.color.rgb = INK
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.line_spacing = 1.12

    for name, size, color in (('Heading 1', 19, GREEN_DARK), ('Heading 2', 14, GREEN), ('Heading 3', 11.5, GREEN_DARK)):
        style = document.styles[name]
        style.font.name = 'Georgia'
        style.font.size = Pt(size)
        style.font.color.rgb = color
        style.font.bold = True
        style.paragraph_format.space_before = Pt(14 if name == 'Heading 1' else 10)
        style.paragraph_format.space_after = Pt(7)
        style.paragraph_format.keep_with_next = True

    for name in ('List Bullet', 'List Number'):
        style = document.styles[name]
        style.font.name = 'Calibri'
        style.font.size = Pt(10.5)
        style.paragraph_format.space_after = Pt(3)


def add_inline(paragraph, text: str, *, size=None, color=None):
    pattern = re.compile(r'(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)]+\)|<https?://[^>]+>)')
    for token in pattern.split(text):
        if not token:
            continue
        bold = False
        code = False
        if token.startswith('**') and token.endswith('**') and len(token) > 4:
            token = token[2:-2]
            bold = True
        elif token.startswith('`') and token.endswith('`') and len(token) > 2:
            token = token[1:-1]
            code = True
        elif token.startswith('[') and '](' in token:
            match = re.match(r'\[([^\]]+)\]\(([^)]+)\)', token)
            if match:
                token = match.group(1) + (f' ({match.group(2)})' if not match.group(2).startswith('#') else '')
        elif token.startswith('<http') and token.endswith('>'):
            token = token[1:-1]
        run = paragraph.add_run(token)
        run.bold = bold
        if code:
            run.font.name = 'Consolas'
            run.font.size = Pt((size or 10.5) - 1.2)
        elif size:
            run.font.size = Pt(size)
        if color:
            run.font.color.rgb = color


def add_rich_paragraph(document, text, *, style=None, size=None, color=None, align=None, space_after=None):
    paragraph = document.add_paragraph(style=style) if style else document.add_paragraph()
    add_inline(paragraph, text, size=size, color=color)
    if align is not None:
        paragraph.alignment = align
    if space_after is not None:
        paragraph.paragraph_format.space_after = Pt(space_after)
    return paragraph


def add_code_block(document, code: str):
    paragraph = document.add_paragraph()
    paragraph.paragraph_format.left_indent = Inches(0.15)
    paragraph.paragraph_format.space_before = Pt(4)
    paragraph.paragraph_format.space_after = Pt(8)
    paragraph.paragraph_format.line_spacing = 1.0
    properties = paragraph._p.get_or_add_pPr()
    shading = OxmlElement('w:shd')
    shading.set(qn('w:val'), 'clear')
    shading.set(qn('w:color'), 'auto')
    shading.set(qn('w:fill'), 'F2F4EE')
    properties.append(shading)
    run = paragraph.add_run(code)
    run.font.name = 'Consolas'
    run.font.size = Pt(8.3)
    run.font.color.rgb = RGBColor(35, 55, 45)


def add_image(document, path: Path, alt: str):
    if not path.exists():
        add_rich_paragraph(document, f'[Missing image: {path.name}]', color=MUTED)
        return
    paragraph = document.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = paragraph.add_run()
    width = Inches(6.55)
    if path.name == 'erd.png':
        width = Inches(6.75)
    run.add_picture(str(path), width=width)
    if alt:
        caption = document.add_paragraph()
        caption.alignment = WD_ALIGN_PARAGRAPH.CENTER
        caption.paragraph_format.space_after = Pt(10)
        caption_run = caption.add_run(alt)
        caption_run.italic = True
        caption_run.font.size = Pt(8)
        caption_run.font.color.rgb = MUTED


def add_table(document, rows):
    if not rows:
        return
    columns = max(len(row) for row in rows)
    table = document.add_table(rows=0, cols=columns)
    table.style = 'Table Grid'
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = True
    set_cell_margins(table)
    for index, row in enumerate(rows):
        cells = table.add_row().cells
        for column in range(columns):
            text = row[column] if column < len(row) else ''
            cell = cells[column]
            cell.text = ''
            paragraph = cell.paragraphs[0]
            paragraph.paragraph_format.space_after = Pt(0)
            add_inline(paragraph, text, size=8 if index == 0 else 8.2)
            for run in paragraph.runs:
                if index == 0:
                    run.bold = True
                    run.font.color.rgb = RGBColor(255, 255, 255)
            if index == 0:
                shade(cell, '245C46')
            elif index % 2 == 0:
                shade(cell, 'F5F7F1')
    document.add_paragraph().paragraph_format.space_after = Pt(2)


def build_cover(document):
    for _ in range(2):
        document.add_paragraph()
    eyebrow = document.add_paragraph()
    eyebrow.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = eyebrow.add_run('SMART E-COMMERCE MARKETPLACE')
    run.font.name = 'Arial'
    run.font.size = Pt(10)
    run.font.bold = True
    run.font.color.rgb = GREEN

    title = document.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run('Rukomeza Market')
    run.font.name = 'Georgia'
    run.font.size = Pt(42)
    run.font.bold = True
    run.font.color.rgb = GREEN_DARK

    subtitle = document.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = subtitle.add_run('A multi-vendor marketplace with concurrency-safe inventory,\nprice snapshots and a documented mock payment flow')
    run.font.name = 'Georgia'
    run.font.size = Pt(15)
    run.font.color.rgb = GREEN

    report = document.add_paragraph()
    report.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = report.add_run('PROJECT REPORT')
    run.font.name = 'Arial'
    run.font.size = Pt(12)
    run.font.bold = True
    run.font.color.rgb = MUTED

    image_path = DOCS / 'screenshots' / '01-home.png'
    if image_path.exists():
        image = document.add_paragraph()
        image.alignment = WD_ALIGN_PARAGRAPH.CENTER
        image.add_run().add_picture(str(image_path), width=Inches(6.4))

    details = [
        ('Student', 'Joelle Rukomeza'),
        ('Stack', 'Django 6.1, PostgreSQL / SQLite, HTML/CSS/JS, Chart.js, Gunicorn, Render'),
        ('Repository', 'smart-ecommerce-marketplace'),
        ('Live URL', 'https://[your-service].onrender.com  (see Section 11)'),
        ('Date', 'November 2026'),
    ]
    table = document.add_table(rows=0, cols=2)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = True
    for label, value in details:
        cells = table.add_row().cells
        cells[0].text = ''
        cells[1].text = ''
        paragraph = cells[0].paragraphs[0]
        run = paragraph.add_run(label)
        run.bold = True
        run.font.size = Pt(9)
        run.font.color.rgb = GREEN_DARK
        paragraph = cells[1].paragraphs[0]
        run = paragraph.add_run(value)
        run.font.size = Pt(9)
        run.font.color.rgb = INK

    document.add_page_break()


def is_block_start(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    if stripped.startswith(('```', '#', '|', '![', '>', '---', '***')):
        return True
    if stripped.startswith(('- ', '* ', '+ ')):
        return True
    return bool(re.match(r'^\d+\.\s', stripped))


def build_document():
    document = Document()
    style_document(document)
    section = document.sections[0]
    section.page_width = Inches(8.27)
    section.page_height = Inches(11.69)
    section.top_margin = Inches(0.75)
    section.bottom_margin = Inches(0.7)
    section.left_margin = Inches(0.8)
    section.right_margin = Inches(0.8)
    add_page_number_footer(section)

    properties = document.core_properties
    properties.title = 'Rukomeza Market - Project Report'
    properties.author = 'Joelle Rukomeza'
    properties.subject = 'Smart E-Commerce Marketplace'
    properties.keywords = 'Django, marketplace, PostgreSQL, concurrency, price snapshot, mock payment'

    build_cover(document)

    contents = document.add_paragraph()
    contents_run = contents.add_run('Contents')
    contents_run.font.name = 'Georgia'
    contents_run.font.size = Pt(20)
    contents_run.font.bold = True
    contents_run.font.color.rgb = GREEN_DARK
    source_text = SOURCE.read_text(encoding='utf-8')
    section_titles = [
        title for title in re.findall(r'^##\s+(.+)$', source_text, flags=re.MULTILINE)
        if title.strip().lower() != 'table of contents'
    ]
    add_toc(document, section_titles)
    document.add_page_break()

    lines = source_text.splitlines()
    try:
        start = next(index for index, line in enumerate(lines) if line.startswith('## 1. Executive summary'))
    except StopIteration:
        start = 0
    lines = lines[start:]

    index = 0
    first_section = True
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        if stripped.startswith('```'):
            index += 1
            code_lines = []
            while index < len(lines) and not lines[index].strip().startswith('```'):
                code_lines.append(lines[index])
                index += 1
            index += 1
            add_code_block(document, '\n'.join(code_lines))
            continue

        if stripped.startswith('!['):
            match = re.match(r'!\[([^\]]*)\]\(([^)]+)\)', stripped)
            if match:
                path = (DOCS / match.group(2)).resolve()
                if not first_section:
                    pass
                add_image(document, path, match.group(1))
            index += 1
            continue

        if stripped.startswith('|'):
            table_lines = []
            while index < len(lines) and lines[index].strip().startswith('|'):
                table_lines.append(lines[index].strip())
                index += 1
            rows = []
            for row_index, table_line in enumerate(table_lines):
                cells = [cell.strip() for cell in table_line.strip('|').split('|')]
                if all(re.fullmatch(r':?-{2,}:?', cell.replace(' ', '')) for cell in cells if cell):
                    continue
                if row_index == 1 and all(set(cell) <= set('-: ') for cell in cells if cell):
                    continue
                rows.append(cells)
            add_table(document, rows)
            continue

        heading = re.match(r'^(#{1,4})\s+(.*)$', stripped)
        if heading:
            level = len(heading.group(1))
            text = heading.group(2).strip()
            if level == 1:
                continue
            if level == 2:
                if not first_section:
                    document.add_page_break()
                first_section = False
                document.add_heading(text, level=1)
            elif level == 3:
                document.add_heading(text, level=2)
            else:
                document.add_heading(text, level=3)
            index += 1
            continue

        if stripped in ('---', '***'):
            index += 1
            continue

        if stripped.startswith('> '):
            add_rich_paragraph(document, stripped[2:], style=None, color=MUTED, size=9.5)
            index += 1
            continue

        if stripped.startswith(('- ', '* ', '+ ')):
            parts = [stripped[2:]]
            index += 1
            while index < len(lines) and not is_block_start(lines[index]):
                parts.append(lines[index].strip())
                index += 1
            add_rich_paragraph(document, ' '.join(parts), style='List Bullet')
            continue

        numbered = re.match(r'^\d+\.\s+(.*)$', stripped)
        if numbered:
            parts = [numbered.group(1)]
            index += 1
            while index < len(lines) and not is_block_start(lines[index]):
                parts.append(lines[index].strip())
                index += 1
            add_rich_paragraph(document, ' '.join(parts), style='List Number')
            continue

        if not stripped:
            index += 1
            continue

        parts = [stripped]
        index += 1
        while index < len(lines) and not is_block_start(lines[index]):
            parts.append(lines[index].strip())
            index += 1
        add_rich_paragraph(document, ' '.join(parts))

    document.save(OUTPUT)
    print(f'Wrote {OUTPUT} ({OUTPUT.stat().st_size // 1024} KB)')


if __name__ == '__main__':
    build_document()
