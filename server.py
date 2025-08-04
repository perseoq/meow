import os
import sqlite3
import time
import threading
from datetime import datetime
from bs4 import BeautifulSoup
from flask import Flask, render_template, request, send_from_directory, abort

# Configuración inicial
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(BASE_DIR, 'web')
BACKUP_DIR = os.path.join(BASE_DIR, 'backup')
DB_FILE = os.path.join(BACKUP_DIR, 'pages.db')
TEMPLATES_DIR = os.path.join(BASE_DIR, 'templates')

# Inicializar Flask
app = Flask(__name__, template_folder=TEMPLATES_DIR)

# Crear directorios necesarios
os.makedirs(WEB_DIR, exist_ok=True)
os.makedirs(BACKUP_DIR, exist_ok=True)
os.makedirs(TEMPLATES_DIR, exist_ok=True)

# Inicialización de la base de datos
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS pages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT UNIQUE,
            title TEXT,
            description TEXT,
            keywords TEXT,
            last_updated TIMESTAMP,
            file_hash TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def calculate_file_hash(file_path):
    """Calcula un hash simple del archivo para detectar cambios"""
    try:
        stat = os.stat(file_path)
        return f"{stat.st_mtime}-{stat.st_size}"
    except:
        return ""

def extract_metadata(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            soup = BeautifulSoup(f.read(), 'html.parser')
            
            title = soup.title.string if soup.title else ''
            
            meta_desc = soup.find('meta', attrs={'name': 'description'})
            description = meta_desc['content'] if meta_desc else ''
            
            meta_keywords = soup.find('meta', attrs={'name': 'keywords'})
            keywords = meta_keywords['content'] if meta_keywords else ''
            
            if not description:
                h1 = soup.find('h1')
                first_p = soup.find('p')
                
                title = h1.get_text() if h1 else title
                description = first_p.get_text() if first_p else description
                
                if len(description) > 120:
                    description = description[:117] + '...'
            
            return {
                'title': title.strip(),
                'description': description.strip(),
                'keywords': keywords.strip()
            }
    except Exception as e:
        print(f"Error procesando {file_path}: {str(e)}")
        return {
            'title': '',
            'description': '',
            'keywords': ''
        }

def update_or_insert_page(cursor, path, metadata, file_hash):
    """Actualiza la página solo si ha cambiado o no existe"""
    cursor.execute('SELECT file_hash FROM pages WHERE path = ?', (path,))
    result = cursor.fetchone()
    
    if result:
        existing_hash = result[0]
        if existing_hash == file_hash:
            print(f"Sin cambios: {path}")
            return False
    
    cursor.execute('''
        INSERT OR REPLACE INTO pages 
        (path, title, description, keywords, last_updated, file_hash)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (
        path, 
        metadata['title'], 
        metadata['description'],
        metadata['keywords'], 
        datetime.now(),
        file_hash
    ))
    return True

def crawl_pages():
    print("\nIniciando indexación inteligente...")
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    updated_count = 0
    total_count = 0
    
    for root, _, files in os.walk(WEB_DIR):
        for file in files:
            if file.lower() == 'index.html':
                file_path = os.path.join(root, file)
                web_path = os.path.relpath(file_path, WEB_DIR)
                total_count += 1
                
                try:
                    metadata = extract_metadata(file_path)
                    file_hash = calculate_file_hash(file_path)
                    
                    if update_or_insert_page(cursor, web_path, metadata, file_hash):
                        updated_count += 1
                        print(f"Actualizado: {web_path}")
                    
                except Exception as e:
                    print(f"Error indexando {file_path}: {str(e)}")
    
    conn.commit()
    conn.close()
    print(f"Indexación completada. {updated_count}/{total_count} páginas actualizadas.\n")

def run_periodic_crawler(interval=300):
    while True:
        next_run = time.time() + interval
        crawl_pages()
        
        while time.time() < next_run:
            remaining = int(next_run - time.time())
            print(f"\rPróxima indexación en: {remaining}s", end="")
            time.sleep(1)

# Iniciar el indexador en segundo plano
crawler_thread = threading.Thread(target=run_periodic_crawler, daemon=True)
crawler_thread.start()

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/search')
def search():
    query = request.args.get('q', '').strip()
    page = request.args.get('page', '1')
    
    try:
        page = int(page)
    except ValueError:
        page = 1
    
    per_page = 30
    offset = (page - 1) * per_page
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    if query:
        search_term = f"%{query}%"
        cursor.execute('''
            SELECT COUNT(*) FROM pages
            WHERE title LIKE ? OR description LIKE ? OR keywords LIKE ?
        ''', (search_term, search_term, search_term))
        total_records = cursor.fetchone()[0]
        
        cursor.execute('''
            SELECT path, title, description FROM pages
            WHERE title LIKE ? OR description LIKE ? OR keywords LIKE ?
            ORDER BY title
            LIMIT ? OFFSET ?
        ''', (search_term, search_term, search_term, per_page, offset))
    else:
        cursor.execute('SELECT COUNT(*) FROM pages')
        total_records = cursor.fetchone()[0]
        
        cursor.execute('''
            SELECT path, title, description FROM pages
            ORDER BY title
            LIMIT ? OFFSET ?
        ''', (per_page, offset))
    
    results = cursor.fetchall()
    conn.close()
    
    total_records = int(total_records)
    total_pages = (total_records + per_page - 1) // per_page
    
    return render_template('search.html',
                         results=results,
                         query=query,
                         page=page,
                         total_pages=total_pages,
                         total_records=total_records)

@app.route('/<path:requested_path>')
def serve_content(requested_path):
    if '..' in requested_path or requested_path.startswith('/'):
        abort(403)
    
    safe_path = os.path.normpath(requested_path)
    full_path = os.path.join(WEB_DIR, safe_path)
    
    if os.path.isdir(full_path):
        index_path = os.path.join(full_path, 'index.html')
        if os.path.exists(index_path):
            return send_from_directory(full_path, 'index.html')
    
    if os.path.isfile(full_path):
        dir_path = os.path.dirname(full_path)
        file_name = os.path.basename(full_path)
        return send_from_directory(dir_path, file_name)
    
    dir_path = os.path.join(WEB_DIR, safe_path)
    if os.path.exists(os.path.join(dir_path, 'index.html')):
        return send_from_directory(dir_path, 'index.html')
    
    abort(404)

if __name__ == '__main__':
    crawl_pages()
    app.run(host='0.0.0.0', port=5000, debug=True)