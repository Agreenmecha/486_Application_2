"""
Convert Galil DMC 41X3 Command Reference PDF to Markdown.
Uses pymupdf dict with exact span coordinates for accurate reconstruction.
"""
import fitz
import re

PDF_PATH = r'c:\Users\aaron\Documents\486_Application_2\Galil DMC 41X3 Command Reference.pdf'
OUT_PATH = r'c:\Users\aaron\Documents\486_Application_2\Galil_DMC_41X3_Command_Reference.md'

SECTION_HEADERS = {
    'Description', 'Arguments', 'Remarks', 'Examples', 'Usage',
    'Operands', 'Related Commands', 'See Also', 'Notes', 'Operation',
}

# Column x-thresholds for argument tables (midpoints between header x0 values)
# Header x0s: Argument≈45, Min≈107, Max≈156, Default≈199, Resolution≈242, Description≈291-332, Notes≈388-448
# We bucket by x0 ranges:
COL_THRESHOLDS = [45, 95, 140, 185, 225, 270, 400, 600]  # left edges of each column

def clean(t):
    return t.replace('\ufffd', '©').replace('\u00a9', '©')

def is_bold(flags): return bool(flags & 16)
def is_italic(flags): return bool(flags & 4)

def x_to_col(x, col_starts):
    """Map an x coordinate to a column using midpoints between header positions."""
    if len(col_starts) <= 1:
        return 0
    midpoints = [(col_starts[i] + col_starts[i + 1]) / 2 for i in range(len(col_starts) - 1)]
    col = 0
    for i, mid in enumerate(midpoints):
        if x > mid:
            col = i + 1
    return col


def parse_table_block(block):
    """
    Parse a table block using line x-coordinates.
    Returns (headers, rows) where headers is list of strings and rows is list of lists.
    Returns None if block doesn't look like an arg table.
    """
    lines = block['lines']
    if not lines:
        return None

    # Check first few lines for header pattern
    first_line_texts = [s['text'].strip() for s in lines[0]['spans'] if s['text'].strip()]
    if not first_line_texts or first_line_texts[0] not in ('Argument', 'Usage'):
        return None

    is_arg_table = first_line_texts[0] == 'Argument'
    is_usage_table = first_line_texts[0] == 'Usage'

    if is_usage_table:
        return parse_usage_block(block)

    # It's an argument table - collect header row (bold lines at top y)
    # First, find the y-range of header row (the first ~10 lines should all be at same y)
    header_y = lines[0]['spans'][0]['bbox'][1]
    header_cols = []  # (x0, text) for each header cell
    data_lines = []

    for line in lines:
        spans = [s for s in line['spans'] if s['text'].strip()]
        if not spans:
            continue
        y = spans[0]['bbox'][1]
        text = ' '.join(s['text'] for s in line['spans']).strip()

        # Check if this is a section header (signals end of table)
        if is_bold(spans[0]['flags']) and spans[0]['size'] > 11 and text in SECTION_HEADERS:
            break

        # Determine if header row (all bold, y close to header_y)
        if abs(y - header_y) < 5 and all(is_bold(s['flags']) for s in spans if s['text'].strip()):
            x0 = spans[0]['bbox'][0]
            header_cols.append((x0, text))
        else:
            data_lines.append((y, spans))

    if not header_cols:
        return None

    # Sort header_cols by x
    header_cols.sort(key=lambda h: h[0])
    col_starts = [h[0] for h in header_cols]
    headers = [h[1] for h in header_cols]
    num_cols = len(headers)

    # Group data_lines into rows by y-coordinate
    # Each (y, spans) represents ONE table cell (a PDF "line" = one cell)
    rows_by_y = {}
    for y, spans in data_lines:
        y_key = round(y / 2) * 2
        if y_key not in rows_by_y:
            rows_by_y[y_key] = [''] * num_cols
        # Use x0 of first span to determine column; all spans are part of this cell
        x0 = spans[0]['bbox'][0]
        col_idx = x_to_col(x0, col_starts)
        cell_text = ' '.join(s['text'].strip() for s in spans if s['text'].strip())
        if col_idx < num_cols:
            existing = rows_by_y[y_key][col_idx]
            rows_by_y[y_key][col_idx] = (existing + ' ' + cell_text).strip() if existing else cell_text

    rows = [rows_by_y[y] for y in sorted(rows_by_y.keys())]

    return headers, rows


