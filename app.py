import time
from io import BytesIO
import pandas as pd
import requests
from flask import Flask, render_template, request, jsonify, send_file
from database import init_db, get_connection
from exports import recuperer_conversation, exporter_txt, exporter_json, exporter_pdf, creer_pdf
from data_analysis import analyser_donnees
from sqlite_analysis import analyser_base_sqlite
from sources import extraire, choisir_extraits

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024
init_db()
OLLAMA_URL = 'http://127.0.0.1:11434/api/chat'
OLLAMA_MODEL = 'llama3.2'
DOMAINES = {
    'general': 'Tu es un assistant généraliste.',
    'informatique': 'Tu es un expert en informatique et programmation.',
    'finance': 'Tu es un assistant pédagogique en finance.',
    'data': 'Tu es un expert en analyse et qualité des données.',
    'autre': 'Tu es un assistant polyvalent.'
}

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/api/conversations', methods=['GET'])
def get_conversations():
    with get_connection() as conn:
        return jsonify([dict(r) for r in conn.execute('SELECT * FROM conversations ORDER BY id DESC').fetchall()])

@app.route('/api/conversations', methods=['POST'])
def create_conversation():
    payload = request.get_json(silent=True) or {}
    domaine = payload.get('domaine', 'general')
    if not isinstance(domaine, str) or domaine not in DOMAINES:
        return jsonify(error='Domaine invalide.'), 400
    with get_connection() as conn:
        cursor = conn.execute('INSERT INTO conversations (domaine) VALUES (?)', (domaine,))
        conn.commit()
        return jsonify(id=cursor.lastrowid, titre='Nouvelle conversation', domaine=domaine), 201

@app.route('/api/conversations/<int:cid>', methods=['DELETE'])
def delete_conversation(cid):
    with get_connection() as conn:
        cursor = conn.execute('DELETE FROM conversations WHERE id=?', (cid,))
        conn.commit()
        if cursor.rowcount == 0:
            return jsonify(error='Conversation introuvable.'), 404
    return jsonify(message='Conversation supprimée.')

@app.route('/api/conversations/<int:cid>/messages', methods=['GET'])
def get_messages(cid):
    with get_connection() as conn:
        if not conn.execute('SELECT 1 FROM conversations WHERE id=?', (cid,)).fetchone():
            return jsonify(error='Conversation introuvable.'), 404
        rows = conn.execute('''SELECT m.*, e.note FROM messages m
           LEFT JOIN evaluations e ON e.message_id=m.id
           WHERE m.conversation_id=? ORDER BY m.id''', (cid,)).fetchall()
        result = [dict(m) for m in rows]
        for item in result:
            refs = conn.execute("""SELECT e.id,e.localisation,e.contenu,s.filename AS nom,s.id AS source_id
              FROM citations_reponses c JOIN source_extraits e ON e.id=c.extrait_id
              JOIN sources s ON s.id=e.source_id WHERE c.message_id=?""",(item['id'],)).fetchall()
            item['sources'] = [dict(r) for r in refs]
        return jsonify(result)

@app.route('/api/conversations/<int:cid>/messages', methods=['POST'])
def add_message(cid):
    payload = request.get_json(silent=True) or {}
    content, role = payload.get('contenu'), payload.get('role', 'user')
    if not isinstance(content, str) or not content.strip() or role not in ('user','assistant'):
        return jsonify(error='Message ou rôle invalide.'), 400
    with get_connection() as conn:
        if not conn.execute('SELECT 1 FROM conversations WHERE id=?', (cid,)).fetchone():
            return jsonify(error='Conversation introuvable.'), 404
        cur = conn.execute('INSERT INTO messages (conversation_id,role,contenu) VALUES (?,?,?)', (cid,role,content.strip()))
        conn.commit()
        return jsonify(id=cur.lastrowid), 201

