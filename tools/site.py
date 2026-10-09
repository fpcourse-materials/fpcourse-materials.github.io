#!/usr/bin/env python3
"""Import explicitly selected exports, assemble Quarto pages, verify publication."""
import argparse
from datetime import datetime, timezone
import hashlib
from html import escape
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import shutil
import subprocess
from urllib.parse import unquote, urlsplit
from urllib.error import HTTPError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
FORMATS = {"publish.html": "Слайды", "publish-pauses.html": "По шагам", "publish.pdf": "Слайды в PDF", "paper.pdf": "Листок упражнений"}
KINDS = {"practices": "Практики", "lectures": "Лекции", "sessions": "Справочники"}


def catalog():
    data = json.loads((ROOT / "materials.json").read_text())
    if data["schema_version"] != 1:
        raise ValueError("Unsupported catalog version")
    if not re.fullmatch(r"\d{4}", data["year"]):
        raise ValueError("Invalid publication year")
    seen = set()
    for lesson in data["lessons"]:
        key = (lesson["course"], lesson["id"])
        if key in seen or lesson["course"] not in {"fp1", "fp2"} or lesson["kind"] not in KINDS or not re.fullmatch(r"[pls]\d{2}", lesson["id"]):
            raise ValueError(f"Invalid or duplicate lesson: {key}")
        seen.add(key)
        if not lesson["formats"] or set(lesson["formats"]) - FORMATS.keys():
            raise ValueError(f"Invalid publication formats: {key}")
    for item in data["notes"]:
        for filename in item.get("files", [item.get("file")]):
            if not filename or Path(filename).name != filename or not filename.endswith(".pdf"):
                raise ValueError(f"Invalid document export: {filename}")
    for item in data["homework"]:
        if not item["url"].startswith("https://github.com/fpcourse-students/"):
            raise ValueError("Homework must link to a student repository")
    homework_keys = {(item["course"], item["id"]) for item in data["homework"]}
    if len(homework_keys) != len(data["homework"]):
        raise ValueError("Duplicate homework within a course")
    for lesson in data["lessons"]:
        if lesson.get("homework") and (lesson["course"], lesson["homework"]) not in homework_keys:
            raise ValueError(f'Homework missing for {lesson["course"]}/{lesson["id"]}')
    return data


def exports(data):
    for lesson in data["lessons"]:
        for fmt in lesson["formats"]:
            relative = Path(lesson_path(lesson, data["year"])) / f'{lesson["id"]}-{fmt}'
            yield "slides", Path("out") / lesson["course"] / lesson["id"] / f'{lesson["id"]}-{fmt}', relative
    for item in data["notes"]:
        yield "docs", Path(item["file"]), Path(data["year"]) / "fp2/notes" / item["file"]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def preserve_browser_navigation(path):
    html = path.read_text()
    snippet = (ROOT / "assets/browser-navigation.html").read_text()
    if 'id="fp-browser-navigation"' in html:
        if html.index('id="fp-browser-navigation"') > html.rfind("Reveal.initialize({"):
            return False
        # Reveal's embedded speaker-view template also contains a closing body tag.
        # Repair an earlier insertion into that template before touching the document.
        if snippet not in html:
            raise ValueError(f"Unexpected existing navigation script: {path}")
        html = html.replace(snippet + "\n", "", 1)
    if "</body>" not in html or "Reveal.initialize(" not in html:
        raise ValueError(f"Not a Reveal slide export: {path}")
    at = html.rfind("</body>")
    path.write_text(html[:at] + snippet + "\n" + html[at:])
    return True


