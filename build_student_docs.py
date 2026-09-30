"""Rebuild offline HTML guides: python -m pip install Markdown==3.9; python build_student_docs.py.

Students open START_HERE.html directly; no package installation or server is needed.
"""
from pathlib import Path
import html
import re

import markdown

ROOT = Path(__file__).resolve().parent
GUIDES = [
    ("LANGSMITH_STUDENT_WORKBOOK", "LangSmith hands-on workbook", "Start learning", "12 practical labs for tracing, debugging, monitoring, feedback, testing, and evaluation. Includes commands, expected results, and troubleshooting."),
    ("LANGSMITH_INTEGRATION_EXPLAINED", "How LangSmith was integrated", "Understand the code", "A simple step-by-step walkthrough of the settings, tracing decorator, model and tool spans, privacy controls, and verification."),
    ("README", "Setup and quick start", "Get ready", "Install the demo, configure your connections, start VoltCart, and verify your first trace."),
    ("APP_GUIDE", "VoltCart application guide", "Explore the app", "Learn the shopping agent, approvals, orders, returns, and the classroom application's features."),
    ("API_GUIDE", "API and Postman guide", "Try the API", "Run authenticated API examples, inspect traces, and experiment with replay and agent workflows."),
]

CSS = """
:root{color-scheme:light;--ink:#182d32;--muted:#53696d;--green:#086851;--line:#dce5e3;--paper:#fff;--canvas:#f3f6f4}
*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:85px}
body{margin:0;background:var(--canvas);color:var(--ink);font:16px/1.75 system-ui,-apple-system,'Segoe UI',sans-serif}
a{color:var(--green);text-underline-offset:3px}a:hover{color:#003f30}a:focus-visible,button:focus-visible,summary:focus-visible{outline:3px solid #e7b84c;outline-offset:4px}
.skip{position:absolute;left:12px;top:-80px;background:white;padding:8px;z-index:20}.skip:focus{top:12px}
.topbar{background:#123b36;color:white;padding:13px 28px;display:flex;align-items:center;justify-content:space-between;gap:16px}
.brand{color:white;text-decoration:none;font-weight:750;letter-spacing:.03em}.topbar a:hover{color:#d7f5e6}
.topnav{display:flex;gap:18px;align-items:center;font-size:14px}.topnav a{color:#dbece5}
button,.button{font:inherit;cursor:pointer;border:1px solid var(--line);background:white;color:var(--green);border-radius:7px;padding:7px 12px;text-decoration:none;font-size:13px;font-weight:650}
.layout{display:grid;grid-template-columns:280px minmax(0,960px);max-width:1340px;margin:auto;gap:34px;padding:32px 28px 70px}
aside{font-size:13px;position:sticky;top:20px;align-self:start;max-height:calc(100vh - 40px);overflow:auto;padding-right:10px}
aside .label{font-size:11px;text-transform:uppercase;letter-spacing:.12em;font-weight:800;color:var(--muted);margin:8px 0}
.guide-nav{display:grid;gap:5px;margin-bottom:24px}.guide-nav a{padding:7px 10px;border-radius:6px;text-decoration:none;line-height:1.5}.guide-nav a.active{background:#dfeee6;font-weight:700}
aside ul{list-style:none;margin:0;padding-left:0}aside li{margin:7px 0;line-height:1.5}aside li ul{padding-left:14px;border-left:1px solid var(--line);margin:8px 0}aside a{text-decoration:none;color:var(--muted)}
aside summary{cursor:pointer;font-weight:700;padding:6px 0}.toc>ul>li>a{font-weight:650}
main{min-width:0;background:var(--paper);border:1px solid var(--line);border-radius:13px;padding:36px 44px;box-shadow:0 7px 22px #163d3005}
.eyebrow{color:var(--green);font-size:12px;text-transform:uppercase;letter-spacing:.13em;font-weight:800;margin:0 0 12px}
.doc-note{font-size:13px;background:#edf6f1;border-left:3px solid #379d76;padding:10px 14px;color:#315a4e;margin-bottom:25px}
h1{font-size:36px;line-height:1.2;letter-spacing:-.035em;margin:0 0 20px}h2{font-size:25px;line-height:1.35;margin:44px 0 16px;padding-top:8px;border-top:1px solid var(--line);letter-spacing:-.02em}h3{font-size:19px;line-height:1.4;margin:28px 0 12px}h4{font-size:17px}
p{margin:14px 0}li{margin:6px 0}strong{font-weight:700}blockquote{margin:20px 0;padding:8px 20px;background:#f0f6f3;border-left:4px solid #65a58c;color:#294e43}
code{font:0.88em/1.6 Consolas,'Cascadia Code',monospace;background:#edf2ef;padding:2px 5px;border-radius:4px;overflow-wrap:anywhere}
.code-block{position:relative;margin:20px 0}pre{background:#132b2b;color:#ecf5ee;padding:42px 20px 20px;border-radius:9px;overflow:auto;line-height:1.65;margin:0}pre code{background:none;color:inherit;padding:0;border-radius:0;overflow-wrap:normal;font-size:13px}
.copy{position:absolute;right:9px;top:8px;background:#27423e;border-color:#46615a;color:#e5f4e9;font-size:11px;padding:3px 9px}.copy:hover{background:#365b50}
.code-block .language{position:absolute;left:20px;top:10px;font:10px/1.5 system-ui;color:#aecabd;letter-spacing:.1em;text-transform:uppercase}
.table-wrap{overflow:auto;margin:22px 0;border:1px solid var(--line);border-radius:8px}table{border-collapse:collapse;width:100%;font-size:14px;line-height:1.6}th,td{text-align:left;padding:12px 14px;border-bottom:1px solid var(--line);vertical-align:top}th{background:#eaf2ed;font-weight:700}tr:last-child td{border-bottom:0}tbody tr:nth-child(even){background:#f9fbf9}
hr{border:0;border-top:1px solid var(--line);margin:30px 0}.footer{font-size:12px;color:var(--muted);margin-top:44px;padding-top:18px;border-top:1px solid var(--line)}
.home{max-width:1120px;margin:40px auto;padding:40px}.home h1{font-size:46px;max-width:760px}.intro{font-size:19px;color:var(--muted);max-width:760px}.cards{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-top:30px}.card{border:1px solid var(--line);border-radius:10px;padding:24px;text-decoration:none;color:var(--ink);display:block;background:#fafcfa}.card:hover{background:#eef6f0;border-color:#93bba9}.card.primary{border-top:4px solid var(--green)}.card h2{border:0;margin:10px 0;padding:0;font-size:23px}.card p{font-size:15px;color:var(--muted)}.card .cta{font-size:14px;font-weight:750;color:var(--green)}.steps{background:#edf6f1;border-radius:9px;padding:20px 28px;margin:28px 0}.steps h2{border:0;padding:0;margin:0 0 12px;font-size:22px}
@media(max-width:1000px){.layout{grid-template-columns:230px minmax(0,1fr);gap:20px;padding:22px 16px}main{padding:28px}h1{font-size:31px}}
@media(max-width:720px){.topbar{padding:14px 18px;align-items:flex-start}.topnav{gap:10px;flex-wrap:wrap;justify-content:flex-end}.layout{display:block;padding:18px 12px}aside{position:static;max-height:none;padding:0 8px;margin-bottom:20px}.guide-nav{grid-template-columns:1fr 1fr;margin-bottom:12px}aside details{border:1px solid var(--line);border-radius:7px;padding:8px 12px}main{padding:24px 20px}h1{font-size:29px}h2{font-size:23px}.cards{grid-template-columns:1fr}.home{margin:18px 12px;padding:25px 20px}.home h1{font-size:35px}.intro{font-size:17px}th,td{min-width:140px;padding:10px}}
@media print{body{background:white;font:10pt/1.55 Georgia,serif;color:black}.topbar,aside,.copy,.skip,.doc-note{display:none!important}.layout{display:block;padding:0;margin:0;max-width:none}main,.home{border:0;box-shadow:none;padding:0;margin:0;max-width:none}h1{font-size:25pt}h2{font-size:17pt;margin-top:25px;break-after:avoid}h3{break-after:avoid}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f1f3f1;color:black;border:1px solid #ccc;padding:26px 12px 12px}pre code{font-size:8pt}.code-block .language{color:#555}.table-wrap{overflow:visible}table{font-size:9pt}tr{break-inside:avoid}thead{display:table-header-group}a{color:inherit}.cards{display:block}.card{margin:14px 0;break-inside:avoid}@page{margin:16mm}}
"""