@app.route('/api/chat', methods=['POST'])
def chat():
    payload = request.get_json(silent=True) or {}
    cid, message = payload.get('conversation_id'), payload.get('message')
    if type(cid) is not int or not isinstance(message,str) or not message.strip():
        return jsonify(error='Conversation ou message invalide.'), 400
    with get_connection() as conn:
        conv = conn.execute('SELECT * FROM conversations WHERE id=?', (cid,)).fetchone()
        if not conv:
            return jsonify(error='Conversation introuvable.'), 404
        history = conn.execute('SELECT role,contenu FROM messages WHERE conversation_id=? ORDER BY id', (cid,)).fetchall()
        choix = payload.get('source_ids', [])
        if not isinstance(choix, list) or len(choix) > 20 or any(type(v) is not int for v in choix):
            return jsonify(error='Sélection des sources invalide.'), 400
        extraits = []
        if choix:
            placeholders = ','.join('?' for _ in choix)
            extraits = [dict(row) for row in conn.execute(f"""
                SELECT e.id, e.localisation, e.contenu, s.filename, s.id AS source_id
                FROM source_extraits e JOIN sources s ON s.id=e.source_id
                WHERE s.conversation_id=? AND s.id IN ({placeholders})
            """, (cid, *choix)).fetchall()]
    messages = [{'role':'system','content': DOMAINES.get(conv['domaine'],DOMAINES['general'])+' Réponds clairement en français.'}]
    messages.extend({'role':m['role'],'content':m['contenu']} for m in history)
    # Les sources ne servent que si l'utilisateur les sélectionne explicitement.
    selected = choisir_extraits(message, extraits, limite=max(1,min(8,int(payload.get('nb_extraits', 4))))) if extraits else []
    if choix:
        directives = ('Réponds uniquement à partir des extraits numérotés fournis lorsque tu affirmes '
                      'un fait provenant de ces documents. Cite les identifiants [S1], [S2], etc. '
                      'Si les passages ne suffisent pas, indique-le clairement. '
                      'N’invente ni source ni citation.')
        messages[0]['content'] += ' ' + directives
        references = '\n\n'.join(
            f"[S{i}] Document {e['filename']}, {e['localisation']} :\n{e['contenu'][:1500]}"
            for i,e in enumerate(selected,1))
        messages.append({'role':'user','content':f"Documents consultés :\n{references or '(aucun passage correspondant)'}\n\nQuestion : {message.strip()}"})
    else:
        messages.append({'role':'user','content':message.strip()})
    try:
        start = time.perf_counter()
        r = requests.post(OLLAMA_URL, json={'model':OLLAMA_MODEL,'messages':messages,'stream':False,'options':{'num_predict':350}}, timeout=240)
        r.raise_for_status()
        obj = r.json()
        answer = obj['message']['content']
        if not answer.strip():
            return jsonify(error='Réponse vide.'), 502
        elapsed = round(time.perf_counter()-start,2)
        tin = int(obj.get('prompt_eval_count',0))
        tout = int(obj.get('eval_count',0))
        with get_connection() as conn:
            conn.execute('INSERT INTO messages (conversation_id,role,contenu) VALUES (?,?,?)', (cid,'user',message.strip()))
            cur = conn.execute('INSERT INTO messages (conversation_id,role,contenu) VALUES (?,?,?)', (cid,'assistant',answer))
            conn.execute('''INSERT INTO performances (conversation_id,message_id,temps_reponse,tokens_entree,tokens_sortie)
                            VALUES (?,?,?,?,?)''',(cid,cur.lastrowid,elapsed,tin,tout))
            for e in selected:
                conn.execute('INSERT OR IGNORE INTO citations_reponses(message_id,extrait_id) VALUES (?,?)', (cur.lastrowid, e['id']))
            conn.commit()
        return jsonify(sources=[{'id':e['id'],'source_id':e['source_id'],'nom':e['filename'],'localisation':e['localisation'],'contenu':e['contenu']} for e in selected],reponse=answer,temps_reponse=elapsed,tokens_entree=tin,tokens_sortie=tout,tokens_total=tin+tout)
    except requests.exceptions.ConnectionError:
        return jsonify(error='Ollama est inaccessible. Lance Ollama.'), 503
    except requests.exceptions.Timeout:
        return jsonify(error='Ollama ne répond pas assez vite.'), 504
    except requests.exceptions.RequestException:
        app.logger.exception('Ollama error')
        return jsonify(error='Erreur de communication avec Ollama.'), 502
    except (ValueError,KeyError,TypeError):
        app.logger.exception('Ollama invalid response')
        return jsonify(error='Réponse Ollama invalide.'), 502

