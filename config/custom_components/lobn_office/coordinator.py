"""授权预取协调器：未来 N 分钟写入热路径。"""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .cloud_client import CloudClient
from .hot_path import InMemoryHotPath

_LOGGER = logging.getLogger(__name__)


class GrantCoordinator(DataUpdateCoordinator[list]):
    def __init__(
        self,
        hass: HomeAssistant,
        cloud: CloudClient,
        hot: InMemoryHotPath,
        prefetch_minutes: int = 15,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="lobn_office_grants",
            update_interval=timedelta(seconds=30),
        )
        self.cloud = cloud
        self.hot = hot
        self.prefetch_minutes = prefetch_minutes

    async def _async_update_data(self) -> list:
        grants = await self.cloud.pull_pending_grants(self.prefetch_minutes)
        for g in grants:
            self.hot.upsert_grant(g)
        self.hot.purge_expired()
        settings = await self.cloud.pull_settings()
        runtime = self.hass.data.get("lobn_office", {}).get("runtime")
        if runtime and settings:
            policy = runtime.get("policy")
            if policy is not None and hasattr(policy, "apply_site_settings"):
                policy.apply_site_settings(settings)
            runtime["site_settings"] = settings
        return grants
