#!/usr/bin/env python3
"""One-time migration + ongoing CMS build. Run at the repository root."""
import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlparse

import yaml
from bs4 import BeautifulSoup
from markdownify import markdownify as md
import markdown

import migrate_blog as legacy

ROOT = Path(__file__).resolve().parent
POSTS = ROOT / 'content' / 'posts'
CONTENT = ROOT / 'content'
LANGS = ('it', 'en', 'pl')
STATE = CONTENT / 'cms_generated_paths.json'


def slugify(s):
    s = re.sub(r'[^a-z0-9-]+', '-', s.lower().replace('_', '-')).strip('-')
    return s[:110] or 'article'


def clean_date(value):
    value = str(value or '')
    return value[:10] if re.match(r'^\d{4}-\d{2}-\d{2}', value) else '2026-01-01'


def image_path(value):
    value = str(value or '')
    if value.startswith('/analytics4/assets/blog/'):
        return value.removeprefix('/analytics4/')
    if value.startswith('/assets/blog/'):
        return value.lstrip('/')
    if value.startswith('assets/blog/'):
        return value
    return value


def bootstrap():
    source = CONTENT / 'blog_languages.json'
    if not source.exists():
        raise SystemExit('Missing content/blog_languages.json; cannot import legacy posts')
    data = json.loads(source.read_text(encoding='utf-8'))
    total = 0
    for lang in LANGS:
        folder = POSTS / lang
        folder.mkdir(parents=True, exist_ok=True)
        for post in data.get(lang, []):
            slug = post.get('slug', '')
            if not re.fullmatch(r'[A-Za-z0-9_-]+', slug):
                continue
            target = folder / (slug + '.md')
            if target.exists():
                continue  # Never overwrite editor changes.
            soup = BeautifulSoup(post.get('html', ''), 'html.parser')
            for img in soup.select('img[src]'):
                img['src'] = '/' + image_path(img['src']).lstrip('/') if image_path(img['src']).startswith('assets/blog/') else img['src']
            body = md(str(soup), heading_style='ATX').strip()
            # Existing article source often contains its own H1; remove duplicate title.
            body = re.sub(r'^#\s+[^\n]+\n+', '', body, count=1)
            front = {
                'title': post.get('title', slug),
                'description': post.get('description', ''),
                'date': clean_date(post.get('date')),
                'image': ('/analytics4/' + image_path(post.get('image'))) if image_path(post.get('image')).startswith('assets/blog/') else post.get('image', ''),
                'published': True,
            }
            target.write_text('---\n' + yaml.safe_dump(front, allow_unicode=True, sort_keys=False) + '---\n\n' + body + '\n', encoding='utf-8')
            total += 1
    print(f'Imported {total} existing article versions. Existing CMS files preserved.')


def parse_post(path, lang):
    raw = path.read_text(encoding='utf-8')
    if not raw.startswith('---\n'):
        raise ValueError(f'Missing frontmatter: {path}')
    _, header, body = raw.split('---', 2)
    meta = yaml.safe_load(header) or {}
    if not meta.get('published', False):
        return None
    slug = path.stem
    if not re.fullmatch(r'[A-Za-z0-9_-]+', slug):
        raise ValueError(f'Invalid article filename: {path}')
    html = markdown.markdown(body.strip(), extensions=['extra', 'sane_lists'])
    soup = BeautifulSoup(html, 'html.parser')
    # Pages CMS stores image URLs rooted at /analytics4/; convert for GitHub Pages subpath.
    for img in soup.select('img[src]'):
        src = img.get('src', '')
        if src.startswith('/analytics4/assets/blog/'):
            img['src'] = src.removeprefix('/analytics4/')
        elif src.startswith('/assets/blog/'):
            img['src'] = src.lstrip('/')
    image = image_path(meta.get('image', ''))
    return dict(slug=slug, title=str(meta.get('title') or slug),
                description=str(meta.get('description') or ''), date=clean_date(meta.get('date')),
                image=image, html=str(soup), language=lang)


def build():
    all_posts = {}
    for lang in LANGS:
        all_posts[lang] = []
        for path in sorted((POSTS / lang).glob('*.md')):
            post = parse_post(path, lang)
            if post:
                all_posts[lang].append(post)
        all_posts[lang].sort(key=lambda p: p['date'], reverse=True)
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
            url = ('Blog/' + slug + '/') if lang == 'it' else ('Blog/' + lang + '/' + slug + '/')
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
    # Compatibility with old metadata consumers; CMS is now the authoritative source.
    (CONTENT / 'blog_languages.json').write_text(json.dumps(all_posts, ensure_ascii=False, indent=2), encoding='utf-8')
    (CONTENT / 'blog_manifest.json').write_text(json.dumps({'posts': all_posts['it'], 'exported': len(all_posts['it']), 'discovered': sum(map(len, all_posts.values())), 'failed_articles': 0}, ensure_ascii=False, indent=2), encoding='utf-8')
    # Remove only files previously generated by this CMS, never arbitrary legacy files.
    old = set(json.loads(STATE.read_text(encoding='utf-8'))) if STATE.exists() else set()
    for rel in old - outputs:
        target = (ROOT / rel).resolve()
        if target.is_relative_to((ROOT / 'Blog').resolve()) and target.name == 'index.html' and target.is_file():
            target.unlink()
    STATE.write_text(json.dumps(sorted(outputs), indent=2), encoding='utf-8')
    print('Published article counts:', {k: len(v) for k, v in feeds.items()})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['bootstrap', 'build'])
    args = parser.parse_args()
    globals()[args.command]()
