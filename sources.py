"""Sources locales TXT / MD / PDF : extraction et référencement par passages."""
from io import BytesIO
from pathlib import Path
import re
from pypdf import PdfReader

MAX_BYTES = 5 * 1024 * 1024
MAX_CHARS = 120_000
MAX_CHUNKS = 150


def extraire(fichier):
    nom = Path(fichier.filename or "").name
    ext = Path(nom).suffix.lower()
    if ext not in ('.txt', '.md', '.pdf'):
        raise ValueError('Formats acceptés : TXT, MD et PDF.')
    data = fichier.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError('Document trop volumineux (5 Mo maximum).')
    parties = []
    if ext == '.pdf':
        try:
            lecteur = PdfReader(BytesIO(data))
            if lecteur.is_encrypted:
                raise ValueError('PDF chiffré non accepté.')
            for page_num, page in enumerate(lecteur.pages, 1):
                texte = page.extract_text() or ''
                if texte.strip():
                    parties.append((f'Page {page_num}', texte))
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError('PDF illisible ou endommagé.') from exc
    else:
        try:
            texte = data.decode('utf-8-sig')
        except UnicodeDecodeError:
            raise ValueError('Texte attendu en UTF-8.')
        parties.append(('Texte', texte))
    total = sum(len(texte) for _, texte in parties)
    if total > MAX_CHARS:
        raise ValueError('Document trop long (120 000 caractères maximum).')
    chunks = []
    for lieu, texte in parties:
        # Localiser précisément chaque extrait par page et lignes approximatives.
        lignes = texte.splitlines()
        for debut in range(0, len(lignes), 12):
            fragment = '\n'.join(lignes[debut:debut + 12]).strip()
            if fragment:
                label = f'{lieu}, lignes {debut+1}-{min(debut+12,len(lignes))}'
                chunks.append((label, fragment[:3000]))
                if len(chunks) > MAX_CHUNKS:
                    raise ValueError('Trop de passages dans ce document (150 maximum).')
    if not chunks:
        raise ValueError('Aucun texte extractible. Les PDF scannés ne sont pas pris en charge.')
    return nom, chunks


def choisir_extraits(question, extraits, limite=4):
    """Recherche lexicale simple : pas d'embeddings, ni garantie de pertinence."""
    mots = set(re.findall(r'\w{3,}', question.lower(), flags=re.UNICODE))
    scores = []
    for e in extraits:
        contenu = e['contenu'].lower()
        score = sum(contenu.count(mot) for mot in mots)
        scores.append((score, e))
    scores.sort(key=lambda x: x[0], reverse=True)
    return [e for score,e in scores if score > 0][:limite]
