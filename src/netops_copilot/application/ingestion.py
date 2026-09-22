"""带有失败安全索引激活的持久化摄取编排。"""

from __future__ import annotations

from dataclasses import dataclass

from netops_copilot.application.indexing import VersionedIndexManager
from netops_copilot.application.ports.repositories import MetadataRepository
from netops_copilot.domain.incidents import (
    INGESTION_STAGES,
    IngestionJob,
    IngestionStage,
    IngestionStatus,
)


@dataclass(frozen=True, slots=True)
class IngestionRun:
    """一次运行最终持久化状态和激活结果。"""

    job: IngestionJob
    activated_version_id: str | None = None


class IngestionCoordinator:
    """驱动持久化状态机，仅在验证完成后激活索引。"""

    def __init__(self, repository: MetadataRepository, index_manager: VersionedIndexManager) -> None:
        self._repository = repository
        self._index_manager = index_manager

    def run(
        self,
        job_id: str,
        source_id: str,
        version_id: str,
        *,
        fail_at: IngestionStage | None = None,
    ) -> IngestionRun:
        job = IngestionJob(job_id, source_id)
        self._save(job)
        for stage in INGESTION_STAGES:
            if job.stage is not stage:
                raise RuntimeError("ingestion stage sequence is inconsistent")
            job = job.start()
            self._save(job)
            if fail_at is stage:
                job = job.fail(f"injected_failure:{stage.value}")
                self._save(job)
                return IngestionRun(job)
            if stage is IngestionStage.ACTIVATE:
                self._index_manager.activate(version_id)
            job = job.succeed()
            self._save(job)
        return IngestionRun(job, version_id)

    def retry(self, job_id: str, version_id: str) -> IngestionRun:
        job = self._repository.get_job(job_id)
        if not isinstance(job, IngestionJob) or job.status is not IngestionStatus.FAILED:
            raise ValueError("only a failed ingestion job can be retried")
        job = job.retry()
        self._save(job)
        return self._continue(job, version_id)

    def _continue(self, job: IngestionJob, version_id: str) -> IngestionRun:
        while True:
            job = job.start()
            self._save(job)
            if job.stage is IngestionStage.ACTIVATE:
                self._index_manager.activate(version_id)
            job = job.succeed()
            self._save(job)
            if job.status is IngestionStatus.SUCCEEDED:
                return IngestionRun(job, version_id)

    def _save(self, job: IngestionJob) -> None:
        self._repository.save_job(job.job_id, job)
