"""providers 表访问。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from akc.db.models import Provider


def ensure_provider(
    session: Session,
    provider_id: str,
    *,
    display_name: str | None = None,
    adapter_version: str = "0.0.0",
) -> Provider:
    provider = session.get(Provider, provider_id)
    if provider is None:
        provider = Provider(
            id=provider_id,
            display_name=display_name or provider_id,
            enabled=1,
            adapter_version=adapter_version,
        )
        session.add(provider)
        session.flush()
        return provider
    if display_name and provider.display_name != display_name:
        provider.display_name = display_name
    if adapter_version and provider.adapter_version != adapter_version:
        provider.adapter_version = adapter_version
    return provider


def get_provider(session: Session, provider_id: str) -> Provider | None:
    return session.get(Provider, provider_id)


def list_providers(session: Session) -> list[Provider]:
    return list(session.scalars(select(Provider).order_by(Provider.id)).all())


def set_enabled(session: Session, provider_id: str, enabled: bool) -> Provider | None:
    provider = session.get(Provider, provider_id)
    if provider is None:
        return None
    provider.enabled = 1 if enabled else 0
    return provider
