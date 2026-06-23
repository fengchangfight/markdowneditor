"""
Lightweight Markdown Editor Web Server
Usage: python main.py
Then open http://127.0.0.1:8765
"""

import http.server
import json
import os
import re
import uuid
import base64
import mimetypes
import sys
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote

HOST = '127.0.0.1'
PORT = 8765
BASE_DIR = Path(__file__).parent.resolve()

IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.bmp', '.ico'}
TEXT_EXTS = {'.css', '.js', '.md', '.html', '.txt', '.json', '.xml', '.csv'}

HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Markdown Editor</title>
<link rel="stylesheet" href="https://uicdn.toast.com/editor/latest/toastui-editor.min.css">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/themes/prism.min.css">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;display:flex;height:100vh;overflow:hidden}
#sidebar{width:250px;min-width:250px;background:#f7f8fa;border-right:1px solid #e0e0e0;display:flex;flex-direction:column}
#sidebar-header{padding:14px;border-bottom:1px solid #e0e0e0}
#sidebar-header h2{font-size:15px;margin-bottom:10px;color:#333}
#sidebar-header button{width:100%;padding:7px;background:#4a90d9;color:#fff;border:none;border-radius:4px;cursor:pointer;font-size:13px}
#sidebar-header button:hover{background:#357abd}
#file-list{flex:1;overflow-y:auto;padding:6px 0}
.file-item{padding:9px 14px;cursor:pointer;font-size:13px;color:#555;border-left:3px solid transparent;transition:all .15s;display:flex;align-items:center;gap:6px}
.file-item:hover{background:#eef1f5}
.file-item.active{background:#e3edf7;border-left-color:#4a90d9;color:#222;font-weight:500}
.file-item .name{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.file-item .del-btn{visibility:hidden;background:none;border:none;color:#c0392b;cursor:pointer;font-size:14px;padding:0 4px}
.file-item:hover .del-btn{visibility:visible}
.file-item .del-btn:hover{color:#e74c3c}
#main{flex:1;display:flex;flex-direction:column;overflow:hidden}
#toolbar{padding:8px 14px;border-bottom:1px solid #e0e0e0;background:#fff;display:flex;align-items:center;gap:10px;flex-shrink:0}
#toolbar #current-file{font-size:14px;color:#333;font-weight:500}
#toolbar .status{font-size:12px;color:#999;min-width:60px}
#toolbar .spacer{flex:1}
#toolbar button{padding:5px 12px;background:#4a90d9;color:#fff;border:none;border-radius:4px;cursor:pointer;font-size:12px}
#toolbar button:hover{background:#357abd}
#toolbar button.ghost{background:transparent;color:#555;border:1px solid #ddd}
#toolbar button.ghost:hover{background:#f5f5f5}
#toolbar button.danger{background:#e74c3c}
#toolbar button.danger:hover{background:#c0392b}
#editor-container{flex:1;overflow:hidden}
.toastui-editor-defaultUI{border:none!important;border-radius:0!important}
#editor-container.src-only .toastui-editor-md-preview{display:none!important}
#editor-container.prv-only .toastui-editor-md-editor{display:none!important}
</style>
</head>
<body>
<div id="sidebar">
  <div id="sidebar-header">
    <h2>📝 Markdown Files</h2>
    <button onclick="createFile()">+ New File</button>
  </div>
  <div id="file-list"></div>
</div>
<div id="main">
  <div id="toolbar">
    <span id="current-file">No file selected</span>
    <span class="status" id="save-status"></span>
    <span class="spacer"></span>
    <button id="view-md-btn" class="ghost" onclick="toggleMode()">WYSIWYG</button>
    <button id="split-btn" class="ghost" onclick="toggleViewMode()">◫ Split</button>
    <button onclick="deleteCurrentFile()" class="danger" style="display:none" id="del-btn">Delete</button>
    <button onclick="saveCurrentFile()">💾 Save</button>
  </div>
  <div id="editor-container"></div>
</div>

<script src="https://uicdn.toast.com/editor/latest/toastui-editor-all.min.js"></script>
<script src="https://uicdn.toast.com/editor-plugin-code-syntax-highlight/latest/toastui-editor-plugin-code-syntax-highlight.min.js"></script>
<script>
var E = (window.toastui && window.toastui.Editor) || window.Editor;
var csPlugin = (window.toastui && window.toastui.Editor && window.toastui.Editor.plugin && window.toastui.Editor.plugin.codeSyntaxHighlight) || null;

var editor = null;
var currentFile = null;
var allFiles = [];
var isWysiwyg = false;
var viewMode = 'split';

function initEditor() {
    var plugins = csPlugin ? [csPlugin] : [];
    editor = new E({
        el: document.querySelector('#editor-container'),
        height: '100%',
        initialEditType: 'markdown',
        previewStyle: 'vertical',
        plugins: plugins,
        hooks: {
            addImageBlobHook: function(blob, callback) {
                var reader = new FileReader();
                reader.onload = function(e) {
                    fetch('/api/upload', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({data: e.target.result})
                    }).then(function(r){ return r.json() }).then(function(d){
                        callback(d.url, blob.name || 'image');
                    }).catch(function(err){
                        console.error('Upload failed:', err);
                    });
                };
                reader.readAsDataURL(blob);
            }
        }
    });
}

function loadFileList() {
    fetch('/api/files').then(function(r){return r.json()}).then(function(files){
        allFiles = files;
        renderFileList();
    });
}

function renderFileList() {
    var list = document.getElementById('file-list');
    var html = '';
    for (var i = 0; i < allFiles.length; i++) {
        var f = allFiles[i];
        var cls = currentFile === f.name ? ' active' : '';
        html += '<div class="file-item' + cls + '" onclick="openFile(\'' + esc(f.name) + '\')">' +
            '<span style="opacity:.5">📄</span>' +
            '<span class="name">' + esc(f.name) + '</span>' +
            '<button class="del-btn" onclick="event.stopPropagation();delFile(\'' + esc(f.name) + '\')" title="Delete">×</button>' +
        '</div>';
    }
    list.innerHTML = html;
}

function esc(s) {
    return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

function openFile(name) {
    fetch('/api/file?name=' + encodeURIComponent(name)).then(function(r){
        if (!r.ok) throw new Error('not found');
        return r.json();
    }).then(function(data){
        currentFile = data.name;
        editor.setMarkdown(data.content);
        document.getElementById('current-file').textContent = currentFile;
        document.getElementById('save-status').textContent = '';
        document.getElementById('del-btn').style.display = '';
        renderFileList();
    }).catch(function(){
        alert('Failed to open file: ' + name);
    });
}

function saveCurrentFile() {
    if (!currentFile) { alert('No file selected'); return; }
    var content = editor.getMarkdown();
    fetch('/api/file', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name: currentFile, content: content})
    }).then(function(r){
        return r.json();
    }).then(function(){
        var st = document.getElementById('save-status');
        st.textContent = '✓ Saved';
        st.style.color = '#27ae60';
        setTimeout(function(){ st.textContent = ''; }, 2000);
    }).catch(function(){
        alert('Failed to save');
    });
}

function deleteCurrentFile() {
    if (!currentFile) return;
    if (!confirm('Delete "' + currentFile + '"?')) return;
    fetch('/api/file?name=' + encodeURIComponent(currentFile), { method: 'DELETE' }).then(function(r){
        if (r.ok) {
            currentFile = null;
            editor.setMarkdown('');
            document.getElementById('current-file').textContent = 'No file selected';
            document.getElementById('del-btn').style.display = 'none';
            loadFileList();
        }
    });
}

function delFile(name) {
    if (!confirm('Delete "' + name + '"?')) return;
    fetch('/api/file?name=' + encodeURIComponent(name), { method: 'DELETE' }).then(function(r){
        if (r.ok) {
            if (currentFile === name) {
                currentFile = null;
                editor.setMarkdown('');
                document.getElementById('current-file').textContent = 'No file selected';
                document.getElementById('del-btn').style.display = 'none';
            }
            loadFileList();
        }
    });
}

function createFile() {
    var name = prompt('Enter filename:', 'new-note.md');
    if (!name) return;
    if (!/\.md$/i.test(name)) name += '.md';
    var title = name.replace(/\.md$/i, '');
    var content = '# ' + title + '\n\n';
    fetch('/api/file', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name: name, content: content})
    }).then(function(r){
        if (r.ok) { loadFileList(); openFile(name); }
        else {
            return r.json().then(function(d){ alert(d.error || 'Failed to create'); });
        }
    });
}