@app.route('/api/conversations/<int:cid>/stats', methods=['GET'])
def stats(cid):
    with get_connection() as conn:
        if not conn.execute('SELECT 1 FROM conversations WHERE id=?',(cid,)).fetchone():
            return jsonify(error='Conversation introuvable.'),404
        row=conn.execute('''SELECT COUNT(*) nb_requetes,ROUND(AVG(temps_reponse),2) temps_moyen,
          COALESCE(SUM(tokens_entree),0) tokens_entree,COALESCE(SUM(tokens_sortie),0) tokens_sortie
          FROM performances WHERE conversation_id=?''',(cid,)).fetchone()
        return jsonify(dict(row))

@app.route('/api/evaluations', methods=['POST'])
def evaluer_reponse():
    data=request.get_json(silent=True) or {}
    mid,note=data.get('message_id'),data.get('note')
    if type(mid) is not int or type(note) is not int or note not in (1,2,3):
        return jsonify(error='Note ou message invalide.'),400
    with get_connection() as conn:
        if not conn.execute("SELECT 1 FROM messages WHERE id=? AND role='assistant'",(mid,)).fetchone():
            return jsonify(error='Réponse introuvable.'),404
        conn.execute('''INSERT INTO evaluations(message_id,note) VALUES (?,?)
            ON CONFLICT(message_id) DO UPDATE SET note=excluded.note''',(mid,note))
        conn.commit()
    return jsonify(message='Évaluation enregistrée.',note=note)

@app.route('/api/conversations/<int:cid>/export/<fmt>')
def export_conversation(cid,fmt):
    conv=recuperer_conversation(cid)
    if conv is None:
        return jsonify(error='Conversation introuvable.'),404
    formats={'txt':(exporter_txt,'text/plain'),'json':(exporter_json,'application/json'),'pdf':(exporter_pdf,'application/pdf')}
    if fmt not in formats:
        return jsonify(error='Format invalide.'),400
    try:
        f,mime=formats[fmt]
        result=f(conv)
        buf=result if isinstance(result,BytesIO) else BytesIO(result)
        buf.seek(0)
        return send_file(buf,mimetype=mime,as_attachment=True,download_name=f'conversation_{cid}.{fmt}')
    except Exception:
        app.logger.exception('Export impossible')
        return jsonify(error='Échec de génération du fichier.'),500

@app.route('/api/conversations/<int:cid>/resume/pdf')
def resume_pdf(cid):
    conv=recuperer_conversation(cid)
    if conv is None:
        return jsonify(error='Conversation introuvable.'),404
    if not conv['messages']:
        return jsonify(error='Conversation vide.'),400
    transcript='\n\n'.join(f"{m['role']} : {m['contenu']}" for m in conv['messages'])
    truncated=len(transcript)>12000
    if truncated:
        transcript=transcript[-12000:]
    try:
        r=requests.post(OLLAMA_URL,json={'model':OLLAMA_MODEL,'stream':False,'options':{'num_predict':450},'messages':[
            {'role':'system','content':'Résume en français : sujet, questions, idées importantes, conclusion. N’invente rien.'},
            {'role':'user','content':transcript}]},timeout=240)
        r.raise_for_status()
        summary=r.json()['message']['content']
        if truncated:
            summary='Résumé partiel : seuls les derniers caractères ont été transmis.\n\n'+summary
        doc=creer_pdf(f'Résumé de la conversation #{cid}',conv['domaine'],[('Résumé Ollama',summary)])
        doc.seek(0)
        return send_file(doc,mimetype='application/pdf',as_attachment=True,download_name=f'resume_{cid}.pdf')
    except requests.exceptions.RequestException:
        app.logger.exception('Résumé Ollama')
        return jsonify(error='Ollama est inaccessible ou a échoué.'),503
    except Exception:
        app.logger.exception('Résumé PDF')
        return jsonify(error='Impossible de générer le PDF.'),500

