"""
Election Intelligence — Professional Pitch Deck PDF Generator
Landscape A4, slide-style pages with dark theme.
"""

import io, os
from datetime import datetime
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm, inch
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, HRFlowable, KeepTogether, Frame, PageTemplate, BaseDocTemplate
)
from reportlab.graphics.shapes import Drawing, Rect, String, Circle, Line
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# ── Colors ───────────────────────────────────────────────────────
BG       = colors.HexColor('#0a0c10')
SURFACE  = colors.HexColor('#13151c')
CARD     = colors.HexColor('#1a1d27')
BORDER   = colors.HexColor('#2a2d3a')
TEXT     = colors.HexColor('#e8e8ec')
MUTED    = colors.HexColor('#8b8fa3')
ORANGE   = colors.HexColor('#f97316')
ORANGE_D = colors.HexColor('#c2410c')
GREEN    = colors.HexColor('#22c55e')
RED      = colors.HexColor('#ef4444')
BLUE     = colors.HexColor('#3b82f6')
PURPLE   = colors.HexColor('#a855f7')
YELLOW   = colors.HexColor('#eab308')
TEAL     = colors.HexColor('#14b8a6')
PINK     = colors.HexColor('#ec4899')
WHITE    = colors.white
DARK_CARD_BG = colors.HexColor('#1e2130')

PAGE_W, PAGE_H = landscape(A4)  # 842 x 595
MARGIN = 40

# ── Styles ───────────────────────────────────────────────────────
def _styles():
    S = {}
    S['slide_title'] = ParagraphStyle('SlideTitle', fontName='Helvetica-Bold', fontSize=28,
        textColor=WHITE, leading=34, spaceAfter=6)
    S['slide_title_lg'] = ParagraphStyle('SlideTitleLg', fontName='Helvetica-Bold', fontSize=36,
        textColor=WHITE, leading=42, spaceAfter=8)
    S['section_label'] = ParagraphStyle('SectionLabel', fontName='Helvetica-Bold', fontSize=9,
        textColor=ORANGE, leading=12, spaceAfter=4, tracking=200)
    S['subtitle'] = ParagraphStyle('Subtitle', fontName='Helvetica', fontSize=14,
        textColor=MUTED, leading=20, spaceAfter=16)
    S['body'] = ParagraphStyle('Body', fontName='Helvetica', fontSize=10,
        textColor=colors.HexColor('#c4c4cc'), leading=15, spaceAfter=6)
    S['body_sm'] = ParagraphStyle('BodySm', fontName='Helvetica', fontSize=8.5,
        textColor=MUTED, leading=12, spaceAfter=4)
    S['h2'] = ParagraphStyle('H2', fontName='Helvetica-Bold', fontSize=13,
        textColor=WHITE, leading=16, spaceAfter=6, spaceBefore=8)
    S['h3'] = ParagraphStyle('H3', fontName='Helvetica-Bold', fontSize=11,
        textColor=ORANGE, leading=14, spaceAfter=4, spaceBefore=4)
    S['kpi_num'] = ParagraphStyle('KPINum', fontName='Helvetica-Bold', fontSize=26,
        textColor=ORANGE, leading=30, alignment=TA_CENTER)
    S['kpi_label'] = ParagraphStyle('KPILabel', fontName='Helvetica-Bold', fontSize=7.5,
        textColor=MUTED, leading=10, alignment=TA_CENTER, tracking=100)
    S['bullet'] = ParagraphStyle('Bullet', fontName='Helvetica', fontSize=10,
        textColor=colors.HexColor('#c4c4cc'), leading=14, spaceAfter=3,
        leftIndent=16, bulletIndent=0, bulletFontName='Helvetica', bulletFontSize=10)
    S['center'] = ParagraphStyle('Center', fontName='Helvetica', fontSize=10,
        textColor=MUTED, leading=14, alignment=TA_CENTER)
    S['center_bold'] = ParagraphStyle('CenterBold', fontName='Helvetica-Bold', fontSize=11,
        textColor=WHITE, leading=14, alignment=TA_CENTER)
    S['footer'] = ParagraphStyle('Footer', fontName='Helvetica', fontSize=7,
        textColor=MUTED, alignment=TA_CENTER)
    S['tag'] = ParagraphStyle('Tag', fontName='Helvetica-Bold', fontSize=7.5,
        textColor=ORANGE, leading=10)
    return S


# ── Helper drawing functions ─────────────────────────────────────
def _gradient_bar(x, y, w, h=3):
    """Draw a gradient accent bar."""
    d = Drawing(w, h)
    # Simulate gradient with 3 rects
    third = w / 3
    d.add(Rect(x, 0, third, h, fillColor=ORANGE, strokeColor=None))
    d.add(Rect(x + third, 0, third, h, fillColor=RED, strokeColor=None))
    d.add(Rect(x + 2*third, 0, third, h, fillColor=PURPLE, strokeColor=None))
    return d


def _card_table(rows, col_widths, header=True, accent_col=None):
    """Create a styled table that looks like a dark card."""
    style_cmds = [
        ('BACKGROUND', (0, 0), (-1, -1), CARD),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#c4c4cc')),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 8.5),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
        ('RIGHTPADDING', (0, 0), (-1, -1), 10),
        ('GRID', (0, 0), (-1, -1), 0.5, BORDER),
        ('ROUNDEDCORNERS', [6, 6, 6, 6]),
    ]
    if header:
        style_cmds += [
            ('BACKGROUND', (0, 0), (-1, 0), SURFACE),
            ('TEXTCOLOR', (0, 0), (-1, 0), MUTED),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 7.5),
        ]
    if accent_col is not None:
        style_cmds.append(('TEXTCOLOR', (accent_col, 1), (accent_col, -1), ORANGE))
        style_cmds.append(('FONTNAME', (accent_col, 1), (accent_col, -1), 'Helvetica-Bold'))
    t = Table(rows, colWidths=col_widths, repeatRows=1 if header else 0)
    t.setStyle(TableStyle(style_cmds))
    return t


