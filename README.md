# Analytics 4 — GitHub migration

**Status: STAGING STARTER — DO NOT POINT LIVE DNS HERE YET.**

## Included
- `index.html`: approved visual homepage preview, copied without redesign. Its service views are still client-side placeholders; CTAs require confirmation.
- `scripts/migrate_blog.py`: discovers the existing public 5-page blog archive and exports static article pages at `/Blog/<original-slug>/` with metadata and optional downloaded images.
- `assets/blog.css`: matching dark/orange blog styling.
- `content/blog_manifest.json`: generated on running the migration script; contains extraction statuses and errors.
- GitHub Pages deployment workflow.

## Quick start
1. Extract this ZIP. Create a **private** GitHub repository, e.g. `analytics4-website`, and upload these files.
2. Invite Magdalena as a collaborator. Use separate branches and pull requests for edits.
3. On your computer with internet access, install Python 3.10+, then run:

   ```bash
   python -m pip install -r requirements.txt
   python scripts/migrate_blog.py --pages 5 --download-assets
   ```

4. Inspect `content/blog_manifest.json`: **every** article must have `status: needs_review` until manually checked against the original. Confirm exact title, full body, images, publication date, author, language, links and metadata. The script may require site-specific selector adjustments; it reports errors instead of inventing missing content.
5. Commit the generated `Blog/`, `assets/blog/`, and `content/blog_manifest.json` files to a feature branch. Review, then merge.
6. Under repository Settings → Pages, choose **GitHub Actions** as source. The deployment workflow publishes the static files on push to `main`.
7. Use the GitHub Pages preview URL first. **Do not change analytics4.online DNS until the content audit and form/analytics/SEO checks are complete.**

## Migration checklist
- [ ] Crawl and verify all blog archive pages, articles and images
- [ ] Verify article dates, author names and original language (the exporter uses `language: review` intentionally)
- [ ] Check the blog URL and asset path behavior on preview hosting
- [ ] Replace homepage placeholder service views with real IT/EN/PL pages
- [ ] Confirm CTA destinations and implement a working contact form
- [ ] Restore consent-aware GA4 (`G-TMZ4YGYD8J`) and Search Console verification
- [ ] Generate sitemap, robots.txt and correct per-page canonical/hreflang tags
- [ ] Audit old vs new URLs; configure 301 redirects for any changes
- [ ] Validate accessibility, responsive layout, and links
- [ ] Publish only after final approval

## Important technical notes
- GitHub Pages hosts static files only; the old builder contact form POST endpoint will not work there.
- This starter does **not** claim the 19 articles have already been migrated. The script must run on an internet-enabled computer and every result needs QA.
- The article exporter deliberately leaves the original content intact as much as possible; it does not rewrite articles or invent missing content.
- `/Blog/.../` paths are maintained, but relative image URLs and language-specific canonical URLs must be audited.
- A custom domain requires Pages domain configuration and DNS setup after verification. If deploying to a project subpath before custom domain, root-relative blog assets need adjustment or a preview domain at root.
