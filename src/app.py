"""
Streamlit UI for the RAG-Based Profile Matching Engine.

Two things it lets you do:
  1. Ingest resumes (bundled sample set or your own uploads) into the
     ChromaDB vector store, with metadata extraction (name, skills,
     experience, education).
  2. Paste / pick a job description and run the hybrid (semantic + BM25)
     job-matching engine against the indexed resumes, with score breakdown,
     matched skills, and excerpt-level reasoning.

Run with:
    streamlit run src/app.py
"""
import csv
import io
import json
import sys
import tempfile
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config
from resume_rag import ResumeRAGPipeline, MetadataExtractor
from job_matcher import JobMatcher

st.set_page_config(
    page_title="RAG Profile Matching Engine",
    page_icon="🧩",
    layout="wide",
)

ALL_SKILLS = sorted(MetadataExtractor.SKILLS)


# --------------------------------------------------------------------------
# Cached resources
# --------------------------------------------------------------------------
@st.cache_resource(show_spinner="Loading embedding model & vector store...")
def get_pipeline() -> ResumeRAGPipeline:
    return ResumeRAGPipeline()


@st.cache_resource(show_spinner="Loading matching engine...")
def get_matcher() -> JobMatcher:
    return JobMatcher()


def collection_snapshot():
    """Return (num_chunks, candidates_dict[resume_path] -> metadata) for the current index."""
    pipeline = get_pipeline()
    data = pipeline.collection.get()
    metadatas = data.get("metadatas", []) or []
    candidates = {}
    for meta in metadatas:
        rp = meta.get("resume_path")
        if rp and rp not in candidates:
            candidates[rp] = meta
    return len(metadatas), candidates


def clear_caches():
    get_pipeline.clear()
    get_matcher.clear()


# --------------------------------------------------------------------------
# Sidebar — index status + ingestion controls
# --------------------------------------------------------------------------
with st.sidebar:
    st.title("🧩 Profile Matching Engine")
    st.caption(f"Embedding model: `{config.EMBEDDING_MODEL}`")

    st.divider()
    st.subheader("Vector index")

    try:
        num_chunks, candidates = collection_snapshot()
    except Exception:
        num_chunks, candidates = 0, {}

    c1, c2 = st.columns(2)
    c1.metric("Resumes indexed", len(candidates))
    c2.metric("Chunks stored", num_chunks)

    st.divider()
    st.subheader("Ingest resumes")

    source = st.radio(
        "Source",
        ["Bundled sample resumes", "Upload my own"],
        label_visibility="collapsed",
    )

    uploaded_files = None
    if source == "Upload my own":
        uploaded_files = st.file_uploader(
            "Resumes (.pdf, .docx, .txt)",
            type=["pdf", "docx", "txt"],
            accept_multiple_files=True,
        )

    reset_first = st.checkbox(
        "Reset index before ingesting",
        value=False,
        help="Clears the existing vector store first. Leave unchecked to add/update resumes incrementally.",
    )

    if st.button("▶ Run ingestion", use_container_width=True):
        pipeline = get_pipeline()
        if reset_first:
            pipeline.reset_collection()

        if source == "Bundled sample resumes":
            target_dir = config.RESUMES_DIR
            if not Path(target_dir).exists():
                st.error(f"No bundled resumes found at {target_dir}")
                target_dir = None
        else:
            if not uploaded_files:
                st.warning("Upload at least one resume file first.")
                target_dir = None
            else:
                tmp_dir = tempfile.mkdtemp(prefix="uploaded_resumes_")
                for uf in uploaded_files:
                    (Path(tmp_dir) / uf.name).write_bytes(uf.getvalue())
                target_dir = tmp_dir

        if target_dir:
            progress_bar = st.progress(0.0)
            status = st.empty()
            log_lines = []

            def on_progress(filename, meta, idx, total):
                frac = (idx + 1) / total if total else 1.0
                progress_bar.progress(min(frac, 1.0))
                if meta:
                    log_lines.append(
                        f"✅ {filename} — {meta['candidate_name']} · "
                        f"{meta['experience_years']} yrs · {len(meta['skills'])} skills"
                    )
                else:
                    log_lines.append(f"⚠️ {filename} — could not be read")
                status.text(f"Ingesting {idx + 1}/{total}: {filename}")

            with st.spinner("Chunking, embedding, and indexing resumes..."):
                pipeline.ingest_directory(target_dir, progress_callback=on_progress)

            status.empty()
            progress_bar.empty()
            st.success(f"Ingestion complete — {len(log_lines)} file(s) processed.")
            with st.expander("Ingestion log"):
                st.code("\n".join(log_lines) or "Nothing was ingested.")

            clear_caches()
            st.rerun()


