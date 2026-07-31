#!/bin/sh
# Normalize frontend static tree permissions before nginx starts.
# Windows zip / some unpackers create directories as 644 (no +x) → nginx returns
# 403 on /assets/* and the SPA shows a blank page with only the HTML title.
set -e

html_root="${NGINX_HTML_ROOT:-/usr/share/nginx/html}"

if [ -d "$html_root" ]; then
  # Best-effort: bind mounts may be read-only; image bake already has correct mode.
  find "$html_root" -type d -exec chmod 755 {} \; 2>/dev/null || true
  find "$html_root" -type f -exec chmod 644 {} \; 2>/dev/null || true
fi

# Official nginx image entrypoint (templates, signal handling)
if [ -x /docker-entrypoint.sh ]; then
  exec /docker-entrypoint.sh "$@"
fi
exec "$@"
