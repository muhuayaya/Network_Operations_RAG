"""用于组合 provider 的严格配置 Profile。"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


class ProfileName(StrEnum):
    """支持的运行时 Profile。"""

    DEMO_LITE = "demo-lite"
    LOCAL_MILVUS = "local-milvus"
    CLOUD_MILVUS = "cloud-milvus"
    TEST = "test"


class ProviderReference(BaseModel):
    """由 Profile 选中的命名 provider。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    provider: str = Field(min_length=1)


class ModelProviderReference(ProviderReference):
    """包含可选模型和密钥引用元数据的模型 provider。"""

    model: str = Field(min_length=1)
    api_key_env: str | None = None
    base_url: str | None = None

    @field_validator("api_key_env")
    @classmethod
    def validate_environment_variable_name(cls, value: str | None) -> str | None:
        """保持密钥引用为声明式配置，并与环境变量兼容。"""
        if value is not None and not value.isidentifier():
            raise ValueError("api_key_env must be a valid environment variable name")
        return value

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str | None) -> str | None:
        """要求绝对 HTTP(S) 端点，同时不在配置中保存密钥。"""
        if value is None:
            return None
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or value.endswith("/"):
            raise ValueError("base_url must be an absolute HTTP(S) URL without a trailing slash")
        return value


class EmbeddingProviderReference(ModelProviderReference):
    """索引兼容性检查所需的 Embedding provider 元数据。"""

    dimension: int = Field(gt=0)


class LocalModelReference(ProviderReference):
    """预留的本地模型配置结构；不可用状态必须显式表达。"""

    provider: Literal["local-reserved"]
    available: Literal[False]


class ProfileSettings(BaseModel):
    """一个运行时 Profile 经过校验的 provider 选择。"""

    model_config = ConfigDict(extra="forbid")

    profile: ProfileName
    index_schema_version: int = Field(ge=1)
    device_access_mode: Literal["readonly"]
    llm: ModelProviderReference
    embedding: EmbeddingProviderReference
    dense_search: ProviderReference
    lexical_search: ProviderReference
    metadata_store: ProviderReference
    device_observation: ProviderReference
    local_model: LocalModelReference

    @model_validator(mode="after")
    def validate_profile_provider_combinations(self) -> ProfileSettings:
        """拒绝当前 Profile 不支持的 provider。"""
        expected_backends = {
            ProfileName.DEMO_LITE: ("chroma", "sqlite-fts5", "sqlite"),
            ProfileName.LOCAL_MILVUS: ("milvus", "milvus-bm25", "postgresql"),
            ProfileName.CLOUD_MILVUS: ("milvus", "milvus-bm25", "postgresql"),
            ProfileName.TEST: ("in-memory", "in-memory", "sqlite-memory"),
        }
        expected_dense, expected_lexical, expected_metadata = expected_backends[self.profile]
        actual_backends = (
            self.dense_search.provider,
            self.lexical_search.provider,
            self.metadata_store.provider,
        )
        if actual_backends != (expected_dense, expected_lexical, expected_metadata):
            raise ValueError(f"unsupported provider combination for profile {self.profile.value}")
        expected_model_provider = "fake" if self.profile is ProfileName.TEST else "openai-compatible"
        if self.llm.provider != expected_model_provider or self.embedding.provider != expected_model_provider:
            raise ValueError(f"unsupported model provider for profile {self.profile.value}")
        if expected_model_provider == "openai-compatible" and any(
            reference.api_key_env is None or reference.base_url is None
            for reference in (self.llm, self.embedding)
        ):
            raise ValueError("openai-compatible model providers require api_key_env and base_url")
        if self.device_observation.provider != "simulator":
            raise ValueError("only the simulator device provider is configured at this stage")
        return self


def load_profile(profile: ProfileName, profile_directory: Path | None = None) -> ProfileSettings:
    """加载并校验一个命名 YAML Profile，但不解析任何密钥值。"""
    directory = profile_directory or Path(__file__).resolve().parents[2] / "config" / "profiles"
    profile_path = directory / f"{profile.value}.yaml"
    try:
        parsed = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ValueError(f"profile does not exist: {profile.value}") from error
    if not isinstance(parsed, dict):
        raise TypeError("profile must contain a YAML mapping")
    settings = ProfileSettings.model_validate(parsed)
    if settings.profile is not profile:
        raise ValueError("profile file name and profile field must match")
    return settings


__all__ = ["ProfileName", "ProfileSettings", "ValidationError", "load_profile"]
