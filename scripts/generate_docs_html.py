#!/usr/bin/env python3
"""Generate docs/manual.html with left sidebar TOC from root README.md."""

from __future__ import annotations

import html
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
OUT = ROOT / "docs" / "manual.html"


def strip_inline_toc(md: str) -> str:
    """Remove the markdown TOC block between the comment and first real section."""
    # Drop from HTML comment / "# 目录" through the --- before first <h2 id="s-1">
    pattern = re.compile(
        r"(?:<!--\s*目录锚点[\s\S]*?-->\s*)?"
        r"# 目录\s*\n"
        r"[\s\S]*?"
        r"(?=---\s*\n\s*<h2 id=\"s-1\">)",
        re.MULTILINE,
    )
    md2, n = pattern.subn("", md, count=1)
    if n == 0:
        # fallback: remove from "# 目录" to first <h2 id=
        pattern2 = re.compile(
            r"# 目录\s*\n[\s\S]*?(?=<h2 id=\"s-1\">)",
            re.MULTILINE,
        )
        md2 = pattern2.sub("", md, count=1)
    # remove "返回目录" links (sidebar replaces them)
    md2 = re.sub(r"\[↑ 返回目录\]\([^)]+\)\s*\n?", "", md2)
    return md2


def parse_toc_tree(md: str) -> list[dict]:
    """Parse level-1 (h2) and level-2 (h3) from HTML headings with ids."""
    tree: list[dict] = []
    current = None
    for m in re.finditer(
        r'<(h[23])\s+id="([^"]+)">\s*([^<]+?)\s*</h[23]>',
        md,
        re.IGNORECASE,
    ):
        tag, sid, title = m.group(1).lower(), m.group(2), m.group(3).strip()
        title = html.unescape(title)
        if tag == "h2":
            current = {"id": sid, "title": title, "children": []}
            tree.append(current)
        elif tag == "h3" and current is not None:
            current["children"].append({"id": sid, "title": title})
        elif tag == "h3":
            # orphan h3 -> treat as top-level leaf
            tree.append({"id": sid, "title": title, "children": []})
    return tree


def render_sidebar(tree: list[dict]) -> str:
    parts = ['<nav class="toc" id="sidebar-toc" aria-label="文档目录">']
    parts.append('<div class="toc-title">目录</div>')
    parts.append('<ul class="toc-l1">')
    for item in tree:
        has_kids = bool(item["children"])
        cls = "toc-item has-children" if has_kids else "toc-item"
        parts.append(f'<li class="{cls}" data-id="{html.escape(item["id"])}">')
        parts.append(
            f'<a class="toc-l1-link" href="#{html.escape(item["id"])}">'
            f'{html.escape(item["title"])}</a>'
        )
        if has_kids:
            parts.append('<ul class="toc-l2">')
            for child in item["children"]:
                parts.append(
                    f'<li class="toc-item" data-id="{html.escape(child["id"])}">'
                    f'<a class="toc-l2-link" href="#{html.escape(child["id"])}">'
                    f'{html.escape(child["title"])}</a></li>'
                )
            parts.append("</ul>")
        parts.append("</li>")
    parts.append("</ul></nav>")
    return "\n".join(parts)