var savedViewMode = 'split';

function toggleMode() {
    if (!editor) return;
    isWysiwyg = !isWysiwyg;
    editor.changeMode(isWysiwyg ? 'wysiwyg' : 'markdown');
    document.getElementById('view-md-btn').textContent = isWysiwyg ? 'Markdown' : 'WYSIWYG';
    var sb = document.getElementById('split-btn');
    var el = document.getElementById('editor-container');
    if (isWysiwyg) {
        savedViewMode = viewMode;
        sb.style.display = 'none';
        el.classList.remove('src-only', 'prv-only');
    } else {
        sb.style.display = '';
        viewMode = savedViewMode;
        el.classList.remove('src-only', 'prv-only');
        if (viewMode === 'src') el.classList.add('src-only');
        else if (viewMode === 'prv') el.classList.add('prv-only');
        sb.textContent = viewMode === 'src' ? '📝 Source' : viewMode === 'prv' ? '👁 Preview' : '◫ Split';
    }
}

function toggleViewMode() {
    var el = document.getElementById('editor-container');
    el.classList.remove('src-only', 'prv-only');
    if (viewMode === 'split') {
        viewMode = 'src';
        el.classList.add('src-only');
        document.getElementById('split-btn').textContent = '📝 Source';
    } else if (viewMode === 'src') {
        viewMode = 'prv';
        el.classList.add('prv-only');
        document.getElementById('split-btn').textContent = '👁 Preview';
    } else {
        viewMode = 'split';
        document.getElementById('split-btn').textContent = '◫ Split';
    }
    if (!isWysiwyg) editor.focus();
}

