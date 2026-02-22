import hashlib
import re


def normalize_html(html: str) -> str:
    # Remove script/style to reduce noisy changes
    html = re.sub(r"<script.*?>.*?</script>", "", html, flags=re.S | re.I)
    html = re.sub(r"<style.*?>.*?</style>", "", html, flags=re.S | re.I)

    # Normalize whitespace
    html = re.sub(r"\s+", " ", html).strip()
    return html


def hash_content(html: str) -> str:
    normalized = normalize_html(html)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()