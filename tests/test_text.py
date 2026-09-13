from dictation.text import is_ghost, strip_fillers


def test_strip_fillers_removes_ums() -> None:
    assert strip_fillers("um hello uh world") == "hello world"


def test_strip_fillers_keeps_real_words() -> None:
    assert strip_fillers("write a python dict") == "write a python dict"


def test_strip_fillers_punctuation() -> None:
    assert strip_fillers("ah, ship it") == "ship it"


def test_ghosts() -> None:
    assert is_ghost("thank you")
    assert is_ghost("Thanks for watching.")
    assert is_ghost("you")
    assert is_ghost("   ")
    assert is_ghost(".")


def test_not_ghosts() -> None:
    assert not is_ghost("write a python dict")
    assert not is_ghost("The quick brown fox")