# --------------------------------------------------------------------------
# Main area
# --------------------------------------------------------------------------
st.title("RAG-Based Profile Matching Engine")
st.caption(
    "Hybrid semantic (ChromaDB + Sentence-Transformers) + keyword (BM25) search "
    "over resumes, with metadata filtering and match-level reasoning."
)

tab_match, tab_directory, tab_analytics = st.tabs(
    ["🔍 Match candidates", "📁 Candidate directory", "📊 Analytics"]
)

# --------------------------------------------------------------------------
# Tab 1 — Job matching
# --------------------------------------------------------------------------
with tab_match:
    if not candidates:
        st.info("No resumes are indexed yet. Use the sidebar to run ingestion first.")
    else:
        left, right = st.columns([3, 2])

        with left:
            sample_jd_dir = Path(config.JOB_DESCRIPTIONS_DIR)
            sample_jds = sorted(sample_jd_dir.glob("*.txt")) if sample_jd_dir.exists() else []
            jd_names = ["— write my own —"] + [p.name for p in sample_jds]
            picked = st.selectbox("Start from a sample job description (optional)", jd_names)

            default_text = ""
            if picked != "— write my own —":
                default_text = (sample_jd_dir / picked).read_text(encoding="utf-8", errors="ignore")

            jd_text = st.text_area(
                "Job description",
                value=default_text,
                height=240,
                placeholder="Paste a job description here...",
            )

            if jd_text.strip():
                jd_lower = jd_text.lower()
                detected = [s for s in ALL_SKILLS if s.lower() in jd_lower]
                if detected:
                    st.caption(
                        "Detected skills in this JD: "
                        + " ".join(f"`{s}`" for s in detected)
                    )

        with right:
            k = st.slider("Top-K matches", min_value=1, max_value=20, value=config.TOP_K)

            auto_exp = st.checkbox("Auto-detect min. experience from JD", value=True)
            min_exp = None
            if not auto_exp:
                min_exp = st.number_input("Minimum years of experience", min_value=0, max_value=30, value=0)

            must_have = st.multiselect("Must-have skills (hard filter)", ALL_SKILLS)

            apply_filters = st.checkbox("Apply experience / must-have filters", value=True)

            run = st.button("🔎 Find matches", type="primary", use_container_width=True)

        if run:
            if not jd_text.strip():
                st.warning("Enter or select a job description first.")
            else:
                matcher = get_matcher()
                with st.spinner("Running hybrid semantic + keyword search..."):
                    results = matcher.match(
                        job_description=jd_text,
                        k=k,
                        min_exp=min_exp,
                        must_have_skills=must_have or None,
                        apply_filters=apply_filters,
                    )

                matches = results["top_matches"]
                st.divider()

                if not matches:
                    st.warning(
                        "No candidates met the filters. Try lowering the experience "
                        "requirement, removing must-have skills, or unchecking filters."
                    )
                else:
                    st.subheader(f"Top {len(matches)} match(es)")

                    for rank, m in enumerate(matches, start=1):
                        score = m["match_score"]
                        color = "🟢" if score >= 75 else ("🟡" if score >= 50 else "🔴")

                        with st.container(border=True):
                            top_cols = st.columns([5, 1])
                            top_cols[0].markdown(f"**{rank}. {m['candidate_name']}**")
                            top_cols[1].markdown(f"### {color} {score}")

                            st.progress(score / 100)

                            meta = candidates.get(m["resume_path"], {})
                            info_cols = st.columns(3)
                            info_cols[0].caption(f"📄 {Path(m['resume_path']).name}")
                            info_cols[1].caption(f"🕒 {meta.get('experience_years', '?')} yrs experience")
                            info_cols[2].caption(f"🎓 {meta.get('education', 'Not specified')}")

                            if m["matched_skills"]:
                                st.markdown(
                                    "✅ " + " ".join(f"`{s}`" for s in m["matched_skills"])
                                )
                            if m.get("missing_skills"):
                                st.markdown(
                                    "⚠️ Missing: " + " ".join(f"`{s}`" for s in m["missing_skills"])
                                )

                            st.write(m["reasoning"])

                            with st.expander("Relevant excerpts"):
                                for exc in m["relevant_excerpts"]:
                                    st.markdown(f"> {exc}")

                    st.divider()
                    dl1, dl2 = st.columns(2)
                    dl1.download_button(
                        "⬇ Download results as JSON",
                        data=json.dumps(results, indent=2),
                        file_name="match_results.json",
                        mime="application/json",
                        use_container_width=True,
                    )

                    csv_buf = io.StringIO()
                    writer = csv.writer(csv_buf)
                    writer.writerow([
                        "rank", "candidate_name", "match_score", "experience_years",
                        "education", "matched_skills", "missing_skills", "resume_path",
                    ])
                    for rank, m in enumerate(matches, start=1):
                        meta = candidates.get(m["resume_path"], {})
                        writer.writerow([
                            rank,
                            m["candidate_name"],
                            m["match_score"],
                            meta.get("experience_years", ""),
                            meta.get("education", ""),
                            "; ".join(m["matched_skills"]),
                            "; ".join(m.get("missing_skills", [])),
                            m["resume_path"],
                        ])
                    dl2.download_button(
                        "⬇ Download results as CSV",
                        data=csv_buf.getvalue(),
                        file_name="match_results.csv",
                        mime="text/csv",
                        use_container_width=True,
                    )

