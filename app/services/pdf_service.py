"""
pdf_service.py — PDF generation for school performance reports.

Uses reportlab Platypus for high-level document layout.
Accepts the data dict from report_service.get_report_data()
and returns a BytesIO buffer ready to send as a file download.
"""
import io
from datetime import timezone
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT


# ── Colour palette (matches SESA green brand) ─────────────────────────────────
BRAND_GREEN     = colors.HexColor('#1a3a2a')
BRAND_GREEN_MID = colors.HexColor('#2a6642')
BRAND_GREEN_LIGHT = colors.HexColor('#e8f5ee')
ACCENT_RED      = colors.HexColor('#b91c1c')
ACCENT_ORANGE   = colors.HexColor('#d97706')
ACCENT_YELLOW   = colors.HexColor('#b8860b')
ACCENT_GREY     = colors.HexColor('#6b7280')
WHITE           = colors.white
LIGHT_GREY      = colors.HexColor('#f3f4f6')
MID_GREY        = colors.HexColor('#d1d5db')

STAGE_COLOURS = {
    'Normal Stage':   BRAND_GREEN_MID,
    'Mild Stage':     ACCENT_YELLOW,
    'Elevated Stage': ACCENT_ORANGE,
    'Clinical Stage': ACCENT_RED,
}


def _styles():
    base = getSampleStyleSheet()
    return {
        'title': ParagraphStyle(
            'ReportTitle',
            parent=base['Title'],
            fontSize=22,
            textColor=BRAND_GREEN,
            spaceAfter=4,
            alignment=TA_CENTER,
        ),
        'subtitle': ParagraphStyle(
            'ReportSubtitle',
            parent=base['Normal'],
            fontSize=11,
            textColor=ACCENT_GREY,
            spaceAfter=2,
            alignment=TA_CENTER,
        ),
        'section': ParagraphStyle(
            'SectionHeading',
            parent=base['Heading2'],
            fontSize=13,
            textColor=BRAND_GREEN,
            spaceBefore=14,
            spaceAfter=6,
            borderPad=0,
        ),
        'body': ParagraphStyle(
            'Body',
            parent=base['Normal'],
            fontSize=9,
            textColor=colors.HexColor('#111827'),
            spaceAfter=4,
        ),
        'small': ParagraphStyle(
            'Small',
            parent=base['Normal'],
            fontSize=8,
            textColor=ACCENT_GREY,
            spaceAfter=2,
        ),
        'table_header': ParagraphStyle(
            'TableHeader',
            parent=base['Normal'],
            fontSize=8,
            textColor=WHITE,
            alignment=TA_LEFT,
        ),
        'table_cell': ParagraphStyle(
            'TableCell',
            parent=base['Normal'],
            fontSize=8,
            textColor=colors.HexColor('#111827'),
        ),
        'footer': ParagraphStyle(
            'Footer',
            parent=base['Normal'],
            fontSize=7,
            textColor=ACCENT_GREY,
            alignment=TA_CENTER,
        ),
    }


def _stat_table(stats: list, styles: dict):
    """
    Render a row of stat cards.
    stats: list of (label, value) tuples — max 4.
    """
    data = [[
        Paragraph(f'<b>{value}</b>', ParagraphStyle(
            'StatVal', fontSize=18, textColor=BRAND_GREEN, alignment=TA_CENTER,
            spaceAfter=2,
        ))
        for _, value in stats
    ], [
        Paragraph(label, ParagraphStyle(
            'StatLabel', fontSize=8, textColor=ACCENT_GREY, alignment=TA_CENTER,
        ))
        for label, _ in stats
    ]]

    col_width = 130 * mm / len(stats)
    t = Table(data, colWidths=[col_width] * len(stats))
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), BRAND_GREEN_LIGHT),
        ('ROWBACKGROUNDS', (0, 0), (-1, -1), [BRAND_GREEN_LIGHT]),
        ('BOX', (0, 0), (-1, -1), 0.5, MID_GREY),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, MID_GREY),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('ROUNDEDCORNERS', [4]),
    ]))
    return t


