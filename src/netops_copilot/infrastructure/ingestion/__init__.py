"""来源解析、脱敏、规范化和切分适配器。"""

from netops_copilot.infrastructure.ingestion.chunking import (
    ChunkingError,
    ChunkingPolicy,
    KnowledgeChunkRecord,
    chunk_record,
)
from netops_copilot.infrastructure.ingestion.normalization import (
    NormalizationError,
    NormalizedRecord,
    normalize_record,
)
from netops_copilot.infrastructure.ingestion.parsers import (
    ParsedRecord,
    ParseErrorCode,
    ParseLimits,
    ParseValidationError,
    SourceLocation,
    parse_path,
)
from netops_copilot.infrastructure.ingestion.redaction import (
    RedactionPolicy,
    SensitiveAction,
    SensitiveDataError,
    SensitiveFinding,
    protect_record,
)

__all__ = [
    "ChunkingError",
    "ChunkingPolicy",
    "KnowledgeChunkRecord",
    "NormalizationError",
    "NormalizedRecord",
    "ParseErrorCode",
    "ParseLimits",
    "ParseValidationError",
    "ParsedRecord",
    "RedactionPolicy",
    "SensitiveAction",
    "SensitiveDataError",
    "SensitiveFinding",
    "SourceLocation",
    "chunk_record",
    "normalize_record",
    "parse_path",
    "protect_record",
]
