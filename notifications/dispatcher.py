from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from notifications.enums import NotificationStatus
from notifications.providers import BaseNotificationProvider, NotificationPayload, NotificationSendResult


@dataclass(slots=True)
class NotificationDispatchResult:
    """Aggregated dispatch output for all invoked providers."""

    payload: NotificationPayload
    results: list[NotificationSendResult] = field(default_factory=list)

    @property
    def is_successful(self) -> bool:
        return bool(self.results) and all(
            result.status in {NotificationStatus.SENT, NotificationStatus.SKIPPED}
            for result in self.results
        )


class NotificationDispatcher:
    """Dispatch notifications across multiple providers."""

    def __init__(self, providers: list[BaseNotificationProvider]) -> None:
        self.providers = providers

    def dispatch(self, payload: NotificationPayload) -> NotificationDispatchResult:
        if not self.providers:
            return NotificationDispatchResult(payload=payload, results=[])

        indexed_results: dict[int, NotificationSendResult] = {}
        with ThreadPoolExecutor(max_workers=len(self.providers)) as executor:
            future_map = {
                executor.submit(provider.send, payload): (index, provider)
                for index, provider in enumerate(self.providers)
            }
            for future in as_completed(future_map):
                index, provider = future_map[future]
                try:
                    indexed_results[index] = future.result()
                except Exception as exc:
                    indexed_results[index] = provider.build_result(
                        payload=payload,
                        status=NotificationStatus.FAILED,
                        detail=f'Provider execution failed: {exc}',
                    )

        ordered_results = [indexed_results[index] for index in sorted(indexed_results)]
        return NotificationDispatchResult(payload=payload, results=ordered_results)
