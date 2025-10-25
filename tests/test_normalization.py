import pytest
from lastweekintech.pipeline.clustering import normalize_title

def test_normalize_title():
    """Unit test for the title normalization function."""
    assert normalize_title("AI Startup Raises $50M | TechCrunch") == "ai startup raises 50 million"
    assert normalize_title("Google's New Pixel Phone - A Deep Dive") == "googles new pixel phone deep dive"
    assert normalize_title("  What's next for self-driving cars? ") == "whats next self driving cars"
