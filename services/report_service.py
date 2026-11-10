"""Readable reports from persisted evidence, with no external assets."""
from io import BytesIO
import json
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether


def pdf_report(run):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=(595.28, 841.89), rightMargin=42, leftMargin=42, topMargin=45, bottomMargin=45, title='TestPilot AI - API Test Report')
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='Meta', fontSize=9, leading=14, textColor=colors.HexColor('#475569'), spaceAfter=8))
    styles.add(ParagraphStyle(name='CodeWrap', fontName='Courier', fontSize=7, leading=10, wordWrap='CJK', spaceAfter=8))
    styles['Title'].textColor = colors.HexColor('#312e81')
    styles['BodyText'].spaceAfter = 6
    def para(text, style='BodyText'):
        return Paragraph(escape(str(text)).replace('\n', '<br/>'), styles[style])
    story = [para('TESTPILOT AI', 'Title'), para(run['suite']['api_name'], 'Heading1'), para(f"Run #{run['id']} | {run['created_at']} (UTC)\nTarget: {run['target']}", 'Meta')]
    summary = run['data']['summary']
    table = Table([[para(k.upper(), 'Meta') for k in ('total', 'passed', 'failed', 'skipped', 'error')], [str(summary[k]) for k in ('total', 'passed', 'failed', 'skipped', 'error')]], colWidths=[102] * 5)
    table.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#eef2ff')), ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')), ('TOPPADDING', (0, 0), (-1, -1), 10), ('BOTTOMPADDING', (0, 0), (-1, -1), 10)]))
    story += [table, Spacer(1, 12), para(f"Duration: {summary['duration_ms']} ms. Skipped tests did not execute. Execution errors are not assertion failures.", 'Meta')]
    for result in run['data']['results']:
        story.append(KeepTogether([para(f"{result['id']} - {result['status'].upper()}", 'Heading2'), para(result['scenario'])]))
        story.append(para(f"{result['method']} {result['endpoint']}", 'Meta'))
        story.append(para('Expected: ' + json.dumps(result['expected'], ensure_ascii=True), 'CodeWrap'))
        if result.get('actual'):
            story.append(para('Actual: ' + json.dumps(result['actual'], ensure_ascii=True), 'CodeWrap'))
        if result.get('reason'):
            story.append(para(result['reason']))
        for failure in result.get('failures', []):
            story.append(para(failure))
        for attempt in result.get('attempts', []):
            story.append(para(f"Attempt: status {attempt['status_code']}, {attempt['elapsed_ms']} ms", 'Meta'))
    analysis = run.get('analysis')
    if analysis:
        story.append(para('AI analysis - unconfirmed hypotheses' if analysis['source'] == 'adaption' else 'Evidence summary', 'Heading1'))
        story.append(para(analysis['summary']))
        for hypothesis in analysis['hypotheses']:
            story.append(para(hypothesis['test_id'] + ': ' + hypothesis['hypothesis'], 'Heading3'))
            for step in hypothesis['debugging_steps']:
                story.append(para('- ' + step))
    def footer(canvas, document):
        canvas.saveState()
        canvas.setFont('Helvetica', 8)
        canvas.setFillColor(colors.HexColor('#64748b'))
        canvas.drawString(42, 25, 'TestPilot AI | Recorded execution evidence | Sensitive values redacted')
        canvas.drawRightString(553, 25, str(document.page))
        canvas.restoreState()
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