def convert_md_body(md: str) -> str:
    """Lightweight Markdown → HTML for README body (stdlib only)."""
    lines = md.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    i = 0
    in_code = False
    code_lang = ""
    code_buf: list[str] = []
    in_table = False
    table_rows: list[list[str]] = []

    def flush_table() -> None:
        nonlocal in_table, table_rows
        if not table_rows:
            in_table = False
            return
        out.append('<div class="table-wrap"><table>')
        for ri, row in enumerate(table_rows):
            # skip separator row |---|
            if all(re.fullmatch(r":?-{3,}:?", c.strip()) for c in row):
                continue
            tag = "th" if ri == 0 else "td"
            # if first row was header and second was separator, first already th
            out.append("<tr>")
            for cell in row:
                out.append(f"<{tag}>{inline_md(cell.strip())}</{tag}>")
            out.append("</tr>")
        out.append("</table></div>")
        table_rows = []
        in_table = False

    def flush_para(buf: list[str]) -> None:
        if not buf:
            return
        text = " ".join(s.strip() for s in buf if s.strip())
        if text:
            out.append(f"<p>{inline_md(text)}</p>")
        buf.clear()

    para: list[str] = []

    while i < len(lines):
        line = lines[i]

        # fenced code
        fence = re.match(r"^```(\w*)\s*$", line)
        if fence:
            flush_table()
            flush_para(para)
            if not in_code:
                in_code = True
                code_lang = fence.group(1) or ""
                code_buf = []
            else:
                lang_cls = f' class="language-{html.escape(code_lang)}"' if code_lang else ""
                code_html = html.escape("\n".join(code_buf))
                out.append(f"<pre><code{lang_cls}>{code_html}</code></pre>")
                in_code = False
                code_buf = []
            i += 1
            continue

        if in_code:
            code_buf.append(line)
            i += 1
            continue

        # raw HTML headings already in source
        if re.match(r"^\s*<h[1-6]\b", line, re.I):
            flush_table()
            flush_para(para)
            out.append(line.strip())
            i += 1
            continue

        # HTML comments
        if line.strip().startswith("<!--"):
            i += 1
            continue

        # ATX headings (intro title etc.)
        hm = re.match(r"^(#{1,6})\s+(.+)$", line)
        if hm:
            flush_table()
            flush_para(para)
            level = len(hm.group(1))
            title = hm.group(2).strip()
            # skip pure "目录" heading
            if title == "目录":
                i += 1
                continue
            sid = ""
            # keep simple ids for remaining md headings if any
            out.append(f"<h{level}>{inline_md(title)}</h{level}>")
            i += 1
            continue

        # hr
        if re.match(r"^---+\s*$", line):
            flush_table()
            flush_para(para)
            out.append("<hr/>")
            i += 1
            continue

        # blockquote
        if line.startswith(">"):
            flush_table()
            flush_para(para)
            bq: list[str] = []
            while i < len(lines) and lines[i].startswith(">"):
                bq.append(re.sub(r"^>\s?", "", lines[i]))
                i += 1
            out.append(f"<blockquote>{inline_md(' '.join(bq))}</blockquote>")
            continue

        # unordered list
        if re.match(r"^[-*]\s+", line):
            flush_table()
            flush_para(para)
            out.append("<ul>")
            while i < len(lines) and re.match(r"^[-*]\s+", lines[i]):
                item = re.sub(r"^[-*]\s+", "", lines[i])
                # nested indent lists as flat for simplicity; keep nested bullets if more spaces
                out.append(f"<li>{inline_md(item)}</li>")
                i += 1
            out.append("</ul>")
            continue

        # ordered list
        if re.match(r"^\d+\.\s+", line):
            flush_table()
            flush_para(para)
            out.append("<ol>")
            while i < len(lines) and re.match(r"^\d+\.\s+", lines[i]):
                item = re.sub(r"^\d+\.\s+", "", lines[i])
                out.append(f"<li>{inline_md(item)}</li>")
                i += 1
            out.append("</ol>")
            continue

        # table
        if "|" in line and line.strip().startswith("|"):
            flush_para(para)
            in_table = True
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            table_rows.append(cells)
            i += 1
            continue
        elif in_table:
            flush_table()

        # blank
        if not line.strip():
            flush_para(para)
            i += 1
            continue

        para.append(line)
        i += 1

    flush_table()
    flush_para(para)
    if in_code and code_buf:
        out.append(f"<pre><code>{html.escape(chr(10).join(code_buf))}</code></pre>")
    return "\n".join(out)


def inline_md(text: str) -> str:
    """Convert inline markdown (links, code, bold/italic)."""
    # 1) links first so [`path`](url) works
    parts = re.split(r"(\[[^\]]+\]\([^)]+\))", text)
    built: list[str] = []
    for p in parts:
        lm = re.fullmatch(r"\[([^\]]+)\]\(([^)]+)\)", p)
        if lm:
            label, url = lm.group(1), lm.group(2)
            inner = format_inline_with_code(label)
            href = html.escape(url, quote=True)
            if url.startswith("#"):
                built.append(f'<a href="{href}">{inner}</a>')
            else:
                built.append(
                    f'<a href="{href}" target="_blank" rel="noopener">{inner}</a>'
                )
        else:
            built.append(format_inline_with_code(p))
    return "".join(built)


