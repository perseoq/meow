import os
import time
import threading
from datetime import datetime
from bs4 import BeautifulSoup
from flask import Flask, render_template, request, send_from_directory, abort
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import or_, and_

# Configuración inicial
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(BASE_DIR, 'web')
BACKUP_DIR = os.path.join(BASE_DIR, 'backup')
DB_FILE = os.path.join(BACKUP_DIR, 'pages.db')
TEMPLATES_DIR = os.path.join(BASE_DIR, 'templates')

# Inicializar Flask
app = Flask(__name__, template_folder=TEMPLATES_DIR)
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{DB_FILE}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Inicializar SQLAlchemy
db = SQLAlchemy(app)

# Crear directorios necesarios
os.makedirs(WEB_DIR, exist_ok=True)
os.makedirs(BACKUP_DIR, exist_ok=True)
os.makedirs(TEMPLATES_DIR, exist_ok=True)

# Modelo de datos
class Page(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    path = db.Column(db.String(500), unique=True)
    title = db.Column(db.String(200))
    description = db.Column(db.String(500))
    keywords = db.Column(db.String(200))
    last_updated = db.Column(db.DateTime)
    file_hash = db.Column(db.String(100))

    def __repr__(self):
        return f'<Page {self.path}>'

# Filtros personalizados para las plantillas
@app.template_filter('format_url')
def format_url_filter(path):
    """Formatea la URL para mostrarla como Google"""
    base_url = request.host_url.rstrip('/')
    parts = path.split('/')
    if len(parts) > 1:
        formatted = ' › '.join(parts[:-1])  # Excluye el nombre del archivo
        return f"{base_url}/{formatted.lower()}"
    return f"{base_url}/{path.lower()}"

@app.template_filter('truncate')
def truncate_filter(text, length=160):
    """Trunca el texto a una longitud específica"""
    if not text:
        return ""
    if len(text) > length:
        return text[:length-3] + '...'
    return text

# Crear tablas si no existen
with app.app_context():
    db.create_all()

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
            
            # Extraer todos los encabezados (h1-h6) si no hay título
            if not title:
                headers = []
                for h in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
                    headers.append(h.get_text().strip())
                if headers:
                    title = ' | '.join(headers)
            
            # Extraer primer párrafo si no hay descripción
            if not description:
                first_p = soup.find('p')
                description = first_p.get_text() if first_p else ''
                
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

def update_or_insert_page(path, metadata, file_hash):
    """Actualiza la página solo si ha cambiado o no existe"""
    with app.app_context():
        page = Page.query.filter_by(path=path).first()
        
        if page and page.file_hash == file_hash:
            print(f"Sin cambios: {path}")
            return False
        
        if page:
            # Actualizar página existente
            page.title = metadata['title']
            page.description = metadata['description']
            page.keywords = metadata['keywords']
            page.last_updated = datetime.now()
            page.file_hash = file_hash
        else:
            # Crear nueva página
            page = Page(
                path=path,
                title=metadata['title'],
                description=metadata['description'],
                keywords=metadata['keywords'],
                last_updated=datetime.now(),
                file_hash=file_hash
            )
            db.session.add(page)
        
        db.session.commit()
        return True

def crawl_pages():
    print("\nIniciando indexación inteligente...")
    
    updated_count = 0
    total_count = 0
    
    for root, _, files in os.walk(WEB_DIR):
        for file in files:
            if file.lower().endswith('.html'):
                file_path = os.path.join(root, file)
                web_path = os.path.relpath(file_path, WEB_DIR)
                total_count += 1
                
                try:
                    metadata = extract_metadata(file_path)
                    file_hash = calculate_file_hash(file_path)
                    
                    if update_or_insert_page(web_path, metadata, file_hash):
                        updated_count += 1
                        print(f"Actualizado: {web_path}")
                    
                except Exception as e:
                    print(f"Error indexando {file_path}: {str(e)}")
    
    print(f"Indexación completada. {updated_count}/{total_count} páginas actualizadas.\n")

def run_periodic_crawler(interval=60):
    # Esperar a que la aplicación Flask esté lista
    time.sleep(5)
    
    while True:
        next_run = time.time() + interval
        with app.app_context():
            crawl_pages()
        
        while time.time() < next_run:
            remaining = int(next_run - time.time())
            print(f"\rPróxima indexación en: {remaining}s", end="")
            time.sleep(1)

# Iniciar el indexador en segundo plano
def start_crawler():
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
    
    per_page = 10  # Reducido a 10 resultados por página para estilo Google
    offset = (page - 1) * per_page
    
    if query:
        # Dividir la consulta en términos individuales
        terms = query.split()
        
        # Crear condiciones de búsqueda para cada término
        conditions = []
        for term in terms:
            term_cond = or_(
                Page.title.ilike(f'%{term}%'),
                Page.description.ilike(f'%{term}%'),
                Page.keywords.ilike(f'%{term}%')
            )
            conditions.append(term_cond)
        
        # Combinar condiciones con AND (todos los términos deben coincidir)
        query_filter = and_(*conditions)
        
        # Contar resultados totales
        total_records = Page.query.filter(query_filter).count()
        
        # Obtener resultados paginados
        results = Page.query.filter(query_filter)\
                            .order_by(Page.title)\
                            .limit(per_page)\
                            .offset(offset)\
                            .all()
    else:
        # Si no hay consulta, mostrar todo
        total_records = Page.query.count()
        results = Page.query.order_by(Page.title)\
                           .limit(per_page)\
                           .offset(offset)\
                           .all()
    
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
    # Iniciar el crawler después de que Flask esté listo
    start_crawler()
    
    # Ejecutar la aplicación Flask
    app.run(host='0.0.0.0', port=6100, debug=True)
