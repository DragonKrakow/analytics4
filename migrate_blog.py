#!/usr/bin/env python3
"""Fetch the public builder blog and export SEO-friendly static article pages.
Run from a network-enabled computer; this script never edits the live site.
"""
import argparse, json, re, time, html
from pathlib import Path
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup

BASE='https://analytics4.online/'
ROOT=Path(__file__).resolve().parents[1]
HEADERS={'User-Agent':'Analytics4Migration/1.0 (+site-owner archival migration)'}

def get(session,url):
    r=session.get(url,headers=HEADERS,timeout=30);r.raise_for_status();return r

def clean_slug(url):
    p=urlparse(url).path.strip('/').split('/')
    return p[-1] if len(p)>1 else ''

def article_urls(soup):
    found={}
    for a in soup.select('a[href]'):
        u=urljoin(BASE,a['href']);p=urlparse(u)
        if p.netloc not in ('analytics4.online','www.analytics4.online'):continue
        if re.match(r'^/Blog/[^/]+/?$',p.path,re.I):
            found[p.path.rstrip('/')+'/']=u.split('#')[0].split('?')[0]
    return found

def find_article(soup):
    # Builder article body is usually nested under a blog-post widget.
    selectors=['[data-plugin="BlogPost"]','[data-plugin="Blog"] .post-content','.blog-post-content','.post-content','article','[itemprop="articleBody"]']
    for sel in selectors:
        matches=soup.select(sel)
        matches=[m for m in matches if len(m.get_text(' ',strip=True))>350]
        if matches:return max(matches,key=lambda x:len(x.get_text(' ',strip=True)))
    # Fallback: pick smallest substantial parent of the primary article h1.
    hs=[h for h in soup.select('h1,h2') if len(h.get_text(' ',strip=True))>25]
    for h in hs:
        for p in h.parents:
            if p.name in ('main','body'):break
            text=p.get_text(' ',strip=True)
            if 550<len(text)<18000 and len(p.select('p'))>=3:return p
    return None

def migrate(session,url,assets_dir,download_assets):
    soup=BeautifulSoup(get(session,url).text,'html.parser')
    title=(soup.find('h1') or soup.find('h2'))
    title=title.get_text(' ',strip=True) if title else (soup.title.get_text(' ',strip=True) if soup.title else clean_slug(url))
    body=find_article(soup)
    if body is None:raise ValueError('Could not identify full article body; needs manual extraction')
    content=BeautifulSoup(str(body),'html.parser')
    for el in content.select('script,style,form,nav,footer,header,iframe,.wb_cookie_policy') :el.decompose()
    for el in content.select('[onclick]'):del el['onclick']
    for el in content.select('a[href]'):el['href']=urljoin(url,el['href'])
    for img in content.select('img[src]'):
        src=urljoin(url,img['src']);img['src']=src
        if download_assets:
            try:
                r=get(session,src)
                ext=Path(urlparse(src).path).suffix.lower()
                if ext not in ('.png','.jpg','.jpeg','.webp','.gif','.svg'):ext='.jpg'
                import hashlib
                filename=hashlib.sha256(src.encode()).hexdigest()[:16]+ext
                (assets_dir/filename).write_bytes(r.content)
                img['src']='/assets/blog/'+filename
            except Exception as e:print('IMAGE WARNING',src,e)
    meta=soup.select_one('meta[name="description"]')
    description=meta.get('content','') if meta else ''
    published=soup.select_one('time[datetime]')
    date=published.get('datetime','') if published else ''
    slug=clean_slug(url)
    # Retain only article markup and data, not builder scripts.
    return {'slug':slug,'source_url':url,'path':'/Blog/'+slug+'/','title':title,'description':description,'date':date,'language':'review','html':str(content),'status':'needs_review'}

def render(post):
    title=html.escape(post['title']);desc=html.escape(post['description']);canonical=html.escape(post['source_url'],quote=True)
    return f'''<!doctype html><html lang="it"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title} | Analytics 4</title><meta name="description" content="{desc}"><link rel="canonical" href="{canonical}"><link rel="stylesheet" href="/assets/blog.css"></head><body><header><a class="logo" href="/">Analytics <b>4</b></a><nav><a href="/">Home</a><a href="/Blog/">Blog</a><a href="mailto:stefano@analytics4.online">Contact</a></nav></header><main><p class="eyebrow"><a href="/Blog/">← Blog</a></p><article><h1>{title}</h1>{post['html']}</article></main><footer>© Analytics 4 · <a href="mailto:stefano@analytics4.online">Contact</a></footer></body></html>'''

def index(posts):
    items=''.join(f'<a class="post" href="{html.escape(p["path"])}"><h2>{html.escape(p["title"])}</h2><p>{html.escape(p["description"][:190])}</p></a>' for p in posts)
    return '<!doctype html><html lang="it"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Blog | Analytics 4</title><link rel="stylesheet" href="/assets/blog.css"></head><body><header><a class="logo" href="/">Analytics <b>4</b></a><nav><a href="/">Home</a><a href="/Blog/">Blog</a></nav></header><main><h1>Blog & Insights</h1><p>Articoli e approfondimenti di Analytics 4</p><section class="posts">'+items+'</section></main></body></html>'

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--pages',type=int,default=5);parser.add_argument('--delay',type=float,default=0.8);parser.add_argument('--download-assets',action='store_true');args=parser.parse_args()
    session=requests.Session();found={};errors=[]
    for page in range(1,args.pages+1):
        url=urljoin(BASE,'Blog/')+(f'?bcpp=4&bpage={page}' if page>1 else '')
        try:
            soup=BeautifulSoup(get(session,url).text,'html.parser');matches=article_urls(soup);found.update(matches)
            print('ARCHIVE',page,len(matches));time.sleep(args.delay)
        except Exception as e:errors.append({'url':url,'error':str(e)})
    posts=[];assets=ROOT/'assets'/'blog';assets.mkdir(parents=True,exist_ok=True)
    for path,url in sorted(found.items()):
        try:
            post=migrate(session,url,assets,args.download_assets);posts.append(post)
            dest=ROOT/path.lstrip('/')/'index.html';dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text(render(post),encoding='utf-8')
            print('OK',url)
        except Exception as e:errors.append({'url':url,'error':str(e)});print('ERROR',url,e)
        time.sleep(args.delay)
    (ROOT/'Blog').mkdir(exist_ok=True)
    (ROOT/'Blog'/'index.html').write_text(index(posts),encoding='utf-8')
    (ROOT/'content'/'blog_manifest.json').write_text(json.dumps({'source':BASE+'Blog/','discovered':len(found),'exported':len(posts),'posts':posts,'errors':errors},ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'Finished: {len(posts)}/{len(found)} exported, {len(errors)} errors. Review content/blog_manifest.json before deployment.')
    if errors:raise SystemExit(2)
if __name__=='__main__':main()
