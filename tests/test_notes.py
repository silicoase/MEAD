import pytest

from mad.notes import format_note


def test_timestamps_survive_replacement_and_append():
    first = format_note("initial", "", author="opaque", timestamps=True, append=False, now="t1")
    second = format_note("entry", first, author="opaque", timestamps=True, append=True, now="t2")
    assert "Created: t1\nUpdated: t2" in second
    assert "initial\n\nEntry: t2\nentry" in second
    replaced = format_note(second, second, author="opaque", timestamps=True, append=False, now="t3")
    assert replaced.count("Author: opaque") == 1
    assert "Created: t1\nUpdated: t3" in replaced
    assert "Entry: t2\nentry" in replaced
    with pytest.raises(ValueError):
        format_note("x" * 65536, second, author="opaque", timestamps=True, append=True, now="t4")
