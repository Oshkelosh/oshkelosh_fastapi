"""Tests for utility functions."""

from app.utils.slugify import slugify


class TestSlugify:
    """Test the slugify utility."""

    def test_simple_slug(self):
        assert slugify("Hello World") == "hello-world"

    def test_slug_with_special_chars(self):
        assert slugify("Hello World!") == "hello-world"

    def test_slug_with_numbers(self):
        assert slugify("Oshkelosh 101") == "oshkelosh-101"

    def test_slug_with_spaces(self):
        assert slugify("  Lots   of   spaces  ") == "lots-of-spaces"

    def test_slug_already_slug(self):
        assert slugify("already-a-slug") == "already-a-slug"

    def test_slug_empty(self):
        assert slugify("") == ""

    def test_slug_unicode(self):
        assert slugify("café résumé") == "cafe-resume"