document.addEventListener('keydown', function(e) {
    if ((e.ctrlKey || e.metaKey) && e.key === 's') {
        e.preventDefault();
        saveCurrentFile();
    }
});

initEditor();
loadFileList();
</script>
</body>
</html>"""


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"  [{self.command}] {args[0]} -> {args[1]} {args[2]}")

    def do_GET(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path == '/':
            self._serve_html()
        elif path == '/api/files':
            self._list_files()
        elif path == '/api/file':
            self._get_file(parsed.query)
        else:
            self._serve_static(path)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length)

        if path == '/api/file':
            self._save_file(body)
        elif path == '/api/upload':
            self._upload_image(body)
        else:
            self._json({'error': 'Not found'}, 404)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path == '/api/file':
            self._delete_file(parsed.query)
        else:
            self._json({'error': 'Not found'}, 404)

    def _safe_resolve(self, rel_path):
        resolved = (BASE_DIR / rel_path).resolve()
        try:
            resolved.relative_to(BASE_DIR)
        except ValueError:
            return None
        return resolved

    def _serve_html(self):
        data = HTML.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', len(data))
        self.end_headers()
        self.wfile.write(data)

    def _list_files(self):
        files = []
        for p in BASE_DIR.iterdir():
            if p.is_file() and p.suffix.lower() == '.md':
                files.append({
                    'name': p.name,
                    'size': p.stat().st_size,
                    'mtime': p.stat().st_mtime
                })
        files.sort(key=lambda f: f['name'].lower())
        self._json(files)

    def _get_file(self, query_string):
        params = parse_qs(query_string)
        name = params.get('name', [None])[0]
        if not name:
            return self._json({'error': 'Missing name'}, 400)
        if '..' in name or '/' in name or '\\' in name:
            return self._json({'error': 'Invalid filename'}, 400)

        filepath = BASE_DIR / name
        filepath = filepath.resolve()
        try:
            filepath.relative_to(BASE_DIR)
        except ValueError:
            return self._json({'error': 'Access denied'}, 403)
        if not filepath.exists() or not filepath.is_file():
            return self._json({'error': 'File not found'}, 404)
        if filepath.suffix.lower() != '.md':
            return self._json({'error': 'Not a markdown file'}, 400)

        content = filepath.read_text(encoding='utf-8', errors='ignore')
        self._json({'name': name, 'content': content})

    def _save_file(self, body):
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return self._json({'error': 'Invalid JSON'}, 400)

        name = data.get('name', '')
        content = data.get('content', '')
        if not name:
            return self._json({'error': 'Missing name'}, 400)
        if not name.lower().endswith('.md'):
            return self._json({'error': 'Must be .md file'}, 400)
        if '..' in name or '/' in name or '\\' in name:
            return self._json({'error': 'Invalid filename'}, 400)

        filepath = BASE_DIR / name
        filepath.write_text(content, encoding='utf-8')
        self._json({'ok': True, 'name': name})

    def _delete_file(self, query_string):
        params = parse_qs(query_string)
        name = params.get('name', [None])[0]
        if not name:
            return self._json({'error': 'Missing name'}, 400)
        if '..' in name or '/' in name or '\\' in name:
            return self._json({'error': 'Invalid filename'}, 400)

        filepath = BASE_DIR / name
        filepath = filepath.resolve()
        try:
            filepath.relative_to(BASE_DIR)
        except ValueError:
            return self._json({'error': 'Access denied'}, 403)
        if not filepath.exists():
            return self._json({'error': 'File not found'}, 404)
        if filepath.suffix.lower() != '.md':
            return self._json({'error': 'Not a markdown file'}, 400)

        filepath.unlink()
        self._json({'ok': True})

    def _upload_image(self, body):
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return self._json({'error': 'Invalid JSON'}, 400)

        img_b64 = data.get('data', '')
        if not img_b64 or ',' not in img_b64:
            return self._json({'error': 'Invalid image data'}, 400)

        try:
            header, encoded = img_b64.split(',', 1)
            ext = 'png'
            m = re.search(r'image/(\w+)', header)
            if m:
                ext = m.group(1)
                if ext == 'jpeg':
                    ext = 'jpg'
                if ext not in ('png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'svg+xml'):
                    ext = 'png'
                if ext == 'svg+xml':
                    ext = 'svg'

            raw = base64.b64decode(encoded)
            filename = f"{uuid.uuid4().hex[:8]}.{ext}"
            filepath = BASE_DIR / filename
            while filepath.exists():
                filename = f"{uuid.uuid4().hex[:8]}.{ext}"
                filepath = BASE_DIR / filename
            filepath.write_bytes(raw)
            self._json({'url': f'/{filename}'})
        except Exception as e:
            self._json({'error': str(e)}, 500)

    def _serve_static(self, path):
        rel = path.lstrip('/')
        if not rel:
            return self._json({'error': 'Not found'}, 404)

        filepath = BASE_DIR / rel
        filepath = filepath.resolve()
        try:
            filepath.relative_to(BASE_DIR)
        except ValueError:
            return self._json({'error': 'Access denied'}, 403)
        if not filepath.exists() or not filepath.is_file():
            return self._json({'error': 'Not found'}, 404)

        ext = filepath.suffix.lower()
        if ext not in IMAGE_EXTS and ext not in TEXT_EXTS:
            return self._json({'error': 'Forbidden'}, 403)

        ct = mimetypes.guess_type(str(filepath))[0] or 'application/octet-stream'
        size = filepath.stat().st_size
        self.send_response(200)
        self.send_header('Content-Type', ct)
        self.send_header('Content-Length', size)
        self.end_headers()
        self.wfile.write(filepath.read_bytes())

    def _json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)


def main():
    from socketserver import ThreadingMixIn

    class ThreadedServer(ThreadingMixIn, http.server.HTTPServer):
        daemon_threads = True

    server = ThreadedServer((HOST, PORT), Handler)
    print(f"""
╔══════════════════════════════════════════════════╗
║         Markdown Editor Server                  ║
║                                                  ║
║   Open: http://{HOST}:{PORT}                      ║
║   Dir:  {BASE_DIR}
║                                                  ║
║   Press Ctrl+C to stop                           ║
╚══════════════════════════════════════════════════╝
""")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


if __name__ == '__main__':
    main()
