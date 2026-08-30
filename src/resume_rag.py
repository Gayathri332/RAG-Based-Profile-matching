import re
import json
import hashlib
from pathlib import Path
from typing import Dict, List, Optional
from sentence_transformers import SentenceTransformer
import chromadb

import config
from fs_tools import list_files, read_file

SECTION_HEADERS = [
    'EXPERIENCE', 'WORK EXPERIENCE', 'EDUCATION', 'SKILLS', 'PROJECTS', 
    'CERTIFICATIONS', 'SUMMARY', 'PROFESSIONAL EXPERIENCE', 'ACADEMIC BACKGROUND',
    'TECHNICAL SKILLS', 'AWARDS', 'WORK HISTORY', 'OBJECTIVE'
]


class MetadataExtractor:
    SKILLS = [
        "Python", "Java", "Spring Boot", "AWS", "Docker", "Kubernetes", "SQL", "Kafka", "React",
        "JavaScript", "TypeScript", "HTML", "CSS", "C++", "Go", "Golang", "Rust", "Ruby", "Rails",
        "PHP", "Laravel", "Swift", "Kotlin", "Objective-C", "Android", "iOS", "Flutter", "React Native",
        "Node.js", "Express", "Django", "Flask", "FastAPI", "PostgreSQL", "MySQL", "MongoDB", "Redis",
        "Cassandra", "Elasticsearch", "Spark", "Hadoop", "Pandas", "NumPy", "Scikit-Learn", "TensorFlow",
        "PyTorch", "Git", "CI/CD", "Jenkins", "Terraform", "Ansible", "Linux", "GCP", "Azure", "HTML5",
        "CSS3", "GraphQL", "REST API", "Microservices", "Machine Learning", "Deep Learning", "NLP",
        "Generative AI", "LLM", "LangChain", "RAG", "Data Science"
    ]

    def extract_name(self, filename: str, text: str) -> str:
        # Heuristic 1: Clean filename to extract name if format matches common patterns
        base = Path(filename).stem
        for prefix in ["resume_", "resume-", "cv_", "cv-", "summary_", "summary-"]:
            if base.lower().startswith(prefix):
                base = base[len(prefix):]
        if "_" in base or "-" in base or " " in base:
            name = base.replace("_", " ").replace("-", " ").title()
            name = " ".join(part for part in name.split() if part.isalpha())
            if name:
                return name
        
        # Heuristic 2: Extract from the first few lines of text
        for line in text.splitlines():
            line_stripped = line.strip()
            if not line_stripped:
                continue
            if line_stripped.upper() in SECTION_HEADERS:
                continue
            words = line_stripped.split()
            if 1 <= len(words) <= 4 and all(w.replace(".", "").isalpha() for w in words):
                return line_stripped.title()
            break
        return "Unknown"

    def extract_skills(self, text: str) -> List[str]:
        text_lower = text.lower()
        found = []
        for skill in self.SKILLS:
            pattern = rf"\b{re.escape(skill.lower())}\b"
            if not skill.isalnum():
                if skill.lower() in text_lower:
                    found.append(skill)
            else:
                if re.search(pattern, text_lower):
                    found.append(skill)
        return sorted(list(set(found)))

    def extract_experience(self, text: str) -> int:
        patterns = [
            r"(\d+)\+?\s*(?:years?|yrs?)(?:\s*of)?\s*(?:experience|exp)",
            r"(?:experience|exp)\s*:\s*(\d+)\+?\s*(?:years?|yrs?)",
            r"(\d+)\+?\s*(?:years?|yrs?)\b"
        ]
        years = []
        for pattern in patterns:
            matches = re.findall(pattern, text, re.I)
            for m in matches:
                try:
                    years.append(int(m))
                except ValueError:
                    pass
        return max(years, default=0)

    def extract_education(self, text: str) -> str:
        edu_keywords = ["B.S.", "B.S", "B.Tech", "M.S.", "M.S", "M.Tech", "Ph.D.", "PhD", "Bachelor", "Master", "B.A.", "B.A", "M.A.", "M.A"]
        education_entries = []
        
        for line in text.splitlines():
            line_stripped = line.strip()
            for kw in edu_keywords:
                if re.search(rf"\b{re.escape(kw)}\b", line_stripped, re.I):
                    education_entries.append(line_stripped)
                    break
        
        if education_entries:
            return "; ".join(education_entries[:3])
        return "Not Specified"

    def extract(self, filename: str, text: str) -> Dict:
        return {
            "candidate_name": self.extract_name(filename, text),
            "skills": self.extract_skills(text),
            "experience_years": self.extract_experience(text),
            "education": self.extract_education(text),
        }