# --------------------------------------------------------------------------
# Tab 2 — Candidate directory
# --------------------------------------------------------------------------
with tab_directory:
    if not candidates:
        st.info("No resumes are indexed yet. Use the sidebar to run ingestion first.")
    else:
        rows = []
        for meta in candidates.values():
            rows.append({
                "Name": meta.get("candidate_name", "Unknown"),
                "Experience (yrs)": meta.get("experience_years", 0),
                "Education": meta.get("education", "Not specified"),
                "Skills": meta.get("skills", ""),
                "File": Path(meta.get("resume_path", "")).name,
                "resume_path": meta.get("resume_path", ""),
            })
        rows.sort(key=lambda r: r["Name"])

        search = st.text_input("Filter by name or skill", "")
        if search:
            s = search.lower()
            rows = [r for r in rows if s in r["Name"].lower() or s in r["Skills"].lower()]

        st.dataframe(
            [{k: v for k, v in r.items() if k != "resume_path"} for r in rows],
            use_container_width=True,
            hide_index=True,
        )

        st.divider()
        st.subheader("Remove a candidate")
        st.caption("Removes that resume's chunks from the vector index. Doesn't delete the source file.")
        options = {f"{r['Name']} ({r['File']})": r["resume_path"] for r in rows}
        if options:
            to_remove_label = st.selectbox("Candidate", list(options.keys()))
            if st.button("🗑 Remove from index"):
                get_pipeline().remove_resume(options[to_remove_label])
                clear_caches()
                st.success(f"Removed {to_remove_label} from the index.")
                st.rerun()

# --------------------------------------------------------------------------
# Tab 3 — Analytics
# --------------------------------------------------------------------------
with tab_analytics:
    if not candidates:
        st.info("No resumes are indexed yet. Use the sidebar to run ingestion first.")
    else:
        skill_counts = {}
        exp_values = []
        for meta in candidates.values():
            exp_values.append(meta.get("experience_years", 0))
            for s in (meta.get("skills", "") or "").split(","):
                s = s.strip()
                if s:
                    skill_counts[s] = skill_counts.get(s, 0) + 1

        col1, col2 = st.columns(2)

        with col1:
            st.subheader("Top skills across candidates")
            if skill_counts:
                top_skills = dict(
                    sorted(skill_counts.items(), key=lambda kv: kv[1], reverse=True)[:15]
                )
                st.bar_chart(top_skills)
            else:
                st.caption("No skills extracted yet.")

        with col2:
            st.subheader("Experience distribution")
            if exp_values:
                import collections
                buckets = collections.Counter()
                for v in exp_values:
                    if v == 0:
                        buckets["0"] += 1
                    elif v <= 2:
                        buckets["1-2"] += 1
                    elif v <= 5:
                        buckets["3-5"] += 1
                    elif v <= 8:
                        buckets["6-8"] += 1
                    else:
                        buckets["9+"] += 1
                order = ["0", "1-2", "3-5", "6-8", "9+"]
                st.bar_chart({k: buckets.get(k, 0) for k in order})
