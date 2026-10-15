# -*- coding: utf-8 -*-
"""构建 Zeal / Dash 文档集的公共部分。

Zeal 加载一个文档集只需要三样东西：
    <name>.docset/Contents/Info.plist
    <name>.docset/Contents/Resources/docSet.dsidx      ← SQLite，必须有 searchIndex 表
    <name>.docset/Contents/Resources/Documents/        ← 实际的 HTML

`searchIndex` 表只要有 (name, type, path) 三列就行 —— Zeal 的 Dash 型查询是
`SELECT name, type, path, '' FROM searchIndex ...`，不需要 Dash 格式里那个 `fragment` 列。
type 的取值 Zeal 认这些：func / macro / doc / data / cl / tmplt / var / tdef / Struct。
"""
import os, html, sqlite3

# 页面样式。Zeal 是 Chromium 内核，深色主题下会自动反相，所以这里按浅色写即可。
CSS = """
body{font:15px/1.75 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif;color:#24292f;
     margin:0;padding:22px 26px 60px;max-width:900px;background:#fff}
h1{font-size:23px;margin:0 0 4px;color:#0b3d91;border-bottom:2px solid #0b3d91;padding-bottom:8px}
h2{font-size:18px;margin:26px 0 8px;color:#0b3d91;border-left:4px solid #0b3d91;padding-left:9px}
h3{font-size:16px;margin:18px 0 6px;color:#333}
code,pre{font-family:Consolas,"Cascadia Mono",monospace;font-size:13.5px}
code{background:#f2f4f7;padding:1px 5px;border-radius:4px;color:#b3005c}
pre{background:#f6f8fa;border:1px solid #dfe3e8;border-left:4px solid #0b3d91;
    border-radius:6px;padding:11px 13px;overflow-x:auto;line-height:1.6}
pre code{background:none;color:#24292f;padding:0}
table{border-collapse:collapse;width:100%;margin:12px 0;font-size:14px}
th,td{border:1px solid #dfe3e8;padding:7px 11px;text-align:left;vertical-align:top}
th{background:#eef2f8;font-weight:600}
tr:nth-child(even) td{background:#fafbfc}
a{color:#0b57d0;text-decoration:none}a:hover{text-decoration:underline}
blockquote{margin:12px 0;padding:6px 14px;border-left:4px solid #d0d7de;color:#57606a}
.crumb{font-size:13px;color:#6a737d;margin:0 0 14px}
.crumb a{color:#6a737d}
.tip{background:#fff8e1;border:1px solid #ffe082;border-left:4px solid #ffb300;
     border-radius:6px;padding:9px 13px;margin:14px 0;font-size:14px}
ul.idx{columns:3;column-gap:26px;list-style:none;padding:0;font-size:14px}
ul.idx li{margin:2px 0;break-inside:avoid}
/* 菜鸟教程代码块的语法高亮配色（原本靠站内 CSS，这里自带一份） */
.example{margin:16px 0}
.example_code{background:#f6f8fa;border:1px solid #dfe3e8;border-left:4px solid #0b3d91;
     border-radius:6px;padding:11px 13px;margin:8px 0;overflow-x:auto}
.hl-main{font-family:Consolas,"Cascadia Mono",monospace;font-size:13.5px;line-height:1.65;
     white-space:pre;display:block;color:#24292f}
h2.example{font-size:15px;color:#0b3d91;margin:0 0 8px;border:0;padding:0}
.hl-prepro{color:#a626a4;font-weight:600}
.hl-quotes{color:#4078f2}
.hl-string{color:#50a14f}
.hl-types{color:#c18401;font-weight:600}
.hl-brackets{color:#e45649}
.hl-number{color:#986801}
.hl-identifier,.hl-code{color:#24292f}
.result{background:#f6f8fa;border:1px solid #dfe3e8;border-radius:6px;padding:9px 12px;
     margin:10px 0;white-space:pre-wrap;font-family:Consolas,monospace;font-size:13.5px}
"""

TPL = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>%s</title><style>%s</style></head><body>
<div class="crumb">%s</div>
%s
</body></html>"""


def page_template(title, css, crumb, body):
    return TPL % (html.escape(title), css, crumb, body)


def plist(ident, name, family, keyword, index_path="index.html"):
    """生成 Info.plist。

    DocSetPlatformFamily 决定 Zeal 内部的关键词：设成 `c` 就能被 VS Code 的
    deerawan.vscode-dash 扩展用 `keys=c` 命中（它按语言/文件名映射到 `c`）。
    DashDocSetKeyword 是额外挂上的自定义关键词，方便手动指定单个文档集。
    """
    return """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
<key>CFBundleIdentifier</key><string>%s</string>
<key>CFBundleName</key><string>%s</string>
<key>DocSetPlatformFamily</key><string>%s</string>
<key>DashDocSetKeyword</key><string>%s</string>
<key>isDashDocset</key><true/>
<key>dashIndexFilePath</key><string>%s</string>
<key>DashDocSetBlocksOnlineResources</key><false/>
<key>isJavaScriptEnabled</key><false/>
</dict>
</plist>
""" % (ident, name, family, keyword, index_path)


def build_dsidx(docset_dir, rows):
    """写 Contents/Resources/docSet.dsidx。rows = [(name, type, path), ...]"""
    db = os.path.join(docset_dir, "Contents", "Resources", "docSet.dsidx")
    if os.path.exists(db):
        os.remove(db)
    con = sqlite3.connect(db)
    cur = con.cursor()
    cur.execute("CREATE TABLE searchIndex(id INTEGER PRIMARY KEY, name TEXT, type TEXT, path TEXT)")
    cur.execute("CREATE UNIQUE INDEX anchor ON searchIndex (name, type, path)")
    cur.executemany("INSERT OR IGNORE INTO searchIndex(name,type,path) VALUES(?,?,?)", rows)
    con.commit()
    n = cur.execute("SELECT COUNT(*) FROM searchIndex").fetchone()[0]
    con.close()
    return n


def write_index(docs_dir, heading, items, tip_html):
    """写首页。

    items 里每项是 (标题, 相对路径)，或 (分组名, 标题, 相对路径)；
    没给分组名的就按路径的第一段目录分组。
    """
    groups = {}
    for it in items:
        if len(it) == 3:
            group, title, path = it
        else:
            title, path = it
            group = path.split("/")[0] if "/" in path else "其他"
        groups.setdefault(group, []).append((title, path))
    parts = ["<h1>%s</h1>" % html.escape(heading), '<div class="tip">%s</div>' % tip_html]
    for g in sorted(groups):
        parts.append("<h2>%s</h2>" % g if g != "其他" else "<h2>其他</h2>")
        parts.append('<ul class="idx">')
        for title, path in sorted(groups[g], key=lambda x: x[1]):
            parts.append('<li><a href="%s">%s</a></li>' % (path, title))
        parts.append("</ul>")
    open(os.path.join(docs_dir, "index.html"), "w", encoding="utf-8").write(
        page_template(heading, CSS, "首页", "\n".join(parts)))


def report(docset_dir, docs_dir, n_entries):
    total = sum(os.path.getsize(os.path.join(r, f))
                for r, _, fs in os.walk(docs_dir) for f in fs)
    n_files = sum(len(fs) for _, _, fs in os.walk(docs_dir))
    print("\n构建完成 -> %s" % docset_dir)
    print("  Documents: %d 个文件, %.1f MB" % (n_files, total / 1024 / 1024))
    print("  docSet.dsidx: %d 条索引" % n_entries)