def parse_usage_block(block):
    """Parse a Usage/Operands block into a simple list."""
    lines = block['lines']
    usage_items = []
    operands = []
    mode = 'usage'
    section_end = None

    for line in lines:
        spans = [s for s in line['spans'] if s['text'].strip()]
        if not spans:
            continue
        text = ' '.join(s['text'] for s in spans).strip()
        bold = is_bold(spans[0]['flags'])
        size = spans[0]['size']

        if text == 'Usage':
            mode = 'usage'
            continue
        if text == 'Operands':
            mode = 'operands'
            continue
        if bold and size > 11 and text in SECTION_HEADERS:
            section_end = text
            break

        if mode == 'usage':
            # Two columns: syntax | description
            if bold:
                # It's a new syntax entry
                x0 = spans[0]['bbox'][0]
                desc_spans = [s for s in spans if s['bbox'][0] > x0 + 20]
                cmd = spans[0]['text'].strip()
                desc = ' '.join(s['text'] for s in desc_spans).strip()
                usage_items.append((cmd, desc))
            else:
                # Continuation
                if usage_items:
                    cmd, desc = usage_items[-1]
                    extra = ' '.join(s['text'] for s in spans)
                    usage_items[-1] = (cmd, (desc + ' ' + extra).strip())
        elif mode == 'operands':
            x0 = spans[0]['bbox'][0]
            op_spans = [s for s in spans if s['bbox'][0] < x0 + 60]
            desc_spans = [s for s in spans if s['bbox'][0] >= x0 + 60]
            op = ' '.join(s['text'] for s in op_spans).strip()
            desc = ' '.join(s['text'] for s in desc_spans).strip()
            operands.append((op, desc))

    return ('usage_operands', usage_items, operands, section_end)


def table_to_md(headers, rows):
    sep = ' | '.join(['---'] * len(headers))
    lines = ['| ' + ' | '.join(headers) + ' |', '| ' + sep + ' |']
    for row in rows:
        lines.append('| ' + ' | '.join(str(c) for c in row) + ' |')
    return '\n'.join(lines)


def is_footer_block(block):
    """Detect footer blocks by y position or text pattern."""
    y0 = block['bbox'][1]
    if y0 > 700:  # Very bottom of page
        return True
    all_spans = [s for line in block['lines'] for s in line['spans']]
    text = ''.join(s['text'] for s in all_spans).strip()
    return bool(
        re.match(r'^©\d{4} Galil', text) or
        re.search(r'Corrections, Feedback: support@galil\.com', text)
    )


def is_toc_page(blocks):
    """
    TOC pages have a block that is a long run of concatenated page numbers,
    or contain a 'Table of Content' block.
    """
    for b in blocks:
        all_spans = [s for line in b['lines'] for s in line['spans']]
        text = ''.join(s['text'] for s in all_spans).strip()
        if re.match(r'^\d{4,}', text):   # Long concatenated digit string
            return True
        if text == 'Table of Content':
            return True
    return False


def process_toc(page):
    """Use plain text for TOC pages — dict mode concatenates TOC entries."""
    raw = clean(page.get_text())
    lines = []
    seen_toc = False
    for line in raw.split('\n'):
        line = line.strip()
        if not line or re.match(r'^\d+$', line):
            continue
        if re.match(r'^©\d{4} Galil', line):
            continue
        if 'Galil Motion Control' in line:
            continue
        if re.search(r'\d+/\d+$', line):
            continue
        if line == 'Table of Content':
            if not seen_toc:
                lines.append('## Table of Contents\n')
                seen_toc = True
            continue
        lines.append(line)
    return '\n'.join(lines)


