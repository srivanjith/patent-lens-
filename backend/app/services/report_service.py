import os
import uuid
import tempfile
from datetime import datetime, timezone
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from app.models.models import Search, SearchResult, Patent

def get_reports_dir() -> str:
    """Safely obtain writable reports directory, falling back to tempdir if filesystem is read-only (e.g. Vercel)."""
    primary_dir = os.path.join(os.path.dirname(__file__), "..", "..", "generated_reports")
    try:
        os.makedirs(primary_dir, exist_ok=True)
        test_file = os.path.join(primary_dir, f".write_test_{uuid.uuid4().hex[:6]}")
        with open(test_file, "w") as f:
            f.write("ok")
        os.remove(test_file)
        return primary_dir
    except (OSError, PermissionError):
        tmp_dir = os.path.join(tempfile.gettempdir(), "generated_reports")
        os.makedirs(tmp_dir, exist_ok=True)
        return tmp_dir

def generate_pdf_report(search: Search, results: list) -> str:
    """
    Generate a clean PDF prior-art search report using ReportLab.
    Returns absolute path of generated PDF file.
    """
    reports_dir = get_reports_dir()
    filename = f"patentlens_report_{search.id[:8]}_{int(datetime.now(timezone.utc).timestamp())}.pdf"
    filepath = os.path.join(reports_dir, filename)

    doc = SimpleDocTemplate(
        filepath,
        pagesize=letter,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36
    )

    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontSize=22,
        leading=26,
        textColor=colors.HexColor('#0F172A'),
        fontName='Helvetica-Bold'
    )
    subtitle_style = ParagraphStyle(
        'DocSubtitle',
        parent=styles['Normal'],
        fontSize=11,
        leading=15,
        textColor=colors.HexColor('#475569')
    )
    section_style = ParagraphStyle(
        'SectionHeader',
        parent=styles['Heading2'],
        fontSize=14,
        leading=18,
        textColor=colors.HexColor('#1E293B'),
        fontName='Helvetica-Bold',
        spaceBefore=12,
        spaceAfter=6
    )
    body_style = ParagraphStyle(
        'BodyDark',
        parent=styles['Normal'],
        fontSize=10,
        leading=14,
        textColor=colors.HexColor('#334155')
    )
    disclaimer_style = ParagraphStyle(
        'DisclaimerText',
        parent=styles['Normal'],
        fontSize=8,
        leading=11,
        textColor=colors.HexColor('#64748B'),
        fontName='Helvetica-Oblique'
    )

    elements = []

    # 1. Header & Branding
    elements.append(Paragraph("PATENTLENS AI", title_style))
    elements.append(Paragraph("AI-Powered Semantic Prior-Art Search Report", subtitle_style))
    elements.append(Spacer(1, 10))
    elements.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor('#2563EB'), spaceAfter=15))

    # 2. Metadata Table
    inv_title_str = str(getattr(search, "invention_title", "") or "")
    domain_str = str(getattr(search, "domain", "") or "")
    created_at_val = getattr(search, "created_at", None)
    date_str = created_at_val.strftime("%Y-%m-%d %H:%M UTC") if (created_at_val is not None and hasattr(created_at_val, "strftime")) else str(created_at_val or "")
    risk_lvl_str = str(getattr(search, "risk_level", "") or "")
    highest_sim_val = getattr(search, "highest_similarity", 0.0)

    meta_data = [
        [Paragraph("<b>Invention Title:</b>", body_style), Paragraph(inv_title_str, body_style)],
        [Paragraph("<b>Technology Domain:</b>", body_style), Paragraph(domain_str, body_style)],
        [Paragraph("<b>Search Date:</b>", body_style), Paragraph(date_str, body_style)],
        [Paragraph("<b>Prior-Art Risk Level:</b>", body_style), Paragraph(f"<font color='#DC2626'><b>{risk_lvl_str}</b></font>", body_style)],
        [Paragraph("<b>Highest Similarity Score:</b>", body_style), Paragraph(f"<b>{highest_sim_val}%</b>", body_style)],
    ]
    t_meta = Table(meta_data, colWidths=[140, 390])
    t_meta.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#F8FAFC')),
        ('PADDING', (0,0), (-1,-1), 6),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#E2E8F0')),
    ]))
    elements.append(t_meta)
    elements.append(Spacer(1, 15))

    # 3. Invention Summary
    problem_stmt_str = str(getattr(search, "problem_statement", "") or "")
    desc_str = str(getattr(search, "description", "") or "")
    keywords_val = getattr(search, "keywords", None)

    elements.append(Paragraph("Invention Summary & Problem Solved", section_style))
    elements.append(Paragraph(f"<b>Problem Statement:</b> {problem_stmt_str}", body_style))
    elements.append(Spacer(1, 4))
    elements.append(Paragraph(f"<b>Detailed Description:</b> {desc_str}", body_style))
    if keywords_val and isinstance(keywords_val, (list, tuple)):
        elements.append(Spacer(1, 4))
        kw_str = ", ".join([str(k) for k in keywords_val])
        elements.append(Paragraph(f"<b>User Keywords:</b> {kw_str}", body_style))
    elements.append(Spacer(1, 15))

    # 4. Search Methodology
    elements.append(Paragraph("AI Search Methodology & Scoring Formula", section_style))
    methodology_text = (
        "This prior-art assessment utilizes SBERT vector embedding retrieval, Lens Patent API multi-path search, "
        "and an authoritative 5-factor scoring architecture: (25% SBERT Semantic Similarity) + (35% Technical Feature Overlap) + "
        "(20% Evidence Verification Strength) + (10% Distinctive Concepts) + (10% Domain & CPC Classification Alignment). "
        "Scores are subject to transparent data availability caps and evidence verification gating."
    )
    elements.append(Paragraph(methodology_text, body_style))
    elements.append(Spacer(1, 15))

    # 5. Top Patent Results Table
    elements.append(Paragraph("Top 5 Similar Patent Results", section_style))
    
    table_data = [
        [
            Paragraph("<b>Rank</b>", body_style),
            Paragraph("<b>Patent Number & Title</b>", body_style),
            Paragraph("<b>Domain</b>", body_style),
            Paragraph("<b>Semantic</b>", body_style),
            Paragraph("<b>Canonical Score</b>", body_style)
        ]
    ]

    def _get_val(obj, key, default=""):
        if obj is None:
            return default
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default) if getattr(obj, key, default) is not None else default

    for item in results[:5]:
        pat = _get_val(item, "patent", None)
        pat_num = _get_val(pat, "patent_number", "Unknown")
        pat_title = _get_val(pat, "title", "Untitled Patent")
        pat_domain = _get_val(pat, "domain", "General")
        rank_val = _get_val(item, "rank", 1)
        sem_val = _get_val(item, "semantic_score", 0.0)
        final_val = _get_val(item, "final_score", 0.0)

        p_info = f"<b>{pat_num}</b><br/>{pat_title}"
        table_data.append([
            Paragraph(f"#{rank_val}", body_style),
            Paragraph(p_info, body_style),
            Paragraph(str(pat_domain), body_style),
            Paragraph(f"{sem_val}%", body_style),
            Paragraph(f"<b>{final_val}%</b>", body_style)
        ])

    t_results = Table(table_data, colWidths=[40, 260, 90, 70, 70])
    t_results.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#E2E8F0')),
        ('PADDING', (0,0), (-1,-1), 5),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#CBD5E1')),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
    ]))
    elements.append(t_results)
    elements.append(Spacer(1, 20))

    # 6. Legal Disclaimer
    elements.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#CBD5E1'), spaceAfter=10))
    disclaimer_notice = (
        "<b>IMPORTANT LEGAL DISCLAIMER:</b> PatentLens AI provides AI-assisted preliminary prior-art search results "
        "for informational and research purposes only. The results do not constitute legal advice, a patentability "
        "determination, or a professional patent opinion. All search findings are based on vector dataset analysis."
    )
    elements.append(Paragraph(disclaimer_notice, disclaimer_style))

    doc.build(elements)
    return filepath
