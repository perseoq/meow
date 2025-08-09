import os
import asyncio
from datetime import datetime
from bs4 import BeautifulSoup
from flask import Flask, render_template, request, send_from_directory, abort
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import sessionmaker

# ───── Configuración inicial ───────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(BASE_DIR, 'web')
BACKUP_DIR = os.path.join(BASE_DIR, 'backup')
DB_FILE = os.path.join(BACKUP_DIR, 'pages.db')
TEMPLATES_DIR = os.path.join(BASE_DIR, 'templates')

os.makedirs(WEB_DIR, exist_ok=True)
os.makedirs(BACKUP_DIR, exist_ok=True)
os.makedirs(TEMPLATES_DIR, exist_ok=True)

# ───── Flask + SQLAlchemy ───────────────────────────────────────────
app = Flask(__name__, template_folder=TEMPLATES_DIR)
app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{DB_FILE}"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    "connect_args": {"timeout": 30}
}
db = SQLAlchemy(app)

# ───── Modelo ──────────────────────────────────────────────────────
class Page(db.Model):
    __tablename__ = 'pages'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    path = db.Column(db.String, unique=True)
    title = db.Column(db.String)
    description = db.Column(db.String)
    keywords = db.Column(db.String)
    last_updated = db.Column(db.DateTime)
    file_hash = db.Column(db.String)

# Inicializar BD y activar WAL dentro del contexto de la app
with app.app_context():
    with db.engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA journal_mode=WAL")
    db.create_all()
    CrawlerSession = sessionmaker(bind=db.engine)

# ───── Funciones auxiliares ─────────────────────────────────────────
def calculate_file_hash(file_path):
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
        return {'title': '', 'description': '', 'keywords': ''}

def update_or_insert_page(session, path, metadata, file_hash):
    page = session.query(Page).filter_by(path=path).first()
    if page:
        if page.file_hash == file_hash:
            print(f"Sin cambios: {path}")
            return False
        page.title = metadata['title']
        page.description = metadata['description']
        page.keywords = metadata['keywords']
        page.last_updated = datetime.now()
        page.file_hash = file_hash
    else:
        page = Page(
            path=path,
            title=metadata['title'],
            description=metadata['description'],
            keywords=metadata['keywords'],
            last_updated=datetime.now(),
            file_hash=file_hash
        )
        session.add(page)
    return True

# ───── Crawler asíncrono ───────────────────────────────────────────
async def crawl_pages_async():
    print("\nIniciando indexación inteligente...")
    updated_count = 0
    total_count = 0
    session = CrawlerSession()

    for root, _, files in os.walk(WEB_DIR):
        for file in files:
            if file.lower() == 'index.html':
                file_path = os.path.join(root, file)
                web_path = os.path.relpath(file_path, WEB_DIR)
                total_count += 1
                try:
                    metadata = extract_metadata(file_path)
                    file_hash = calculate_file_hash(file_path)
                    if update_or_insert_page(session, web_path, metadata, file_hash):
                        updated_count += 1
                        print(f"Actualizado: {web_path}")
                except Exception as e:
                    print(f"Error indexando {file_path}: {str(e)}")

        await asyncio.sleep(0)  # libera el control al event loop

    session.commit()
    session.close()
    print(f"Indexación completada. {updated_count}/{total_count} páginas actualizadas.\n")

async def run_periodic_crawler_async(interval=60):
    while True:
        await crawl_pages_async()
        await asyncio.sleep(interval)

# Variable para controlar si el crawler ya fue iniciado
crawler_started = False

@app.before_request
def initialize_crawler_once():
    """Inicia el crawler solo una vez cuando se recibe el primer request"""
    global crawler_started
    if not crawler_started:
        asyncio.create_task(run_periodic_crawler_async())
        crawler_started = True

# ───── Rutas ───────────────────────────────────────────────────────
@app.route('/')
def home():
    return render_template('index.html')

@app.route('/search')
def search():
    query = request.args.get('q', '').strip()
    page_num = int(request.args.get('page', '1') or 1)
    per_page = 30

    if query:
        search_term = f"%{query}%"
        pagination = Page.query.filter(
            (Page.title.like(search_term)) |
            (Page.description.like(search_term)) |
            (Page.keywords.like(search_term))
        ).order_by(Page.title).paginate(page=page_num, per_page=per_page, error_out=False)
    else:
        pagination = Page.query.order_by(Page.title).paginate(page=page_num, per_page=per_page, error_out=False)

    return render_template('search.html',
                           results=[(p.path, p.title, p.description) for p in pagination.items],
                           query=query,
                           page=page_num,
                           total_pages=pagination.pages,
                           total_records=pagination.total)

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
        return send_from_directory(os.path.dirname(full_path), os.path.basename(full_path))
    if os.path.exists(os.path.join(os.path.join(WEB_DIR, safe_path), 'index.html')):
        return send_from_directory(os.path.join(WEB_DIR, safe_path), 'index.html')
    abort(404)

# ───── Main ────────────────────────────────────────────────────────
if __name__ == '__main__':
    # Ejecuta el crawler inicial de forma síncrona
    asyncio.run(crawl_pages_async())
    app.run(host='0.0.0.0', port=2025, debug=True)