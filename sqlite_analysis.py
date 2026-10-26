import sqlite3
import tempfile
from pathlib import Path
import pandas as pd
from data_analysis import analyser_donnees

def analyser_base_sqlite(contenu, nom_table=None):
    if not contenu.startswith(b'SQLite format 3\x00'):
        raise ValueError('Fichier SQLite invalide.')
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp)/'import.db'
        db.write_bytes(contenu)
        # URI SQLite en lecture seule : aucune modification de la base importée.
        with sqlite3.connect(db.resolve().as_uri()+'?mode=ro', uri=True) as conn:
            check = conn.execute('PRAGMA integrity_check').fetchone()
            if not check or check[0] != 'ok':
                raise ValueError('Base corrompue.')
            tables = [r[0] for r in conn.execute('''SELECT name FROM sqlite_master
                         WHERE type='table' AND name NOT LIKE 'sqlite_%'
                         ORDER BY name''').fetchall()]
            if not tables:
                raise ValueError('Aucune table détectée.')
            if not nom_table:
                return {'tables': tables, 'selection_requise': True}
            if nom_table not in tables:
                raise ValueError('Table inexistante.')
            safe = nom_table.replace('"', '""')
            df = pd.read_sql_query(f'SELECT * FROM "{safe}"', conn)
            return {'tables': tables, 'selection_requise': False,
                    'table_analysee': nom_table, 'analyse': analyser_donnees(df)}