@app.route('/api/analyse',methods=['POST'])
def analyse_fichier():
    f=request.files.get('fichier')
    if not f or not f.filename:
        return jsonify(error='Fichier requis.'),400
    ext=f.filename.rsplit('.',1)[-1].lower()
    if ext not in ('csv','xlsx'):
        return jsonify(error='Seuls CSV et XLSX sont acceptés.'),400
    try:
        data=BytesIO(f.read())
        if ext=='xlsx':
            df=pd.read_excel(data)
        else:
            try:
                df=pd.read_csv(data,sep=None,engine='python')
            except UnicodeDecodeError:
                data.seek(0)
                df=pd.read_csv(data,sep=None,engine='python',encoding='latin-1')
        return jsonify(analyser_donnees(df))
    except (ValueError,pd.errors.ParserError) as exc:
        return jsonify(error=str(exc)),400
    except Exception:
        app.logger.exception('CSV analysis')
        return jsonify(error='Analyse impossible.'),500

@app.route('/api/analyse/sqlite',methods=['POST'])
def analyse_sqlite():
    f=request.files.get('fichier')
    if not f or not f.filename:
        return jsonify(error='Base SQLite requise.'),400
    if not f.filename.lower().endswith(('.db','.sqlite','.sqlite3')):
        return jsonify(error='Extension SQLite invalide.'),400
    try:
        return jsonify(analyser_base_sqlite(f.read(),request.form.get('table') or None))
    except ValueError as exc:
        return jsonify(error=str(exc)),400
    except Exception:
        app.logger.exception('SQLite analysis')
        return jsonify(error='Impossible d’analyser la base.'),500

@app.route('/api/conversations/<int:cid>/sources', methods=['GET'])
def liste_sources(cid):
    with get_connection() as conn:
        if not conn.execute('SELECT 1 FROM conversations WHERE id=?',(cid,)).fetchone():
            return jsonify(error='Conversation introuvable.'),404
        rows=conn.execute('SELECT id,filename,created_at FROM sources WHERE conversation_id=? ORDER BY id DESC',(cid,)).fetchall()
    return jsonify([dict(r) for r in rows])

@app.route('/api/conversations/<int:cid>/sources', methods=['POST'])
def ajouter_source(cid):
    f=request.files.get('fichier')
    if f is None or not f.filename:
        return jsonify(error='Document requis.'),400
    with get_connection() as conn:
        if not conn.execute('SELECT 1 FROM conversations WHERE id=?',(cid,)).fetchone():
            return jsonify(error='Conversation introuvable.'),404
        try:
            nom, fragments=extraire(f)
        except ValueError as exc:
            return jsonify(error=str(exc)),400
        cur=conn.execute('INSERT INTO sources(conversation_id,filename) VALUES (?,?)',(cid,nom))
        conn.executemany('INSERT INTO source_extraits(source_id,localisation,contenu) VALUES (?,?,?)',[(cur.lastrowid,loc,txt) for loc,txt in fragments])
        conn.commit()
    return jsonify(id=cur.lastrowid,filename=nom,nb_extraits=len(fragments)),201

@app.route('/api/conversations/<int:cid>/sources/<int:sid>', methods=['DELETE'])
def supprimer_source(cid,sid):
    with get_connection() as conn:
        cur=conn.execute('DELETE FROM sources WHERE id=? AND conversation_id=?',(sid,cid))
        conn.commit()
        if cur.rowcount==0:
            return jsonify(error='Source introuvable.'),404
    return jsonify(message='Source supprimée.')

@app.route('/api/conversations/<int:cid>/sources/<int:sid>/extraits')
def afficher_extraits(cid,sid):
    try:
        debut=max(0,int(request.args.get('debut',0)))
        limite=max(1,min(30,int(request.args.get('limite',5))))
    except ValueError:
        return jsonify(error='Pagination invalide.'),400
    with get_connection() as conn:
        if not conn.execute('SELECT 1 FROM sources WHERE id=? AND conversation_id=?',(sid,cid)).fetchone():
            return jsonify(error='Source introuvable.'),404
        rows=conn.execute('SELECT id,localisation,contenu FROM source_extraits WHERE source_id=? ORDER BY id LIMIT ? OFFSET ?',(sid,limite,debut)).fetchall()
    return jsonify([dict(r) for r in rows])

@app.errorhandler(413)
def file_too_large(_):
    return jsonify(error='Fichier trop volumineux (maximum 10 Mo).'),413

if __name__=='__main__':
    app.run(debug=True)