def get_block_text(block):
    all_spans = [s for line in block['lines'] for s in line['spans']]
    return clean(''.join(s['text'] for s in all_spans)).strip()


def get_block_lines(block):
    """Return list of non-empty line strings from a block."""
    result = []
    for line in block['lines']:
        line_text = ''.join(s['text'] for s in line['spans'])
        if line_text.strip():
            result.append(line_text)
    return result


def process_command_page(blocks):
    parts = []
    processed_block_indices = set()

    for i, b in enumerate(blocks):
        if i in processed_block_indices:
            continue
        if is_footer_block(b):
            continue

        all_spans = [s for line in b['lines'] for s in line['spans']]
        text = get_block_text(b)
        if not text:
            continue

        first_sp = next((s for s in all_spans if s['text'].strip()), all_spans[0])
        size = first_sp['size']
        flags = first_sp['flags']

        # ── Block 0: Command header ──
        if i == 0:
            cat, cmd, desc = '', '', ''
            for sp in all_spans:
                t = sp['text'].strip()
                if not t:
                    continue
                if abs(sp['size'] - 16.7) < 1:
                    cmd = t
                elif abs(sp['size'] - 10.9) < 1:
                    desc = (desc + ' ' + t).strip()
                elif abs(sp['size'] - 9.8) < 1:
                    cat = (cat + ' ' + t).strip().strip(',')
            if cmd:
                parts.append(f'## `{cmd}` — {desc}')
                if cat:
                    parts.append(f'*Category: {cat}*\n')
            else:
                parts.append(f'## {text}')
            continue

        # ── Skip spacer blocks (only whitespace) ──
        if not text:
            continue

        # ── Syntax block: bold+italic, size ~13.2 ──
        if abs(size - 13.2) < 0.4 and is_bold(flags) and text not in SECTION_HEADERS:
            syntax_lines = get_block_lines(b)
            parts.append('\n**Syntax:**')
            parts.append('```')
            parts.extend(syntax_lines)
            parts.append('```')
            continue

        # ── Section header block: bold, size ~12.7 ──
        if abs(size - 12.7) < 1 and is_bold(flags) and text in SECTION_HEADERS:
            parts.append(f'\n### {text}')
            continue

        # ── Usage/Operands table block ──
        if is_bold(flags) and abs(size - 9.8) < 1 and text.startswith('Usage'):
            result = parse_usage_block(b)
            if result and result[0] == 'usage_operands':
                _, usage_items, operands, section_end = result
                if usage_items:
                    parts.append('\n### Usage')
                    for cmd_s, desc_s in usage_items:
                        if desc_s:
                            parts.append(f'- `{cmd_s}` — {desc_s}')
                        else:
                            parts.append(f'- `{cmd_s}`')
                if operands:
                    parts.append('\n### Operands')
                    for op, desc_s in operands:
                        if desc_s:
                            parts.append(f'- `{op}` — {desc_s}')
                        else:
                            parts.append(f'- `{op}`')
                if section_end:
                    parts.append(f'\n### {section_end}')
            continue

        # ── Argument table block ──
        if is_bold(flags) and abs(size - 9.8) < 1 and text.startswith('Argument'):
            result = parse_table_block(b)
            if result and result[0] != 'usage_operands':
                headers, rows = result
                parts.append(table_to_md(headers, rows))
                # Check if block ends with a section header
                last_lines = b['lines'][-3:]
                for line in last_lines:
                    for sp in line['spans']:
                        t = sp['text'].strip()
                        if t in SECTION_HEADERS and is_bold(sp['flags']) and sp['size'] > 11:
                            parts.append(f'\n### {t}')
            continue

        # ── Applies-to line ──
        applies_match = re.match(r'^(.+?)\s+applies to\s+(.+)$', text)
        if applies_match or re.match(r'^# applies to', text, re.I):
            if applies_match:
                cmd_part = applies_match.group(1).strip()
                devices = applies_match.group(2).strip()
                parts.append(f'\n*Applies to: {devices}*')
            else:
                parts.append(f'\n*{text}*')
            continue

        # ── Code example block: size ~8.1 ──
        if abs(size - 8.1) < 0.5:
            code_lines = get_block_lines(b)
            if code_lines:
                parts.append('```dmc')
                parts.extend(code_lines)
                parts.append('```')
            continue

        # ── Body text: detect embedded section headers and split ──
        # Some blocks have body text + section header appended (e.g. "...text.Arguments")
        # Split these out
        body_parts = split_embedded_headers(b, all_spans, text)
        parts.extend(body_parts)

    return '\n'.join(parts)


