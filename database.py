import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / 'conversations.db'

def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn

def init_db():
    with get_connection() as conn:
        conn.executescript('''
        CREATE TABLE IF NOT EXISTS conversations (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          titre TEXT NOT NULL DEFAULT 'Nouvelle conversation',
          domaine TEXT NOT NULL DEFAULT 'general',
          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS messages (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          conversation_id INTEGER NOT NULL,
          role TEXT NOT NULL CHECK(role IN ('user','assistant')),
          contenu TEXT NOT NULL,
          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE);
        CREATE TABLE IF NOT EXISTS performances (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          conversation_id INTEGER NOT NULL,
          message_id INTEGER UNIQUE,
          temps_reponse REAL NOT NULL,
          tokens_entree INTEGER NOT NULL DEFAULT 0,
          tokens_sortie INTEGER NOT NULL DEFAULT 0,
          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
          FOREIGN KEY(message_id) REFERENCES messages(id) ON DELETE CASCADE);
        CREATE TABLE IF NOT EXISTS evaluations (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          message_id INTEGER NOT NULL UNIQUE,
          note INTEGER NOT NULL CHECK(note BETWEEN 1 AND 3),
          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY(message_id) REFERENCES messages(id) ON DELETE CASCADE);
        CREATE TABLE IF NOT EXISTS sources (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          conversation_id INTEGER NOT NULL,
          filename TEXT NOT NULL,
          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE);
        CREATE TABLE IF NOT EXISTS source_extraits (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          source_id INTEGER NOT NULL,
          localisation TEXT NOT NULL,
          contenu TEXT NOT NULL,
          FOREIGN KEY(source_id) REFERENCES sources(id) ON DELETE CASCADE);
        CREATE TABLE IF NOT EXISTS citations_reponses (
          message_id INTEGER NOT NULL,
          extrait_id INTEGER NOT NULL,
          PRIMARY KEY(message_id, extrait_id),
          FOREIGN KEY(message_id) REFERENCES messages(id) ON DELETE CASCADE,
          FOREIGN KEY(extrait_id) REFERENCES source_extraits(id) ON DELETE CASCADE);
        ''')
        conn.commit()

if __name__ == '__main__':
    init_db()
    print('Base SQLite prête.')