def format_inline_with_code(text: str) -> str:
    codes: list[str] = []

    def save_code(m: re.Match) -> str:
        codes.append(html.escape(m.group(1)))
        return f"\x00C{len(codes) - 1}\x00"

    text = re.sub(r"`([^`]+)`", save_code, text)
    # escape remainder, then bold/italic
    # protect placeholders from html.escape by temp tokens
    tmp = text
    for i in range(len(codes)):
        tmp = tmp.replace(f"\x00C{i}\x00", f"@@C{i}@@")
    tmp = html.escape(tmp)
    tmp = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", tmp)
    tmp = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<em>\1</em>", tmp)
    for i, code in enumerate(codes):
        tmp = tmp.replace(f"@@C{i}@@", f"<code>{code}</code>")
    return tmp


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>AI Quant Trader Pro — 项目文档</title>
  <style>
    :root {{
      --bg: #0f1419;
      --panel: #161b22;
      --panel-2: #1c2330;
      --border: #30363d;
      --text: #e6edf3;
      --muted: #8b949e;
      --link: #58a6ff;
      --accent: #3fb950;
      --active: #1f6feb;
      --active-bg: rgba(31, 111, 235, 0.15);
      --code-bg: #0d1117;
      --warn-bg: rgba(210, 153, 34, 0.12);
      --warn-border: #d29922;
      --sidebar-w: 300px;
      --header-h: 56px;
      --font: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      --mono: "Cascadia Code", "Consolas", "SF Mono", monospace;
    }}
    * {{ box-sizing: border-box; }}
    html {{ scroll-behavior: smooth; }}
    body {{
      margin: 0;
      font-family: var(--font);
      background: var(--bg);
      color: var(--text);
      line-height: 1.65;
      font-size: 15px;
    }}
    a {{ color: var(--link); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}

    .topbar {{
      position: fixed; top: 0; left: 0; right: 0; height: var(--header-h);
      background: rgba(22, 27, 34, 0.92);
      border-bottom: 1px solid var(--border);
      backdrop-filter: blur(8px);
      display: flex; align-items: center; gap: 16px;
      padding: 0 16px 0 20px;
      z-index: 100;
    }}
    .topbar .brand {{
      font-weight: 700; font-size: 15px; color: var(--text);
      white-space: nowrap;
    }}
    .topbar .brand span {{ color: var(--accent); margin-right: 6px; }}
    .topbar .search {{
      flex: 1; max-width: 360px;
    }}
    .topbar input {{
      width: 100%;
      background: var(--code-bg);
      border: 1px solid var(--border);
      color: var(--text);
      border-radius: 6px;
      padding: 7px 12px;
      font-size: 13px;
      outline: none;
    }}
    .topbar input:focus {{ border-color: var(--active); }}
    .menu-btn {{
      display: none;
      background: var(--panel-2);
      border: 1px solid var(--border);
      color: var(--text);
      border-radius: 6px;
      padding: 6px 10px;
      cursor: pointer;
    }}

    .layout {{
      display: flex;
      padding-top: var(--header-h);
      min-height: 100vh;
    }}

    .sidebar {{
      position: fixed;
      top: var(--header-h);
      left: 0;
      bottom: 0;
      width: var(--sidebar-w);
      background: var(--panel);
      border-right: 1px solid var(--border);
      overflow-y: auto;
      overflow-x: hidden;
      padding: 12px 0 32px;
      z-index: 50;
    }}
    .toc-title {{
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--muted);
      padding: 8px 18px 12px;
    }}
    .toc-l1 {{
      list-style: none;
      margin: 0;
      padding: 0 8px;
    }}
    .toc-l1 > .toc-item {{
      margin: 2px 0;
    }}
    .toc-l1-link {{
      display: block;
      padding: 8px 12px;
      border-radius: 6px;
      color: var(--text);
      font-weight: 600;
      font-size: 13.5px;
      line-height: 1.4;
      text-decoration: none !important;
    }}
    .toc-l1-link:hover {{
      background: var(--panel-2);
    }}
    .toc-l2 {{
      list-style: none;
      margin: 0 0 6px 0;
      padding: 0 0 0 10px;
      border-left: 2px solid var(--border);
      margin-left: 14px;
    }}
    .toc-l2-link {{
      display: block;
      padding: 5px 10px;
      border-radius: 5px;
      color: var(--muted);
      font-size: 12.5px;
      line-height: 1.4;
      text-decoration: none !important;
    }}
    .toc-l2-link:hover {{
      color: var(--text);
      background: var(--panel-2);
    }}
    .toc-item.active > a,
    .toc-l2 .toc-item.active > a {{
      color: #fff !important;
      background: var(--active-bg);
      box-shadow: inset 2px 0 0 var(--active);
    }}
    .toc-item.hidden-by-filter {{ display: none; }}

    .content {{
      margin-left: var(--sidebar-w);
      flex: 1;
      min-width: 0;
      padding: 28px 40px 80px;
      max-width: 960px;
    }}
    .content > h1:first-child {{
      margin-top: 0;
      font-size: 1.9rem;
      border-bottom: 1px solid var(--border);
      padding-bottom: 12px;
    }}
    .content h2 {{
      margin-top: 2.4rem;
      padding-top: 0.6rem;
      font-size: 1.45rem;
      border-bottom: 1px solid var(--border);
      padding-bottom: 0.4rem;
      scroll-margin-top: calc(var(--header-h) + 12px);
    }}
    .content h3 {{
      margin-top: 1.6rem;
      font-size: 1.15rem;
      color: #f0f3f6;
      scroll-margin-top: calc(var(--header-h) + 12px);
    }}
    .content h4 {{
      margin-top: 1.2rem;
      font-size: 1.02rem;
      scroll-margin-top: calc(var(--header-h) + 12px);
    }}
    .content p {{ margin: 0.75rem 0; color: #d0d7de; }}
    .content li {{ margin: 0.25rem 0; color: #d0d7de; }}
    .content ul, .content ol {{ padding-left: 1.4rem; }}
    .content hr {{
      border: none;
      border-top: 1px solid var(--border);
      margin: 1.8rem 0;
    }}
    .content blockquote {{
      margin: 1rem 0;
      padding: 10px 14px;
      border-left: 4px solid var(--warn-border);
      background: var(--warn-bg);
      color: #e6edf3;
      border-radius: 0 8px 8px 0;
    }}
    .content code {{
      font-family: var(--mono);
      font-size: 0.88em;
      background: var(--code-bg);
      border: 1px solid var(--border);
      border-radius: 4px;
      padding: 0.1em 0.35em;
    }}
    .content pre {{
      background: var(--code-bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 14px 16px;
      overflow-x: auto;
      line-height: 1.5;
    }}
    .content pre code {{
      border: none;
      background: transparent;
      padding: 0;
      font-size: 12.5px;
    }}
    .table-wrap {{
      overflow-x: auto;
      margin: 1rem 0;
      border: 1px solid var(--border);
      border-radius: 8px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 13.5px;
    }}
    th, td {{
      border-bottom: 1px solid var(--border);
      padding: 8px 12px;
      text-align: left;
      vertical-align: top;
    }}
    th {{
      background: var(--panel-2);
      color: var(--text);
      font-weight: 600;
      white-space: nowrap;
    }}
    tr:last-child td {{ border-bottom: none; }}
    tr:hover td {{ background: rgba(255,255,255,0.02); }}
    strong {{ color: #f0f3f6; }}

    .sidebar-mask {{
      display: none;
      position: fixed;
      inset: 0;
      background: rgba(0,0,0,0.45);
      z-index: 40;
    }}

    @media (max-width: 900px) {{
      :root {{ --sidebar-w: 280px; }}
      .menu-btn {{ display: inline-block; }}
      .sidebar {{
        transform: translateX(-105%);
        transition: transform 0.2s ease;
      }}
      .sidebar.open {{ transform: translateX(0); }}
      .sidebar-mask.open {{ display: block; }}
      .content {{
        margin-left: 0;
        padding: 20px 16px 60px;
      }}
    }}
  </style>
</head>
<body>
  <header class="topbar">
    <button class="menu-btn" id="menuBtn" type="button" aria-label="打开目录">☰ 目录</button>
    <div class="brand"><span>■</span>AI Quant Trader Pro 文档</div>
    <div class="search">
      <input id="tocFilter" type="search" placeholder="筛选目录…" autocomplete="off" />
    </div>
  </header>
  <div class="sidebar-mask" id="sidebarMask"></div>
  <div class="layout">
    <aside class="sidebar" id="sidebar">
{sidebar}
    </aside>
    <main class="content" id="content">
{body}
    </main>
  </div>
  <script>
    (function () {{
      const sidebar = document.getElementById('sidebar');
      const mask = document.getElementById('sidebarMask');
      const menuBtn = document.getElementById('menuBtn');
      const filter = document.getElementById('tocFilter');
      const links = Array.from(document.querySelectorAll('.toc a[href^="#"]'));
      const items = Array.from(document.querySelectorAll('.toc .toc-item[data-id]'));

      function closeMobile() {{
        sidebar.classList.remove('open');
        mask.classList.remove('open');
      }}
      function openMobile() {{
        sidebar.classList.add('open');
        mask.classList.add('open');
      }}
      menuBtn && menuBtn.addEventListener('click', () => {{
        if (sidebar.classList.contains('open')) closeMobile();
        else openMobile();
      }});
      mask && mask.addEventListener('click', closeMobile);

      // Smooth jump + mobile close
      links.forEach((a) => {{
        a.addEventListener('click', (e) => {{
          const id = a.getAttribute('href').slice(1);
          const el = document.getElementById(id);
          if (!el) return;
          e.preventDefault();
          history.replaceState(null, '', '#' + id);
          el.scrollIntoView({{ behavior: 'smooth', block: 'start' }});
          setActive(id);
          closeMobile();
        }});
      }});

      function setActive(id) {{
        items.forEach((li) => li.classList.toggle('active', li.dataset.id === id));
      }}

      // Scroll spy
      const headings = Array.from(document.querySelectorAll('.content h2[id], .content h3[id]'));
      function onScroll() {{
        const y = window.scrollY + 80;
        let current = headings[0] && headings[0].id;
        for (const h of headings) {{
          if (h.offsetTop <= y) current = h.id;
        }}
        if (current) setActive(current);
      }}
      window.addEventListener('scroll', onScroll, {{ passive: true }});
      onScroll();

      // Open hash on load
      if (location.hash) {{
        const el = document.getElementById(location.hash.slice(1));
        if (el) {{
          setTimeout(() => el.scrollIntoView({{ block: 'start' }}), 50);
          setActive(location.hash.slice(1));
        }}
      }}

      // Filter TOC
      filter && filter.addEventListener('input', () => {{
        const q = filter.value.trim().toLowerCase();
        const l1Items = Array.from(document.querySelectorAll('.toc-l1 > .toc-item'));
        l1Items.forEach((li) => {{
          const text = li.textContent.toLowerCase();
          const show = !q || text.includes(q);
          li.classList.toggle('hidden-by-filter', !show);
        }});
      }});
    }})();
  </script>
</body>
</html>
"""


def main() -> int:
    if not README.exists():
        print(f"README not found: {README}", file=sys.stderr)
        return 1

    raw = README.read_text(encoding="utf-8")
    body_md = strip_inline_toc(raw)
    # tree from full readme (has all h2/h3)
    tree = parse_toc_tree(raw)
    if not tree:
        print("No TOC headings found (expected <h2 id=...>).", file=sys.stderr)
        return 1

    sidebar = render_sidebar(tree)
    body = convert_md_body(body_md)

    html_out = HTML_TEMPLATE.format(sidebar=sidebar, body=body)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html_out, encoding="utf-8")
    print(f"Wrote {OUT} ({len(tree)} top-level sections)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
