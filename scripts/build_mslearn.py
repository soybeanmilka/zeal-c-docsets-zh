# -*- coding: utf-8 -*-
"""把 learn.microsoft.com 的《C 运行库参考》（中文，msvc-170）打包成 Zeal/Dash 文档集。

用法：
    python build_mslearn.py [工作目录]        # 默认 ./work/mslearn

原理（关键技巧）：
    给 learn.microsoft.com 加请求头 `Accept: text/markdown`，它直接吐 markdown 源文
    （带 YAML frontmatter），比抓 HTML 干净得多——没有导航/侧边栏/脚本/广告，
    正文结构完整（标题、代码块、表格都在）。所以这里逐页抓 markdown 再自己转 HTML。

文档来源：https://learn.microsoft.com/zh-cn/cpp/c-runtime-library/   （CC BY 4.0）
"""
import os, re, sys, json, html, sqlite3, subprocess, time, shutil
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from docset_lib import (plist, page_template, CSS, write_index, build_dsidx, report)

sys.stdout.reconfigure(encoding="utf-8")

BASE = "https://learn.microsoft.com/zh-cn/cpp/c-runtime-library/"
TOC = BASE + "toc.json"
IDENT, NAME, FAMILY, KEYWORD = "c-win-zh", "C 运行库（微软中文）", "c", "c-ms"


def curl(url, out, accept=None):
    args = ["curl.exe", "-s", "--ssl-no-revoke", "-L", "--max-time", "60",
            "-w", "%{http_code}", "-o", out]
    if accept:
        args += ["-H", "Accept: " + accept]
    for _ in range(4):
        r = subprocess.run(args + [url], capture_output=True, text=True)
        code = (r.stdout or "").strip()
        if code == "200" and os.path.exists(out) and os.path.getsize(out) > 200:
            return code
        time.sleep(1.5)
    return code


# ---------------- 1. 目录树 ----------------
def load_hrefs(work):
    cache = os.path.join(work, "toc.json")
    if not os.path.exists(cache):
        curl(TOC, cache)
    d = json.load(open(cache, encoding="utf-8"))
    hrefs = []

    def walk(items):
        for it in items or []:
            if it.get("href"):
                hrefs.append(it["href"])
            walk(it.get("children"))

    walk(d.get("items"))
    # 目录树里有个别 href 重复出现（同一个页面挂在两个位置），按出现顺序去重
    seen, uniq = set(), []
    for h in hrefs:
        if h not in seen:
            seen.add(h)
            uniq.append(h)
    return uniq


# ---------------- 2. 抓 markdown ----------------
def fetch_all(work, hrefs):
    md_dir = os.path.join(work, "md")
    os.makedirs(md_dir, exist_ok=True)

    def one(h):
        path = os.path.join(md_dir, h.replace("/", "__") + ".md")
        if os.path.exists(path) and os.path.getsize(path) > 500:
            return h, True
        return h, curl(BASE + h + "?view=msvc-170", path, accept="text/markdown") == "200"

    with ThreadPoolExecutor(max_workers=8) as ex:
        res = list(ex.map(one, hrefs))
    bad = [h for h, ok in res if not ok]
    print("下载: 成功 %d / 失败 %d" % (len(res) - len(bad), len(bad)))
    for h in bad[:20]:
        print("   !! " + h)
    return md_dir


# ---------------- 3. frontmatter ----------------
def parse_frontmatter(text):
    """只解析我们需要的几个键（没有 yaml 依赖）。返回 (meta, body)。"""
    m = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n?(.*)$", text, re.S)
    if not m:
        return {}, text
    fm, body = m.group(1), m.group(2)
    meta, key = {}, None
    for line in fm.splitlines():
        mi = re.match(r"^([A-Za-z_][\w.]*):\s*(.*)$", line)
        if mi:
            key, val = mi.group(1), mi.group(2).strip()
            meta[key] = val if val else []
        elif line.startswith("- ") and key is not None:
            if not isinstance(meta.get(key), list):
                meta[key] = []
            meta[key].append(line[2:].strip())
    return meta, body


# ---------------- 4. markdown -> HTML ----------------
try:
    import markdown
except ImportError:
    sys.exit("缺 markdown 库：pip install --target ./pylibs markdown，再把 pylibs 加进 PYTHONPATH")

