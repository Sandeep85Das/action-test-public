import re


def slugify(text):
    """Lowercase, with runs of non-alphanumerics turned into one dash."""
    return re.sub(r"[^a-z0-9]", "-", text.lower())
