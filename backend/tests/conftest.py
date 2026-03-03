"""Test fixtures and shared configuration."""
import os
import sys
import tempfile
import pytest
import fitz  # PyMuPDF

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Sample PDF paths (AEC-Q101 if available)
SAMPLE_DIR = "/sessions/brave-gifted-babbage/mnt/Claude/PDF compare"
OLD_PDF = os.path.join(SAMPLE_DIR, "AEC-Q101_Rev_D1_2013.pdf")
NEW_PDF = os.path.join(SAMPLE_DIR, "AEC-Q101_Rev_E_2021.pdf")

HAS_SAMPLE_PDFS = os.path.exists(OLD_PDF) and os.path.exists(NEW_PDF)


@pytest.fixture
def sample_pdf_pair():
    """Return paths to sample PDFs if available."""
    if not HAS_SAMPLE_PDFS:
        pytest.skip("Sample AEC-Q101 PDFs not available")
    return OLD_PDF, NEW_PDF


@pytest.fixture
def tiny_pdf(tmp_path):
    """Create a minimal test PDF with known content."""
    path = str(tmp_path / "test.pdf")
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), "1 Introduction\nThis is the introduction section.\n\nHello world.")
    page.insert_text((72, 200), "2 Methods\nThe quick brown fox jumps over the lazy dog.")
    page.insert_text((72, 300), "3 Results\nTest results are positive.\nAll 10 samples passed.")
    doc.save(path)
    doc.close()
    return path


@pytest.fixture
def two_tiny_pdfs(tmp_path):
    """Create two slightly different test PDFs for diff testing."""
    old_path = str(tmp_path / "old.pdf")
    new_path = str(tmp_path / "new.pdf")

    # Old version
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), "1 Introduction\nThis document describes version 1.")
    page.insert_text((72, 200), "2 Methods\nWe use the alpha method for testing.")
    page.insert_text((72, 300), "3 Results\nAll 5 tests passed.")
    doc.save(old_path)
    doc.close()

    # New version (modified Introduction, changed Results, added section)
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), "1 Introduction\nThis document describes version 2 with improvements.")
    page.insert_text((72, 200), "2 Methods\nWe use the alpha method for testing.")
    page.insert_text((72, 300), "3 Results\nAll 10 tests passed with flying colors.")
    page.insert_text((72, 400), "4 Conclusions\nThe new version is better.")
    doc.save(new_path)
    doc.close()

    return old_path, new_path


@pytest.fixture
def tmp_output_dir(tmp_path):
    """Temp directory for output files."""
    return str(tmp_path / "output")
