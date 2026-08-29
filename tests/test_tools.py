import pytest

from researchguard.tools import estimate_two_arm_sample_size, search_corpus


def test_sample_size_is_positive_and_even():
    result = estimate_two_arm_sample_size.invoke({"effect_size": 0.4, "power": 0.8})
    assert result > 100
    assert result % 2 == 0


def test_sample_size_rejects_invalid_effect():
    with pytest.raises(ValueError):
        estimate_two_arm_sample_size.invoke({"effect_size": 0})


def test_corpus_returns_traceable_sources():
    evidence = search_corpus("Does sleep improve student learning and memory?")
    assert evidence
    assert all(item.source.startswith("demo://") for item in evidence)
