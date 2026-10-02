"""Pure permission rules and fact-pack assembly."""

from collections.abc import Iterable

from app.modules.candidate_profile.models import (
    CandidateContact,
    CandidateExperience,
    CandidateFact,
    CandidateProfile,
    CandidateRule,
    CandidateSkill,
    CandidateStrength,
)
from app.modules.candidate_profile.schemas import (
    CandidateExperienceCreate,
    CandidateSkillCreate,
    CandidateStrengthCreate,
    FactPackContact,
    FactPackFact,
    FactPackPreview,
    FactPackPurpose,
    FactPackRule,
    PermissionFields,
)

_PURPOSE_FIELD = {
    FactPackPurpose.AI_ANALYSIS: "use_for_ai_analysis",
    FactPackPurpose.SCORING: "use_in_scoring",
    FactPackPurpose.DRAFT: "use_in_draft",
    FactPackPurpose.EXTERNAL_SEND: "send_externally",
    FactPackPurpose.SIGNATURE: "use_in_signature",
    FactPackPurpose.PUBLICATION: "publish_publicly",
}


StructuredCandidateRecord = CandidateExperience | CandidateSkill | CandidateStrength


def validate_permissions(
    entity: CandidateFact | CandidateContact | StructuredCandidateRecord,
) -> None:
    """Validate a complete ORM entity after applying a partial update."""

    PermissionFields(
        store_private=bool(entity.store_private),
        use_for_ai_analysis=bool(entity.use_for_ai_analysis),
        use_in_scoring=bool(entity.use_in_scoring),
        use_in_draft=bool(entity.use_in_draft),
        send_externally=bool(entity.send_externally),
        use_in_signature=bool(entity.use_in_signature),
        publish_publicly=bool(entity.publish_publicly),
    )


def validate_structured_record(entity: StructuredCandidateRecord) -> None:
    """Revalidate a complete structured record after a partial update."""

    if isinstance(entity, CandidateExperience):
        CandidateExperienceCreate.model_validate(entity, from_attributes=True)
    elif isinstance(entity, CandidateSkill):
        CandidateSkillCreate.model_validate(entity, from_attributes=True)
    else:
        CandidateStrengthCreate.model_validate(entity, from_attributes=True)


def _allowed(entity: CandidateFact | CandidateContact, purpose: FactPackPurpose) -> bool:
    permission_field = _PURPOSE_FIELD[purpose]
    return bool(entity.store_private and getattr(entity, permission_field))


def build_fact_pack(
    profile: CandidateProfile,
    facts: Iterable[CandidateFact],
    contacts: Iterable[CandidateContact],
    rules: Iterable[CandidateRule],
    purpose: FactPackPurpose,
) -> FactPackPreview:
    """Build a minimal pack using only verified, explicitly permitted records."""

    included_facts: list[FactPackFact] = []
    excluded_fact_ids = []
    for fact in facts:
        if fact.verified and _allowed(fact, purpose):
            included_facts.append(
                FactPackFact(
                    id=fact.id,
                    fact_type=fact.fact_type,
                    text=fact.text,
                    evidence=fact.evidence,
                    source_link=fact.source_link,
                )
            )
        else:
            excluded_fact_ids.append(fact.id)

    included_contacts: list[FactPackContact] = []
    excluded_contact_ids = []
    for contact in contacts:
        signature_allowed = purpose in {
            FactPackPurpose.DRAFT,
            FactPackPurpose.EXTERNAL_SEND,
            FactPackPurpose.SIGNATURE,
            FactPackPurpose.PUBLICATION,
        }
        if (
            contact.verified
            and _allowed(contact, purpose)
            and (not signature_allowed or contact.use_in_signature)
        ):
            included_contacts.append(
                FactPackContact(
                    id=contact.id,
                    contact_type=contact.contact_type,
                    value=contact.value,
                    allowed_in_signature=contact.use_in_signature,
                )
            )
        else:
            excluded_contact_ids.append(contact.id)

    active_rules = [
        FactPackRule(
            id=rule.id,
            rule_type=rule.rule_type,
            text=rule.text,
            severity=rule.severity,
            priority=rule.priority,
        )
        for rule in sorted(rules, key=lambda item: item.priority)
        if rule.active
    ]

    return FactPackPreview(
        purpose=purpose,
        profile_version=profile.version,
        facts=included_facts,
        contacts=included_contacts,
        rules=active_rules,
        excluded_fact_ids=excluded_fact_ids,
        excluded_contact_ids=excluded_contact_ids,
    )
