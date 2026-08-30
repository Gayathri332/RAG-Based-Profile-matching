import re
import json
from typing import Dict, List, Optional
from sentence_transformers import SentenceTransformer
from rank_bm25 import BM25Okapi
import chromadb

import config
from resume_rag import MetadataExtractor


class JobMatcher:
    def __init__(self, model_name: Optional[str] = None, collection_name: str = 'resumes'):
        self.model_name = model_name or config.EMBEDDING_MODEL
        self.embedder = SentenceTransformer(self.model_name)
        self.client = chromadb.PersistentClient(path=config.VECTOR_DB_PATH)
        self.collection = self.client.get_collection(collection_name)

    def match(
        self,
        job_description: str,
        k: int = 10,
        min_exp: Optional[int] = None,
        must_have_skills: Optional[List[str]] = None,
        apply_filters: bool = True
    ) -> Dict:
        # Auto-detect minimum experience years from JD if not explicitly provided
        if min_exp is None:
            exp_matches = re.findall(r"(\d+)\+?\s*(?:years?|yrs?)(?:\s*(?:of)?\s*(?:experience|exp))?", job_description, re.I)
            # Find the minimum mentioned years of experience, or default to 0
            parsed_exps = []
            for x in exp_matches:
                try:
                    parsed_exps.append(int(x))
                except ValueError:
                    pass
            min_exp = min(parsed_exps) if parsed_exps else 0
            print(f"Auto-detected experience requirement from JD: {min_exp}+ years")
        else:
            print(f"Using explicit experience requirement: {min_exp}+ years")

        if must_have_skills is None:
            must_have_skills = []
            print("No explicit must-have skills filter applied.")
        else:
            print(f"Applying must-have skills filter: {must_have_skills}")

        # Fetch all documents to build the BM25 index for keyword search
        all_chunks = self.collection.get()
        documents = all_chunks['documents']
        metadatas = all_chunks['metadatas']
        ids = all_chunks['ids']

        if not documents:
            return {"job_description": job_description, "top_matches": []}

        # 1. Semantic Search using ChromaDB
        query_emb = self.embedder.encode(job_description).tolist()
        results = self.collection.query(query_embeddings=[query_emb], n_results=len(ids))

        semantic_scores_dict = {}
        if results and 'ids' in results and len(results['ids']) > 0:
            res_ids = results['ids'][0]
            res_distances = results['distances'][0]
            for r_id, dist in zip(res_ids, res_distances):
                # Cosine distance to similarity: 1.0 - (dist / 2.0)
                sim = 1.0 - (dist / 2.0)
                semantic_scores_dict[r_id] = max(0.0, min(1.0, sim))

        # 2. Keyword Search using BM25
        tokenized_corpus = [doc.lower().split() for doc in documents]
        bm25 = BM25Okapi(tokenized_corpus)
        tokenized_query = job_description.lower().split()
        bm25_scores = bm25.get_scores(tokenized_query)
        
        # Normalize BM25 scores
        max_bm25 = max(bm25_scores) if len(bm25_scores) > 0 else 0
        normalized_bm25_scores = [s / max_bm25 if max_bm25 > 0 else 0.0 for s in bm25_scores]

        # 3. Hybrid Retrieval & Filtering
        candidate_matches = {}

        for chunk_idx, (doc_id, doc_text, meta) in enumerate(zip(ids, documents, metadatas)):
            candidate_exp = int(meta.get('experience_years', 0))
            if apply_filters:
                # Filter by experience
                if candidate_exp < min_exp:
                    continue

                # Filter by must-have skills
                candidate_skills_str = meta.get('skills', '')
                candidate_skills = [s.strip().lower() for s in candidate_skills_str.split(',') if s.strip()]
                
                if must_have_skills:
                    meets_skills = all(s.lower() in candidate_skills for s in must_have_skills)
                    if not meets_skills:
                        continue

            # Compute combined hybrid score: 60% semantic + 40% keyword
            semantic_score = semantic_scores_dict.get(doc_id, 0.5)
            bm25_score = normalized_bm25_scores[chunk_idx]
            
            hybrid_score = 0.6 * semantic_score + 0.4 * bm25_score
            score_100 = max(0, min(100, int(hybrid_score * 100)))

            resume_path = meta.get('resume_path')
            if resume_path not in candidate_matches:
                candidate_matches[resume_path] = {
                    "candidate_name": meta.get('candidate_name', 'Unknown'),
                    "resume_path": resume_path,
                    "max_score": score_100,
                    "chunks": [],
                    "skills": [s.strip() for s in meta.get('skills', '').split(',') if s.strip()],
                    "experience_years": candidate_exp,
                    "education": meta.get('education', 'Not Specified')
                }
            else:
                if score_100 > candidate_matches[resume_path]["max_score"]:
                    candidate_matches[resume_path]["max_score"] = score_100

            candidate_matches[resume_path]["chunks"].append({
                "section": meta.get('section', 'GENERAL'),
                "content": doc_text,
                "score": score_100
            })

        # 4. Score Matching & Match Reasoning Generation
        top_matches = []
        for resume_path, info in candidate_matches.items():
            # Sort candidate's matching chunks
            info["chunks"].sort(key=lambda x: x["score"], reverse=True)
            
            # Find which sections matched best
            matched_sections = list(set(ch["section"] for ch in info["chunks"] if ch["score"] >= 65))
            if not matched_sections:
                matched_sections = [info["chunks"][0]["section"]]

            # Find matching skills between the candidate's extracted skills
            # and the JD text. Substring matching (not a word-set membership
            # check) so multi-word skills like "Machine Learning" or "Spring
            # Boot" are detected correctly - splitting the JD into single
            # tokens would never match a two-word skill name.
            jd_lower = job_description.lower()
            matched_skills = [s for s in info["skills"] if s.lower() in jd_lower]

            # Skill gap: known skills that are mentioned in the JD but this
            # candidate's resume doesn't list.
            candidate_skills_lower = {s.lower() for s in info["skills"]}
            jd_required_skills = [
                s for s in MetadataExtractor.SKILLS
                if s.lower() in jd_lower and s.lower() not in candidate_skills_lower
            ]

            # Relevant excerpts from the highest scoring chunks
            relevant_excerpts = [
                ch["content"][:300] + ("..." if len(ch["content"]) > 300 else "") 
                for ch in info["chunks"][:2]
            ]

            # Custom, readable match reasoning
            reasoning = (
                f"Candidate possesses {info['experience_years']} years of experience (education: '{info['education']}'). "
                f"Highest matching content was found in sections: {', '.join(matched_sections)}."
            )
            if matched_skills:
                reasoning = f"Strong skill overlap for {', '.join(matched_skills)}. " + reasoning

            top_matches.append({
                "candidate_name": info["candidate_name"],
                "resume_path": info["resume_path"],
                "match_score": info["max_score"],
                "matched_skills": matched_skills,
                "missing_skills": jd_required_skills,
                "relevant_excerpts": relevant_excerpts,
                "reasoning": reasoning
            })

        # Sort matches by score descending
        top_matches.sort(key=lambda x: x["match_score"], reverse=True)

        return {
            "job_description": job_description,
            "top_matches": top_matches[:k]
        }


if __name__ == "__main__":
    import sys
    matcher = JobMatcher()
    
    # Simple CLI test
    test_jd = "Looking for a Python developer with 3+ years experience and knowledge of Docker/Kubernetes."
    if len(sys.argv) > 1:
        test_jd = sys.argv[1]
        
    print(f"Matching JD: '{test_jd}'")
    results = matcher.match(test_jd)
    print(json.dumps(results, indent=2))
