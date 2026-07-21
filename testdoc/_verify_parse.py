from pathlib import Path

from app.services.parsers import extract_text

root = Path("/out")
for path in sorted(root.iterdir()):
    if path.name.startswith("_") or path.name == "README.md":
        continue
    suffix = path.suffix.lower().lstrip(".")
    if suffix not in {"txt", "md", "pdf", "doc", "docx"}:
        continue
    try:
        text = extract_text(path.name, path.read_bytes(), suffix)
        head = text[:48].replace("\n", " ")
        print(f"OK {path.name} type={suffix} chars={len(text)} head={head}")
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL {path.name}: {type(exc).__name__}: {exc}")
