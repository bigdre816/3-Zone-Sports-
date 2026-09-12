"""Backend-only configuration and production safety gates."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    env: str
    database_path: str
    xrpl_mode: str
    xrpl_network: str
    xrpl_account: str
    xrpl_secret: str | None
    signing_profile_id: str
    treasure_mode: str

    @classmethod
    def from_env(cls) -> "Config":
        config = cls(
            env=os.getenv("MOTEN_ENV", "development").lower(),
            database_path=os.getenv("MOTEN_AUDIT_DATABASE_PATH", "data/moten_audit.sqlite3"),
            # Defaults to simulation. For /ops wallet-confirm honesty labels + testnet mode,
            # set MOTEN_XRPL_MODE=testnet on the Moten on-chain service (Render env; not in render-moten.yaml).
            xrpl_mode=os.getenv("MOTEN_XRPL_MODE", "simulation").lower(),
            xrpl_network=os.getenv("MOTEN_XRPL_NETWORK", "testnet").lower(),
            xrpl_account=os.getenv("MOTEN_XRPL_ACCOUNT", ""),
            xrpl_secret=os.getenv("MOTEN_XRPL_SECRET") or None,
            signing_profile_id=os.getenv("MOTEN_SIGNING_PROFILE_ID", "moten-audit-local"),
            treasure_mode=os.getenv("MOTEN_TREASURE_MODE", "simulation").lower(),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if self.xrpl_mode not in {"simulation", "testnet"}:
            raise RuntimeError("MOTEN_XRPL_MODE must be simulation or testnet; mainnet is disabled")
        if self.treasure_mode != "simulation":
            raise RuntimeError("only the explicitly labeled Treasure simulator is currently supported")
        if self.env == "production" and (self.xrpl_mode != "testnet" or not self.xrpl_secret or not self.xrpl_account):
            raise RuntimeError("refusing production publisher startup without secure testnet signing configuration")

    @property
    def is_simulation(self) -> bool:
        return self.xrpl_mode == "simulation"