JS = """
document.querySelectorAll('pre').forEach(pre => {
  const wrap = document.createElement('div'); wrap.className = 'code-block';
  pre.parentNode.insertBefore(wrap, pre); wrap.appendChild(pre);
  const code = pre.querySelector('code');
  const label = document.createElement('span'); label.className = 'language';
  label.textContent = ((code && code.className.match(/language-([\\w-]+)/)) || [,'example'])[1];
  wrap.appendChild(label);
  const button = document.createElement('button'); button.className = 'copy';
  button.type = 'button'; button.textContent = 'Copy'; button.setAttribute('aria-label','Copy code example');
  button.addEventListener('click', async () => {
    const text = pre.textContent; let copied = false;
    try { await navigator.clipboard.writeText(text); copied = true; } catch (_) {
      const area = document.createElement('textarea'); area.value = text;
      area.style.position='fixed'; area.style.opacity='0'; document.body.appendChild(area);
      area.select(); copied = document.execCommand('copy'); area.remove();
    }
    button.textContent = copied ? 'Copied!' : 'Select and copy';
    if (!copied) { const range=document.createRange(); range.selectNodeContents(pre); const selection=window.getSelection(); selection.removeAllRanges(); selection.addRange(range); }
    setTimeout(() => button.textContent = 'Copy', 1800);
  });
  wrap.appendChild(button);
});
if (window.matchMedia('(max-width: 720px)').matches) document.querySelectorAll('aside details').forEach(d => d.open = false);
"""


