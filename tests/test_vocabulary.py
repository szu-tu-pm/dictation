from dictation.paths import history_path, vocabulary_path
from dictation.vocabulary import (
    Replacement,
    Vocabulary,
    apply_replacements,
    load_vocabulary,
    save_vocabulary,
)


def test_apply_replacements_whole_word() -> None:
    vocab = Vocabulary(replacements=[Replacement(heard="wisper", meant="Whisper")])
    assert apply_replacements("try wisper Flow", vocab) == "try Whisper Flow"


def test_apply_replacements_case_insensitive() -> None:
    vocab = Vocabulary(replacements=[Replacement(heard="ana", meant="Anna")])
    assert apply_replacements("Ana and ANA", vocab) == "Anna and Anna"


def test_apply_replacements_ignores_partial() -> None:
    vocab = Vocabulary(replacements=[Replacement(heard="cat", meant="dog")])
    assert apply_replacements("category", vocab) == "category"


def test_apply_replacements_symbol_terms() -> None:
    vocab = Vocabulary(
        replacements=[
            Replacement(heard="C++", meant="Cplusplus"),
            Replacement(heard="C#", meant="CSharp"),
            Replacement(heard="Node.js", meant="NodeJS"),
        ]
    )
    assert apply_replacements("I write C++ and C# with Node.js", vocab) == (
        "I write Cplusplus and CSharp with NodeJS"
    )
    # Still avoid matching inside longer alphanumeric tokens
    assert apply_replacements("category", Vocabulary(replacements=[Replacement("cat", "dog")])) == (
        "category"
    )


def test_prompt_joins_unique_names() -> None:
    vocab = Vocabulary(
        words=["Cursor", "Vulkan"],
        replacements=[Replacement(heard="courser", meant="Cursor")],
    )
    assert vocab.prompt() == "Cursor, Vulkan"


def test_prompt_truncates_at_comma() -> None:
    vocab = Vocabulary(words=["alpha", "beta-word", "gamma"])
    assert vocab.prompt(limit=12) == "alpha"


def test_vocabulary_roundtrip(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    vocab = Vocabulary(
        words=["Dictation"],
        replacements=[Replacement(heard="wisper", meant="Whisper")],
    )
    save_vocabulary(vocab)
    assert vocabulary_path() == tmp_path / "Dictation" / "vocabulary.json"
    loaded = load_vocabulary()
    assert loaded.words == ["Dictation"]
    assert loaded.replacements[0].meant == "Whisper"


def test_load_vocabulary_accepts_dict_replacements(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    vocabulary_path().parent.mkdir(parents=True, exist_ok=True)
    vocabulary_path().write_text(
        '{"words": ["Cursor"], "replacements": {"wisper": "Whisper"}}\n',
        encoding="utf-8",
    )
    loaded = load_vocabulary()
    assert loaded.words == ["Cursor"]
    assert apply_replacements("wisper", loaded) == "Whisper"


def test_load_vocabulary_creates_default(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    loaded = load_vocabulary()
    assert loaded.words == []
    assert vocabulary_path().is_file()


def test_load_vocabulary_quarantines_corrupt_json(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    path = vocabulary_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not-json", encoding="utf-8")
    loaded = load_vocabulary()
    assert loaded.words == []
    assert path.is_file()
    bak = path.with_name(path.name + ".bak")
    assert bak.is_file()
    assert bak.read_text(encoding="utf-8") == "{not-json"


def test_load_vocabulary_quarantines_non_object(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    path = vocabulary_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[1, 2]\n", encoding="utf-8")
    loaded = load_vocabulary()
    assert loaded.words == []
    assert path.with_name(path.name + ".bak").is_file()
