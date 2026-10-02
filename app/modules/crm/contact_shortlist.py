"""Choose a small, owner-actionable set of public outreach routes."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from app.modules.crm.contact_channel_semantics import is_semantic_contact_channel
from app.modules.crm.contact_presentation import ContactPresentation, present_contact
from app.modules.crm.models import Contact, ContactChannel


@dataclass(frozen=True)
class PreferredContactRoute:
    """One verified route the owner can actually open and use."""

    contact: Contact
    channel: ContactChannel
    presentation: ContactPresentation


_ROLE_ORDER = {
    "ceo": 0,
    "managing_director": 0,
    "founder": 1,
    "co_founder": 1,
    "head_of_business_development": 2,
    "head_of_expansion": 2,
    "country_manager": 2,
    "head_of_operations": 3,
    "coo": 3,
    "head_of_projects": 3,
    "head_of_transformation": 3,
    "recruiter": 4,
    "talent_acquisition": 4,
    "hiring_manager": 4,
    "public": 9,
}
_CHANNEL_ORDER = {
    "email": 0,
    "linkedin": 1,
    "facebook": 2,
    "telegram": 3,
    "whatsapp": 4,
    "official_form": 5,
}


def _best_verified_channel(contact: Contact) -> ContactChannel | None:
    verified = [
        item
        for item in contact.channels
        if item.validation_status == "VERIFIED"
        and is_semantic_contact_channel(item.channel_type, item.url or item.value)
    ]
    return min(
        verified,
        key=lambda item: (
            _CHANNEL_ORDER.get(item.channel_type, 9),
            -(item.confidence or 0),
            item.value.casefold(),
        ),
        default=None,
    )


def has_usable_verified_route(contact: Contact) -> bool:
    """Do not expose a nominally verified but semantically wrong web page."""

    return _best_verified_channel(contact) is not None


def _role_group(contact: Contact, presentation: ContactPresentation) -> str:
    role = (contact.decision_maker_role or "").casefold()
    if role in _ROLE_ORDER and role != "public":
        return role
    return presentation.category


def preferred_contact_routes(
    contacts: Iterable[Contact], locale: str, *, limit: int = 2
) -> list[PreferredContactRoute]:
    """Return at most two non-duplicated verified routes, ranked for outreach.

    Research may discover a dozen careers pages on a single website.  They are
    useful evidence but not twelve decisions for the owner.  A named executive
    or founder wins; otherwise the best verified hiring channel wins.  A generic
    public channel is retained only when no targeted route exists.
    """
    candidates: list[tuple[int, float, str, PreferredContactRoute]] = []
    for contact in contacts:
        if contact.do_not_contact or contact.validation_status != "VERIFIED_CONTACT":
            continue
        presentation = present_contact(contact, locale)
        if presentation.category in {"support", "press"}:
            continue
        channel = _best_verified_channel(contact)
        if channel is None:
            continue
        role = (contact.decision_maker_role or "public").casefold()
        candidates.append(
            (
                _ROLE_ORDER.get(role, _ROLE_ORDER["public"]),
                -(contact.discovery_score or 0),
                contact.name.casefold(),
                PreferredContactRoute(contact, channel, presentation),
            )
        )

    candidates.sort(key=lambda item: item[:3])
    targeted = [item for item in candidates if item[0] < _ROLE_ORDER["public"]]
    pool = targeted or candidates
    selected: list[PreferredContactRoute] = []
    seen_groups: set[str] = set()
    for _, _, _, route in pool:
        group = _role_group(route.contact, route.presentation)
        if group in seen_groups:
            continue
        selected.append(route)
        seen_groups.add(group)
        if len(selected) >= limit:
            break
    return selected
