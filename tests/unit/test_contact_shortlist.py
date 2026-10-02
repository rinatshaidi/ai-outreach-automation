from types import SimpleNamespace

from app.modules.crm.contact_shortlist import preferred_contact_routes


def channel(kind: str, value: str) -> SimpleNamespace:
    return SimpleNamespace(
        channel_type=kind,
        value=value,
        url=value,
        confidence=0.9,
        validation_status="VERIFIED",
    )


def contact(
    name: str, role: str | None, score: float, channels: list[SimpleNamespace], *, maker: str | None
) -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        role=role,
        discovery_score=score,
        decision_maker_role=maker,
        validation_status="VERIFIED_CONTACT",
        do_not_contact=False,
        channels=channels,
    )


def test_shortlist_prefers_ceo_then_hr_and_limits_to_two_routes() -> None:
    ceo = contact(
        "Ada Lovelace", "CEO", 80, [channel("linkedin", "https://linkedin/ada")], maker="ceo"
    )
    hr = contact(
        "Company Hiring Team",
        "Recruiting",
        90,
        [channel("official_form", "https://company/jobs")],
        maker="talent_acquisition",
    )
    public = contact(
        "Company Official Contact",
        "Official company contact",
        99,
        [channel("official_form", "https://company/contact")],
        maker=None,
    )

    routes = preferred_contact_routes([public, hr, ceo], "ru")

    assert [item.contact.name for item in routes] == ["Ada Lovelace", "Company Hiring Team"]


def test_shortlist_collapses_many_hiring_pages_to_one_best_route() -> None:
    primary = contact(
        "Company Hiring Team",
        "Recruiting",
        90,
        [channel("official_form", "https://company/jobs")],
        maker="talent_acquisition",
    )
    duplicate = contact(
        "Company Careers",
        "Recruiting",
        80,
        [channel("official_form", "https://company/careers")],
        maker="talent_acquisition",
    )
    public = contact(
        "Company Official Contact",
        "Official company contact",
        99,
        [channel("official_form", "https://company/contact")],
        maker=None,
    )

    routes = preferred_contact_routes([public, duplicate, primary], "ru")

    assert len(routes) == 1
    assert routes[0].contact.name == "Company Hiring Team"


def test_shortlist_omits_semantically_wrong_verified_article() -> None:
    article = contact(
        "Company Official Contact",
        "Official company contact",
        99,
        [channel("official_form", "https://company/blog/contacting-our-team")],
        maker=None,
    )

    assert preferred_contact_routes([article], "ru") == []
