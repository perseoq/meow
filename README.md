## Web Server with Smart Indexing System

This Python Flask web server automatically indexes HTML pages and provides a search functionality with the following features:

### How It Works

1. **Automatic Indexing**
   - Scans the `web` directory recursively every 60 seconds
   - Processes all `index.html` files found in subdirectories
   - Detects file changes using file hashes (modification time + size)
   - Only updates the database when content actually changes

2. **Metadata Extraction**
   - Extracts standard meta tags (`title`, `description`, `keywords`)
   - Falls back to using the first `<h1>` as title and first `<p>` as description if meta tags are missing
   - Automatically truncates long descriptions to 120 characters

3. **Search Functionality**
   - Full-text search across titles, descriptions and keywords
   - Paginated results (30 items per page)
   - Shows total matches and page navigation

4. **Content Serving**
   - Serves static files from the `web` directory
   - Automatically serves `index.html` when directories are requested
   - Prevents directory traversal attacks

5. **Database**
   - Uses SQLite stored in the `backup` directory
   - Maintains file hashes to detect changes
   - Preserves historical data between server restarts

### Technical Components

- **Main File**: `server.py` (Flask application)
- **Required Packages**: `flask`, `beautifulsoup4`
- **Directory Structure**:
  ```
  /project-root
  ├── web/          # Website files (HTML, CSS, JS)
  ├── backup/       # SQLite database
  ├── templates/    # Flask templates
  └── static/       # Static assets (optional)
  ```

### Usage Instructions

1. Install requirements:
   ```bash
   pip install flask beautifulsoup4
   ```

2. Create directory structure:
   ```bash
   mkdir -p web backup
   ```

3. Add your HTML files in `web/` (e.g., `web/my-site/index.html`)

4. Run the server:
   ```bash
   python server.py
   ```

5. Access at `http://localhost:5000`

The system will automatically:
- Index existing pages on startup
- Continuously monitor for changes
- Provide search functionality through the web interface
