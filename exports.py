import json
from io import BytesIO
from pathlib import Path
from fpdf import FPDF
from database import get_connection

def recuperer_conversation(conversation_id):
    with get_connection() as conn:
        row = conn.execute('SELECT * FROM conversations WHERE id=?', (conversation_id,)).fetchone()
        if row is None:
            return None
        messages = conn.execute('SELECT id,role,contenu,created_at FROM messages WHERE conversation_id=? ORDER BY id', (conversation_id,)).fetchall()
        return {**dict(row), 'messages': [dict(m) for m in messages]}

def exporter_txt(conversation):
    lignes = [f"Conversation #{conversation['id']}", f"Domaine : {conversation['domaine']}", '']
    for m in conversation['messages']:
        lignes += [('Utilisateur' if m['role']=='user' else 'Assistant') + ' :', m['contenu'], '']
    return '\n'.join(lignes).encode('utf-8-sig')

def exporter_json(conversation):
    return json.dumps(conversation, ensure_ascii=False, indent=2).encode('utf-8')

def creer_pdf(titre, domaine, sections):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(18,18,18)
    font_dir = Path('C:/Windows/Fonts')
    fonts = [(font_dir/'segoeui.ttf', font_dir/'segoeuib.ttf'),
             (font_dir/'arial.ttf', font_dir/'arialbd.ttf')]
    normal, bold = next(((a,b) for a,b in fonts if a.exists() and b.exists()), (None,None))
    if normal is None:
        raise FileNotFoundError('Polices Windows Segoe UI/Arial absentes.')
    pdf.add_font('App', '', str(normal))
    pdf.add_font('App', 'B', str(bold))
    pdf.add_page()
    pdf.set_font('App', 'B', 16)
    pdf.multi_cell(0, 10, titre)
    pdf.set_font('App', '', 10)
    pdf.multi_cell(0, 7, 'Domaine : ' + domaine)
    pdf.ln(5)
    for nom, contenu in sections:
        pdf.set_font('App', 'B', 11)
        pdf.multi_cell(0, 8, nom)
        pdf.set_font('App', '', 10)
        pdf.multi_cell(0, 6, contenu or '(vide)')
        pdf.ln(4)
    return BytesIO(bytes(pdf.output()))

def exporter_pdf(conversation):
    sections = [('Utilisateur' if m['role']=='user' else 'Assistant', m['contenu']) for m in conversation['messages']]
    return creer_pdf(f"Conversation #{conversation['id']}", conversation['domaine'], sections)
