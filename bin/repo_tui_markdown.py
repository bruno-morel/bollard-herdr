"""Glow presentation, parsed into safe curses spans (never terminal escape output)."""
from functools import lru_cache
import os
from pathlib import Path
import re
import shutil
import subprocess as sp
import unicodedata

MARKDOWN = {'.md', '.markdown', '.mdown', '.mkd'}
BOLD, DIM, ITALIC, UNDERLINE, STRIKE = 1, 2, 4, 8, 16
ESCAPE = re.compile(r'\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[[0-?]*[ -/]*[@-~]|\x1b[@-_]')
SGR = re.compile(r'\x1b\[([0-9;]*)m')

def plain(text):
    text = ESCAPE.sub('', text)
    return ''.join(c for c in text if c in '\n\t' or (c >= ' ' and not '\x7f' <= c <= '\x9f' and c not in '\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069'))

def cells(text):
    return sum(0 if unicodedata.combining(c) else 2 if unicodedata.east_asian_width(c) in 'WF' else 1 for c in text)

def spans(ansi, width):
    """Keep only text and a small SGR style set; wrap every cell without clipping."""
    lines = [[]]; used = 0; flags = color = 0
    def add(text):
        nonlocal used
        for c in plain(text).expandtabs(4):
            if c == '\n':
                lines.append([]); used = 0; continue
            size = cells(c)
            if used + size > width:
                lines.append([]); used = 0
            line = lines[-1]
            if line and line[-1][1:] == (flags, color):
                line[-1] = (line[-1][0]+c, flags, color)
            else: line.append((c, flags, color))
            used += size
    position = 0
    for match in SGR.finditer(ansi):
        add(ansi[position:match.start()]); position = match.end()
        codes = [int(n or 0) for n in match[1].split(';')]; i = 0
        while i < len(codes):
            code = codes[i]; i += 1
            if code == 0: flags = color = 0
            elif code in (1, 2, 3, 4, 9): flags |= {1:BOLD,2:DIM,3:ITALIC,4:UNDERLINE,9:STRIKE}[code]
            elif code in (22,23,24,29): flags &= ~{22:BOLD|DIM,23:ITALIC,24:UNDERLINE,29:STRIKE}[code]
            elif code == 39: color = 0
            elif 30 <= code <= 37: color = {31:4,32:2,33:3,34:1,35:1,36:1}.get(code,0)
            elif code in (38,48):
                if i < len(codes) and codes[i] == 5 and i+1 < len(codes):
                    if code == 38: color = {1:4,2:2,3:3,4:1,5:1,6:1}.get(codes[i+1],0)
                    i += 2
                elif i < len(codes) and codes[i] == 2: i += 4
    add(ansi[position:])
    # Glow pads block lines to the requested width. Do not spend phone rows on
    # that padding or on leading/trailing blank rows.
    for line in lines:
        while line and not line[-1][0].rstrip(): line.pop()
        if line: line[-1] = (line[-1][0].rstrip(), *line[-1][1:])
    while lines and not lines[0]: lines.pop(0)
    while lines and not lines[-1]: lines.pop()
    return lines or [[]]

def glow_binary():
    found = shutil.which('glow')
    if found: return found
    for p in ('/opt/homebrew/bin/glow','/usr/local/bin/glow'):
        if os.access(p, os.X_OK): return p
    raise RuntimeError('Install the Markdown renderer: brew install glow')

@lru_cache(maxsize=3)
def render(text, width):
    width = max(12, int(width))
    env = dict(os.environ, TERM='xterm-256color', CLICOLOR_FORCE='1',
               GLOW_CONFIG_HOME=str(Path(__file__).with_name('repo-tui-markdown')),
               GLOW_PAGER='false', GLOW_TUI='false', GLOW_DEBUG='false',
               GLAMOUR_STYLE=str(Path(__file__).with_name('repo-tui-markdown.json')))
    env.pop('NO_COLOR', None); env.pop('COLORTERM', None)
    result = sp.run([glow_binary(),'-s',env['GLAMOUR_STYLE'],'-w',str(width),'-'],
                    input=plain(text), capture_output=True, text=True, env=env, timeout=12)
    if result.returncode: raise RuntimeError((plain(result.stderr).strip() or 'Markdown formatting failed').splitlines()[0][:300])
    return spans(result.stdout, width)


def file_links(text, current):
    """Local Markdown links, resolved relative to the document, within checkout."""
    import posixpath
    from urllib.parse import unquote, urlsplit
    # Code examples are not navigation targets.
    text = re.sub(r'(?ms)^\s*(`{3,}|~{3,}).*?^\s*\1\s*$', '', text)
    text = re.sub(r'`[^`\n]*`', '', text)
    refs = {m[1].strip().lower(): m[2] for m in re.finditer(r'(?m)^ {0,3}\[([^]]+)\]:\s*<?([^\s>]+)>?', text)}
    found = []
    pattern = r'(?<!!)\[([^]\n]+)\](?:\(\s*(<[^>]+>|[^\s)]+)(?:\s+[^)]*)?\)|\[([^]]*)\])'
    for m in re.finditer(pattern, text):
        target = m[2] or refs.get((m[3] or m[1]).strip().lower())
        if not target: continue
        target = target.strip('<>')
        try: url = urlsplit(target)
        except ValueError: continue
        if url.scheme or url.netloc or url.query: continue
        path = unquote(url.path)
        if path.startswith('/') or '\\' in path or any(ord(c)<32 for c in path): continue
        path = posixpath.normpath(posixpath.join(posixpath.dirname(current), path)) if path else current
        if path == '..' or path.startswith('../'): continue
        item = (m[1], path, unquote(url.fragment))
        if item not in found: found.append(item)
    return found
