# -*- coding: utf-8 -*-
"""从菜鸟教程的 C 标准库页面构建 Zeal/Dash 中文文档集（C-zh-cn.docset）。

用法：
    python build_runoob.py [工作目录]        # 默认 ./work/runoob

抓取范围：c-standard-library.html 里的 21 个头文件页 + 它们表格里链接到的全部函数页
（159 个），抽出每页 `<div class="article-body">` 的正文，丢掉广告/导航，做成文档集。

⚠️ 版权提示：菜鸟教程的正文是有版权的，**本仓库不预置构建产物**，只提供脚本。
   请自行运行本脚本生成，并仅用于个人学习查阅。

数据来源：https://www.runoob.com/cprogramming/c-standard-library.html
"""
import os, re, sys, html, subprocess, shutil, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from docset_lib import CSS, page_template, plist, build_dsidx, report, write_index

sys.stdout.reconfigure(encoding="utf-8")

BASE = "https://www.runoob.com/cprogramming/"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120 Safari/537.36")
IDENT, NAME, FAMILY, KEYWORD = "c-zh-cn", "C 中文", "c", "c-zh"


def fetch(cache, name):
    """下载并缓存 cprogramming/<name>。返回 HTML 文本或 None。"""
    f = os.path.join(cache, name)
    if not os.path.exists(f) or os.path.getsize(f) < 500:
        subprocess.run(["curl.exe", "-s", "--ssl-no-revoke", "-L", "--max-time", "60",
                        "-A", UA, "-o", f, BASE + name], capture_output=True)
        time.sleep(0.25)
    if os.path.exists(f) and os.path.getsize(f) > 500:
        return open(f, encoding="utf-8", errors="replace").read()
    return None


def extract_article(raw):
    """取 class="article-body" 那个 div 的内容（平衡 <div> 扫描，非贪婪正则会截断）。"""
    i = raw.find('class="article-body"')
    if i < 0:
        return None
    s = raw.rfind("<div", 0, i)
    depth, j = 0, s
    while j < len(raw):
        m = re.compile(r"<(/?)div\b", re.I).search(raw, j)
        if not m:
            break
        if m.group(1):
            depth -= 1
            if depth == 0:
                return raw[s:m.end() + raw[m.end():].find(">") + 1]
        else:
            depth += 1
        j = m.end()
    return raw[s:]


DROP_CLASSES = ("responsive_ad1", "adsbygoogle", "previous-next-links", "navup",
                "next-design-link", "previous-design-link", "post-intro")
KEEP_CLASS = re.compile(r"^(hl-|example$|example_code$|hl-main$|result$|list$|reference$)")


def strip_balanced(text, class_name):
    """删掉 class 含 class_name 的整个元素（平衡标签扫描）。"""
    while True:
        m = re.search(r'<(\w+)[^>]*class="[^"]*\b%s\b[^"]*"[^>]*>' % re.escape(class_name), text)
        if not m:
            return text
        tag, start = m.group(1), m.start()
        pat, depth, j, end = re.compile(r"<(/?)%s\b" % tag, re.I), 0, start, None
        while True:
            mm = pat.search(text, j)
            if not mm:
                break
            depth += -1 if mm.group(1) else 1
            j = mm.end()
            if depth == 0:
                end = text.find(">", mm.end()) + 1
                break
        text = text[:start] + (text[end:] if end else text[m.end():])


def clean_html(frag):
    frag = re.sub(r"<script.*?</script>", "", frag, flags=re.S | re.I)
    frag = re.sub(r"<style.*?</style>", "", frag, flags=re.S | re.I)
    frag = re.sub(r"<!--.*?-->", "", frag, flags=re.S)
    frag = re.sub(r"<(ins|iframe)\b[^>]*>.*?</\1>", "", frag, flags=re.S | re.I)
    for c in DROP_CLASSES:
        frag = strip_balanced(frag, c)
    # 只保留白名单里的 class（runoob 的语法高亮类要留着，CSS 里配了同款配色）
    def fix_class(m):
        keep = [c for c in m.group(1).split() if KEEP_CLASS.match(c)]
        return 'class="%s"' % " ".join(keep) if keep else ""

    frag = re.sub(r'class="([^"]*)"', fix_class, frag)
    # 站内相对链接保留（同目录已生成），其余补成绝对地址
    frag = re.sub(r'(href|src)="/(?!/)', r'\1="https://www.runoob.com/', frag)
    frag = re.sub(r'(href|src)="//', r'\1="https://', frag)
    frag = re.sub(r'\s(id|style|data-[a-z-]+|onclick|target|align|width|height|border'
                  r'|cellpadding|cellspacing)="[^"]*"', "", frag)
    return re.sub(r"\n{3,}", "\n\n", frag).strip()


