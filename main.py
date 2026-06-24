"""
Lightweight Markdown Editor Web Server
Usage: python main.py
Then open http://127.0.0.1:8765
"""

import base64
import http.server
import json
import mimetypes
import os
import re
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

HOST = "127.0.0.1"
PORT = 8765
BASE_DIR = Path(__file__).parent.resolve()

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".ico"}
TEXT_EXTS = {".css", ".js", ".md", ".html", ".txt", ".json", ".xml", ".csv"}

# In-memory content cache: filename -> (mtime, content)
_CONTENT_CACHE = {}

# Auth
USERNAME = os.environ.get("MDEDITOR_USER", "fengchang")
PASSWORD = os.environ.get("MDEDITOR_PASS", "Passw0rd")
SESSIONS = {}  # token -> expiry (timestamp)

HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Markdown Editor</title>
<link rel="icon" type="image/x-icon" href="{FAVICON}">
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
#search-box{width:100%;padding:6px 8px;border:1px solid #ddd;border-radius:4px;font-size:13px;outline:none;margin-bottom:8px}
#search-box:focus{border-color:#4a90d9}
</style>
</head>
<body>
<div id="sidebar">
  <div id="sidebar-header">
    <h2>📝 Markdown Files</h2>
    <input id="search-box" type="text" placeholder="Search title / content..." oninput="onSearch()">
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
    <button onclick="logout()" class="ghost" title="Logout">⏻</button>
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
var autoSaveTimer = null;

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
    editor.on('change', onEditorChange);
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
    clearTimeout(autoSaveTimer);
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
    clearTimeout(autoSaveTimer);
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

function onEditorChange() {
    if (!currentFile) return;
    var st = document.getElementById('save-status');
    st.textContent = '●';
    st.style.color = '#f0ad4e';
    clearTimeout(autoSaveTimer);
    autoSaveTimer = setTimeout(autoSave, 2000);
}

function autoSave() {
    if (!currentFile) return;
    var content = editor.getMarkdown();
    var st = document.getElementById('save-status');
    fetch('/api/file', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name: currentFile, content: content})
    }).then(function(r){ return r.json() }).then(function(){
        st.textContent = '✓';
        st.style.color = '#27ae60';
        setTimeout(function(){ st.textContent = ''; }, 1500);
    }).catch(function(){
        st.textContent = '✗';
        st.style.color = '#e74c3c';
    });
}

function logout() {
    fetch('/api/logout', { method: 'POST' }).then(function(){
        location.href = '/';
    });
}

document.addEventListener('keydown', function(e) {
    if ((e.ctrlKey || e.metaKey) && e.key === 's') {
        e.preventDefault();
        saveCurrentFile();
    }
});

var searchTimer = null;

function onSearch() {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(doSearch, 250);
}

function doSearch() {
    var q = document.getElementById('search-box').value.trim();
    if (!q) { loadFileList(); return; }
    fetch('/api/search?q=' + encodeURIComponent(q)).then(function(r){return r.json()}).then(function(r){
        renderSearchResults(r, q);
    });
}

