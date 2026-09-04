"""Livescore → WhoScored ranking must not reuse Livescore ids or sibling dates."""

from recap.resolve_match import LivescoreFixture
from recap.scrape import classify_source, extract_match_id
from recap.source_chain import parse_search_candidates, rank_candidates

MEXICO_LIVESCORE = (
    "https://www.livescore.com/en/football/world-cup-qualification-afc/"
    "group-b/mexico-vs-south-korea/1234567/"
)


def _fixture() -> LivescoreFixture:
    return LivescoreFixture(
        url=MEXICO_LIVESCORE,
        home="Mexico",
        away="South Korea",
        date="2025-08-09",
        event_id="1234567",
    )


def test_livescore_numeric_id_is_not_treated_as_whoscored_id():
    assert extract_match_id(MEXICO_LIVESCORE) is None
    classified = classify_source(MEXICO_LIVESCORE)
    assert classified["kind"] == "livescore"
    assert classified["match_id"] is None
    assert classified["whoscored_url"] == ""
    assert classified["can_scrape"] is True


def test_ranking_prefers_date_in_link_text_over_sibling_context():
    html = """
    <div>
      <a href="/Matches/1111111/Live/international-afc-mexico-south-korea">Mexico vs South Korea</a>
      2025-08-09 other result
    </div>
    <div>
      <a href="/Matches/1953854/Live/international-afc-mexico-south-korea">Mexico vs South Korea 2025-08-09</a>
    </div>
    """
    candidates = parse_search_candidates(html, "https://www.whoscored.com", source="whoscored")
    ranked = rank_candidates(candidates, _fixture())
    assert ranked["status"] == "found"
    assert "1953854" in ranked["candidate"]["url"]
    by_url = {row["url"]: row["score"] for row in ranked["candidates"]}
    dated = next(score for url, score in by_url.items() if "1953854" in url)
    sibling = next(score for url, score in by_url.items() if "1111111" in url)
    assert dated > sibling


def test_bare_whoscored_id_still_extracts():
    assert extract_match_id("1953854") == "1953854"
    assert extract_match_id(
        "https://www.whoscored.com/matches/1953854/live/international-afc-mexico-south-korea"
    ) == "1953854"
