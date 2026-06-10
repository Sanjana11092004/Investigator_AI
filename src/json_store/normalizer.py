"""
File Normalizer — classifies any incoming file into a canonical pipeline so the
rest of the system handles every type consistently (the "FILE NORMALIZER" box).

    csv / xls / xlsx        -> tabular   (headers -> rows -> JSON)
    json                    -> structured_json
    pdf / doc / docx / txt  -> document  (text extraction -> chunks -> JSON)
"""
from pathlib import Path


class FileNormalizer:
    TABULAR = {".csv", ".xls", ".xlsx"}
    STRUCTURED_JSON = {".json"}
    DOCUMENT = {".pdf", ".doc", ".docx", ".txt", ".rtf"}

    def classify(self, filename: str) -> str:
        ext = Path(filename).suffix.lower()
        if ext in self.TABULAR:
            return "tabular"
        if ext in self.STRUCTURED_JSON:
            return "structured_json"
        if ext in self.DOCUMENT:
            return "document"
        return "unknown"

    def canonical_format(self, filename: str) -> str:
        """The intermediate form each type is converted to before JSON."""
        kind = self.classify(filename)
        return {
            "tabular": "excel/tabular-rows",
            "structured_json": "json",
            "document": "extracted-text",
        }.get(kind, "unknown")

    def is_supported(self, filename: str) -> bool:
        return self.classify(filename) != "unknown"