def _kpi_card(num, label, num_color=ORANGE):
    """Single KPI as a mini table-cell."""
    S = _styles()
    ns = ParagraphStyle('n', parent=S['kpi_num'], textColor=num_color)
    return Table(
        [[Paragraph(str(num), ns)], [Paragraph(label.upper(), S['kpi_label'])]],
        colWidths=[120], rowHeights=[34, 16]
    )


def _kpi_row(kpis, total_width=None):
    """Row of KPI cards. kpis = [(num, label, color), ...]"""
    if total_width is None:
        total_width = PAGE_W - 2 * MARGIN
    w = total_width / len(kpis)
    cells = []
    for num, label, clr in kpis:
        cells.append(_kpi_card(num, label, clr))
    t = Table([cells], colWidths=[w]*len(kpis))
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), CARD),
        ('GRID', (0, 0), (-1, -1), 0.5, BORDER),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    return t


def _divider():
    return HRFlowable(width="100%", thickness=1, color=BORDER, spaceAfter=8, spaceBefore=4)


def _check(text, S):
    return Paragraph(f'<font color="#22c55e"><b>✓</b></font>&nbsp;&nbsp;{text}', S['body'])


def _cross(text, S):
    return Paragraph(f'<font color="#ef4444"><b>✗</b></font>&nbsp;&nbsp;{text}', S['body'])


def _bullet(text, S):
    return Paragraph(f'<font color="#f97316">▸</font>&nbsp;&nbsp;{text}', S['body'])


def _tag(text, color_hex='#f97316'):
    S = _styles()
    ps = ParagraphStyle('tg', parent=S['tag'], textColor=colors.HexColor(color_hex))
    return Paragraph(f'<font size="7.5"><b>[{text}]</b></font>', ps)


def _flow_arrow():
    d = Drawing(20, 14)
    d.add(String(2, 2, '→', fontName='Helvetica-Bold', fontSize=14, fillColor=ORANGE))
    return d


# ── Page background ──────────────────────────────────────────────
def _draw_bg(canvas, doc):
    """Dark background + footer on every page."""
    canvas.saveState()
    canvas.setFillColor(BG)
    canvas.rect(0, 0, PAGE_W, PAGE_H, fill=True, stroke=False)
    # Top accent line
    canvas.setFillColor(ORANGE)
    canvas.rect(0, PAGE_H - 3, PAGE_W / 3, 3, fill=True, stroke=False)
    canvas.setFillColor(RED)
    canvas.rect(PAGE_W / 3, PAGE_H - 3, PAGE_W / 3, 3, fill=True, stroke=False)
    canvas.setFillColor(PURPLE)
    canvas.rect(2 * PAGE_W / 3, PAGE_H - 3, PAGE_W / 3, 3, fill=True, stroke=False)
    # Footer
    canvas.setFont('Helvetica', 7)
    canvas.setFillColor(MUTED)
    canvas.drawCentredString(PAGE_W / 2, 18, f'Election Intelligence — Confidential Product Overview — {datetime.now().strftime("%B %Y")}')
    canvas.drawRightString(PAGE_W - MARGIN, 18, f'{doc.page}')
    canvas.restoreState()


