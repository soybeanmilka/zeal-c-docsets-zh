# -*- coding: utf-8 -*-
"""从 quericy/Zeal-docset-CN 的中文 Linux man 文档集里裁出 C/POSIX 部分，
做成第二个 Zeal/Dash 文档集（C-man-zh.docset）。

用法：
    python build_man_zh.py [工作目录]        # 默认 ./work/manzh

为什么要裁：
    那份 Linux.docset 共 734 条，但 section 分布是 nosect 292 / man7 142 / man3tcl 98 /
    man8 78 / man5 37 / man3tk 36 / man3 34 / man2 12 / man4 3 / man6 1 / man7tcl 1。
    - man7 那 142 条里绝大多数是 **PostgreSQL 的 SQL 命令**（alter_table / create_index /
      vacuum / grant …）和 **Perl 文档**（perlfunc / perlbook / perlfaq* …），真正属于
      Linux man7 的只有 signal / socket / tcp / unix 等三十来条 —— 留着只会污染搜索，整体丢掉。
    - man1 / man3tcl / man3tk / man8 / man5 是命令手册和 Tcl/Tk，与 C 无关。
    最后只留 man2（POSIX 系统调用）+ man3（库函数），并剔除菜鸟教程那份已经收录的同名函数。

    只裁索引，**HTML 页面全部保留** —— 这样 man 页之间的互相跳转不会 404。

数据来源：https://github.com/quericy/Zeal-docset-CN （中文 man 手册翻译，man-pages 原项目为 GPL）
"""
import os, re, sys, html, shutil, sqlite3, subprocess, tarfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from docset_lib import CSS, page_template, plist, build_dsidx, report

sys.stdout.reconfigure(encoding="utf-8")

SRC_URL = "https://api.github.com/repos/quericy/Zeal-docset-CN/contents/docsets/Linux.docset.tgz"
IDENT, NAME, FAMILY, KEYWORD = "c-man-zh", "C Linux 中文手册", "c", "c-man"

# 菜鸟教程那份已收录的函数，不再在 man 索引里重复登记
# （两边名字一样长时 Zeal 评分相同，谁赢看运气；留菜鸟那份，页面更好看）
SKIP_NAMES = {"clearerr", "exit", "fclose", "feof", "ferror", "fflush", "fopen", "freopen",
              "setbuf", "setlocale", "setvbuf", "strcoll", "strxfrm"}

SECTION_NAMES = {"2": "系统调用（man2）", "3": "库函数（man3）"}


def download(work):
    """下载并解压中文 Linux.docset，返回解压出来的 docset 目录。"""
    os.makedirs(work, exist_ok=True)
    tgz = os.path.join(work, "Linux.docset.tgz")
    if not os.path.exists(tgz) or os.path.getsize(tgz) < 100000:
        # raw.githubusercontent.com 在部分网络下不通，走 GitHub contents 接口取原始字节
        r = subprocess.run(["curl.exe", "-s", "--ssl-no-revoke", "-L", "--max-time", "300",
                            "-H", "Accept: application/vnd.github.raw", "-o", tgz, SRC_URL],
                           capture_output=True)
        if not os.path.exists(tgz) or os.path.getsize(tgz) < 100000:
            sys.exit("下载 Linux.docset.tgz 失败（%s）" % r.returncode)
    out = os.path.join(work, "src")
    if not os.path.exists(out):
        os.makedirs(out, exist_ok=True)
        with tarfile.open(tgz, "r:gz") as t:
            try:
                t.extractall(out, filter="data")   # Python 3.12+，避免 DeprecationWarning
            except TypeError:
                t.extractall(out)
    for root, dirs, _ in os.walk(out):
        for d in dirs:
            if d.endswith(".docset"):
                return os.path.join(root, d)
    sys.exit("解压后找不到 .docset 目录")


def covered_by_runoob(work):
    """如果本地已经构建过菜鸟那份，读出它收录的函数名，用来去重。"""
    db = os.path.join(os.path.dirname(work), "build", "C-zh-cn.docset",
                      "Contents", "Resources", "docSet.dsidx")
    if not os.path.exists(db):
        return set()
    con = sqlite3.connect("file:%s?mode=ro" % db.replace("\\", "/"), uri=True)
    names = {n for (n,) in con.execute("select name from searchIndex")}
    con.close()
    return names


def main():
    work = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.getcwd(), "work", "manzh")
    work = os.path.abspath(work)
    src = download(work)

    out = os.path.join(os.path.dirname(work), "build", "C-man-zh.docset")
    if os.path.exists(out):
        shutil.rmtree(out)
    shutil.copytree(src, out)

    res = os.path.join(out, "Contents", "Resources")
    docs = os.path.join(res, "Documents")
    con = sqlite3.connect(os.path.join(res, "docSet.dsidx"))
    rows = list(con.execute("select name,type,path from searchIndex"))
    con.close()

    keep = [(n, p) for n, t, p in rows if re.search(r"\.(2|3)\.html$", p)]
    already = covered_by_runoob(work)
    if already:
        dup = sorted(n for n, _ in keep if n in already)
        keep = [(n, p) for n, p in keep if n not in already]
        print("菜鸟已收录、跳过 %d 条: %s" % (len(dup), ", ".join(dup)))
    print("原始 %d 条 -> 保留 %d 条" % (len(rows), len(keep)))
    for sec in ("2", "3"):
        print("  man%s: %d" % (sec, sum(1 for n, p in keep if p.endswith(".%s.html" % sec))))

    n = build_dsidx(out, [(n, "func", p) for n, p in keep])

    # 首页
    def title_of(path):
        try:
            r = open(os.path.join(docs, path), encoding="utf-8", errors="replace").read(4000)
            m = re.search(r"<title>(.*?)</title>", r, re.S | re.I)
            return re.sub(r"\s+", " ", html.unescape(m.group(1))).strip() if m else path
        except Exception:
            return path

    groups = {}
    for n_, p in keep:
        groups.setdefault(re.search(r"\.(\d)\.html$", p).group(1), []).append((n_, p))
    items = [(SECTION_NAMES.get(s, "man" + s), n_, p)
             for s in sorted(groups) for n_, p in sorted(groups[s])]
    body = ["<h1>C / Linux 中文手册</h1>",
            '<div class="tip">共 <b>%d</b> 页，来自 <a href="https://github.com/quericy/Zeal-docset-CN">'
            "quericy/Zeal-docset-CN</a>（中文 man 手册翻译）。只保留了 man2/man3 里菜鸟教程"
            "没有收录的部分：POSIX 系统调用（open/read/write/close/socket…）和少数 stdio 函数。</div>"
            % len(keep)]
    for s in sorted(groups):
        body.append("<h2>%s</h2><table><tr><th style=\"width:30%%\">名称</th><th>页面标题</th></tr>"
                    % SECTION_NAMES.get(s, "man" + s))
        for n_, p in sorted(groups[s]):
            body.append('<tr><td><a href="%s">%s</a></td><td>%s</td></tr>'
                        % (p, html.escape(n_), html.escape(title_of(p))))
        body.append("</table>")
    open(os.path.join(docs, "index.html"), "w", encoding="utf-8").write(
        page_template(NAME, CSS, "首页", "\n".join(body)))

    open(os.path.join(out, "Contents", "Info.plist"), "w", encoding="utf-8").write(
        plist(IDENT, NAME, FAMILY, KEYWORD))
    report(out, docs, n)


if __name__ == "__main__":
    main()
