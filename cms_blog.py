
#!/usr/bin/env python3
"""Analytics4 blog CMS: recover legacy articles into Markdown, then publish CMS posts.

bootstrap: imports available article HTML into content/posts/<language>/*.md.
           Never overwrites existing Markdown. Does not change the public site.
build:     publishes only published CMS Markdown posts. Run after reviewing bootstrap.
"""
import argparse
import json
import re
from pathlib import Path
from urllib.parse import unquote, urlparse

import markdown
import yaml
from bs4 import BeautifulSoup
from markdownify import markdownify as to_md

import migrate_blog as legacy

ROOT = Path(__file__).resolve().parent
CONTENT = ROOT / 'content'
POSTS = CONTENT / 'posts'
LANGS = ('it', 'en', 'pl')
STATE = CONTENT / 'cms_generated_paths.json'


def read_json(path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (ValueError, UnicodeError) as exc:
        print(f'WARNING: Cannot parse {path.relative_to(ROOT)}: {exc}')
        return default


def clean_date(value):
    value = str(value or '')
    return value[:10] if re.match(r'^\d{4}-\d{2}-\d{2}', value) else '2026-01-01'


def image_path(value):
    value = str(value or '')
    if value.startswith('/analytics4/assets/blog/'):
        return value.removeprefix('/analytics4/')
    if value.startswith('/assets/blog/'):
        return value.lstrip('/')
    return value


def safe_slug(value):
    return bool(re.fullmatch(r'[A-Za-z0-9_-]+', str(value or '')))


def get_source_records():
    """Use JSON metadata only to locate actual HTML; do not trust its language labels."""
    grouped = read_json(CONTENT / 'blog_languages.json', {})
    records = {lang: {} for lang in LANGS}
    for lang in LANGS:
        for item in grouped.get(lang, []) if isinstance(grouped, dict) else []:
            if isinstance(item, dict) and safe_slug(item.get('slug')):
                records[lang][item['slug']] = item
        cards = read_json(CONTENT / f'blog_cards_{lang}.json', [])
        if isinstance(cards, list):
            for item in cards:
                if isinstance(item, dict) and safe_slug(item.get('slug')):
                    # Prefer full original source, but use cards to recover missing entries.
                    records[lang].setdefault(item['slug'], item)
    # Italian compatibility feed (older imports may have no per-language cards).
    cards = read_json(CONTENT / 'blog_cards.json', [])
    if isinstance(cards, list):
        for item in cards:
            if isinstance(item, dict) and safe_slug(item.get('slug')):
                records['it'].setdefault(item['slug'], item)
    return records


def article_page(lang, slug):
    locations = ([ROOT / 'Blog' / slug / 'index.html', ROOT / 'Blog' / 'it' / slug / 'index.html']
                 if lang == 'it' else [ROOT / 'Blog' / lang / slug / 'index.html'])
    return next((p for p in locations if p.is_file()), None)


def find_article_content(soup):
    """Try semantic article selectors first; refuse to import navigation-only pages."""
    selectors = [
        'article .entry-content', 'article .post-content', 'article .article-content',
        '.blog-post-content', '.post-body', '.article-body', '.entry-content',
        '.post-content', '.article-content', 'main article', 'article',
        'main .prose', 'main',
    ]
    for selector in selectors:
        for candidate in soup.select(selector):
            clone = BeautifulSoup(str(candidate), 'html.parser')
            for bad in clone.select('nav, footer, header, aside, script, style, form, .related-posts, .share-buttons, .breadcrumbs'):
                bad.decompose()
            text = clone.get_text(' ', strip=True)
            # At least 140 chars so we do not accidentally import an archive/card.
            if len(text) >= 140:
                return clone
    return None


def normalized_body(html, page, title):
    if not html and page:
        soup = BeautifulSoup(page.read_text(encoding='utf-8', errors='replace'), 'html.parser')
        content = find_article_content(soup)
        if content is None:
            return None
    elif html:
        content = BeautifulSoup(html, 'html.parser')
    else:
        return None
    for node in content.select('script, style, iframe, form'):
        node.decompose()
    for img in content.select('img[src]'):
        src = img.get('src', '')
        if src.startswith('assets/blog/') or src.startswith('/assets/blog/'):
            img['src'] = '/analytics4/' + src.lstrip('/')
    body = to_md(str(content), heading_style='ATX').strip()
    # Only remove first heading if it duplicates metadata title.
    lines = body.splitlines()
    if lines and lines[0].startswith('# ') and lines[0][2:].strip().casefold() == str(title).strip().casefold():
        body = '\n'.join(lines[1:]).strip()
    return body if len(re.sub(r'\s+', ' ', BeautifulSoup(str(content), 'html.parser').get_text(' ', strip=True))) >= 140 else None


def bootstrap():
    records = get_source_records()
    report = ['# CMS import review', '', 'This report is informational. No published pages were changed.',
              'Language labels from legacy URLs/feeds are NOT proof of the text language.',
              'Review every imported article before running the CMS publish workflow.', '']
    imported = 0
    for lang in LANGS:
        folder = POSTS / lang
        folder.mkdir(parents=True, exist_ok=True)
        count = 0
        skipped = []
        for slug, post in sorted(records[lang].items()):
            target = folder / f'{slug}.md'
            if target.exists():
                continue  # Protect all CMS changes.
            page = article_page(lang, slug)
            title = str(post.get('title') or slug).strip()
            body = normalized_body(post.get('html', ''), page, title)
            if not body:
                skipped.append(f'{slug}: no usable article body in JSON or HTML')
                continue
            cover = image_path(post.get('image', ''))
            if cover.startswith('assets/blog/'):
                cover = '/analytics4/' + cover
            front = {
                'title': title,
                'description': str(post.get('description') or ''),
                'date': clean_date(post.get('date')),
                'image': cover,
                # Legacy language feeds contain known wrong-language entries.
                # Review before explicitly changing this field to true.
                'published': False,
            }
            target.write_text('---\n' + yaml.safe_dump(front, allow_unicode=True, sort_keys=False)
                              + '---\n\n' + body + '\n', encoding='utf-8')
            count += 1
            imported += 1
        report.extend([f'## {lang.upper()}', f'Created {count} draft Markdown files.',
                       f'Source entries: {len(records[lang])}.',
                       f'Skipped: {len(skipped)}.', *[f'- {item}' for item in skipped], ''])
        print(f'{lang}: created {count} draft articles from {len(records[lang])} source entries; skipped {len(skipped)}')
    report_path = CONTENT / 'cms_import_review.md'
    report_path.write_text('\n'.join(report), encoding='utf-8')
    print(f'Created {imported} new DRAFT posts. Existing Markdown untouched. Review {report_path.relative_to(ROOT)}.')
    if not imported and not any((POSTS / lang).glob('*.md') for lang in LANGS):
        raise SystemExit('No articles recovered. Check content/blog_cards_<lang>.json and Blog/<lang>/<slug>/index.html.')


def parse_post(path, lang):
    raw = path.read_text(encoding='utf-8')
    if not raw.startswith('---\n'):
        raise ValueError(f'Missing YAML frontmatter: {path}')
    match = re.match(r'\A---\s*\n(.*?)\n---\s*\n(.*)\Z', raw, flags=re.S)
    if not match:
        raise ValueError(f'Invalid YAML frontmatter: {path}')
    meta = yaml.safe_load(match.group(1)) or {}
    if not meta.get('published', False):
        return None
    slug = path.stem
    if not safe_slug(slug):
        raise ValueError(f'Invalid article filename: {path}')
    html = markdown.markdown(match.group(2).strip(), extensions=['extra', 'sane_lists'])
    soup = BeautifulSoup(html, 'html.parser')
    for img in soup.select('img[src]'):
        src = img.get('src', '')
        if src.startswith('/analytics4/assets/blog/'):
            img['src'] = src.removeprefix('/analytics4/')
        elif src.startswith('/assets/blog/'):
            img['src'] = src.lstrip('/')
    return dict(slug=slug, title=str(meta.get('title') or slug),
                description=str(meta.get('description') or ''), date=clean_date(meta.get('date')),
                image=image_path(meta.get('image', '')), html=str(soup), language=lang)


def build():
    all_posts = {}
    for lang in LANGS:
        all_posts[lang] = []
        for path in sorted((POSTS / lang).glob('*.md')):
            post = parse_post(path, lang)
            if post:
                all_posts[lang].append(post)
        all_posts[lang].sort(key=lambda p: p['date'], reverse=True)
    if not any(all_posts.values()):
        raise SystemExit('Refusing to publish an empty blog. Review imported drafts and mark correct articles published: true.')
    versions = {}
    for lang in LANGS:
        for post in all_posts[lang]:
            versions.setdefault(post['slug'], set()).add(lang)
    outputs = set()
    feeds = {}
    for lang in LANGS:
        cards = []
        for post in all_posts[lang]:
            slug = post['slug']
            rel = Path('Blog') / slug / 'index.html' if lang == 'it' else Path('Blog') / lang / slug / 'index.html'
            page = ROOT / rel
            page.parent.mkdir(parents=True, exist_ok=True)
            page.write_text(legacy.article_html(post, lang, versions[slug]), encoding='utf-8')
            outputs.add(rel.as_posix())
            url = f'Blog/{slug}/' if lang == 'it' else f'Blog/{lang}/{slug}/'
            cards.append({k: post[k] for k in ('slug', 'title', 'description', 'date', 'image', 'language')} | {'url': url})
        feeds[lang] = cards
        archive_rel = Path('Blog') / lang / 'index.html'
        archive_file = ROOT / archive_rel
        archive_file.parent.mkdir(parents=True, exist_ok=True)
        archive_file.write_text(legacy.archive(all_posts[lang], lang, 2), encoding='utf-8')
        outputs.add(archive_rel.as_posix())
        (CONTENT / f'blog_cards_{lang}.json').write_text(json.dumps(cards, ensure_ascii=False, indent=2), encoding='utf-8')
    (CONTENT / 'blog_cards.json').write_text(json.dumps(feeds['it'], ensure_ascii=False, indent=2), encoding='utf-8')
    (CONTENT / 'blog_cards_multilingual.json').write_text(json.dumps(feeds, ensure_ascii=False, indent=2), encoding='utf-8')
    (CONTENT / 'blog_languages.json').write_text(json.dumps(all_posts, ensure_ascii=False, indent=2), encoding='utf-8')
    (CONTENT / 'blog_manifest.json').write_text(json.dumps({
        'posts': all_posts['it'], 'exported': len(all_posts['it']),
        'discovered': sum(map(len, all_posts.values())), 'failed_articles': 0
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    old = set(read_json(STATE, []))
    for rel in old - outputs:
        target = (ROOT / rel).resolve()
        if target.is_relative_to((ROOT / 'Blog').resolve()) and target.name == 'index.html' and target.is_file():
            target.unlink()
    STATE.write_text(json.dumps(sorted(outputs), indent=2), encoding='utf-8')
    print('Published article counts:', {k: len(v) for k, v in feeds.items()})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['bootstrap', 'build'])
    args = parser.parse_args()
    globals()[args.command]()