MD_EXT = ["fenced_code", "tables", "sane_lists", "attr_list", "md_in_html"]


def strip_learn_suffix(t):
    return re.sub(r"\s*\|\s*Microsoft Learn\s*$", "", t).strip()


def rewrite_links(body, page_dir, known):
    """把 markdown 里的相对链接改成文档集内的 .html，指不到的改回 learn.microsoft.com。"""
    def repl(m):
        url = m.group(1)
        if re.match(r"^(https?:|mailto:|#|/)", url):
            return m.group(0)
        path, _, anchor = url.partition("#")
        if not path:
            return m.group(0)
        target = os.path.normpath(os.path.join(page_dir, path)).replace("\\", "/")
        if target.startswith("../"):
            target = target[3:]
        if target in known:
            return "](%s.html%s)" % (target, "#" + anchor if anchor else "")
        return "](%s%s)" % (BASE + target, "#" + anchor if anchor else "")

    return re.sub(r"\]\(([^)\s]*)\)", repl, body)


def convert(body, title, page_dir, known, crumb):
    body = re.sub(r"(?m)^#\s+.*$", "", body, count=1)          # 去掉原 H1（模板里自己加）
    body = rewrite_links(body, page_dir, known)
    htm = markdown.markdown(body, extensions=MD_EXT)
    return page_template(title, CSS, crumb, htm)


# ---------------- 5. 索引条目 ----------------
def index_entries(meta, title, path):
    rows, seen = [], set()

    def add(name, typ):
        name = name.strip()
        if name and (name, typ, path) not in seen:
            seen.add((name, typ, path))
            rows.append((name, typ, path))

    for n in meta.get("api_name", []) or []:
        if re.match(r"^_?[A-Za-z_]\w*$", n):
            add(n, "func")
    for tok in re.split(r"[、，,/]", title):
        if re.match(r"^_?[A-Za-z_]\w*$", tok.strip()):
            add(tok.strip(), "func")
    add(title, "doc")
    return rows


# ---------------- 主流程 ----------------
def main():
    work = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.getcwd(), "work", "mslearn")
    work = os.path.abspath(work)
    os.makedirs(work, exist_ok=True)

    hrefs = load_hrefs(work)
    print("目录树: %d 页" % len(hrefs))
    md_dir = fetch_all(work, hrefs)

    out = os.path.join(os.path.dirname(work), "build", "C-win-zh.docset")
    docs = os.path.join(out, "Contents", "Resources", "Documents")
    if os.path.exists(out):
        shutil.rmtree(out)
    os.makedirs(docs, exist_ok=True)

    known = set(hrefs)
    pages, rows = {}, []
    for h in hrefs:
        f = os.path.join(md_dir, h.replace("/", "__") + ".md")
        if not os.path.exists(f):
            continue
        meta, body = parse_frontmatter(open(f, encoding="utf-8", errors="replace").read())
        title = strip_learn_suffix(meta.get("title") or h.split("/")[-1])
        p = h + ".html"
        pages[p] = (title, convert(body, title, os.path.dirname(h), known,
                                   '<a href="index.html">C 运行库（微软中文）</a>'))
        rows += index_entries(meta, title, p)

    for p, (_, htm) in pages.items():
        fp = os.path.join(docs, p)
        os.makedirs(os.path.dirname(fp), exist_ok=True)
        open(fp, "w", encoding="utf-8").write(htm)

    write_index(docs, "C 运行库（微软中文）", [(t, p) for p, (t, _) in pages.items()],
                "共 <b>%d</b> 页。数据来源：<a href=\"https://learn.microsoft.com/zh-cn/cpp/c-runtime-library/\">"
                "Microsoft Learn · C 运行库参考</a>（CC BY 4.0）。在 VS Code 里把光标放在函数名上按 <b>Ctrl+H</b> 可直接跳到对应页面。" % len(pages))
    rows.append(("C 运行库（微软中文）", "doc", "index.html"))

    n = build_dsidx(out, rows)
    open(os.path.join(out, "Contents", "Info.plist"), "w", encoding="utf-8").write(
        plist(IDENT, NAME, FAMILY, KEYWORD))
    report(out, docs, n)


if __name__ == "__main__":
    main()
