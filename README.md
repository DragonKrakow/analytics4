# Analytics 4 — corrected GitHub Pages migration

## What this package fixes
- Homepage's **Blog / all articles** navigation now points to `Blog/`.
- Blog exporter creates relative links compatible with `https://dragonkrakow.github.io/analytics4/` and a root custom domain.
- New **Import original blog (manual)** GitHub Actions workflow can fetch posts and images and commit them to your repository.
- Export script will NOT replace the blog with an empty archive if extraction fails.

**Important:** The original blog articles are **not** inside this ZIP. They require a successful import from the public site. Blog archive and article selectors may need adjustment if the source builder has changed. Check the generated pages and manifest before launching the custom domain.

## Upload / replace files
1. Open https://github.com/DragonKrakow/analytics4
2. Upload the **contents** of this ZIP to the root of the repository, keeping directory paths intact (do not upload the ZIP as a single file).
3. Commit the changes to `main`.
4. Go to **Actions** → **Import original blog (manual)** → **Run workflow**.
5. Open the workflow log. On success, the repository will contain `Blog/index.html`, `Blog/<article-slug>/index.html`, `assets/blog/` images and `content/blog_manifest.json`.
6. Go to **Actions** → **Deploy static website** and wait for deployment. Visit https://dragonkrakow.github.io/analytics4/Blog/ .
7. Compare every article with the original: text, images, links, dates, language, and SEO. Do not switch your production domain before review.

## If the import workflow fails
Read the log. If it says `No articles found` or `Article body not identified`, the builder's archive/article markup differs from the extraction selectors. Do not assume posts migrated. Send the workflow log and one article's saved HTML so we can adapt the parser. The original website remains untouched.

## Collaborating
Invite Madi via repository Settings → Collaborators. Work in separate branches, open pull requests, review changes, and merge to `main` for deployment.

## Still pending
- Actual successful extraction and manual validation of every article.
- Separate service pages and translations (not included in this blog-specific correction).
- Forms, SEO audits, 301 redirects where needed, consent configuration, and final domain switch.
