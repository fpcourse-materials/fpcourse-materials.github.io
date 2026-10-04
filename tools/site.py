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

ROOT = Path(__file__).resolve().parents[1]
FORMATS = {"publish.html": "Слайды", "publish-pauses.html": "По шагам", "publish.pdf": "Слайды в PDF", "paper.pdf": "Листок упражнений"}
KINDS = {"practices": "Практики", "lectures": "Лекции", "sessions": "Справочники"}


def catalog():
    data = json.loads((ROOT / "materials.json").read_text())
    if data["schema_version"] != 1:
        raise ValueError("Unsupported catalog version")
    seen = set()
    for lesson in data["lessons"]:
        key = (lesson["course"], lesson["id"])
        if key in seen or lesson["course"] not in {"fp1", "fp2"} or lesson["kind"] not in KINDS or not re.fullmatch(r"[pls]\d{2}", lesson["id"]):
            raise ValueError(f"Invalid or duplicate lesson: {key}")
        seen.add(key)
        if not lesson["formats"] or set(lesson["formats"]) - FORMATS.keys():
            raise ValueError(f"Invalid publication formats: {key}")
    for item in data["notes"] + data["archive"]:
        for filename in item.get("files", [item.get("file")]):
            if not filename or Path(filename).name != filename or not filename.endswith(".pdf"):
                raise ValueError(f"Invalid document export: {filename}")
    for item in data["homework"]:
        if not item["url"].startswith("https://github.com/fpcourse-students/"):
            raise ValueError("Homework must link to a student repository")
    return data


def exports(data):
    for lesson in data["lessons"]:
        for fmt in lesson["formats"]:
            relative = Path(lesson["course"]) / "2026" / lesson["kind"] / lesson["id"] / f'{lesson["id"]}-{fmt}'
            yield "slides", Path("out") / lesson["course"] / lesson["id"] / f'{lesson["id"]}-{fmt}', relative
    for item in data["notes"]:
        yield "docs", Path(item["file"]), Path("fp2/2026/notes") / item["file"]
    for item in data["archive"]:
        for filename in item["files"]:
            yield "docs", Path(filename), Path("archive/fp1/2025") / filename


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


def import_materials(data, slides, docs):
    sources = {"slides": slides.resolve(), "docs": docs.resolve()}
    decks = " ".join(f'{x["course"]}/{x["id"]}' for x in data["lessons"])
    papers = " ".join(f'{x["course"]}/{x["id"]}' for x in data["lessons"] if "paper.pdf" in x["formats"])
    subprocess.run(["make", "-C", str(slides), "public", f"PUBLIC_DECKS={decks}", f"PAPER_DECKS={papers}"], check=True)
    pending = ROOT / "out/import"
    if pending.exists():
        shutil.rmtree(pending)
    pending.mkdir(parents=True)
    records = {}
    for source, original, relative in exports(data):
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
        records[str(relative)] = {"source": source, "export": str(original), "sha256": sha(destination), "bytes": destination.stat().st_size}
    provenance = {
        "imported_at": datetime.now(timezone.utc).isoformat(),
        "sources": {name: {"repository": data["sources"][name], **source_revision(path)} for name, path in sources.items()},
        "files": records,
    }
    target = ROOT / "materials"
    if target.exists():
        shutil.rmtree(target)
    shutil.move(str(pending), target)
    (ROOT / "publication.json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + "\n")
    print(f"Imported {len(records)} selected exports")


def write_page(project, path, title, body, toc=True):
    target = project / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f'---\ntitle: {json.dumps(title, ensure_ascii=False)}\ntoc: {str(toc).lower()}\n---\n\n{body.strip()}\n')


