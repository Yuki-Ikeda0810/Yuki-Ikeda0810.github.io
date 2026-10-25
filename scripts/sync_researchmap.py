"""Fetch public researchmap data and render the marked parts of both pages."""

import argparse
from datetime import datetime, timezone
from html import escape
import json
from pathlib import Path
import re
import sys
from urllib.request import Request, urlopen
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
API = "https://api.researchmap.jp/yukiikeda"
PROFILE = "https://researchmap.jp/yukiikeda"
CACHE = ROOT / "data/researchmap.json"
TYPES = ("research_experience", "published_papers", "presentations", "media_coverage")


def localized(value, lang):
    if isinstance(value, dict):
        return value.get(lang) or value.get("ja") or value.get("en") or ""
    return value if isinstance(value, str) else ""


def public_items(items):
    return [item for item in items if item.get("display", "disclosed") == "disclosed"]


def normalize(raw):
    if raw.get("permalink") != "yukiikeda" or not isinstance(raw.get("affiliations"), list):
        raise ValueError("Unexpected researchmap profile response")
    groups = {group["@type"]: group for group in raw.get("@graph", [])}
    if not all(kind in groups for kind in TYPES):
        raise ValueError("Required researchmap sections are missing")
    # Store only the fields used by this site, not the entire researcher record.
    affiliations = []
    for item in raw["affiliations"]:
        entry = {}
        if item.get("display_affiliation", "disclosed") == "disclosed":
            entry.update({key: item[key] for key in ("affiliation", "section") if key in item})
        if item.get("display_job", "disclosed") == "disclosed":
            entry.update({key: item[key] for key in ("job",) if key in item})
        if entry:
            affiliations.append(entry)
    fields = ("@id", "affiliation", "section", "job", "from_date", "to_date",
              "paper_title", "presentation_title", "publication_name", "event",
              "publication_date", "from_event_date", "authors", "presenters",
              "media_coverage_title", "publisher", "description", "see_also")
    result = {"schema_version": 3, "source": PROFILE,
              "synced_at": datetime.now(timezone.utc).isoformat(),
              "affiliations": affiliations}
    for kind in TYPES:
        group = groups[kind]
        if not isinstance(group.get("items"), list):
            raise ValueError(f"Invalid {kind} response")
        # Career must be complete. Publications are explicitly displayed as a preview.
        if kind == "research_experience" and group.get("total_items", 0) > len(group["items"]):
            raise ValueError("Career response is incomplete; retaining previous data")
        result[kind] = {
            "total": group.get("total_items", len(group["items"])),
            "items": [{key: item[key] for key in fields if key in item}
                      for item in public_items(group["items"])],
        }
    return result


def fetch():
    request = Request(API, headers={"Accept": "application/json", "User-Agent": "YukiIkedaPortfolio/1.0"})
    with urlopen(request, timeout=45) as response:
        return normalize(json.loads(response.read().decode("utf-8-sig")))


def text(value):
    return escape(str(value), quote=True)


def researchmap_url(path, lang):
    return f'{path}?lang={lang}'


def safe_external_url(value):
    if not isinstance(value, str) or any(c.isspace() or ord(c) < 32 for c in value):
        return False
    try:
        parts = urlsplit(value)
        return parts.scheme in ("https", "http") and bool(parts.hostname) and not parts.username and not parts.password
    except ValueError:
        return False


def media_url(item, lang):
    # Only explicitly labelled URLs select a language; prose URLs are ignored.
    description = item.get("description", {})
    descriptions = ([description.get(lang, ""), description.get("ja" if lang == "en" else "en", "")]
                    if isinstance(description, dict) else [description])
    label = "JP" if lang == "ja" else "EN"
    for value in descriptions:
        if not isinstance(value, str):
            continue
        for match in re.finditer(r'URL\s*\(\s*' + label + r'\s*\)\s*:\s*(\S+)', value, re.I):
            if safe_external_url(match[1]):
                return match[1]
    for link in item.get("see_also", []):
        if isinstance(link, dict) and safe_external_url(link.get("@id")):
            return link["@id"]
    url = item.get("@id", "").replace(API + "/", PROFILE + "/", 1)
    if not url.startswith(PROFILE + "/media_coverage/"):
        url = PROFILE + "/media_coverage"
    return researchmap_url(url, lang)


