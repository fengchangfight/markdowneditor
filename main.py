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
import shutil
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

# In-memory content cache: relpath -> (mtime, content)
_CONTENT_CACHE = {}

# Search index
_INDEX = None  # {word: set(path)}
_INDEX_MTIMES = {}  # {path: mtime}
_INDEX_DIRTY = True
_INDEX_FILE = BASE_DIR / ".mdeditor_index.json"

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
<link rel="icon" type="image/png" href="{FAVICON}">
<link rel="stylesheet" href="https://uicdn.toast.com/editor/latest/toastui-editor.min.css">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/themes/prism.min.css">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;display:flex;height:100vh;overflow:hidden}
#sidebar{width:260px;min-width:260px;background:#f7f8fa;border-right:1px solid #e0e0e0;display:flex;flex-direction:column}
#sidebar-header{padding:12px;border-bottom:1px solid #e0e0e0}
#sidebar-header h2{font-size:15px;margin-bottom:8px;color:#333}
#sidebar-header .hdr-actions{display:flex;gap:4px;margin-top:6px}
#sidebar-header .hdr-actions button{flex:1;padding:5px;font-size:11px;background:#4a90d9;color:#fff;border:none;border-radius:4px;cursor:pointer}
#sidebar-header .hdr-actions button:hover{background:#357abd}
#tree-container{flex:1;overflow-y:auto;padding:4px 0}
.tree-dir{padding:5px 8px;cursor:pointer;display:flex;align-items:center;gap:2px;font-size:13px;color:#555;user-select:none}
.tree-dir:hover{background:#eef1f5}
.tree-dir .arrow{font-size:9px;width:10px;text-align:center;display:inline-block;transition:transform .15s}
.tree-dir.open>.arrow{transform:rotate(90deg)}
.tree-dir .dname{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.tree-dir .dact{display:none;gap:1px;margin-left:2px}
.tree-dir:hover>.dact{display:flex}
.tree-dir .dact button{background:none;border:none;cursor:pointer;font-size:10px;padding:0 3px;color:#aaa}
.tree-dir .dact button:hover{color:#333}
.tree-dir.drag-over{background:#d4e6f9;outline:2px dashed #4a90d9}
.file-item.drag-over{background:#d4e6f9}
.file-item{padding:5px 8px 5px 30px;cursor:pointer;font-size:13px;color:#555;border-left:3px solid transparent;display:flex;align-items:center;gap:4px}
.file-item:hover{background:#eef1f5}
.file-item.active{background:#e3edf7;border-left-color:#4a90d9;color:#222;font-weight:500}
.file-item .fname{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.file-item .del-btn{visibility:hidden;background:none;border:none;color:#c0392b;cursor:pointer;font-size:14px;padding:0 4px}
.file-item:hover .del-btn{visibility:visible}
.file-item .del-btn:hover{color:#e74c3c}
.file-item .ren-btn{visibility:hidden;background:none;border:none;color:#888;cursor:pointer;font-size:14px;padding:0 4px}
.file-item:hover .ren-btn{visibility:visible}
.file-item .ren-btn:hover{color:#333}
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
#search-box{width:100%;padding:6px 8px;border:1px solid #ddd;border-radius:4px;font-size:13px;outline:none;margin-bottom:6px}
#search-box:focus{border-color:#4a90d9}
</style>
</head>
<body>
<div id="sidebar">
  <div id="sidebar-header">
    <h2>📝 Files</h2>
    <input id="search-box" type="text" placeholder="Search..." oninput="onSearch()">
    <div class="hdr-actions">
      <button onclick="createFile('')">+ File</button>
      <button onclick="createDir('')">+ Dir</button>
    </div>
  </div>
  <div id="tree-container"></div>
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
var allTreeData = [];
var isWysiwyg = false;
var viewMode = 'split';
var autoSaveTimer = null;
var savedViewMode = 'split';

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
                    var dir = currentFile ? currentFile.substring(0, currentFile.lastIndexOf('/') + 1) : '';
                    fetch('/api/upload', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({data: e.target.result, dir: dir})
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

function loadTree() {
    fetch('/api/tree').then(function(r){return r.json()}).then(function(tree){
        allTreeData = tree;
        renderTreeView();
    });
}

function renderTreeView() {
    var expanded = [];
    var dirs = document.querySelectorAll('.tree-dir.open');
    for (var i = 0; i < dirs.length; i++) {
        expanded.push(dirs[i].getAttribute('data-path'));
    }
    document.getElementById('tree-container').innerHTML = buildTreeHTML(allTreeData);
    if (expanded.length > 0) {
        dirs = document.querySelectorAll('.tree-dir');
        for (var i = 0; i < dirs.length; i++) {
            if (expanded.indexOf(dirs[i].getAttribute('data-path')) >= 0) {
                dirs[i].classList.add('open');
                var c = dirs[i].nextElementSibling;
                if (c && c.classList.contains('tree-children')) {
                    c.style.display = 'block';
                }
            }
        }
    }
}

function buildTreeHTML(nodes, depth) {
    if (!depth) depth = 0;
    var html = '';
    for (var i = 0; i < nodes.length; i++) {
        var n = nodes[i];
        if (n.type === 'dir') {
            html += '<div class="tree-dir" data-path="' + esc(n.path) + '" style="padding-left:' + (8 + depth * 14) + 'px" onclick="toggleDir(this)" draggable="true" ondragstart="dragStart(event,\'dir\',\'' + esc(n.path) + '\')" ondragend="dragEnd(event)" ondragover="dragOver(event)" ondragleave="dragLeave(event)" ondrop="dropOnDir(event,\'' + esc(n.path) + '\')">';
            html += '<span class="arrow">▶</span>';
            html += '<span class="dname">📁 ' + esc(n.name) + '</span>';
            html += '<span class="dact">';
            html += '<button title="Rename" onclick="event.stopPropagation();startRename(this,\'dir\',\'' + esc(n.path) + '\')">✏</button>';
            html += '<button title="New File" onclick="event.stopPropagation();createFile(\'' + esc(n.path) + '\')">+📄</button>';
            html += '<button title="New Dir" onclick="event.stopPropagation();createDir(\'' + esc(n.path) + '\')">+📁</button>';
            html += '<button title="Delete" onclick="event.stopPropagation();deleteDir(\'' + esc(n.path) + '\')">×</button>';
            html += '</span></div>';
            html += '<div class="tree-children" style="display:none">';
            html += buildTreeHTML(n.children, depth + 1);
            html += '</div>';
        } else {
            var cls = (currentFile === n.path) ? ' file-item active' : ' file-item';
            html += '<div class="' + cls + '" style="padding-left:' + (26 + depth * 14) + 'px" onclick="openFile(\'' + esc(n.path) + '\')" draggable="true" ondragstart="dragStart(event,\'file\',\'' + esc(n.path) + '\')" ondragend="dragEnd(event)">';
            html += '📄 <span class="fname">' + esc(n.name) + '</span>';
            html += '<button class="ren-btn" onclick="event.stopPropagation();startRename(this,\'file\',\'' + esc(n.path) + '\')">✏</button>';
            html += '<button class="del-btn" onclick="event.stopPropagation();delFile(\'' + esc(n.path) + '\')">×</button>';
            html += '</div>';
        }
    }
    return html;
}

function toggleDir(el) {
    el.classList.toggle('open');
    var c = el.nextElementSibling;
    if (c && c.classList.contains('tree-children')) {
        c.style.display = c.style.display === 'none' ? 'block' : 'none';
    }
}

function esc(s) {
    return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

function openFile(path) {
    clearTimeout(autoSaveTimer);
    fetch('/api/file?path=' + encodeURIComponent(path)).then(function(r){
        if (!r.ok) throw new Error('not found');
        return r.json();
    }).then(function(data){
        currentFile = data.path;
        editor.setMarkdown(data.content);
        document.getElementById('current-file').textContent = currentFile;
        document.getElementById('save-status').textContent = '';
        document.getElementById('del-btn').style.display = '';
        renderTreeView();
    }).catch(function(){
        alert('Failed to open: ' + path);
    });
}

function saveCurrentFile() {
    if (!currentFile) { alert('No file selected'); return; }
    clearTimeout(autoSaveTimer);
    doSave(currentFile, editor.getMarkdown(), true);
}

function doSave(path, content, showAlert) {
    var st = document.getElementById('save-status');
    fetch('/api/file', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({path: path, content: content})
    }).then(function(r){ return r.json() }).then(function(){
        if (showAlert) {
            st.textContent = '✓ Saved';
            st.style.color = '#27ae60';
            setTimeout(function(){ st.textContent = ''; }, 2000);
        } else {
            st.textContent = '✓';
            st.style.color = '#27ae60';
            setTimeout(function(){ st.textContent = ''; }, 1500);
        }
    }).catch(function(){
        if (showAlert) alert('Failed to save');
        else { st.textContent = '✗'; st.style.color = '#e74c3c'; }
    });
}

function deleteCurrentFile() {
    if (!currentFile) return;
    delFile(currentFile);
}

function delFile(path) {
    if (!confirm('Delete "' + path + '"?')) return;
    fetch('/api/file?path=' + encodeURIComponent(path), { method: 'DELETE' }).then(function(r){
        if (r.ok) {
            if (currentFile === path) {
                currentFile = null;
                editor.setMarkdown('');
                document.getElementById('current-file').textContent = 'No file selected';
                document.getElementById('del-btn').style.display = 'none';
            }
            loadTree();
        } else {
            r.json().then(function(d){ alert(d.error); });
        }
    });
}

function createFile(parentPath) {
    var name = prompt('Enter filename:', 'new-note.md');
    if (!name) return;
    if (!/\.md$/i.test(name)) name += '.md';
    var fullPath = parentPath ? parentPath + '/' + name : name;
    var title = name.replace(/\.md$/i, '');
    var content = '# ' + title + '\n\n';
    fetch('/api/file', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({path: fullPath, content: content})
    }).then(function(r){
        if (r.ok) { loadTree(); openFile(fullPath); }
        else { r.json().then(function(d){ alert(d.error); }); }
    });
}

function createDir(parentPath) {
    var name = prompt('Enter directory name:');
    if (!name) return;
    var fullPath = parentPath ? parentPath + '/' + name : name;
    fetch('/api/dir', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({path: fullPath})
    }).then(function(r){
        if (r.ok) { loadTree(); }
        else { r.json().then(function(d){ alert(d.error); }); }
    });
}

function deleteDir(path) {
    if (!confirm('Delete directory "' + path + '" and ALL its contents?')) return;
    fetch('/api/dir?path=' + encodeURIComponent(path), { method: 'DELETE' }).then(function(r){
        if (r.ok) {
            if (currentFile && currentFile.indexOf(path + '/') === 0) {
                currentFile = null;
                editor.setMarkdown('');
                document.getElementById('current-file').textContent = 'No file selected';
                document.getElementById('del-btn').style.display = 'none';
            }
            loadTree();
        } else {
            r.json().then(function(d){ alert(d.error); });
        }
    });
}

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
    doSave(currentFile, editor.getMarkdown(), false);
}

function logout() {
    fetch('/api/logout', { method: 'POST' }).then(function(){
        location.href = '/';
    });
}

var dragInfo = null;

function dragStart(e, type, path) {
    dragInfo = {type: type, path: path};
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', path);
    e.currentTarget.style.opacity = '0.4';
}

function dragEnd(e) {
    e.currentTarget.style.opacity = '1';
    var all = document.querySelectorAll('.drag-over');
    for (var i = 0; i < all.length; i++) all[i].classList.remove('drag-over');
    dragInfo = null;
}

function dragOver(e) {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    e.currentTarget.classList.add('drag-over');
}

function dragLeave(e) {
    e.currentTarget.classList.remove('drag-over');
}

function dropOnDir(e, targetDir) {
    e.preventDefault();
    e.currentTarget.classList.remove('drag-over');
    if (!dragInfo) return;
    if (dragInfo.path === targetDir) return;
    if (dragInfo.type === 'dir' && (dragInfo.path === targetDir || targetDir.indexOf(dragInfo.path + '/') === 0)) return;
    fetch('/api/move', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({from: dragInfo.path, to: targetDir})
    }).then(function(r){ return r.json() }).then(function(d){
        if (d.ok) {
            if (currentFile && currentFile === dragInfo.path) {
                currentFile = d.to;
                document.getElementById('current-file').textContent = currentFile;
            }
            loadTree();
        } else { alert(d.error); }
    });
    dragInfo = null;
}

function startRename(btn, type, path) {
    var item = btn.parentElement;
    while (item && !item.classList.contains('tree-dir') && !item.classList.contains('file-item')) {
        item = item.parentElement;
    }
    if (!item) return;
    var nameSpan = item.querySelector('.dname') || item.querySelector('.fname');
    if (!nameSpan) return;
    var oldName = path.split('/').pop();
    var input = document.createElement('input');
    input.type = 'text';
    input.value = type === 'file' ? oldName.replace(/\.md$/i, '') : oldName;
    input.style.cssText = 'width:100%;border:1px solid #4a90d9;outline:none;font-size:13px;padding:1px 4px;border-radius:2px;background:#fff';
    nameSpan.style.display = 'none';
    nameSpan.parentNode.insertBefore(input, nameSpan);
    input.focus();
    input.select();
    var done = false;
    function finish() {
        if (done) return;
        done = true;
        nameSpan.style.display = '';
        input.remove();
    }
    function submit() {
        var newName = input.value.trim();
        if (!newName || newName === (type === 'file' ? oldName.replace(/\.md$/i, '') : oldName)) {
            finish();
            return;
        }
        if (type === 'file' && !/\.md$/i.test(newName)) newName += '.md';
        finish();
        doRename(path, newName);
    }
    input.addEventListener('blur', function() { setTimeout(finish, 100); });
    input.addEventListener('keydown', function(e) {
        if (e.key === 'Enter') { e.preventDefault(); submit(); }
        else if (e.key === 'Escape') { finish(); }
    });
}

function doRename(oldPath, newName) {
    fetch('/api/rename', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({from: oldPath, name: newName})
    }).then(function(r){ return r.json() }).then(function(d){
        if (d.ok) {
            if (currentFile === oldPath) {
                currentFile = d.to;
                document.getElementById('current-file').textContent = currentFile;
            }
            loadTree();
        } else { alert(d.error); }
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
    if (!q) { renderTreeView(); return; }
    fetch('/api/search?q=' + encodeURIComponent(q)).then(function(r){return r.json()}).then(function(r){
        renderSearchResults(r, q);
    });
}

function renderSearchResults(results, q) {
    var el = document.getElementById('tree-container');
    if (results.length === 0) {
        el.innerHTML = '<div style="padding:12px;color:#999;font-size:13px">No results</div>';
        return;
    }
    var html = '';
    for (var i = 0; i < results.length; i++) {
        var r = results[i];
        html += '<div class="file-item" style="padding:5px 8px 5px 12px" onclick="openFile(\'' + esc(r.path) + '\')">' +
            '<span style="opacity:.5">📄</span>' +
            '<div style="flex:1;min-width:0">' +
            '<div style="font-size:13px">' + hl(r.path, q) + '</div>' +
            (r.snippet ? '<div style="font-size:11px;color:#999;margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + esc(r.snippet) + '</div>' : '') +
            '</div>' +
        '</div>';
    }
    el.innerHTML = html;
}

function hl(text, q) {
    var s = esc(text);
    var re = new RegExp('(' + q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')', 'gi');
    return s.replace(re, '<mark style="background:#fff3b0;padding:0 2px">$1</mark>');
}

initEditor();
loadTree();
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
_FAVICON_DATA_URI = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAAAAXNSR0IArs4c6QAAAVlJREFUWEftljFKBEEQRf+rgRcQBBEMDAwEEW/AyAsIgpGxoIGRJ5hLeAQjA+MJDPQGYiAiiJggGPgDQU0ErSaDZJbqbff0TI9Id0HTPV39XnV1dVcye96DWnQBSnZR4PAD/T/5jR94AZ4s5OtvC5j5AtgtSu5HAEOYFaTf7wMYc78jiPg5ioBWBVAE9KwL0BUIdQLfni7dLYDpBND7b8b5QwBduklg2oJQBbQ1IcIvQnDH9JlyZROACB1zWj3/coCbjAEMNl0CXHBP4s8qwNkOYMk8Qh8D0nv1DcC5tw8FEYjs9v7Tw78dIQSYkUeB0IXgSjC1WNAAEbYQ7GcYvwwgylr5/sRQ7PkHgNucB0SOsoMA96IePxR/LYBYE8GCCT0Hz6ysX7AxHsCbCbM60odZCF9Bo9d8u54IAOdjqAjjB5oADswF+r8LLBAvIMTHjOGXy8l7AE5KzN8FqzO/AWRG8AnBikFkAAAAAElFTkSuQmCC"

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
        elif path == "/api/tree":
            self._tree()
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
        elif path == "/api/dir":
            self._make_dir(body)
        elif path == "/api/upload":
            self._upload_image(body)
        elif path == "/api/move":
            self._move(body)
        elif path == "/api/rename":
            self._rename(body)
        else:
            self._json({"error": "Not found"}, 404)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if not self._check_auth():
            self._json({"error": "Unauthorized"}, 401)
        elif path == "/api/file":
            self._delete_file(parsed.query)
        elif path == "/api/dir":
            self._remove_dir(parsed.query)
        else:
            self._json({"error": "Not found"}, 404)

    def _safe_resolve(self, rel_path):
        rel_path = rel_path.replace("\\", "/")
        parts = [p for p in rel_path.split("/") if p and p != ".."]
        if not parts:
            return BASE_DIR
        resolved = BASE_DIR
        for part in parts:
            resolved = (resolved / part).resolve()
            try:
                resolved.relative_to(BASE_DIR)
            except ValueError:
                return None
        return resolved

    def _read_cached(self, filepath, relpath):
        mtime = filepath.stat().st_mtime
        if relpath in _CONTENT_CACHE:
            cmtime, content = _CONTENT_CACHE[relpath]
            if cmtime == mtime:
                return content
        content = filepath.read_text(encoding="utf-8", errors="ignore")
        _CONTENT_CACHE[relpath] = (mtime, content)
        return content

    def _mark_index_dirty(self):
        global _INDEX_DIRTY
        _INDEX_DIRTY = True

    def _ensure_index(self):
        global _INDEX, _INDEX_MTIMES, _INDEX_DIRTY
        if not _INDEX_DIRTY and _INDEX is not None:
            return
        if not _INDEX_DIRTY and _INDEX_FILE.exists():
            try:
                data = json.loads(_INDEX_FILE.read_text(encoding="utf-8"))
                _INDEX = {k: set(v) for k, v in data.get("index", {}).items()}
                _INDEX_MTIMES = data.get("mtimes", {})
                _INDEX_DIRTY = False
                return
            except Exception:
                pass
        self._build_index()

    def _build_index(self):
        global _INDEX, _INDEX_MTIMES, _INDEX_DIRTY
        _INDEX = {}
        _INDEX_MTIMES = {}
        for p in BASE_DIR.rglob("*.md"):
            rel = str(p.relative_to(BASE_DIR)).replace("\\", "/")
            try:
                _INDEX_MTIMES[rel] = p.stat().st_mtime
                text = (rel + " " + p.read_text(encoding="utf-8", errors="ignore")).lower()
                words = set(re.findall(r"[\u4e00-\u9fff\w]{2,}", text))
                for w in words:
                    _INDEX.setdefault(w, set()).add(rel)
            except Exception:
                pass
        _INDEX_DIRTY = False
        try:
            data = {
                "mtimes": _INDEX_MTIMES,
                "index": {k: list(v) for k, v in _INDEX.items()},
            }
            _INDEX_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    def _build_tree(self, base_path=None, rel_prefix=""):
        if base_path is None:
            base_path = BASE_DIR
        result = []
        try:
            entries = sorted(
                base_path.iterdir(),
                key=lambda p: (not p.is_dir(), p.name.lower()),
            )
        except OSError:
            return result

        for entry in entries:
            if entry.name.startswith("."):
                continue
            rel = (
                (rel_prefix + "/" + entry.name).lstrip("/")
                if rel_prefix
                else entry.name
            )
            rel = rel.replace("\\", "/")

            if entry.is_dir():
                children = self._build_tree(entry, rel)
                result.append(
                    {
                        "name": entry.name,
                        "path": rel,
                        "type": "dir",
                        "children": children,
                    }
                )
            elif entry.suffix.lower() == ".md":
                result.append(
                    {"name": entry.name, "path": rel, "type": "file"}
                )
        return result

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

    def _tree(self):
        tree = self._build_tree()
        self._json(tree)

    def _list_files(self):
        files = []
        for p in BASE_DIR.rglob("*.md"):
            rel = str(p.relative_to(BASE_DIR)).replace("\\", "/")
            files.append(
                {
                    "name": p.name,
                    "path": rel,
                    "size": p.stat().st_size,
                    "mtime": p.stat().st_mtime,
                }
            )
        files.sort(key=lambda f: f["path"].lower())
        self._json(files)

    def _search_files(self, query_string):
        params = parse_qs(query_string)
        q = params.get("q", [""])[0].strip()
        if not q:
            return self._json([])

        q_lower = q.lower()
        self._ensure_index()

        results = []
        seen = set()

        def _snippet(content, idx, q_len):
            s = max(0, idx - 40)
            e = min(len(content), idx + q_len + 40)
            snip = content[s:e].replace("\n", " ")
            if s > 0:
                snip = "..." + snip
            if e < len(content):
                snip = snip + "..."
            return snip

        # Word-indexed search
        terms = re.findall(r"[\u4e00-\u9fff\w]{2,}", q_lower)
        if terms and _INDEX:
            candidates = None
            for t in terms:
                files = _INDEX.get(t, set())
                candidates = files if candidates is None else candidates & files
                if not candidates:
                    break
            if candidates:
                for rel in candidates:
                    filepath = BASE_DIR / rel
                    try:
                        content = self._read_cached(filepath, rel)
                        idx = content.lower().find(q_lower)
                        if idx >= 0:
                            results.append({
                                "path": rel,
                                "name": filepath.name,
                                "snippet": _snippet(content, idx, len(q)),
                            })
                            seen.add(rel)
                    except Exception:
                        pass

        # Fallback: full scan for queries without word hits
        if not seen and (not terms or not _INDEX):
            for p in BASE_DIR.rglob("*.md"):
                rel = str(p.relative_to(BASE_DIR)).replace("\\", "/")
                try:
                    content = self._read_cached(p, rel)
                    idx = content.lower().find(q_lower)
                    if idx >= 0:
                        results.append({
                            "path": rel,
                            "name": p.name,
                            "snippet": _snippet(content, idx, len(q)),
                        })
                        seen.add(rel)
                except Exception:
                    pass

        # Filename / path match fallback
        for p in BASE_DIR.rglob("*.md"):
            rel = str(p.relative_to(BASE_DIR)).replace("\\", "/")
            if q_lower in rel.lower() and rel not in seen:
                results.append({"path": rel, "name": p.name, "snippet": ""})

        results.sort(key=lambda r: r["path"].lower())
        self._json(results)

    def _get_file(self, query_string):
        params = parse_qs(query_string)
        filepath_str = params.get("path", [None])[0]
        if not filepath_str:
            return self._json({"error": "Missing path"}, 400)

        filepath = self._safe_resolve(filepath_str)
        if not filepath or not filepath.exists() or not filepath.is_file():
            return self._json({"error": "File not found"}, 404)
        if filepath.suffix.lower() != ".md":
            return self._json({"error": "Not a markdown file"}, 400)

        rel = str(filepath.relative_to(BASE_DIR)).replace("\\", "/")
        content = self._read_cached(filepath, rel)
        self._json({"path": rel, "name": filepath.name, "content": content})

    def _save_file(self, body):
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return self._json({"error": "Invalid JSON"}, 400)

        filepath_str = data.get("path", "")
        content = data.get("content", "")
        if not filepath_str:
            return self._json({"error": "Missing path"}, 400)
        if not filepath_str.lower().endswith(".md"):
            return self._json({"error": "Must be .md file"}, 400)

        filepath = self._safe_resolve(filepath_str)
        if not filepath:
            return self._json({"error": "Invalid path"}, 400)

        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(content, encoding="utf-8")
        rel = str(filepath.relative_to(BASE_DIR)).replace("\\", "/")
        _CONTENT_CACHE[rel] = (filepath.stat().st_mtime, content)
        self._mark_index_dirty()
        self._json({"ok": True, "path": rel})

    def _delete_file(self, query_string):
        params = parse_qs(query_string)
        filepath_str = params.get("path", [None])[0]
        if not filepath_str:
            return self._json({"error": "Missing path"}, 400)

        filepath = self._safe_resolve(filepath_str)
        if not filepath or not filepath.exists() or not filepath.is_file():
            return self._json({"error": "File not found"}, 404)
        if filepath.suffix.lower() != ".md":
            return self._json({"error": "Not a markdown file"}, 400)

        rel = str(filepath.relative_to(BASE_DIR)).replace("\\", "/")
        filepath.unlink()
        _CONTENT_CACHE.pop(rel, None)
        self._mark_index_dirty()
        self._json({"ok": True})

    def _make_dir(self, body):
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return self._json({"error": "Invalid JSON"}, 400)

        dirpath_str = data.get("path", "")
        if not dirpath_str:
            return self._json({"error": "Missing path"}, 400)

        dirpath = self._safe_resolve(dirpath_str)
        if not dirpath:
            return self._json({"error": "Invalid path"}, 400)
        if dirpath.exists():
            return self._json({"error": "Already exists"}, 409)

        dirpath.mkdir(parents=True, exist_ok=True)
        self._json({"ok": True, "path": dirpath_str})

    def _remove_dir(self, query_string):
        params = parse_qs(query_string)
        dirpath_str = params.get("path", [None])[0]
        if not dirpath_str:
            return self._json({"error": "Missing path"}, 400)

        dirpath = self._safe_resolve(dirpath_str)
        if not dirpath or not dirpath.exists() or not dirpath.is_dir():
            return self._json({"error": "Directory not found"}, 404)
        if dirpath == BASE_DIR:
            return self._json({"error": "Cannot delete root"}, 400)

        # Remove cache entries for files inside this dir
        prefix = dirpath_str.replace("\\", "/") + "/"
        for key in list(_CONTENT_CACHE.keys()):
            if key == dirpath_str or key.startswith(prefix):
                del _CONTENT_CACHE[key]

        # Recursively delete
        import shutil
        shutil.rmtree(str(dirpath))
        self._mark_index_dirty()
        self._json({"ok": True})

    def _move(self, body):
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return self._json({"error": "Invalid JSON"}, 400)
        src = data.get("from", "")
        dst = data.get("to", "")
        if not src:
            return self._json({"error": "Missing from"}, 400)
        src_path = self._safe_resolve(src)
        dst_path = self._safe_resolve(dst) if dst else BASE_DIR
        if not src_path or not src_path.exists():
            return self._json({"error": "Source not found"}, 404)
        if not dst_path or not dst_path.is_dir():
            return self._json({"error": "Destination must be a directory"}, 400)
        if src_path == BASE_DIR:
            return self._json({"error": "Cannot move root"}, 400)
        try:
            dst_path.relative_to(src_path)
            return self._json({"error": "Cannot move into itself"}, 400)
        except ValueError:
            pass
        new_name = data.get("name", "")
        target = dst_path / (new_name if new_name else src_path.name)
        if target.resolve() == src_path.resolve():
            new_path = str(target.relative_to(BASE_DIR)).replace("\\", "/")
            return self._json({"ok": True, "from": src, "to": new_path})
        if target.exists():
            return self._json({"error": "Target already exists"}, 409)
        shutil.move(str(src_path), str(target))
        # Invalidate cache for moved paths
        prefix = src.replace("\\", "/") + "/"
        for k in list(_CONTENT_CACHE.keys()):
            if k == src or k.startswith(prefix):
                del _CONTENT_CACHE[k]
        self._mark_index_dirty()
        new_path = str(target.relative_to(BASE_DIR)).replace("\\", "/")
        self._json({"ok": True, "from": src, "to": new_path})

    def _rename(self, body):
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return self._json({"error": "Invalid JSON"}, 400)
        old = data.get("from", "")
        name = data.get("name", "")
        if not old or not name:
            return self._json({"error": "Missing from/name"}, 400)
        src_path = self._safe_resolve(old)
        if not src_path or not src_path.exists():
            return self._json({"error": "Source not found"}, 404)
        if src_path == BASE_DIR:
            return self._json({"error": "Cannot rename root"}, 400)
        if "/" in name or ".." in name:
            return self._json({"error": "Invalid name"}, 400)
        target = src_path.parent / name
        if target.resolve() == src_path.resolve():
            new_rel = str(target.relative_to(BASE_DIR)).replace("\\", "/")
            return self._json({"ok": True, "from": old, "to": new_rel})
        if target.exists():
            return self._json({"error": "Target already exists"}, 409)
        shutil.move(str(src_path), str(target))
        prefix = old.replace("\\", "/") + "/"
        for k in list(_CONTENT_CACHE.keys()):
            if k == old or k.startswith(prefix):
                del _CONTENT_CACHE[k]
        self._mark_index_dirty()
        new_rel = str(target.relative_to(BASE_DIR)).replace("\\", "/")
        self._json({"ok": True, "from": old, "to": new_rel})

    def _upload_image(self, body):
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return self._json({"error": "Invalid JSON"}, 400)

        img_b64 = data.get("data", "")
        if not img_b64 or "," not in img_b64:
            return self._json({"error": "Invalid image data"}, 400)

        target_dir_str = data.get("dir", "").strip()

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

            if target_dir_str:
                target_dir = self._safe_resolve(target_dir_str)
                if not target_dir:
                    target_dir = BASE_DIR
                target_dir.mkdir(parents=True, exist_ok=True)
            else:
                target_dir = BASE_DIR

            filepath = target_dir / filename
            while filepath.exists():
                filename = f"{uuid.uuid4().hex[:8]}.{ext}"
                filepath = target_dir / filename

            filepath.write_bytes(raw)
            rel = str(filepath.relative_to(BASE_DIR)).replace("\\", "/")
            self._json({"url": f"/{rel}"})
        except Exception as e:
            self._json({"error": str(e)}, 500)

    def _serve_static(self, path):
        rel = path.lstrip("/")
        if not rel:
            return self._json({"error": "Not found"}, 404)

        filepath = self._safe_resolve(rel)
        if not filepath or not filepath.exists() or not filepath.is_file():
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
