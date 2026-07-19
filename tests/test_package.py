"""Tests for the package setup."""


def test_package_is_importable() -> None:
    """The package can be imported from the configured src layout."""
    import drum_score_converter

    assert drum_score_converter.__doc__