def page(title, content, sidebar="", home=False):
    container = f'<main id="content" class="home">{content}</main>' if home else f'<div class="layout">{sidebar}<main id="content">{content}</main></div>'
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="VoltCart student documentation: executable LangSmith labs and application guides.">
<title>{html.escape(title)} | VoltCart student guides</title><style>{CSS}</style></head>
<body><a class="skip" href="#content">Skip to content</a>
<header class="topbar"><a class="brand" href="START_HERE.html">VOLTCART / LEARNING LAB</a>
<nav class="topnav" aria-label="Page actions"><a href="START_HERE.html">All guides</a><button type="button" onclick="window.print()">Print / Save PDF</button></nav></header>
{container}<script>{JS}</script></body></html>'''


def build():
    for stem, title, category, description in GUIDES:
        parser = markdown.Markdown(extensions=["fenced_code", "tables", "toc", "sane_lists"],
                                   extension_configs={"toc": {"toc_depth": "2-3", "permalink": False}})
        body = parser.convert((ROOT / (stem + ".md")).read_text(encoding="utf-8"))
        # Keep inter-guide navigation in HTML, including links with anchors.
        body = re.sub(r'href="([^"#:?]+)\.md(#[^"]*)?"',
                      lambda m: f'href="{m.group(1)}.html{m.group(2) or ""}"', body)
        body = re.sub(r'(<table>.*?</table>)', r'<div class="table-wrap">\1</div>', body, flags=re.S)
        nav = ''.join(f'<a {"class=active aria-current=page" if key == stem else ""} href="{key}.html">{html.escape(name)}</a>' for key, name, _, _ in GUIDES)
        sidebar = f'<aside aria-label="Guide navigation"><p class="label">Student guides</p><nav class="guide-nav">{nav}</nav><details open><summary>On this page</summary>{parser.toc}</details></aside>'
        content = f'<p class="eyebrow">{html.escape(category)}</p><div class="doc-note">Open this file in any browser. Use Copy on command examples, or Print / Save PDF for a printable copy. The page itself works offline; live services and first-time setup require internet.</div>{body}<footer class="footer">VoltCart student edition · <a href="START_HERE.html">All guides</a> · <a href="{stem}.md">Markdown source</a></footer>'
        (ROOT / (stem + ".html")).write_text(page(title, content, sidebar), encoding="utf-8")

    cards = ''.join(f'<a class="card {"primary" if i == 0 else ""}" href="{stem}.html"><span class="eyebrow">{html.escape(category)}</span><h2>{html.escape(title)}</h2><p>{html.escape(description)}</p><span class="cta">Open guide &rarr;</span></a>' for i, (stem, title, category, description) in enumerate(GUIDES))
    content = f'''<p class="eyebrow">Student documentation · Open in your browser</p>
<h1>Learn, run, and debug VoltCart.</h1>
<p class="intro">Your classroom guides in one place. Follow executable examples, inspect real LangSmith traces, and learn how to test an AI agent.</p>
<div class="steps"><h2>New here?</h2><ol><li>Open <a href="README.html">Setup and quick start</a> to prepare Python and VoltCart.</li><li>Follow the <a href="LANGSMITH_STUDENT_WORKBOOK.html">LangSmith hands-on workbook</a> from its first offline exercise.</li><li>Add your LangSmith key when you are ready to inspect live traces.</li></ol></div>
<div class="cards">{cards}</div>
<h2>No Markdown viewer needed</h2><p>Double-click <strong>START_HERE.html</strong> to return here. These guides include a table of contents, copyable commands, and a print option. They have no external fonts, scripts, or stylesheet dependencies.</p>
<p>Keep these HTML files in the project folder when sharing, so links to the runnable examples and other guides continue to work. Reading the pages requires no server; executing examples requires the setup described in the guides.</p>
<p><a href="VoltCart_AI_Agent_Test_Cases_100.csv">Download / open the 100 classroom test cases (CSV)</a></p>
<footer class="footer">Instructor maintenance: edit the Markdown sources, then run <code>python build_student_docs.py</code> with <code>Markdown==3.9</code> installed. Share a copy with placeholder credentials.</footer>'''
    (ROOT / "START_HERE.html").write_text(page("Start here", content, home=True), encoding="utf-8")
    print("Built START_HERE.html and " + ", ".join(stem + ".html" for stem, *_ in GUIDES))


if __name__ == "__main__":
    build()