def lesson_path(lesson):
    return f'{lesson["course"]}/2026/{lesson["kind"]}/{lesson["id"]}'


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
    shutil.copytree(ROOT / "materials", project / "materials")
    homework = {item["id"]: item for item in data["homework"]}
    for lesson in data["lessons"]:
        path = lesson_path(lesson)
        label = "Практика" if lesson["kind"] == "practices" else "Лекция" if lesson["kind"] == "lectures" else "Справочник"
        title = f'{label} {int(lesson["id"][1:])}. {lesson["title"]}'
        buttons = "\n".join(f'<a href="/materials/{path}/{lesson["id"]}-{fmt}">{FORMATS[fmt]}</a>' for fmt in lesson["formats"])
        body = f'[ФП {lesson["course"][-1]} · осень 2026](../../index.qmd)\n\n{lesson["description"]}\n\n<div class="material-links">\n{buttons}\n</div>\n\n## Перед занятием\n\n{lesson["prerequisites"]}\n\n## Самостоятельная работа\n\nОткройте версию «По шагам» и попробуйте ответить на вопрос или решить задачу до следующего клика. Обычная версия слайдов и PDF подходят для повторения.'
        if "paper.pdf" in lesson["formats"]:
            body += "\n\nЛисток упражнений — один двусторонний лист A4 с условиями и местом для записей."
        if lesson.get("homework"):
            hw = homework[lesson["homework"]]
            body += f'\n\n## Домашнее задание\n\n[Домашнее задание {hw["id"]}: {hw["title"]}]({hw["url"]}). Условия и инструкции по работе находятся в README репозитория.'
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
        if course == "fp1":
            body += "\n\n## Домашние задания\n\n" + "\n".join(f'- [{item["id"]} · {item["title"]}]({item["url"]})' for item in data["homework"])
            body += "\n\nУсловия, настройка окружения и инструкции по сдаче находятся в README каждого задания.\n\n## Другие темы\n\n[Практики 6–14 и эпилог в версии 2025 года](../../archive/fp1-2025.qmd)."
        else:
            body += "\n\n## Конспект\n\n" + "\n".join(f'- [{item["title"]}](/materials/fp2/2026/notes/{item["file"]}) — {item["description"]}' for item in data["notes"])
        write_page(project, f"{course}/2026/index.qmd", f"ФП {course[-1]} · осень 2026", body)
    body = "Практики прошлой итерации курса. Обычный PDF удобен для чтения; PDF с паузами показывает промежуточные состояния слайдов.\n\n"
    for item in data["archive"]:
        label = f'Практика {int(item["id"])}. ' if item["id"].isdigit() else ""
        links = " · ".join(f'[{"PDF с паузами" if "-pause.pdf" in name else "PDF"}](/materials/archive/fp1/2025/{name})' for name in item["files"])
        body += f'## {label}{item["title"]}\n\n{links}\n\n'
    write_page(project, "archive/fp1-2025.qmd", "ФП 1 · осень 2025", body)
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
    html_pages = [p for p in site.rglob("*.html") if "materials" not in p.relative_to(site).parts]
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
    expected = {str(relative) for _, _, relative in exports(data)}
    actual = {str(p.relative_to(site / "materials")) for p in (site / "materials").rglob("*") if p.is_file()}
    if actual != expected:
        errors.append("Deployment contains missing or unexpected teaching exports")
    for relative in expected:
        published = site / "materials" / relative
        if published.is_file() and sha(published) != sha(ROOT / "materials" / relative):
            errors.append(f"Deployment export differs: {relative}")
    if not (site / "search.json").is_file():
        errors.append("Search index missing")
    if errors:
        raise ValueError("\n".join(errors))
    print(f"Verified {len(html_pages)} pages, all local links/anchors, search index, and {len(expected)} export checksums")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["import", "prepare", "check"])
    parser.add_argument("--slides", type=Path)
    parser.add_argument("--docs", type=Path)
    args = parser.parse_args()
    data = catalog()
    if args.command == "import":
        if not args.slides or not args.docs:
            parser.error("import requires --slides and --docs")
        import_materials(data, args.slides, args.docs)
    elif args.command == "prepare":
        prepare(data)
    else:
        check(data)


if __name__ == "__main__":
    main()