function renderSearchResults(results, q) {
    var list = document.getElementById('file-list');
    if (results.length === 0) {
        list.innerHTML = '<div style="padding:12px;color:#999;font-size:13px">No results</div>';
        return;
    }
    var html = '';
    for (var i = 0; i < results.length; i++) {
        var r = results[i];
        html += '<div class="file-item" onclick="openFile(\'' + esc(r.name) + '\')">' +
            '<span style="opacity:.5">📄</span>' +
            '<div style="flex:1;min-width:0">' +
            '<div>' + hl(r.name, q) + '</div>' +
            (r.snippet ? '<div style="font-size:11px;color:#999;margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + esc(r.snippet) + '</div>' : '') +
            '</div>' +
        '</div>';
    }
    list.innerHTML = html;
}

function hl(text, q) {
    var s = esc(text);
    var re = new RegExp('(' + q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')', 'gi');
    return s.replace(re, '<mark style="background:#fff3b0;padding:0 2px">$1</mark>');
}

initEditor();
loadFileList();
</script>
</body>
</html>"""

LOGIN_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Login - Markdown Editor</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;background:#f0f2f5}
.card{background:#fff;padding:40px;border-radius:8px;box-shadow:0 2px 12px rgba(0,0,0,0.1);width:360px}
.card h1{font-size:22px;margin-bottom:24px;text-align:center;color:#333}
.card input{width:100%;padding:10px 12px;margin-bottom:12px;border:1px solid #ddd;border-radius:4px;font-size:14px;outline:none}
.card input:focus{border-color:#4a90d9}
.card button{width:100%;padding:10px;background:#4a90d9;color:#fff;border:none;border-radius:4px;font-size:14px;cursor:pointer}
.card button:hover{background:#357abd}
.card .error{color:#e74c3c;font-size:13px;text-align:center;margin-top:8px;display:none}
</style>
</head>
<body>
<div class="card">
  <h1>📝 Markdown Editor</h1>
  <form onsubmit="login(event)">
    <input type="text" id="user" placeholder="Username" autofocus>
    <input type="password" id="pass" placeholder="Password">
    <button type="submit">Login</button>
    <div class="error" id="error">Invalid credentials</div>
  </form>
</div>
<script>
function login(e) {
    e.preventDefault();
    var u = document.getElementById('user').value;
    var p = document.getElementById('pass').value;
    fetch('/api/login', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({username: u, password: p})
    }).then(function(r){ return r.json() }).then(function(d){
        if (d.ok) { location.href = '/'; }
        else { document.getElementById('error').style.display = 'block'; }
    });
}
</script>
</body>
</html>"""

# Favicon data URI (hardcoded base64)
_FAVICON_DATA_URI = 'data:image/x-icon;base64,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'


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"  [{self.command}] {args[0]} -> {args[1]} {args[2]}")

    def do_GET(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path == "/":
            if self._check_auth():
                self._serve_html()
            else:
                self._serve_login_page()
        elif not self._check_auth():
            self._json({"error": "Unauthorized"}, 401)
        elif path == "/api/files":
            self._list_files()
        elif path == "/api/file":
            self._get_file(parsed.query)
        elif path == "/api/search":
            self._search_files(parsed.query)
        else:
            self._serve_static(path)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)

        if path == "/api/login":
            self._login(body)
        elif path == "/api/logout":
            self._logout()
        elif not self._check_auth():
            self._json({"error": "Unauthorized"}, 401)
        elif path == "/api/file":
            self._save_file(body)
        elif path == "/api/upload":
            self._upload_image(body)
        else:
            self._json({"error": "Not found"}, 404)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if not self._check_auth():
            self._json({"error": "Unauthorized"}, 401)
        elif path == "/api/file":
            self._delete_file(parsed.query)
        else:
            self._json({"error": "Not found"}, 404)

    def _safe_resolve(self, rel_path):
        resolved = (BASE_DIR / rel_path).resolve()
        try:
            resolved.relative_to(BASE_DIR)
        except ValueError:
            return None
        return resolved

    def _read_cached(self, filepath):
        name = filepath.name
        mtime = filepath.stat().st_mtime
        if name in _CONTENT_CACHE:
            cmtime, content = _CONTENT_CACHE[name]
            if cmtime == mtime:
                return content
        content = filepath.read_text(encoding="utf-8", errors="ignore")
        _CONTENT_CACHE[name] = (mtime, content)
        return content

    def _check_auth(self):
        cookie = self.headers.get("Cookie", "")
        m = re.search(r"session=([^;]+)", cookie)
        if m and m.group(1) in SESSIONS:
            if SESSIONS[m.group(1)] > time.time():
                return True
            del SESSIONS[m.group(1)]
        return False

    def _serve_login_page(self):
        data = LOGIN_HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", len(data))
        self.end_headers()
        self.wfile.write(data)

    def _login(self, body):
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return self._json({"error": "Invalid JSON"}, 400)
        if data.get("username") == USERNAME and data.get("password") == PASSWORD:
            token = uuid.uuid4().hex
            SESSIONS[token] = time.time() + 86400
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header(
                "Set-Cookie", f"session={token}; Path=/; HttpOnly; SameSite=Lax"
            )
            body_bytes = json.dumps({"ok": True}).encode("utf-8")
            self.send_header("Content-Length", len(body_bytes))
            self.end_headers()
            self.wfile.write(body_bytes)
        else:
            self._json({"error": "Invalid credentials"}, 401)

    def _logout(self):
        cookie = self.headers.get("Cookie", "")
        m = re.search(r"session=([^;]+)", cookie)
        if m:
            SESSIONS.pop(m.group(1), None)
        self._json({"ok": True})

    def _serve_html(self):
        data = HTML.replace("{FAVICON}", _FAVICON_DATA_URI).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", len(data))
        self.end_headers()
        self.wfile.write(data)

    def _list_files(self):
        files = []
        for p in BASE_DIR.iterdir():
            if p.is_file() and p.suffix.lower() == ".md":
                files.append(
                    {
                        "name": p.name,
                        "size": p.stat().st_size,
                        "mtime": p.stat().st_mtime,
                    }
                )
        files.sort(key=lambda f: f["name"].lower())
        self._json(files)

    def _search_files(self, query_string):
        params = parse_qs(query_string)
        q = params.get("q", [""])[0].strip()
        if not q:
            return self._json([])

        results = []
        q_lower = q.lower()
        seen = set()

        for p in BASE_DIR.iterdir():
            if not p.is_file() or p.suffix.lower() != ".md":
                continue
            try:
                content = self._read_cached(p)
                idx = content.lower().find(q_lower)
                if idx >= 0:
                    start = max(0, idx - 40)
                    end = min(len(content), idx + len(q) + 40)
                    snip = content[start:end].replace("\n", " ")
                    if start > 0:
                        snip = "..." + snip
                    if end < len(content):
                        snip = snip + "..."
                    results.append({"name": p.name, "snippet": snip})
                    seen.add(p.name)
            except Exception:
                pass

        # also match by filename
        for p in BASE_DIR.iterdir():
            if not p.is_file() or p.suffix.lower() != ".md":
                continue
            if q_lower in p.name.lower() and p.name not in seen:
                results.append({"name": p.name, "snippet": ""})

        results.sort(key=lambda r: r["name"].lower())
        self._json(results)

    def _get_file(self, query_string):
        params = parse_qs(query_string)
        name = params.get("name", [None])[0]
        if not name:
            return self._json({"error": "Missing name"}, 400)
        if ".." in name or "/" in name or "\\" in name:
            return self._json({"error": "Invalid filename"}, 400)

        filepath = BASE_DIR / name
        filepath = filepath.resolve()
        try:
            filepath.relative_to(BASE_DIR)
        except ValueError:
            return self._json({"error": "Access denied"}, 403)
        if not filepath.exists() or not filepath.is_file():
            return self._json({"error": "File not found"}, 404)
        if filepath.suffix.lower() != ".md":
            return self._json({"error": "Not a markdown file"}, 400)

        content = self._read_cached(filepath)
        self._json({"name": name, "content": content})

    def _save_file(self, body):
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return self._json({"error": "Invalid JSON"}, 400)

        name = data.get("name", "")
        content = data.get("content", "")
        if not name:
            return self._json({"error": "Missing name"}, 400)
        if not name.lower().endswith(".md"):
            return self._json({"error": "Must be .md file"}, 400)
        if ".." in name or "/" in name or "\\" in name:
            return self._json({"error": "Invalid filename"}, 400)

        filepath = BASE_DIR / name
        filepath.write_text(content, encoding="utf-8")
        _CONTENT_CACHE[name] = (filepath.stat().st_mtime, content)
        self._json({"ok": True, "name": name})

    def _delete_file(self, query_string):
        params = parse_qs(query_string)
        name = params.get("name", [None])[0]
        if not name:
            return self._json({"error": "Missing name"}, 400)
        if ".." in name or "/" in name or "\\" in name:
            return self._json({"error": "Invalid filename"}, 400)

        filepath = BASE_DIR / name
        filepath = filepath.resolve()
        try:
            filepath.relative_to(BASE_DIR)
        except ValueError:
            return self._json({"error": "Access denied"}, 403)
        if not filepath.exists():
            return self._json({"error": "File not found"}, 404)
        if filepath.suffix.lower() != ".md":
            return self._json({"error": "Not a markdown file"}, 400)

        filepath.unlink()
        _CONTENT_CACHE.pop(name, None)
        self._json({"ok": True})

    def _upload_image(self, body):
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return self._json({"error": "Invalid JSON"}, 400)

        img_b64 = data.get("data", "")
        if not img_b64 or "," not in img_b64:
            return self._json({"error": "Invalid image data"}, 400)

        try:
            header, encoded = img_b64.split(",", 1)
            ext = "png"
            m = re.search(r"image/(\w+)", header)
            if m:
                ext = m.group(1)
                if ext == "jpeg":
                    ext = "jpg"
                if ext not in ("png", "jpg", "jpeg", "gif", "webp", "bmp", "svg+xml"):
                    ext = "png"
                if ext == "svg+xml":
                    ext = "svg"

            raw = base64.b64decode(encoded)
            filename = f"{uuid.uuid4().hex[:8]}.{ext}"
            filepath = BASE_DIR / filename
            while filepath.exists():
                filename = f"{uuid.uuid4().hex[:8]}.{ext}"
                filepath = BASE_DIR / filename
            filepath.write_bytes(raw)
            self._json({"url": f"/{filename}"})
        except Exception as e:
            self._json({"error": str(e)}, 500)

    def _serve_static(self, path):
        rel = path.lstrip("/")
        if not rel:
            return self._json({"error": "Not found"}, 404)

        filepath = BASE_DIR / rel
        filepath = filepath.resolve()
        try:
            filepath.relative_to(BASE_DIR)
        except ValueError:
            return self._json({"error": "Access denied"}, 403)
        if not filepath.exists() or not filepath.is_file():
            return self._json({"error": "Not found"}, 404)

        ext = filepath.suffix.lower()
        if ext not in IMAGE_EXTS and ext not in TEXT_EXTS:
            return self._json({"error": "Forbidden"}, 403)

        ct = mimetypes.guess_type(str(filepath))[0] or "application/octet-stream"
        size = filepath.stat().st_size
        self.send_response(200)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", size)
        self.end_headers()
        self.wfile.write(filepath.read_bytes())

    def _json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", len(body))
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


if __name__ == "__main__":
    main()
