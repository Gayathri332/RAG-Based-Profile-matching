import sys
from pathlib import Path

# Add src/ to path
sys.path.append(str(Path(__file__).resolve().parent.parent / "src"))

from resume_rag import MetadataExtractor, ResumeChunker
from job_matcher import JobMatcher


def test_metadata_extractor_experience():
    extractor = MetadataExtractor()
    assert extractor.extract_experience("Senior Software Engineer with 8+ years of experience in Java.") == 8
    assert extractor.extract_experience("DevOps exp: 5 yrs in AWS") == 5
    assert extractor.extract_experience("Frontend developer with 3 years exp") == 3
    assert extractor.extract_experience("No experience mentioned") == 0


def test_metadata_extractor_skills():
    extractor = MetadataExtractor()
    text = "We use Python, Java, Docker, and Kubernetes. Also React."
    skills = extractor.extract_skills(text)
    assert "Python" in skills
    assert "Java" in skills
    assert "Docker" in skills
    assert "Kubernetes" in skills
    assert "React" in skills
    assert "C++" not in skills


def test_metadata_extractor_name():
    extractor = MetadataExtractor()
    assert extractor.extract_name("resume_john_doe.pdf", "John Doe\nSummary: Python developer") == "John Doe"
    assert extractor.extract_name("alex-kumar.docx", "Alex Kumar\nSkills: Java") == "Alex Kumar"
    assert extractor.extract_name("random.txt", "Diana Prince\nSkills: Go") == "Diana Prince"


def test_metadata_extractor_education():
    extractor = MetadataExtractor()
    text = "Education:\nB.Tech in Computer Science, IIT\nM.S. in Software Engineering, Stanford"
    edu = extractor.extract_education(text)
    assert "B.Tech" in edu
    assert "M.S." in edu


def test_resume_chunker():
    chunker = ResumeChunker()
    text = """Alex Kumar
Machine Learning Engineer

SKILLS:
Python, ML, PyTorch

EXPERIENCE:
ML Engineer at TechAI
Built LLM apps.

EDUCATION:
B.Tech, IIT
"""
    chunks = chunker.chunk(text)
    assert len(chunks) > 0
    sections = [c['section'] for c in chunks]
    assert 'SKILLS' in sections
    assert 'EXPERIENCE' in sections
    assert 'EDUCATION' in sections


def test_job_matcher_initialization():
    matcher = JobMatcher()
    assert matcher.embedder is not None
    assert matcher.collection is not None


if __name__ == "__main__":
    test_metadata_extractor_experience()
    test_metadata_extractor_skills()
    test_metadata_extractor_name()
    test_metadata_extractor_education()
    test_resume_chunker()
    test_job_matcher_initialization()
    print("All unit tests passed successfully!")