def _stage_table(stage_breakdown: list, styles: dict):
    """Render the stage breakdown table."""
    if not stage_breakdown:
        return Paragraph('No assessments recorded in this period.', styles['small'])

    header = ['Stage', 'Count', 'Percentage']
    rows = [header] + [
        [row['stage'], str(row['count']), f"{row['pct']}%"]
        for row in stage_breakdown
    ]

    col_widths = [80 * mm, 30 * mm, 30 * mm]
    t = Table(rows, colWidths=col_widths)

    style = [
        ('BACKGROUND', (0, 0), (-1, 0), BRAND_GREEN),
        ('TEXTCOLOR', (0, 0), (-1, 0), WHITE),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [WHITE, LIGHT_GREY]),
        ('GRID', (0, 0), (-1, -1), 0.5, MID_GREY),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
    ]

    # Colour-code stage rows
    for i, row in enumerate(stage_breakdown, start=1):
        stage_colour = STAGE_COLOURS.get(row['stage'])
        if stage_colour:
            style.append(('TEXTCOLOR', (0, i), (0, i), stage_colour))
            style.append(('FONTNAME', (0, i), (0, i), 'Helvetica-Bold'))

    t.setStyle(TableStyle(style))
    return t


def _at_risk_table(at_risk: list, styles: dict):
    """Render the at-risk students table."""
    if not at_risk:
        return Paragraph('No students at Elevated or Clinical stage in this period.', styles['small'])

    header = ['Student Name', 'Class', 'Assessment', 'Stage', 'Date']
    rows = [header] + [
        [
            s['name'],
            s['class_group'],
            s['test_type'],
            s['stage'],
            s['taken_at'].strftime('%d %b %Y') if s['taken_at'] else '—',
        ]
        for s in at_risk
    ]

    col_widths = [38 * mm, 18 * mm, 48 * mm, 26 * mm, 20 * mm]
    t = Table(rows, colWidths=col_widths, repeatRows=1)

    style = [
        ('BACKGROUND', (0, 0), (-1, 0), BRAND_GREEN),
        ('TEXTCOLOR', (0, 0), (-1, 0), WHITE),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 8),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [WHITE, LIGHT_GREY]),
        ('GRID', (0, 0), (-1, -1), 0.5, MID_GREY),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]

    # Highlight Clinical rows in light red
    for i, s in enumerate(at_risk, start=1):
        if s['stage'] == 'Clinical Stage':
            style.append(('BACKGROUND', (0, i), (-1, i), colors.HexColor('#fef2f2')))
            style.append(('TEXTCOLOR', (3, i), (3, i), ACCENT_RED))
            style.append(('FONTNAME', (3, i), (3, i), 'Helvetica-Bold'))
        elif s['stage'] == 'Elevated Stage':
            style.append(('TEXTCOLOR', (3, i), (3, i), ACCENT_ORANGE))

    t.setStyle(TableStyle(style))
    return t


def _by_test_table(by_test_type: list, styles: dict):
    """Render per-test-type breakdown table."""
    if not by_test_type:
        return Paragraph('No data available.', styles['small'])

    header = ['Assessment', 'Total', 'Normal', 'Mild', 'Elevated', 'Clinical']
    rows = [header]
    for item in by_test_type:
        sc = item['stage_counts']
        rows.append([
            item['test_type'],
            str(item['total']),
            str(sc.get('Normal Stage', 0)),
            str(sc.get('Mild Stage', 0)),
            str(sc.get('Elevated Stage', 0)),
            str(sc.get('Clinical Stage', 0)),
        ])

    col_widths = [60 * mm, 15 * mm, 17 * mm, 13 * mm, 17 * mm, 17 * mm]
    t = Table(rows, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), BRAND_GREEN),
        ('TEXTCOLOR', (0, 0), (-1, 0), WHITE),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [WHITE, LIGHT_GREY]),
        ('GRID', (0, 0), (-1, -1), 0.5, MID_GREY),
        ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    return t


def _class_table(class_breakdown: list, styles: dict):
    """Render class group breakdown table."""
    if not class_breakdown:
        return Paragraph('No class group data available.', styles['small'])

    header = ['Class Group', 'Students', 'At-Risk Count', 'At-Risk Rate']
    rows = [header]
    for item in class_breakdown:
        rate = round((item['at_risk_count'] / item['total']) * 100, 1) if item['total'] else 0
        rows.append([
            item['class_group'],
            str(item['total']),
            str(item['at_risk_count']),
            f"{rate}%",
        ])

    col_widths = [50 * mm, 30 * mm, 30 * mm, 30 * mm]
    t = Table(rows, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), BRAND_GREEN),
        ('TEXTCOLOR', (0, 0), (-1, 0), WHITE),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [WHITE, LIGHT_GREY]),
        ('GRID', (0, 0), (-1, -1), 0.5, MID_GREY),
        ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    return t


