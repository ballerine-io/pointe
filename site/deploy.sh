#!/bin/sh
# Publish site/ to eng.ballerine.com: Cloudflare Pages project "pointe-site" in Ballerine's Cloudflare account.
# site/index.html is the Ballerine Engineering hub at /, site/pointe/ is Pointe's page at /pointe/.
# Needs `npx wrangler login` with access to that account. The DNS records (eng.ballerine.com and the old
# pointe.ballerine.com, both CNAMEs to pointe-site-9tz.pages.dev) live in Route 53 and do not change on a deploy.
#
#   site/deploy.sh            production (branch main): only after the owner has seen a preview
#   site/deploy.sh <branch>   a preview at <branch>.pointe-site-9tz.pages.dev
set -eu
cd "$(dirname "$0")/.."
exec npx -y wrangler@4.166.0 pages deploy site --project-name pointe-site --branch "${1:-main}" --commit-dirty=true
