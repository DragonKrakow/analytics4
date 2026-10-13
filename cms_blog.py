            try:
                soup = BeautifulSoup(page.read_text(encoding='utf-8', errors='replace'), 'html.parser')
                article = find_article_content(soup)
                if article is None:
                    continue
                h1 = article.find('h1') or soup.find('h1')
                og = soup.find('meta', attrs={'property': 'og:title'})
                title = (h1.get_text(' ', strip=True) if h1 else
                         (og.get('content', '') if og else slug.replace('-', ' ')))
                desc = soup.find('meta', attrs={'name': 'description'})
                image = soup.find('meta', attrs={'property': 'og:image'})
                date = soup.find('meta', attrs={'property': 'article:published_time'})
                fallback = {'slug': slug, 'title': title,
                            'description': desc.get('content', '') if desc else '',
                            'image': image.get('content', '') if image else '',
                            'date': date.get('content', '') if date else ''}
                records[lang].setdefault(slug, fallback)
            except Exception as exc:
                print(f'WARNING: Skipping {page.relative_to(ROOT)}: {exc}')