# ═════════════════════════════════════════════════════════════════
# MAIN GENERATOR
# ═════════════════════════════════════════════════════════════════
def generate_pitch_deck():
    buf = io.BytesIO()
    doc = BaseDocTemplate(buf, pagesize=landscape(A4),
        leftMargin=MARGIN, rightMargin=MARGIN, topMargin=MARGIN + 8, bottomMargin=MARGIN)
    
    content_w = PAGE_W - 2 * MARGIN
    half_w = (content_w - 20) / 2
    third_w = (content_w - 24) / 3
    quarter_w = (content_w - 24) / 4

    frame = Frame(MARGIN, MARGIN, content_w, PAGE_H - 2*MARGIN - 8,
                  id='main', showBoundary=0)
    doc.addPageTemplates([PageTemplate(id='slide', frames=[frame], onPage=_draw_bg)])

    S = _styles()
    story = []

    # ─────────────────────────────────────────────────────────────
    # SLIDE 1: COVER
    # ─────────────────────────────────────────────────────────────
    story.append(Spacer(1, 60))
    story.append(Paragraph(
        '<font color="#f97316" size="9"><b>⚡ ELECTION CAMPAIGN INTELLIGENCE PLATFORM</b></font>', S['center']))
    story.append(Spacer(1, 16))
    title_s = ParagraphStyle('CoverTitle', fontName='Helvetica-Bold', fontSize=38,
        textColor=WHITE, leading=44, alignment=TA_CENTER)
    story.append(Paragraph('Win Elections with', title_s))
    story.append(Paragraph('<font color="#f97316">Data-Driven</font> Ground Strategy', title_s))
    story.append(Spacer(1, 16))
    story.append(Paragraph(
        'AI-powered voter analytics, micro-targeting, and field operations platform —<br/>'
        'from PDF voter lists to winning formula in minutes.', 
        ParagraphStyle('cs', parent=S['subtitle'], alignment=TA_CENTER, fontSize=13)))
    story.append(Spacer(1, 30))
    story.append(_kpi_row([
        ('30+', 'Analytics Metrics', ORANGE),
        ('16', 'Report Sections', GREEN),
        ('9', 'Hierarchy Levels', BLUE),
        ('< 1s', 'Per Page OCR', PURPLE),
        ('10', 'Dashboard Tabs', TEAL),
    ]))
    story.append(PageBreak())

    # ─────────────────────────────────────────────────────────────
    # SLIDE 2: PROBLEM
    # ─────────────────────────────────────────────────────────────
    story.append(Paragraph('THE PROBLEM', S['section_label']))
    story.append(Paragraph('Election campaigns still rely on <font color="#f97316">gut feeling</font> over ground data', S['slide_title']))
    story.append(Spacer(1, 12))
    
    problems = [
        ('📄', 'Unusable Voter Data', 'Voter lists are 50-page image PDFs — require days of manual data entry before any analysis.'),
        ('🎯', 'No Booth-Level Strategy', 'Same blanket approach for every polling station. No micro-targeting, no prioritization.'),
        ('🏘️', 'Caste Arithmetic on Paper', 'Community composition discussed in meetings, never connected to actual voter records.'),
        ('📞', 'No Field Tracking', 'Contacts, slip delivery, sentiment — all lost in phone calls and WhatsApp groups.'),
        ('🗳️', 'Election Day Chaos', 'No priority list, no real-time turnout tracking, no transport coordination system.'),
        ('📊', 'History Ignored', 'Past election patterns and turnout trends never systematically analyzed.'),
    ]
    
    prob_rows = []
    for icon, title, desc in problems:
        prob_rows.append([
            Paragraph(f'<font size="14">{icon}</font>', S['center']),
            Paragraph(f'<b>{title}</b>', ParagraphStyle('pt', parent=S['body'], textColor=WHITE)),
            Paragraph(desc, S['body_sm']),
        ])
    
    prob_table = Table(prob_rows, colWidths=[30, 140, content_w - 190])
    prob_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), CARD),
        ('GRID', (0, 0), (-1, -1), 0.5, BORDER),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('ROWBACKGROUNDS', (0, 0), (-1, -1), [CARD, DARK_CARD_BG]),
    ]))
    story.append(prob_table)
    story.append(Spacer(1, 12))
    story.append(Paragraph(
        '<font color="#ef4444"><b>Result:</b></font> Campaigns waste <font color="#ef4444"><b>40-60%</b></font> '
        'of field effort on non-convertible voters. No data means no strategy.', S['body']))
    story.append(PageBreak())

    # ─────────────────────────────────────────────────────────────
    # SLIDE 3: SOLUTION — 3 STEPS
    # ─────────────────────────────────────────────────────────────
    story.append(Paragraph('THE SOLUTION', S['section_label']))
    story.append(Paragraph('From <font color="#f97316">raw PDF</font> to <font color="#f97316">winning strategy</font> — in 3 steps', S['slide_title']))
    story.append(Spacer(1, 20))

    steps = [
        ('📄', 'Upload PDF', 'Drop any ECI voter list\n(scanned or digital)'),
        ('🔍', 'AI Extraction', 'OCR + smart parsing\nextracts every voter'),
        ('👥', 'Auto-Enrich', 'Families, communities,\nflags auto-detected'),
        ('📊', '30+ Analytics', 'Demographics, caste,\nbooth analysis'),
        ('🎯', 'Winning Formula', 'Per-booth targets,\nswing voters needed'),
        ('📋', 'Action Plan', 'Field ops, contacts,\nelection day plan'),
    ]
    
    step_cells = []
    for icon, title, desc in steps:
        step_cells.append(Table([
            [Paragraph(f'<font size="18">{icon}</font>', S['center'])],
            [Paragraph(f'<b>{title}</b>', S['center_bold'])],
            [Paragraph(desc, ParagraphStyle('sd', parent=S['body_sm'], alignment=TA_CENTER))],
        ], colWidths=[110]))
    
    flow_cells = []
    for i, cell in enumerate(step_cells):
        flow_cells.append(cell)
        if i < len(step_cells) - 1:
            flow_cells.append(Paragraph('<font color="#f97316" size="14"><b>→</b></font>', S['center']))
    
    widths = []
    for i in range(len(flow_cells)):
        widths.append(110 if i % 2 == 0 else 18)
    
    flow_table = Table([flow_cells], colWidths=widths)
    flow_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
    ]))
    story.append(flow_table)
    story.append(Spacer(1, 24))

    # 3 value props
    vp_data = [
        ('⚡ Instant Intelligence', 'Upload a scanned PDF voter list. OCR processes ~1 second/page, extracts name, age, gender, house, family — automatically.'),
        ('🧠 Smart Enrichment', 'Auto-detects surnames, maps 60+ communities, groups households, flags youth/senior/first-time voters, assigns unique IDs.'),
        ('🏆 Winning Formula', 'Per-booth: expected turnout × 50%+1 = target. Confirms Pakka voters. Calculates swing needed. Status: SAFE / WINNABLE / TOUGH.'),
    ]
    vp_rows = [[
        Table([
            [Paragraph(f'<b>{t}</b>', ParagraphStyle('vt', parent=S['h3']))],
            [Paragraph(d, S['body_sm'])],
        ], colWidths=[third_w]) for t, d in vp_data
    ]]
    vp_table = Table(vp_rows, colWidths=[third_w + 8]*3)
    vp_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), CARD),
        ('GRID', (0, 0), (-1, -1), 0.5, BORDER),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 12),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
        ('LEFTPADDING', (0, 0), (-1, -1), 12),
        ('RIGHTPADDING', (0, 0), (-1, -1), 12),
    ]))
    story.append(vp_table)
    story.append(PageBreak())

    # ─────────────────────────────────────────────────────────────
    # SLIDE 4: PLATFORM OVERVIEW — 10 TABS
    # ─────────────────────────────────────────────────────────────
    story.append(Paragraph('PLATFORM OVERVIEW', S['section_label']))
    story.append(Paragraph('10-Tab Dashboard — Everything a Campaign Needs', S['slide_title']))
    story.append(Spacer(1, 10))

    tabs = [
        ('📊', 'Overview', 'Demographics, age distribution, gender charts, community composition, top surnames'),
        ('⚡', 'Strategy', 'Conversion funnel, caste arithmetic, 3-contact plan, family influence, time slots'),
        ('🏠', 'Family Tree', 'Household grouping, family heads, member details, influence mapping'),
        ('🎯', 'Booth Strategy', 'Booth strength meter, winning formula per booth, SAFE/WINNABLE/TOUGH status'),
        ('👥', 'Voter Data', 'Search, filter, classify, tag every voter. Inline editing. CSV export'),
        ('🏷️', 'Tags', 'Scheme beneficiaries, party lean, bulk tagging, scheme coverage analysis'),
        ('📈', 'History', 'Past election results, party trends, turnout patterns, historical analysis'),
        ('🚶', 'Field Ops', 'Panna Pramukh plan, contact tracking, sentiment analysis, slip distribution'),
        ('🗳️', 'Election Day', 'Live turnout tracker, priority pending, transport needs, vote simulator'),
        ('✅', 'Data Quality', 'Missing fields, duplicates, quality score, volunteer requirement calculator'),
    ]
    
    tab_rows = []
    for i in range(0, 10, 2):
        row = []
        for j in range(2):
            idx = i + j
            icon, name, desc = tabs[idx]
            row.append(Table([
                [Paragraph(f'<font size="12">{icon}</font> <b>{name}</b>', 
                    ParagraphStyle('tn', parent=S['body'], textColor=WHITE, fontSize=10))],
                [Paragraph(desc, S['body_sm'])],
            ], colWidths=[half_w]))
        tab_rows.append(row)
    
    tab_table = Table(tab_rows, colWidths=[half_w + 10]*2)
    tab_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), CARD),
        ('GRID', (0, 0), (-1, -1), 0.5, BORDER),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ('LEFTPADDING', (0, 0), (-1, -1), 12),
        ('RIGHTPADDING', (0, 0), (-1, -1), 12),
        ('ROWBACKGROUNDS', (0, 0), (-1, -1), [CARD, DARK_CARD_BG]),
    ]))
    story.append(tab_table)
    story.append(PageBreak())

    # ─────────────────────────────────────────────────────────────
    # SLIDE 5: DATA INGESTION
    # ─────────────────────────────────────────────────────────────
    story.append(Paragraph('DATA INGESTION', S['section_label']))
    story.append(Paragraph('Upload scanned PDFs — we handle the rest', S['slide_title']))
    story.append(Spacer(1, 10))

    ing_data = [
        ('📄 Image PDF', 'Scanned ECI voter list PDFs processed with\nnative Windows OCR at ~1 second per page'),
        ('🔤 Text PDF', 'Digitally generated PDFs parsed directly\nwith PyMuPDF — instant extraction'),
        ('📊 CSV / TXT', 'Import voter data from spreadsheets\nor plain text files'),
        ('🧩 Smart Parsing', '3 cascading parsers auto-detect ECI roll\nformat, box format, and text format'),
    ]
    ing_cells = []
    for t, d in ing_data:
        ing_cells.append(Table([
            [Paragraph(f'<b>{t}</b>', ParagraphStyle('it', parent=S['h3'], fontSize=10))],
            [Paragraph(d, S['body_sm'])],
        ], colWidths=[quarter_w]))
    
    ing_table = Table([ing_cells], colWidths=[quarter_w + 6]*4)
    ing_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), CARD),
        ('GRID', (0, 0), (-1, -1), 0.5, BORDER),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 12),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
    ]))
    story.append(ing_table)
    story.append(Spacer(1, 14))

    story.append(Paragraph('<b>Auto-Extracted Per Voter (17 fields)</b>', S['h2']))
    fields = ['Name', 'Father Name', 'Age', 'Gender', 'Voter ID (EPIC)', 'House Number',
              'Serial Number', 'Booth / Part No', 'Surname', 'Community (auto-mapped)',
              'Family ID', 'Family Size', 'First-Time Voter', 'Youth Flag', 'Senior Flag',
              'Transport Need', 'Unique NQT ID']
    field_text = ' &nbsp; | &nbsp; '.join([f'<font color="#f97316"><b>{f}</b></font>' for f in fields])
    story.append(Paragraph(field_text, ParagraphStyle('ft', parent=S['body_sm'], fontSize=8, leading=13)))
    story.append(Spacer(1, 10))

    enrich = ['Classification (Pakka/Virodhi/Swing/Doubtful)', 'Sentiment', 'Contact Count',
              'Slip Delivered', 'Voted', 'Tags[ ]', 'Caste (override)', 'Party Lean',
              'Beneficiary Status', 'Migrated', 'Notes', 'Influence Score']
    enrich_text = ' &nbsp; | &nbsp; '.join([f'<font color="#3b82f6"><b>{f}</b></font>' for f in enrich])
    story.append(Paragraph('<b>Enrichable Fields (field worker edits)</b>', S['h2']))
    story.append(Paragraph(enrich_text, ParagraphStyle('et', parent=S['body_sm'], fontSize=8, leading=13)))
    story.append(Spacer(1, 10))
    story.append(Paragraph(
        '<font color="#22c55e"><b>60+ surnames</b></font> auto-mapped to communities: '
        'Brahmin, OBC, SC, ST, Muslim, Jain, Rajput, Reddy, Kamma, Nair + more — powers caste arithmetic instantly.',
        S['body']))
    story.append(PageBreak())

    # ─────────────────────────────────────────────────────────────
    # SLIDE 6: WINNING STRATEGY ENGINE
    # ─────────────────────────────────────────────────────────────
    story.append(Paragraph('WINNING STRATEGY ENGINE', S['section_label']))
    story.append(Paragraph('Booth-level strategy that <font color="#f97316">wins elections</font>', S['slide_title']))
    story.append(Spacer(1, 10))

    strat_data = [
        ('🎯 Winning Formula',
         'Per-booth math:\nTurnout × 50%+1 = Target\nPakka confirmed vs gap\nStatus: SAFE / WINNABLE / TOUGH',
         'Uses historical turnout when available (default 65%). Shows exactly how many swing voters you must convert per booth.'),
        ('📞 3-Contact Plan',
         'Every Swing voter gets 3 contacts.\nPrioritized by influence score\nand family head status.',
         'Auto-generated priority list with stage tracking (need 1st / 2nd / 3rd contact).'),
        ('🏘️ Family Influence',
         'Target family heads of 4+ members.\nConvert head → get family vote.',
         'Shows head classification, sentiment, contact status, and total family potential votes.'),
        ('🕐 Time Slot Plan',
         '7-9 AM: Pakka first\n9-12 PM: Seniors + Transport\n12-3 PM: Remaining\n3-5 PM: Final push',
         'Auto-assigns every voter to an optimal election-day time slot.'),
    ]
    
    strat_rows = []
    for i in range(0, 4, 2):
        row = []
        for j in range(2):
            t, sub, desc = strat_data[i+j]
            row.append(Table([
                [Paragraph(f'<b>{t}</b>', S['h3'])],
                [Paragraph(sub, ParagraphStyle('ss', parent=S['body_sm'], textColor=colors.HexColor('#a0a0b0')))],
                [Paragraph(desc, S['body_sm'])],
            ], colWidths=[half_w]))
        strat_rows.append(row)
    
    strat_table = Table(strat_rows, colWidths=[half_w + 10]*2)
    strat_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), CARD),
        ('GRID', (0, 0), (-1, -1), 0.5, BORDER),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ('LEFTPADDING', (0, 0), (-1, -1), 12),
    ]))
    story.append(strat_table)
    story.append(Spacer(1, 12))

    # Caste + Simulator row
    cs_data = [
        ('🎪 Caste Arithmetic', 
         'Per-community Pakka/Virodhi/Swing breakdown with auto-recommendation:\n'
         'CONSOLIDATE (high Pakka) · CONVERT (high Swing) · SPLIT (high Virodhi) · ENGAGE (unclassified)'),
        ('🎛️ Vote Share Simulator',
         'Adjust Pakka turnout %, Swing capture %, First-time capture % with sliders.\n'
         'Instant prediction: estimated vote share and WIN / NEEDS MORE EFFORT verdict.'),
    ]
    cs_cells = []
    for t, d in cs_data:
        cs_cells.append(Table([
            [Paragraph(f'<b>{t}</b>', S['h3'])],
            [Paragraph(d, S['body_sm'])],
        ], colWidths=[half_w]))
    
    cs_table = Table([cs_cells], colWidths=[half_w + 10]*2)
    cs_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), CARD),
        ('GRID', (0, 0), (-1, -1), 0.5, BORDER),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ('LEFTPADDING', (0, 0), (-1, -1), 12),
    ]))
    story.append(cs_table)
    story.append(PageBreak())

    # ─────────────────────────────────────────────────────────────
    # SLIDE 7: HIERARCHY
    # ─────────────────────────────────────────────────────────────
    story.append(Paragraph('DATA ORGANIZATION', S['section_label']))
    story.append(Paragraph('9-Level Hierarchy — <font color="#f97316">drill down or roll up</font>', S['slide_title']))
    story.append(Spacer(1, 8))
    
    hier_levels = [
        ('🌐', 'All Data', 'Aggregated view across everything', MUTED),
        ('🗺️', 'Region', 'e.g. South India', TEAL),
        ('🏛️', 'State', 'e.g. Karnataka', PURPLE),
        ('📊', 'Division', 'e.g. Gulbarga Division', BLUE),
        ('🏢', 'District', 'e.g. Kalaburagi', BLUE),
        ('🗺️', 'Taluka', 'e.g. Aland', GREEN),
        ('📍', 'Hobli', 'e.g. Aland Hobli', YELLOW),
        ('🏘️', 'Gram Panchayat', 'e.g. Khajuri GP', ORANGE),
        ('🏠', 'Village', 'e.g. Khajuri', PINK),
        ('📋', 'Ward (leaf)', 'Editable — all data entry here', GREEN),
    ]
    
    hier_rows = []
    for icon, name, desc, clr in hier_levels:
        hier_rows.append([
            Paragraph(f'<font size="11">{icon}</font>', S['center']),
            Paragraph(f'<b>{name}</b>', ParagraphStyle('hn', parent=S['body'], textColor=WHITE)),
            Paragraph(desc, S['body_sm']),
        ])
    
    hier_table = Table(hier_rows, colWidths=[30, 120, 200])
    hier_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), CARD),
        ('GRID', (0, 0), (-1, -1), 0.5, BORDER),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('BACKGROUND', (0, 9), (-1, 9), colors.HexColor('#1a2a1a')),
        ('ROWBACKGROUNDS', (0, 0), (-1, 8), [CARD, DARK_CARD_BG]),
    ]))
    
    # Right side — features
    feat_items = [
        _check('Select any level — dashboard shows aggregated analytics across all wards below', S),
        _check('Cascading dropdown navigation — switch levels without leaving the dashboard', S),
        _check('Multi-ward PDF reports from any hierarchy level', S),
        _check('Ward-level editing: classify, tag, contact, track — changes persist', S),
        _check('Merge voters, metadata, and election history from multiple wards', S),
        _check('Empty levels auto-skipped (no region? goes straight to state)', S),
    ]
    
    feat_table = Table([[item] for item in feat_items], colWidths=[content_w - 400])
    feat_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), CARD),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 12),
    ]))
    
    layout = Table([[hier_table, feat_table]], colWidths=[370, content_w - 390])
    layout.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP')]))
    story.append(layout)
    story.append(PageBreak())

    # ─────────────────────────────────────────────────────────────
    # SLIDE 8: FIELD OPS + ELECTION DAY
    # ─────────────────────────────────────────────────────────────
    story.append(Paragraph('FIELD OPERATIONS & ELECTION DAY', S['section_label']))
    story.append(Paragraph('From <font color="#f97316">strategy room</font> to <font color="#f97316">polling booth</font>', S['slide_title']))
    story.append(Spacer(1, 8))

    ops_data = [
        ('📋 Panna Pramukh Plan', '1 worker per 25 voters per booth.\nAuto-generates page assignments\nwith SR number ranges.'),
        ('📞 Contact Tracking', 'Log every voter contact — track\n1x, 2x, 3x rates per booth.\nSee gaps in coverage.'),
        ('😊 Sentiment Tracking', 'Positive / Neutral / Negative / Hostile\nper voter. Per-booth sentiment\nheatmap for leaders.'),
        ('📨 Slip Distribution', 'Track which voters received their\npolling slip. Per-booth delivery\nrates and pending list.'),
        ('🏷️ Scheme Beneficiary Tags', 'PM-KISAN, Ujjwala, Ration Card,\nMNREGA, Pension, DBT — bulk\ntag with one click.'),
        ('📊 Party Lean Analysis', 'Track party inclination per voter.\nAnalyze distribution across\nbooths and communities.'),
    ]
    
    ops_rows = []
    for i in range(0, 6, 3):
        row = []
        for j in range(3):
            t, d = ops_data[i+j]
            row.append(Table([
                [Paragraph(f'<b>{t}</b>', ParagraphStyle('ot', parent=S['h3'], fontSize=9))],
                [Paragraph(d, S['body_sm'])],
            ], colWidths=[third_w]))
        ops_rows.append(row)
    
    ops_table = Table(ops_rows, colWidths=[third_w + 8]*3)
    ops_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), CARD),
        ('GRID', (0, 0), (-1, -1), 0.5, BORDER),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
    ]))
    story.append(ops_table)
    story.append(Spacer(1, 12))

    # Election Day row
    story.append(Paragraph('<b>🗳️ Election Day War Room</b>', S['h2']))
    eday = [
        ['Slot', 'Target Voters', 'Strategy', 'Tools'],
        ['7-9 AM', 'Pakka (confirmed)', 'Get supporters out first', 'Priority list, phone tree'],
        ['9-12 PM', 'Seniors, Women', 'Transport assistance', 'Transport pending list'],
        ['12-3 PM', 'Remaining voters', 'Second round push', 'Door-to-door tracking'],
        ['3-5 PM', 'Swing / Doubtful', 'Final persuasion push', 'Live turnout dashboard'],
    ]
    eday_table = _card_table(eday, [70, 120, 160, content_w - 380], accent_col=0)
    story.append(eday_table)
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        '<b>Live features:</b> Mark voters as voted in real-time · Booth-wise turnout % · '
        'Pakka-not-voted priority alerts · Transport coordination · Turnout prediction per booth', S['body_sm']))
    story.append(PageBreak())

    # ─────────────────────────────────────────────────────────────
    # SLIDE 9: PDF REPORT
    # ─────────────────────────────────────────────────────────────
    story.append(Paragraph('PROFESSIONAL REPORTS', S['section_label']))
    story.append(Paragraph('16-Section PDF Report — <font color="#f97316">ready to print</font>', S['slide_title']))
    story.append(Spacer(1, 8))
    
    sections = [
        '01. Executive Summary', '02. Voter Demographics', '03. Age & Gender Analysis',
        '04. Caste Arithmetic', '05. Family & Household', '06. Booth Strength Assessment',
        '07. Winning Formula', '08. Historical Election Analysis',
        '09. Classification & Funnel', '10. Tags & Scheme Coverage',
        '11. 3-Contact Strategy Plan', '12. Family Influence Targets',
        '13. Election Day Time Slots', '14. Field Operations Plan',
        '15. Data Quality Audit', '16. Ground Action Plan',
    ]
    
    sec_rows = []
    for i in range(0, 16, 4):
        row = []
        for j in range(4):
            s = sections[i+j]
            num, name = s.split('. ', 1)
            row.append(Paragraph(
                f'<font color="#f97316"><b>{num}.</b></font> {name}',
                ParagraphStyle('sn', parent=S['body'], fontSize=9, textColor=WHITE)))
        sec_rows.append(row)
    
    sec_table = Table(sec_rows, colWidths=[quarter_w + 6]*4)
    sec_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), CARD),
        ('GRID', (0, 0), (-1, -1), 0.5, BORDER),
        ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ('LEFTPADDING', (0, 0), (-1, -1), 12),
        ('ROWBACKGROUNDS', (0, 0), (-1, -1), [CARD, DARK_CARD_BG]),
    ]))
    story.append(sec_table)
    story.append(Spacer(1, 14))

    rep_features = [
        ('📄 One-Click Generation', 'Hit "Download Report" — professional multi-page PDF with cover, TOC, KPI tables, charts, and booth-level strategy.'),
        ('🎨 Professional Design', 'Color-coded tables, branded cover page with hierarchy context, confidential header/footer, page numbers.'),
        ('📊 Export Options', 'PDF Report (16 sections) · CSV Export (all voter fields, UTF-8) · JSON Export (full data + metadata).'),
    ]
    rf_cells = []
    for t, d in rep_features:
        rf_cells.append(Table([
            [Paragraph(f'<b>{t}</b>', S['h3'])],
            [Paragraph(d, S['body_sm'])],
        ], colWidths=[third_w]))
    rf_table = Table([rf_cells], colWidths=[third_w + 8]*3)
    rf_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), CARD),
        ('GRID', (0, 0), (-1, -1), 0.5, BORDER),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
    ]))
    story.append(rf_table)
    story.append(PageBreak())

    # ─────────────────────────────────────────────────────────────
    # SLIDE 10: TECHNOLOGY
    # ─────────────────────────────────────────────────────────────
    story.append(Paragraph('TECHNOLOGY', S['section_label']))
    story.append(Paragraph('Built for <font color="#f97316">speed, privacy & portability</font>', S['slide_title']))
    story.append(Spacer(1, 12))

    tech = [
        ('💻', 'Runs Locally', 'No cloud dependency. All data stays on your machine.\nZero internet required after setup. Complete data sovereignty.'),
        ('⚡', 'Blazing Fast', 'OCR ~1s/page. PDF report <1s. Dashboard loads\n18 analytics endpoints in parallel. No spinners.'),
        ('🔒', 'Data Privacy', 'Voter data never leaves the local machine.\nNo cloud APIs, no external servers. ECI-compliant.'),
        ('📱', 'Mobile Responsive', 'Dark-themed dashboard works on tablets and phones.\nField workers classify voters from mobile browser.'),
        ('🐍', 'Python + Flask', 'Lightweight stack: PyMuPDF, Windows OCR,\nReportLab for PDF, Chart.js for visualizations.'),
        ('💾', 'JSON Storage', 'No database needed. Ward data as JSON files.\nEasy backup, share, transfer between machines.'),
    ]
    
    tech_rows = []
    for i in range(0, 6, 3):
        row = []
        for j in range(3):
            icon, t, d = tech[i+j]
            row.append(Table([
                [Paragraph(f'<font size="16">{icon}</font>', S['center'])],
                [Paragraph(f'<b>{t}</b>', S['center_bold'])],
                [Paragraph(d, ParagraphStyle('td', parent=S['body_sm'], alignment=TA_CENTER))],
            ], colWidths=[third_w]))
        tech_rows.append(row)
    
    tech_table = Table(tech_rows, colWidths=[third_w + 8]*3)
    tech_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), CARD),
        ('GRID', (0, 0), (-1, -1), 0.5, BORDER),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 14),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 14),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
    ]))
    story.append(tech_table)
    story.append(Spacer(1, 14))
    stack_text = '  ·  '.join(['Python 3.13', 'Flask', 'PyMuPDF', 'WinOCR', 'ReportLab', 'Chart.js 4.4', 'JSON Storage'])
    story.append(Paragraph(
        f'<font color="#f97316"><b>Tech Stack:</b></font> {stack_text}', S['center']))
    story.append(PageBreak())

    # ─────────────────────────────────────────────────────────────
    # SLIDE 11: COMPETITIVE COMPARISON
    # ─────────────────────────────────────────────────────────────
    story.append(Paragraph('COMPETITIVE ADVANTAGE', S['section_label']))
    story.append(Paragraph('Why Election Intelligence <font color="#f97316">wins</font>', S['slide_title']))
    story.append(Spacer(1, 10))

    G = '<font color="#22c55e"><b>✓</b></font>'
    X = '<font color="#ef4444"><b>✗</b></font>'
    H = '<font color="#eab308"><b>◐</b></font>'
    
    comp_header = ['Capability', 'Election Intelligence', 'Spreadsheets', 'Generic CRM']
    comp_rows = [
        ['PDF OCR Voter Extraction', f'{G} Auto (~1s/pg)', f'{X} Manual entry', f'{X}'],
        ['Auto Caste/Community Mapping', f'{G} 60+ surnames', f'{X}', f'{X}'],
        ['Family/Household Detection', f'{G} Auto-grouped', f'{X}', f'{X}'],
        ['Booth-Level Winning Formula', f'{G} Per-booth', f'{H} Manual calc', f'{X}'],
        ['Caste Arithmetic Strategy', f'{G} Auto-recommend', f'{H} Basic', f'{X}'],
        ['3-Contact Priority Planning', f'{G} Prioritized', f'{X}', f'{H} Generic'],
        ['Election Day Time Slots', f'{G} Auto-assigned', f'{X}', f'{X}'],
        ['9-Level Hierarchy Drill-down', f'{G}', f'{X}', f'{X}'],
        ['Offline / Local-Only', f'{G} 100% local', f'{G} Local', f'{X} Cloud'],
        ['16-Section PDF Report', f'{G} One-click', f'{X}', f'{X}'],
    ]
    
    all_comp = [comp_header] + comp_rows
    ps_cell = ParagraphStyle('cc', parent=S['body'], fontSize=8.5, leading=11)
    ps_hdr = ParagraphStyle('ch', parent=S['body_sm'], textColor=MUTED, fontName='Helvetica-Bold')
    
    formatted = []
    for i, row in enumerate(all_comp):
        formatted.append([Paragraph(cell, ps_hdr if i == 0 else ps_cell) for cell in row])
    
    comp_table = Table(formatted, colWidths=[180, 180, 140, 140])
    comp_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), SURFACE),
        ('BACKGROUND', (0, 1), (-1, -1), CARD),
        ('TEXTCOLOR', (0, 0), (-1, -1), TEXT),
        ('GRID', (0, 0), (-1, -1), 0.5, BORDER),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [CARD, DARK_CARD_BG]),
        # highlight our column
        ('BACKGROUND', (1, 1), (1, -1), colors.HexColor('#0f1f0f')),
    ]))
    story.append(comp_table)
    story.append(PageBreak())

    # ─────────────────────────────────────────────────────────────
    # SLIDE 12: PRICING
    # ─────────────────────────────────────────────────────────────
    story.append(Paragraph('PRICING', S['section_label']))
    story.append(Paragraph('Flexible plans for every <font color="#f97316">campaign size</font>', S['slide_title']))
    story.append(Spacer(1, 16))

    plans = [
        ('WARD', '₹5K', 'per ward / election cycle', [
            '1 ward (up to 2,000 voters)',
            'Full analytics dashboard',
            'PDF report generation',
            'Voter classification & tagging',
            'Field ops tracking',
        ]),
        ('CONSTITUENCY', '₹50K', 'per constituency / election cycle', [
            'Unlimited wards',
            '9-level hierarchy navigation',
            'Multi-ward aggregation',
            'Historical election analysis',
            'Vote share simulator',
            'Priority support',
        ]),
        ('PARTY', 'Custom', 'multi-constituency licensing', [
            'All Constituency features',
            'Unlimited constituencies',
            'Custom branding',
            'Training & deployment',
            'Dedicated support team',
            'Custom analytics modules',
        ]),
    ]
    
    plan_cells = []
    for name, price, period, features in plans:
        feat_text = '<br/>'.join([f'<font color="#22c55e">✓</font> {f}' for f in features])
        is_featured = name == 'CONSTITUENCY'
        bg = colors.HexColor('#141820') if not is_featured else colors.HexColor('#1a1408')
        
        cell = Table([
            [Paragraph(f'<font color="#8b8fa3" size="8"><b>{name}</b></font>', S['center'])],
            [Paragraph(f'<font size="28"><b>{price}</b></font>', 
                ParagraphStyle('pr', parent=S['kpi_num'], textColor=ORANGE if is_featured else WHITE))],
            [Paragraph(period, ParagraphStyle('pp', parent=S['body_sm'], alignment=TA_CENTER))],
            [Spacer(1, 6)],
            [Paragraph(feat_text, ParagraphStyle('pf', parent=S['body'], fontSize=9, leading=14))],
        ], colWidths=[third_w - 20])
        
        plan_cells.append(cell)
    
    plan_table = Table([plan_cells], colWidths=[third_w + 8]*3)
    plan_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), CARD),
        ('BACKGROUND', (1, 0), (1, 0), colors.HexColor('#1a1408')),
        ('GRID', (0, 0), (-1, -1), 0.5, BORDER),
        ('BOX', (1, 0), (1, 0), 1.5, ORANGE),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 16),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 16),
        ('LEFTPADDING', (0, 0), (-1, -1), 16),
        ('RIGHTPADDING', (0, 0), (-1, -1), 16),
    ]))
    story.append(plan_table)
    story.append(Spacer(1, 12))
    story.append(Paragraph(
        '<font color="#f97316"><b>★ MOST POPULAR:</b></font> Constituency plan — covers the entire assembly segment with unlimited wards.',
        S['center']))
    story.append(PageBreak())

    # ─────────────────────────────────────────────────────────────
    # SLIDE 13: CLOSING
    # ─────────────────────────────────────────────────────────────
    story.append(Spacer(1, 50))
    story.append(Paragraph(
        '<font color="#f97316" size="9"><b>⚡ ELECTION INTELLIGENCE</b></font>', S['center']))
    story.append(Spacer(1, 16))
    
    close_s = ParagraphStyle('Close', fontName='Helvetica-Bold', fontSize=36,
        textColor=WHITE, leading=44, alignment=TA_CENTER)
    story.append(Paragraph('Stop guessing.', close_s))
    story.append(Paragraph('<font color="#f97316">Start winning.</font>', close_s))
    story.append(Spacer(1, 16))
    story.append(Paragraph(
        'Every vote counts. Every contact matters. Every booth has a formula.<br/>'
        'Let data drive your next victory.',
        ParagraphStyle('cm', parent=S['subtitle'], alignment=TA_CENTER, fontSize=14)))
    story.append(Spacer(1, 30))
    
    story.append(_kpi_row([
        ('< 1 min', 'PDF to Dashboard', GREEN),
        ('30+', 'Analytics Metrics', ORANGE),
        ('100%', 'Offline & Secure', BLUE),
        ('16', 'Report Sections', PURPLE),
    ]))
    story.append(Spacer(1, 30))
    story.append(Paragraph(
        'Contact: <b>sales@electionintel.in</b> &nbsp; | &nbsp; '
        'Demo: <b>http://127.0.0.1:5001</b>',
        ParagraphStyle('ct', parent=S['center'], textColor=MUTED, fontSize=11)))

    # Build PDF
    doc.build(story)
    buf.seek(0)
    return buf


# ═════════════════════════════════════════════════════════════════
if __name__ == '__main__':
    import time
    start = time.time()
    buf = generate_pitch_deck()
    elapsed = time.time() - start
    
    out_path = os.path.join(os.path.dirname(__file__), 'Election_Intelligence_Pitch_Deck.pdf')
    with open(out_path, 'wb') as f:
        f.write(buf.getvalue())
    
    size_kb = os.path.getsize(out_path) / 1024
    print(f'Generated: {out_path}')
    print(f'Size: {size_kb:.0f} KB | Time: {elapsed:.1f}s')
