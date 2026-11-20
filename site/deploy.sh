#!/bin/sh
# Publish site/ to pointe.ballerine.com: Cloudflare Pages project "pointe-site" in Ballerine's Cloudflare account.
# Needs `npx wrangler login` with access to that account. The DNS record (a CNAME to pointe-site-9tz.pages.dev) lives in
# Route 53 and does not change on a deploy.
set -eu
cd "$(dirname "$0")/.."
exec npx -y wrangler@4.166.0 pages deploy site --project-name pointe-site --branch main --commit-dirty=true