def fix_navigation(data):
    provenance = integrity(data)
    count = 0
    for relative, record in provenance["files"].items():
        path = ROOT / "materials" / relative
        if path.suffix == ".html" and preserve_browser_navigation(path):
            record["sha256"] = sha(path)
            record["bytes"] = path.stat().st_size
            transformations = record.setdefault("transformations", [])
            if "preserve-browser-navigation" not in transformations:
                transformations.append("preserve-browser-navigation")
            count += 1
    provenance["navigation_updated_at"] = datetime.now(timezone.utc).isoformat()
    (ROOT / "publication.json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + "\n")
    print(f"Updated browser navigation in {count} slide exports")


def source_revision(path):
    def git(*args):
        return subprocess.check_output(["git", "-C", str(path), *args], text=True).strip()
    # Identify the working source version without publishing private source contents.
    digest = hashlib.sha256()
    files = subprocess.check_output(["git", "-C", str(path), "ls-files", "--cached", "--others", "--exclude-standard", "-z"]).decode().split("\0")
    for name in sorted(set(filter(None, files))):
        source = path / name
        if source.is_file():
            digest.update(name.encode() + b"\0" + bytes.fromhex(sha(source)))
    return {"revision": git("rev-parse", "HEAD"), "working_tree_sha256": digest.hexdigest(), "working_tree_modified": bool(git("status", "--porcelain"))}


def import_materials(data, slides, docs, course=None, lesson=None):
    sources = {"slides": slides.resolve(), "docs": docs.resolve()}
    lessons = [x for x in data["lessons"] if (course is None or x["course"] == course) and (lesson is None or x["id"] == lesson)]
    if not lessons:
        raise ValueError("No matching lessons in the publication catalog")
    decks = " ".join(f'{x["course"]}/{x["id"]}' for x in lessons)
    papers = " ".join(f'{x["course"]}/{x["id"]}' for x in lessons if "paper.pdf" in x["formats"])
    subprocess.run(["make", "-C", str(slides), "public", f"PUBLIC_DECKS={decks}", f"PAPER_DECKS={papers}"], check=True)
    versions = {name: {"repository": data["sources"][name], **source_revision(path)} for name, path in sources.items()}
    previous = json.loads((ROOT / "publication.json").read_text()) if course or lesson else None
    pending = ROOT / "out/import"
    if pending.exists():
        shutil.rmtree(pending)
    pending.mkdir(parents=True)
    records = {}
    for source, original, relative in exports(data):
        if (course and relative.parts[1] != course) or (lesson and relative.parts[3] != lesson):
            record = previous["files"][str(relative)].copy()
            path = ROOT / "materials" / relative
            if not path.is_file() or sha(path) != record["sha256"] or path.stat().st_size != record["bytes"]:
                raise ValueError(f"Existing publication export differs: {relative}")
            destination = pending / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)
            record.setdefault("source_version", previous["sources"][source])
            records[str(relative)] = record
            continue
        path = sources[source] / original
        if not path.is_file():
            raise FileNotFoundError(f"Missing export: {path}")
        if path.suffix == ".pdf" and not path.read_bytes().startswith(b"%PDF-"):
            raise ValueError(f"Invalid PDF: {path}")
        if path.suffix == ".html":
            html = path.read_text()
            if "<!-- katex-inlined -->" not in html or re.search(r'<aside\b[^>]*class="[^"]*\bnotes\b', html):
                raise ValueError(f"Export lacks inline math or contains speaker notes: {path}")
        destination = pending / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
        patched = destination.suffix == ".html" and preserve_browser_navigation(destination)
        records[str(relative)] = {"source": source, "export": str(original), "sha256": sha(destination), "bytes": destination.stat().st_size, "source_version": versions[source]}
        if patched:
            records[str(relative)]["transformations"] = ["preserve-browser-navigation"]
    provenance = {
        "imported_at": datetime.now(timezone.utc).isoformat(),
        "sources": versions,
        "files": records,
    }
    target = ROOT / "materials"
    if target.exists():
        shutil.rmtree(target)
    shutil.move(str(pending), target)
    (ROOT / "publication.json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + "\n")
    print(f"Imported {len(records)} selected exports")


def sync_catalog(data):
    """Relocate/restrict existing exports without rebuilding their source checkouts."""
    provenance = json.loads((ROOT / "publication.json").read_text())
    previous = {}
    for relative, record in provenance["files"].items():
        path = ROOT / "materials" / relative
        if not path.is_file() or sha(path) != record["sha256"]:
            raise ValueError(f"Existing publication export differs: {relative}")
        previous[(record["source"], record["export"])] = (path, record)
    pending = ROOT / "out/catalog-sync"
    if pending.exists():
        shutil.rmtree(pending)
    pending.mkdir(parents=True)
    records = {}
    for source, original, relative in exports(data):
        key = (source, str(original))
        if key not in previous:
            raise ValueError(f"New export requires make import: {original}")
        path, record = previous[key]
        destination = pending / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
        records[str(relative)] = record
    shutil.rmtree(ROOT / "materials")
    shutil.move(str(pending), ROOT / "materials")
    provenance["files"] = records
    provenance["catalog_updated_at"] = datetime.now(timezone.utc).isoformat()
    (ROOT / "publication.json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + "\n")
    print(f"Synchronized catalog: {len(records)} selected exports")


def write_page(project, path, title, body, toc=True):
    target = project / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f'---\ntitle: {json.dumps(title, ensure_ascii=False)}\ntoc: {str(toc).lower()}\n---\n\n{body.strip()}\n')


def lesson_path(lesson, year):
    return f'{year}/{lesson["course"]}/{lesson["kind"]}/{lesson["id"]}'


def list_lessons(lessons, prefix=""):
    items = []
    for lesson in lessons:
        path = f'{prefix}{lesson["kind"]}/{lesson["id"]}/'
        label = f'{lesson["id"].upper()} · {lesson["title"]}'
        items.append(f'<li><a href="{escape(path)}">{escape(label)}</a><small>{escape(lesson["description"])}</small></li>')
    return '<ul class="lesson-list">\n' + "\n".join(items) + "\n</ul>"


def integrity(data):
    expected = {str(relative) for _, _, relative in exports(data)}
    actual = {str(p.relative_to(ROOT / "materials")) for p in (ROOT / "materials").rglob("*") if p.is_file()}
    provenance = json.loads((ROOT / "publication.json").read_text())
    if expected != actual or set(provenance["files"]) != expected:
        raise ValueError(f"Publication/catalog mismatch: missing={expected - actual}, unexpected={actual - expected}")
    for relative, record in provenance["files"].items():
        path = ROOT / "materials" / relative
        if sha(path) != record["sha256"] or path.stat().st_size != record["bytes"]:
            raise ValueError(f"Export changed without import: {relative}")
    return provenance


def prepare(data):
    integrity(data)
    project = ROOT / "out/project"
    rendered = ROOT / "out/site"
    if rendered.exists():
        shutil.rmtree(rendered)
    if project.exists():
        shutil.rmtree(project)
    shutil.copytree(ROOT / "pages", project)
    for name in ["_quarto.yml", "theme.scss", "favicon.svg", "publication.json"]:
        shutil.copyfile(ROOT / name, project / name)
    shutil.copytree(ROOT / "materials", project, dirs_exist_ok=True)
    homework = {(item["course"], item["id"]): item for item in data["homework"]}
    for lesson in data["lessons"]:
        path = lesson_path(lesson, data["year"])
        label = "Практика" if lesson["kind"] == "practices" else "Лекция" if lesson["kind"] == "lectures" else "Справочник"
        title = f'{label} {int(lesson["id"][1:])}. {lesson["title"]}'
        buttons = "\n".join(f'<a class="no-external" href="/{path}/{lesson["id"]}-{fmt}">{FORMATS[fmt]}</a>' for fmt in lesson["formats"])
        hw = homework.get((lesson["course"], lesson.get("homework")))
        if hw:
            buttons += f'\n<a href="{escape(hw["url"], quote=True)}">Домашнее задание</a>'
        body = f'[ФП {lesson["course"][-1]} · осень 2026](../../index.qmd)\n\n{lesson["description"]}\n\n<div class="material-links">\n{buttons}\n</div>\n\n## Перед занятием\n\n{lesson["prerequisites"]}\n\n## Самостоятельная работа\n\nОткройте версию «По шагам» и попробуйте ответить на вопрос или решить задачу до следующего клика. Обычная версия слайдов и PDF подходят для повторения.'
        if "paper.pdf" in lesson["formats"]:
            body += "\n\nЛисток упражнений — один двусторонний лист A4 с условиями и местом для записей."
        if hw:
            body += "\n\nУсловия домашнего задания и инструкции по работе находятся в README по кнопке «Домашнее задание»."
            if hw.get("visibility") == "private":
                body += " Для этого задания нужен доступ к закрытому репозиторию курса в GitHub."
        siblings = [x for x in data["lessons"] if x["course"] == lesson["course"] and x["kind"] == lesson["kind"]]
        position = siblings.index(lesson)
        links = []
        for index, direction in [(position - 1, "← Предыдущее занятие"), (position + 1, "Следующее занятие →")]:
            if 0 <= index < len(siblings):
                sibling = siblings[index]
                links.append(f'[{direction}: {sibling["title"]}](../{sibling["id"]}/index.qmd)')
        body += "\n\n" + " · ".join(links)
        write_page(project, path + "/index.qmd", title, body)
    for course in ["fp1", "fp2"]:
        selected = [x for x in data["lessons"] if x["course"] == course]
        body = "Слайды и PDF к занятиям. Версия «По шагам» раскрывает примеры и решения по клику."
        for kind, title in KINDS.items():
            group = [x for x in selected if x["kind"] == kind]
            if group:
                body += f"\n\n## {title}\n\n" + list_lessons(group)
        if course == "fp2" and data["notes"]:
            body += "\n\n## Конспект\n\n" + "\n".join(f'- [{item["title"]}](/{data["year"]}/fp2/notes/{item["file"]}) — {item["description"]}' for item in data["notes"])
        write_page(project, f'{data["year"]}/{course}/index.qmd', f'ФП {course[-1]} · осень {data["year"]}', body)
    print(f"Prepared {len(list(project.rglob('*.qmd')))} pages")


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.ids = set()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get("id"):
            self.ids.add(attrs["id"])
        for attribute in ["href", "src"]:
            if attrs.get(attribute):
                self.links.append(attrs[attribute])


def check(data):
    integrity(data)
    site = ROOT / "out/site"
    if not (site / "index.html").is_file():
        raise ValueError("Build the site first")
    expected = {str(relative) for _, _, relative in exports(data)}
    html_pages = [p for p in site.rglob("*.html") if str(p.relative_to(site)) not in expected]
    parsed = {}
    for path in html_pages:
        parser = Links()
        parser.feed(path.read_text())
        parsed[path.resolve()] = parser
    errors = []
    for path, page in parsed.items():
        for link in page.links:
            url = urlsplit(link)
            if url.scheme or url.netloc or link.startswith("javascript:"):
                continue
            if not url.path:
                destination = path
            else:
                destination = (site / unquote(url.path.lstrip("/")) if url.path.startswith("/") else path.parent / unquote(url.path)).resolve()
                if destination.is_dir():
                    destination /= "index.html"
            if not destination.is_relative_to(site.resolve()) or not destination.is_file():
                errors.append(f"{path.relative_to(site)}: missing {link}")
            elif url.fragment and destination in parsed and unquote(url.fragment) not in parsed[destination].ids:
                errors.append(f"{path.relative_to(site)}: missing anchor {link}")
    actual = {str(p.relative_to(site)) for p in (site / data["year"]).rglob("*") if p.is_file() and p.suffix in {".html", ".pdf"} and p.name != "index.html"}
    if actual != expected:
        errors.append("Deployment contains missing or unexpected teaching exports")
    for relative in expected:
        published = site / relative
        if published.is_file() and sha(published) != sha(ROOT / "materials" / relative):
            errors.append(f"Deployment export differs: {relative}")
        if published.suffix == ".html":
            html = published.read_text()
            marker = 'id="fp-browser-navigation"'
            if marker not in html or html.index(marker) < html.rfind("Reveal.initialize({"):
                errors.append(f"Slide export lacks a correctly placed browser navigation fix: {relative}")
    if not (site / "search.json").is_file():
        errors.append("Search index missing")
    if any((site / path).exists() for path in ["archive", "materials", "fp1", "fp2", "2025"]):
        errors.append("Obsolete course-first or archive paths remain in deployment")
    if errors:
        raise ValueError("\n".join(errors))
    print(f"Verified {len(html_pages)} pages, all local links/anchors, search index, and {len(expected)} export checksums")


def check_live(data):
    provenance = integrity(data)
    base = "https://fpcourse-materials.github.io/"
    for path, expected in [("", "Функциональное программирование")] + [(lesson_path(lesson, data["year"]) + "/", lesson["title"]) for lesson in data["lessons"]]:
        with urlopen(base + path, timeout=30) as response:
            body = response.read().decode()
            if response.status != 200 or expected not in body:
                raise ValueError(f"Unexpected deployed page: {path}")
    with urlopen(base + "search.json", timeout=30) as response:
        index = json.load(response)
        for lesson in data["lessons"]:
            if not any(lesson["title"] in item.get("title", "") for item in index):
                raise ValueError(f'Deployed search index lacks {lesson["id"]}')
    with urlopen(base + "publication.json", timeout=30) as response:
        if json.load(response)["files"] != provenance["files"]:
            raise ValueError("Deployed publication list differs from the selected catalog")
    samples = [relative for relative in provenance["files"] if relative.endswith(("publish.html", "paper.pdf"))][:2]
    samples += [relative for relative in provenance["files"] if "/fp2/lectures/" in relative and relative.endswith(("publish.html", "publish.pdf"))]
    samples += [relative for relative in provenance["files"] if "/notes/" in relative]
    latest_practice = [lesson for lesson in data["lessons"] if lesson["course"] == "fp1" and lesson["kind"] == "practices"][-1]
    samples += [relative for relative in provenance["files"] if relative.startswith(lesson_path(latest_practice, data["year"]) + "/")]
    for relative in samples:
        with urlopen(base + relative, timeout=30) as response:
            if hashlib.sha256(response.read()).hexdigest() != provenance["files"][relative]["sha256"]:
                raise ValueError(f"Deployed file differs: {relative}")
    selected = {lesson_path(lesson, data["year"]) for lesson in data["lessons"]} | set(provenance["files"])
    for removed in ["archive/", "materials/fp2/2026/notes/fp2.pdf", "materials/archive/fp1/2025/mse2025-fp1-slides-01-handout.pdf", "fp1/2026/practices/p05/", "fp2/2026/lectures/l03/", f'{data["year"]}/fp1/practices/p05/', f'{data["year"]}/fp1/sessions/s01/', f'{data["year"]}/fp2/lectures/l03/', f'{data["year"]}/fp2/notes/fp2.pdf', f'{data["year"]}/fp2/notes/fp2-ch1-3.1.4.pdf']:
        if removed.rstrip("/") in selected:
            continue
        try:
            with urlopen(base + removed, timeout=30):
                raise ValueError(f"Removed material is still published: {removed}")
        except HTTPError as error:
            if error.code != 404:
                raise
    print("Live year-first pages, search, selected downloads and removed-material 404s verified")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["import", "fix-navigation", "sync-catalog", "prepare", "check", "live"])
    parser.add_argument("--slides", type=Path)
    parser.add_argument("--docs", type=Path)
    parser.add_argument("--course", choices=["fp1", "fp2"], help="Rebuild this course and retain other courses' existing exports")
    parser.add_argument("--lesson", help="Rebuild one lesson and retain the other exports; requires --course")
    args = parser.parse_args()
    data = catalog()
    if args.command == "import":
        if not args.slides or not args.docs:
            parser.error("import requires --slides and --docs")
        if args.lesson and not args.course:
            parser.error("--lesson requires --course")
        import_materials(data, args.slides, args.docs, args.course, args.lesson)
    elif args.command == "fix-navigation":
        fix_navigation(data)
    elif args.command == "sync-catalog":
        sync_catalog(data)
    elif args.command == "prepare":
        prepare(data)
    elif args.command == "check":
        check(data)
    else:
        check_live(data)


if __name__ == "__main__":
    main()
