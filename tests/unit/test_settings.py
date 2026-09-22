"""严格运行时 Profile 设置测试。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from netops_copilot.settings import ProfileName, ProfileSettings, load_profile


class SettingsTests(unittest.TestCase):
    """Profile 接受声明的设置，并拒绝不支持的输入。"""

    def test_all_builtin_profiles_load(self) -> None:
        for profile in ProfileName:
            self.assertEqual(load_profile(profile).profile, profile)

    def test_cloud_profiles_use_bailian_compatible_models(self) -> None:
        for profile in (ProfileName.DEMO_LITE, ProfileName.LOCAL_MILVUS, ProfileName.CLOUD_MILVUS):
            settings = load_profile(profile)

            self.assertEqual(settings.llm.model, "qwen-plus")
            self.assertEqual(settings.embedding.model, "text-embedding-v4")
            self.assertEqual(settings.embedding.dimension, 1024)
            self.assertEqual(settings.llm.api_key_env, "DASHSCOPE_API_KEY")
            self.assertEqual(settings.embedding.api_key_env, "DASHSCOPE_API_KEY")
            self.assertEqual(
                settings.llm.base_url,
                "https://dashscope.aliyuncs.com/compatible-mode/v1",
            )
            self.assertEqual(settings.embedding.base_url, settings.llm.base_url)

    def test_unknown_fields_are_rejected(self) -> None:
        data = load_profile(ProfileName.TEST).model_dump()
        data["unrecognized"] = "not allowed"

        with self.assertRaises(ValidationError):
            ProfileSettings.model_validate(data)

    def test_unknown_provider_combination_is_rejected(self) -> None:
        data = load_profile(ProfileName.TEST).model_dump()
        data["dense_search"]["provider"] = "unknown-vector-store"

        with self.assertRaises(ValidationError):
            ProfileSettings.model_validate(data)

    def test_openai_compatible_profiles_require_secret_and_endpoint_references(self) -> None:
        data = load_profile(ProfileName.DEMO_LITE).model_dump()
        data["llm"]["base_url"] = None

        with self.assertRaises(ValidationError):
            ProfileSettings.model_validate(data)

    def test_profile_file_name_must_match_its_contents(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            (directory / "test.yaml").write_text("profile: demo-lite\n", encoding="utf-8")

            with self.assertRaises(ValueError):
                load_profile(ProfileName.TEST, directory)
