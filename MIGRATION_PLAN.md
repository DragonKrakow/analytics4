# Migration scope

**Priority 1:** Existing blog posts, preserving original URLs and content.
**Priority 2:** Approved redesigned homepage (`index.html`).
**Priority 3:** Rewritten service pages and Italian, English, Polish localization.

Current original homepage links include `/Google-Ads/`, `/Blog/`, `/Referenze/`, `/offerta-promozionale-google-ads/`. Preserve or redirect them after reviewing the content.

The original homepage includes the GA4 ID `G-TMZ4YGYD8J` and a Search Console verification tag. Re-implement consent mode with a compliant consent manager; don't blindly copy the old builder's consent scripts.

The new homepage preview is a single HTML file with client-side service page switching, not independent SEO-indexable pages. Split service pages during the second development phase. Avoid publishing unverified case-study performance claims.

The existing builder's form submission is not portable; choose and test a replacement form service before cutover.