def split_embedded_headers(block, all_spans, full_text):
    """
    Handle blocks where section header text is embedded at start/end.
    e.g. "body text.Remarks" or "Arguments\nbody text"
    """
    parts = []

    # Check if last span is a section header (bold, size 12.7)
    # Scan spans in reverse to find trailing section header
    trailing_header = None
    leading_header = None

    for sp in all_spans:
        t = sp['text'].strip()
        if t in SECTION_HEADERS and is_bold(sp['flags']) and abs(sp['size'] - 12.7) < 1:
            # Is this at the very end?
            trailing_header = t

    # Also check if full text ends with a known header
    for hdr in SECTION_HEADERS:
        if full_text.endswith(hdr):
            body = full_text[:-len(hdr)].rstrip()
            if body:
                parts.append(format_body(block, all_spans, body))
            parts.append(f'\n### {hdr}')
            return parts

    # Check if full text starts with a known header
    for hdr in SECTION_HEADERS:
        if full_text.startswith(hdr + '\n') or full_text == hdr:
            rest = full_text[len(hdr):].strip()
            parts.append(f'\n### {hdr}')
            if rest:
                parts.append(format_body(block, all_spans, rest))
            return parts

    # Plain body
    parts.append(format_body(block, all_spans, full_text))
    return parts


def format_body(block, all_spans, text):
    """
    Format body text. Uses the pre-trimmed `text` string for content,
    and inline-formats based on spans that fall within it.
    """
    if not text:
        return ''
    # Simple approach: return clean text as-is (inline bold/italic rarely
    # critical in reference body text, and avoids re-reading trimmed spans)
    result = re.sub(r' {2,}', ' ', text)
    result = re.sub(r'\n{3,}', '\n\n', result)
    return result.strip()


def convert_pdf_to_md(pdf_path, out_path):
    doc = fitz.open(pdf_path)
    total = len(doc)
    print(f"Converting {total} pages...")

    sections = []
    sections.append('# Galil DMC-41X3 Firmware Command Reference\n')
    sections.append('> Revision: 1840 — 05/17/22  \n> © 2022 Galil Motion Control\n')
    sections.append('---\n')

    for page_num in range(total):
        page = doc[page_num]
        d = page.get_text('dict')
        blocks = [b for b in d['blocks'] if 'lines' in b]

        if page_num == 0:
            continue

        if is_toc_page(blocks):
            toc = process_toc(page)
            if toc.strip():
                sections.append(toc)
            continue

        cmd_md = process_command_page(blocks)
        if cmd_md.strip():
            sections.append(cmd_md)
            sections.append('\n---\n')

        if (page_num + 1) % 50 == 0:
            print(f"  {page_num + 1}/{total} pages...")

    result = '\n'.join(sections)
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(result)
    print(f"\nDone! {out_path}")
    print(f"Size: {len(result):,} chars, {result.count(chr(10)):,} lines")


if __name__ == '__main__':
    convert_pdf_to_md(PDF_PATH, OUT_PATH)