def period(item, lang):
    start = item.get("from_date", "")
    end = item.get("to_date", "")
    if not end or end.startswith("9999"):
        end = "現在" if lang == "ja" else "Present"
    return f"{start} {'～' if lang == 'ja' else '–'} {end}"


def affiliation(item, lang):
    # Display researchmap affiliation data without adding organization links.
    return " / ".join(
        text(localized(item.get(key), lang).strip())
        for key in ("affiliation", "section", "job")
        if localized(item.get(key), lang).strip()
    )


def source_note(data, lang):
    label = "最終取得" if lang == "ja" else "Last synced"
    return (f'<p class="sync-note">{label}: {text(data["synced_at"][:10])} (UTC) · '
            f'<a href="{researchmap_url(PROFILE, lang)}" target="_blank" rel="noopener noreferrer">researchmap ↗</a></p>')


def render_career(data, lang):
    ja = lang == "ja"
    heading = "所属・経歴" if ja else "Affiliations &amp; experience"
    result = [f'<div class="section-title"><p>02 / CAREER</p><h2>{heading}</h2></div>',
              source_note(data, lang),
              f'<h3>{"現在の所属" if ja else "Current affiliations"}</h3>',
              '<ul class="affiliation-list">']
    result += [f'<li>{affiliation(item, lang)}</li>' for item in data["affiliations"]]
    result += ['</ul>', f'<h3>{"経歴" if ja else "Experience"}</h3>', '<div class="career">']
    items = sorted(data["research_experience"]["items"], key=lambda x: x.get("from_date", ""), reverse=True)
    for item in items:
        result.append(f'<div><span>{text(period(item, lang))}</span><h4>{affiliation(item, lang)}</h4></div>')
    if not items:
        result.append(f'<p>{"公開されている経歴はありません。" if ja else "No public experience records available."}</p>')
    result.append('</div>')
    return "\n".join(result)


def render_publications(data, lang):
    ja = lang == "ja"
    result = [source_note(data, lang)]
    for kind, title, field, limit in (
        ("published_papers", "論文" if ja else "Publications", "paper_title", 10),
        ("presentations", "講演・口頭発表" if ja else "Presentations", "presentation_title", 10),
    ):
        group = data[kind]
        items = sorted(group["items"], key=lambda x: x.get("publication_date", x.get("from_event_date", "")), reverse=True)[:limit]
        count = f'公開登録 {group["total"]}件 / {len(items)}件を表示' if ja else f'{len(items)} shown / {group["total"]} public records'
        result += [f'<h3>{title}</h3>', f'<p class="sync-note">{text(count)}</p>', '<ol class="publication-list">']
        for item in items:
            name = localized(item.get(field), lang) or ("無題" if ja else "Untitled")
            # Only known researchmap URLs are emitted; remote text is always escaped.
            url = item.get("@id", "").replace(API + "/", PROFILE + "/", 1)
            if not url.startswith(PROFILE + "/"):
                url = PROFILE
            url = researchmap_url(url, lang)
            authors = localized(item.get("authors", item.get("presenters", {})), lang)
            authors = ", ".join(person.get("name", "") for person in authors) if isinstance(authors, list) else authors
            venue = localized(item.get("publication_name", item.get("event", {})), lang)
            date = item.get("publication_date", item.get("from_event_date", ""))
            metadata = " · ".join(value for value in (authors, venue, date) if value)
            result.append(f'<li><a href="{text(url)}" target="_blank" rel="noopener noreferrer">{text(name)}</a><p>{text(metadata)}</p></li>')
        result.append('</ol>')
        if not items:
            result.append(f'<p>{"公開情報はありません。" if ja else "No public records available."}</p>')
    label = "すべての研究業績をresearchmapで見る ↗" if ja else "View all research outputs on researchmap ↗"
    result.append(f'<a class="primary" href="{researchmap_url(PROFILE, lang)}" target="_blank" rel="noopener noreferrer">{label}</a>')
    return "\n".join(result)


