from app.services.retrieval_planner import RetrievalPlanner, filter_by_content_type, dedup_matches


def test_planner_returns_lanes_for_benefit_intent() -> None:
    planner = RetrievalPlanner()
    lanes = planner.plan("benefit_query", "重疾赔多少")
    assert len(lanes) >= 2
    methods = {l.method for l in lanes}
    assert "dense" in methods
    assert "bm25" in methods


def test_planner_includes_section_bm25_for_disease_definition() -> None:
    planner = RetrievalPlanner()
    lanes = planner.plan("disease_definition", "原位癌算不算轻症")
    methods = {l.method for l in lanes}
    assert "section_bm25" in methods


def test_planner_includes_section_bm25_for_exclusion() -> None:
    planner = RetrievalPlanner()
    lanes = planner.plan("exclusion_query", "酒驾赔不赔")
    section_lanes = [l for l in lanes if l.method == "section_bm25"]
    assert len(section_lanes) >= 1


def test_planner_includes_section_hints() -> None:
    planner = RetrievalPlanner()
    lanes = planner.plan("waiting_period", "等待期多久")
    section_lanes = [l for l in lanes if l.method == "section_bm25"]
    assert len(section_lanes) >= 1
    assert len(section_lanes[0].section_hints) > 0


def test_planner_general_returns_basic_lanes() -> None:
    planner = RetrievalPlanner()
    lanes = planner.plan("general", "hello")
    methods = {l.method for l in lanes}
    assert "dense" in methods
    assert "bm25" in methods
    assert "section_bm25" not in methods


def test_planner_unknown_intent_falls_back_to_general() -> None:
    planner = RetrievalPlanner()
    lanes = planner.plan("unknown_intent_type", "hello")
    assert len(lanes) == 2


def test_describe_returns_lane_summaries() -> None:
    planner = RetrievalPlanner()
    lanes = planner.plan("benefit_query", "赔多少")
    descriptions = planner.describe(lanes)
    assert len(descriptions) == len(lanes)
    for d in descriptions:
        assert "method" in d
        assert "weight" in d


def test_filter_by_content_type_empty_list_returns_all() -> None:
    matches = [
        {"metadata": {"content_type": "clause"}},
        {"metadata": {"content_type": "insurance_liability"}},
    ]
    assert len(filter_by_content_type(matches, [])) == 2


def test_filter_by_content_type_filters_correctly() -> None:
    matches = [
        {"id": "1", "metadata": {"content_type": "clause"}},
        {"id": "2", "metadata": {"content_type": "exclusion"}},
        {"id": "3", "metadata": {"content_type": "insurance_liability"}},
    ]
    result = filter_by_content_type(matches, ["exclusion"])
    assert len(result) == 1
    assert result[0]["id"] == "2"


def test_dedup_matches_removes_duplicate_ids() -> None:
    matches = [
        {"id": "a", "metadata": {"content_type": "clause"}},
        {"id": "b", "metadata": {"content_type": "exclusion"}},
        {"id": "a", "metadata": {"content_type": "clause"}},
    ]
    result = dedup_matches(matches)
    assert len(result) == 2


def test_dedup_matches_removes_same_parent_section() -> None:
    matches = [
        {"id": "1", "metadata": {"parent_id": "p1", "section_no": "2.4", "content_type": "clause"}},
        {"id": "2", "metadata": {"parent_id": "p1", "section_no": "2.4", "content_type": "insurance_liability"}},
        {"id": "3", "metadata": {"parent_id": "p2", "section_no": "2.6", "content_type": "exclusion"}},
    ]
    result = dedup_matches(matches)
    assert len(result) <= 2


def test_dedup_matches_keeps_different_sections() -> None:
    matches = [
        {"id": "1", "metadata": {"parent_id": "p1", "section_no": "2.4"}},
        {"id": "2", "metadata": {"parent_id": "p2", "section_no": "2.6"}},
        {"id": "3", "metadata": {"parent_id": "p3", "section_no": "10.1"}},
    ]
    result = dedup_matches(matches)
    assert len(result) == 3


def test_dedup_without_metadata_preserves_all() -> None:
    matches = [
        {"id": "1"},
        {"id": "2"},
    ]
    result = dedup_matches(matches)
    assert len(result) == 2