def collect_functions(cache, headers):
    """逐个 header 页扫 <tr>，收集 {slug: (签名, 描述, header)}。"""
    functions = {}
    clean = lambda s: html.unescape(re.sub(r"<[^>]+>", "", s)).strip()
    for h in headers:
        raw = fetch(cache, "c-standard-library-%s-h.html" % h)
        if not raw:
            print("  !! 下载失败: %s" % h)
            continue
        for tr in re.finditer(r"<tr[^>]*>(.*?)</tr>", raw, re.S):
            row = tr.group(1)
            m = re.search(r'<a\s+href="(c-function-([a-z0-9_]+)\.html)"[^>]*>(.*?)</a>', row, re.S)
            if not m:
                continue
            slug, sig = m.group(2), m.group(3)
            # 描述可能在同一个 <td> 的 </a><br> 之后，也可能在相邻的 <td> 里。
            # 注意两种表格格式：stdio 式是 <td>序号</td><td><a>…</a><br>描述</td>，
            # signal 式是 <td><code><a>…</a></code></td><td>描述</td>。
            desc = ""
            for td in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S):
                if "c-function-" in td:
                    after = td.split("</a>", 1)[1] if "</a>" in td else ""
                    after = re.sub(r"^\s*(<br\s*/?>)?\s*", "", after)
                    if clean(after):
                        desc = after
                        break
                elif clean(td):
                    desc = td
                    break
            if slug not in functions:
                functions[slug] = (clean(sig), clean(desc), h)
        print("  %-16s -> 累计 %d 个函数" % (h, len(functions)))
    return functions


def main():
    work = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.getcwd(), "work", "runoob")
    work = os.path.abspath(work)
    cache = os.path.join(work, "pages")
    os.makedirs(cache, exist_ok=True)

    # ---------- 1. 收集函数清单 ----------
    idx = fetch(cache, "c-standard-library.html")
    if not idx:
        sys.exit("抓不到索引页 c-standard-library.html")
    headers = sorted(set(re.findall(r"c-standard-library-([a-z0-9_]+)-h\.html", idx)))
    print("header 页 %d 个: %s" % (len(headers), ", ".join(headers)))
    functions = collect_functions(cache, headers)
    print("函数总数: %d" % len(functions))

    # ---------- 2. 下载函数页 ----------
    bad = [s for s in sorted(functions) if not fetch(cache, "c-function-%s.html" % s)]
    print("函数页下载: 成功 %d / 失败 %d %s" % (len(functions) - len(bad), len(bad), bad))

    # ---------- 3. 写出页面 ----------
    out = os.path.join(os.path.dirname(work), "build", "C-zh-cn.docset")
    docs = os.path.join(out, "Contents", "Resources", "Documents")
    if os.path.exists(out):
        shutil.rmtree(out)
    os.makedirs(docs, exist_ok=True)

    n = 0
    for slug, (sig, desc, h) in functions.items():
        raw = fetch(cache, "c-function-%s.html" % slug)
        body = extract_article(raw) if raw else None
        if not body:
            print("  !! 抽取失败: %s" % slug)
            continue
        name = re.sub(r"^c-function-", "", slug)
        crumb = '<a href="index.html">C 标准库（中文）</a> &rsaquo; <a href="c-standard-library-%s-h.html">&lt;%s.h&gt;</a>' % (h, h)
        open(os.path.join(docs, "c-function-%s.html" % slug), "w", encoding="utf-8").write(
            page_template("%s() - C 标准库（中文）" % name, CSS, crumb, clean_html(body)))
        n += 1
    print("写出函数页: %d" % n)

    for h in headers:
        raw = fetch(cache, "c-standard-library-%s-h.html" % h)
        body = extract_article(raw) if raw else None
        if not body:
            continue
        open(os.path.join(docs, "c-standard-library-%s-h.html" % h), "w", encoding="utf-8").write(
            page_template("<%s.h> - C 标准库（中文）" % h, CSS,
                          '<a href="index.html">C 标准库</a>', clean_html(body)))

    # ---------- 4. 首页 ----------
    by_header = {}
    for slug, (sig, desc, h) in functions.items():
        by_header.setdefault(h, []).append((re.sub(r"^c-function-", "", slug), sig, desc))
    items = []
    for h in headers:
        for name, sig, desc in sorted(by_header.get(h, [])):
            items.append(("<%s.h>" % h, name, "c-function-%s.html" % name))
    write_index(docs, "C 标准库 · 中文速查", items,
                "共 <b>%d</b> 个函数 / <b>%d</b> 个头文件。数据来源："
                "<a href=\"https://www.runoob.com/cprogramming/c-standard-library.html\">菜鸟教程 C 标准库</a>。"
                "在 VS Code 里把光标放在函数名上按 <b>Ctrl+H</b> 可直接跳到对应页面。"
                % (len(functions), len(headers)))

    # ---------- 5. 索引 + Info.plist ----------
    rows = [(re.sub(r"^c-function-", "", s), "func", "c-function-%s.html" % s) for s in functions]
    for h in headers:
        rows.append(("<%s.h>" % h, "doc", "c-standard-library-%s-h.html" % h))
        rows.append((h + ".h", "doc", "c-standard-library-%s-h.html" % h))
    rows.append(("C 标准库（中文）", "doc", "index.html"))
    n = build_dsidx(out, rows)
    open(os.path.join(out, "Contents", "Info.plist"), "w", encoding="utf-8").write(
        plist(IDENT, NAME, FAMILY, KEYWORD))
    report(out, docs, n)


if __name__ == "__main__":
    main()