def render_media(data, lang):
    """Render a compact preview; full articles remain on their original sites."""
    ja = lang == "ja"
    group = data.get("media_coverage")
    if group is None:
        # Older snapshots have no media data; do not report this as zero records.
        message = "メディア報道は次回の同期成功時に取得します。" if ja else "Media coverage will be available after the next successful sync."
        return f'<p>{message}</p><a href="{researchmap_url(PROFILE + "/media_coverage", lang)}" target="_blank" rel="noopener noreferrer">researchmap ↗</a>'
    items = sorted(group["items"], key=lambda item: item.get("publication_date", ""), reverse=True)[:10]
    count = f'公開登録 {group["total"]}件 / {len(items)}件を表示' if ja else f'{len(items)} shown / {group["total"]} public records'
    result = [source_note(data, lang), f'<p class="sync-note">{text(count)}</p>', '<ol class="publication-list">']
    for item in items:
        title = localized(item.get("media_coverage_title"), lang) or ("無題" if ja else "Untitled")
        url = media_url(item, lang)
        values = [localized(item.get(key), lang) for key in ("publisher", "event")]
        values.append(item.get("publication_date", ""))
        metadata = " · ".join(dict.fromkeys(value for value in values if value))
        result.append(f'<li><a href="{text(url)}" target="_blank" rel="noopener noreferrer">{text(title)}</a><p>{text(metadata)}</p></li>')
    result.append('</ol>')
    if not items:
        result.append(f'<p>{"公開されているメディア報道はありません。" if ja else "No public media coverage records available."}</p>')
    label = "すべてのメディア報道をresearchmapで見る ↗" if ja else "View all media coverage on researchmap ↗"
    result.append(f'<a class="primary" href="{researchmap_url(PROFILE + "/media_coverage", lang)}" target="_blank" rel="noopener noreferrer">{label}</a>')
    return "\n".join(result)


def replace_block(page, name, content):
    start = f'<!-- researchmap:{name}:start -->'
    end = f'<!-- researchmap:{name}:end -->'
    if page.count(start) != 1 or page.count(end) != 1:
        raise ValueError(f"Missing or duplicate {name} sync markers")
    return re.sub(re.escape(start) + r'.*?' + re.escape(end),
                  lambda _: start + "\n" + "\n".join("        " + line for line in content.splitlines()) + "\n        " + end,
                  page, flags=re.S)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="Render the saved snapshot without fetching")
    parser.add_argument("--allow-stale", action="store_true", help="Use saved snapshot if fetching fails")
    args = parser.parse_args()
    fresh = False
    if args.offline:
        data = json.loads(CACHE.read_text(encoding="utf-8"))
    else:
        try:
            data = fetch()
            fresh = True
        except Exception as error:
            if not args.allow_stale or not CACHE.exists():
                raise
            print(f"::warning::researchmap sync failed; using saved data: {error}", file=sys.stderr)
            data = json.loads(CACHE.read_text(encoding="utf-8"))
    # Validate/render both pages before writing anything.
    pages = []
    for lang, path in (("ja", ROOT / "index.html"), ("en", ROOT / "en/index.html")):
        page = path.read_text(encoding="utf-8")
        page = replace_block(page, "publications", render_publications(data, lang))
        page = replace_block(page, "career", render_career(data, lang))
        page = replace_block(page, "media", render_media(data, lang))
        pages.append((path, page))
    if fresh:
        CACHE.parent.mkdir(exist_ok=True)
        temporary = CACHE.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(CACHE)
    for path, page in pages:
        path.write_text(page, encoding="utf-8")
    print(f"Rendered both pages from researchmap snapshot: {data['synced_at']}")


if __name__ == "__main__":
    main()