class ResumeChunker:
    def chunk(self, text: str) -> List[Dict[str, str]]:
        chunks = []
        current_section = 'GENERAL'
        buf = []
        
        for line in text.splitlines():
            line_clean = line.strip().strip("#").strip().strip(":").strip()
            if line_clean.upper() in SECTION_HEADERS:
                if buf:
                    content = '\n'.join(buf).strip()
                    if content:
                        chunks.append({'section': current_section, 'content': content})
                current_section = line_clean.upper()
                buf = []
            else:
                buf.append(line)
        
        if buf:
            content = '\n'.join(buf).strip()
            if content:
                chunks.append({'section': current_section, 'content': content})
                
        return chunks


class ResumeRAGPipeline:
    def __init__(self, model_name: Optional[str] = None, collection_name: str = 'resumes'):
        self.model_name = model_name or config.EMBEDDING_MODEL
        self.embedder = SentenceTransformer(self.model_name)
        self.client = chromadb.PersistentClient(path=config.VECTOR_DB_PATH)
        # Explicitly request cosine distance: job_matcher.py converts ChromaDB's
        # returned "distance" into a similarity score assuming cosine distance
        # (range 0-2). Without this, Chroma defaults to squared-L2 distance,
        # which is on a different scale and would silently produce meaningless
        # semantic similarity scores.
        self.collection = self.client.get_or_create_collection(
            collection_name, metadata={"hnsw:space": "cosine"}
        )

    def reset_collection(self):
        """Drop and recreate the collection so re-ingestion starts clean."""
        name = self.collection.name
        self.client.delete_collection(name)
        self.collection = self.client.get_or_create_collection(
            name, metadata={"hnsw:space": "cosine"}
        )

    def remove_resume(self, resume_path: str):
        """Delete every chunk belonging to a single indexed resume."""
        self.collection.delete(where={"resume_path": resume_path})

    def ingest_directory(self, resume_dir: str, progress_callback=None):
        """
        Ingest all supported resumes in resume_dir.
        Uses upsert so re-running ingestion on the same files is idempotent
        (safe to call again after adding new resumes to the folder).
        progress_callback(filename, meta, idx, total), if provided, is called
        once per file after it is ingested (used by the Streamlit UI).
        """
        extractor = MetadataExtractor()
        chunker = ResumeChunker()
        files = list_files(resume_dir)

        for idx, f in enumerate(files):
            data = read_file(f['path'])
            if not data.get('success'):
                if progress_callback:
                    progress_callback(f['name'], None, idx, len(files))
                continue
            text = data['content']

            meta = extractor.extract(f['name'], text)
            chunks = chunker.chunk(text)

            # Print for ingestion tracking
            print(f"Ingesting {f['name']} - Name: {meta['candidate_name']}, Exp: {meta['experience_years']} yrs, Skills: {len(meta['skills'])}")

            # Derive the id prefix from the full resume path (not just the
            # filename) so two different resumes that happen to share a
            # filename - e.g. one from data/resumes and one freshly uploaded -
            # never collide and silently overwrite each other's chunks.
            path_hash = hashlib.md5(f['path'].encode('utf-8')).hexdigest()[:10]

            ids, docs, embs, metas = [], [], [], []
            for c_idx, ch in enumerate(chunks):
                emb = self.embedder.encode(ch['content']).tolist()
                chunk_id = f"{path_hash}_{c_idx}"

                chunk_meta = {
                    "candidate_name": meta["candidate_name"],
                    "skills": ", ".join(meta["skills"]),
                    "experience_years": int(meta["experience_years"]),
                    "education": meta["education"],
                    "resume_path": f["path"],
                    "filename": f["name"],
                    "section": ch["section"]
                }
                ids.append(chunk_id)
                docs.append(ch['content'])
                embs.append(emb)
                metas.append(chunk_meta)

            if ids:
                self.collection.upsert(
                    ids=ids,
                    documents=docs,
                    embeddings=embs,
                    metadatas=metas
                )

            if progress_callback:
                progress_callback(f['name'], meta, idx, len(files))


if __name__ == "__main__":
    import sys
    pipeline = ResumeRAGPipeline()
    directory = sys.argv[1] if len(sys.argv) > 1 else config.RESUMES_DIR
    print(f"Ingesting resumes from directory: {directory}")
    pipeline.ingest_directory(directory)
    print("Ingestion complete.")