def generate_report_pdf(school_name: str, data: dict) -> io.BytesIO:
    """
    Build and return a PDF report as a BytesIO buffer.

    school_name: display name for the report header
    data: dict from report_service.get_report_data()
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        title=f"SESA Report — {school_name}",
        author='SESA Platform',
    )

    styles = _styles()
    story = []

    # ── Header ────────────────────────────────────────────────────────────────
    story.append(Paragraph('SESA', styles['title']))
    story.append(Paragraph('Student Emotional and Social Assessment', styles['subtitle']))
    story.append(Paragraph(f'Performance Report — {school_name}', styles['subtitle']))
    story.append(Spacer(1, 2 * mm))
    story.append(HRFlowable(width='100%', thickness=1.5, color=BRAND_GREEN))
    story.append(Spacer(1, 3 * mm))

    period_label = data['period_label']
    generated = data['generated_at']
    if generated.tzinfo is not None:
        generated = generated.replace(tzinfo=None)
    story.append(Paragraph(
        f'Period: <b>{period_label}</b> &nbsp;&nbsp;|&nbsp;&nbsp; '
        f'Generated: <b>{generated.strftime("%d %b %Y, %I:%M %p")}</b>',
        styles['small'],
    ))
    story.append(Spacer(1, 4 * mm))

    # ── Summary stat cards ────────────────────────────────────────────────────
    story.append(Paragraph('Summary', styles['section']))
    stats = [
        ('Total Students', str(data['total_students'])),
        ('Participated', str(data['participating'])),
        ('Assessments Taken', str(data['total_assessments'])),
        ('Participation Rate', f"{data['participation_rate']}%"),
    ]
    story.append(_stat_table(stats, styles))
    story.append(Spacer(1, 4 * mm))

    # ── Stage breakdown ───────────────────────────────────────────────────────
    story.append(Paragraph('Overall Stage Distribution', styles['section']))
    story.append(Paragraph(
        'Distribution of results across all assessments taken during this period.',
        styles['small'],
    ))
    story.append(Spacer(1, 2 * mm))
    story.append(_stage_table(data['stage_breakdown'], styles))
    story.append(Spacer(1, 4 * mm))

    # ── Per test type ─────────────────────────────────────────────────────────
    story.append(Paragraph('Results by Assessment Type', styles['section']))
    story.append(_by_test_table(data['by_test_type'], styles))
    story.append(Spacer(1, 4 * mm))

    # ── Class group breakdown ─────────────────────────────────────────────────
    if data['class_breakdown']:
        story.append(Paragraph('Results by Class Group', styles['section']))
        story.append(_class_table(data['class_breakdown'], styles))
        story.append(Spacer(1, 4 * mm))

    # ── Monthly trend ─────────────────────────────────────────────────────────
    if data['monthly_trend']:
        story.append(Paragraph('6-Month Trend', styles['section']))
        trend_header = ['Month', 'Assessments Taken', 'Average Score (%)']
        trend_rows = [trend_header] + [
            [row['label'], str(row['count']), f"{row['avg_pct']}%"]
            for row in data['monthly_trend']
        ]
        col_widths = [50 * mm, 50 * mm, 50 * mm]
        trend_t = Table(trend_rows, colWidths=col_widths)
        trend_t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), BRAND_GREEN),
            ('TEXTCOLOR', (0, 0), (-1, 0), WHITE),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [WHITE, LIGHT_GREY]),
            ('GRID', (0, 0), (-1, -1), 0.5, MID_GREY),
            ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ]))
        story.append(trend_t)
        story.append(Spacer(1, 4 * mm))

    # ── At-risk students ──────────────────────────────────────────────────────
    story.append(Paragraph('Students Requiring Attention', styles['section']))
    story.append(Paragraph(
        'Students whose most recent result in this period was Elevated or Clinical stage. '
        'Clinical stage rows are highlighted. Please follow up with your school counsellor.',
        styles['small'],
    ))
    story.append(Spacer(1, 2 * mm))
    story.append(_at_risk_table(data['at_risk'], styles))
    story.append(Spacer(1, 6 * mm))

    # ── Footer ────────────────────────────────────────────────────────────────
    story.append(HRFlowable(width='100%', thickness=0.5, color=MID_GREY))
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph(
        'This report was generated by the SESA platform. '
        'Results are for screening purposes only and do not constitute a clinical diagnosis. '
        'Students at Elevated or Clinical stage should be referred to a qualified mental health professional.',
        styles['footer'],
    ))

    doc.build(story)
    buf.seek(0)
    return buf