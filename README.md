# Markdown Editor

A single-file, zero-dependency Python web server for browsing and editing Markdown files with a rich text editor in the browser.

## Features

- **Rich Text Editor** — WYSIWYG and Markdown source editing with live preview
- **Paste Images** — Paste from clipboard, auto-saved and referenced in Markdown
- **Tree File Browser** — Recursive directory tree, drag-and-drop to move, inline rename
- **Full-Text Search** — Inverted index for instant search across thousands of files
- **Authentication** — Simple username/password login with session cookies
- **Auto-Save** — Saves 2 seconds after you stop typing
- **Code Highlighting** — Syntax highlighting for code blocks (via Prism.js)

## Quick Start

```bash
# Default credentials: fengchang / Passw0rd
python main.py
```

Open http://127.0.0.1:8765 in your browser.

## Custom Credentials

```bash
# Linux / macOS
MDEDITOR_USER=myuser MDEDITOR_PASS=mypass python main.py

# Windows PowerShell
$env:MDEDITOR_USER="myuser"; $env:MDEDITOR_PASS="mypass"; python main.py

# Windows CMD
set MDEDITOR_USER=myuser && set MDEDITOR_PASS=mypass && python main.py
```

## Run in Background (Linux)

```bash
nohup env MDEDITOR_USER=fengchang MDEDITOR_PASS=Passw0rd python3 main.py > /dev/null 2>&1 &
```

## Usage

| Action | How |
|--------|-----|
| Open file | Click on any `.md` file in the sidebar tree |
| Create file | Click `+ File` in sidebar, or hover a folder and click `+📄` |
| Create folder | Click `+ Dir` in sidebar, or hover a folder and click `+📁` |
| Rename | Hover a file/folder, click ✏, type new name, press Enter |
| Move | Drag a file or folder onto a target folder |
| Delete | Hover a file/folder, click × |
| Save | `Ctrl+S` or click 💾 Save (also auto-saves 2s after typing stops) |
| Paste image | `Ctrl+V` in the editor when a Markdown file is open |
| Toggle mode | Click `WYSIWYG` / `Markdown` button in toolbar |
| Split view | Click `◫ Split` to cycle: split → source-only → preview-only |
| Search | Type in the search box at top of sidebar |
| Logout | Click ⏻ in toolbar |

## Nginx Reverse Proxy

```
server {
    listen 443 ssl;
    server_name markdown.example.com;
    # ... ssl config ...
    location / {
        proxy_pass http://127.0.0.1:8765;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

## Requirements

- Python 3.7+
- No pip packages needed (uses only standard library)
- Browser with JavaScript enabled (Toast UI Editor loads from CDN)

## Project Structure

```
mdeditor/
├── main.py          # The entire application (single file)
├── .gitignore
├── .mdeditor_index.json  # Auto-generated search index
└── *.md             # Your Markdown files (recursive)
```

## License

MIT
