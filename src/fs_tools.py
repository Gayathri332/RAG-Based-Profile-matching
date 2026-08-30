from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime
import traceback

from pypdf import PdfReader
from docx import Document
# From github.com/shashankch/llm_file_system_assistant

SUPPORTED_EXTENSIONS = {".txt", ".pdf", ".docx"}


def read_file(filepath: str) -> Dict:
    """
    Read PDF/TXT/DOCX file and return content + metadata.
    """

    try:
        path = Path(filepath)

        if not path.exists():
            return {"success": False, "error": f"File not found: {filepath}"}

        extension = path.suffix.lower()

        if extension not in SUPPORTED_EXTENSIONS:
            return {"success": False, "error": f"Unsupported file type: {extension}"}

        content = ""

        if extension == ".txt":
            content = path.read_text(encoding="utf-8", errors="ignore")

        elif extension == ".pdf":
            reader = PdfReader(str(path))

            content = "\n".join(page.extract_text() or "" for page in reader.pages)

        elif extension == ".docx":
            doc = Document(str(path))

            content = "\n".join(paragraph.text for paragraph in doc.paragraphs)

        return {
            "success": True,
            "content": content,
            "metadata": {
                "filename": path.name,
                "filepath": str(path.resolve()),
                "extension": extension,
                "size_bytes": path.stat().st_size,
                "modified_time": datetime.fromtimestamp(
                    path.stat().st_mtime
                ).isoformat(),
            },
        }

    except Exception as e:
        return {"success": False, "error": str(e), "trace": traceback.format_exc()}


def list_files(directory: str, extension: Optional[str] = None) -> List[Dict]:
    """
    List files in a directory.
    Optional extension filtering.
    """

    try:
        path = Path(directory)

        if not path.exists():
            return []

        files = []

        for file in path.rglob("*"):
            if not file.is_file():
                continue

            if extension:
                if file.suffix.lower() != extension.lower():
                    continue

            files.append(
                {
                    "name": file.name,
                    "path": str(file.resolve()),
                    "size_bytes": file.stat().st_size,
                    "modified_time": datetime.fromtimestamp(
                        file.stat().st_mtime
                    ).isoformat(),
                }
            )

        return files

    except Exception:
        return []


def write_file(filepath: str, content: str) -> Dict:
    """
    Write content to file.
    Create directories if required.
    """

    try:
        path = Path(filepath)

        path.parent.mkdir(parents=True, exist_ok=True)

        path.write_text(content, encoding="utf-8")

        return {
            "success": True,
            "filepath": str(path.resolve()),
            "bytes_written": len(content.encode("utf-8")),
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


def search_in_file(
    filepath: str,
    keyword: str,
    context_size: int = 150,
    limit: int = 10,
    offset: int = 0,
) -> Dict:
    """
    Case-insensitive search with context.
    Supports adjustable context size and pagination (limit, offset) to prevent overwhelming the user.
    """

    file_data = read_file(filepath)

    if not file_data["success"]:
        return file_data

    content = file_data["content"]

    content_lower = content.lower()
    keyword_lower = keyword.lower()

    all_matches = []
    start = 0

    while True:
        idx = content_lower.find(keyword_lower, start)

        if idx == -1:
            break

        context_start = max(0, idx - context_size)
        context_end = min(len(content), idx + len(keyword) + context_size)

        all_matches.append({
            "position": idx,
            "context": content[context_start:context_end]
        })

        start = idx + len(keyword)

    total_matches = len(all_matches)
    paginated_matches = all_matches[offset:offset + limit]

    return {
        "success": True,
        "keyword": keyword,
        "total_matches": total_matches,
        "limit": limit,
        "offset": offset,
        "matches": paginated_matches,
        "metadata": file_data["metadata"],
    }
