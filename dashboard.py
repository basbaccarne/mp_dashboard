import os
import base64
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yaml
from collections import OrderedDict
from dotenv import load_dotenv
from io import BytesIO, StringIO
from PIL import Image

# ── Must be first Streamlit call ──────────────────────────────────────────────
st.set_page_config(page_title="MP Evaluatie Dashboard", layout="wide")

load_dotenv()

BUCKET_NAME = "qualtrics-data-bucket-live"
BUCKET_NAME_DAILY = "qualtrics-data-bucket-daily"
SCALE = ["Weak", "Insufficient", "Sufficient", "Good", "Very Good", "Excellent"]

# Qualtrics exports scores in Dutch — map to the English labels used in rubric.csv
DUTCH_TO_EN_SCORE = {
    "Zwak": "Weak",
    "Onvoldoende": "Insufficient",
    "Voldoende": "Sufficient",
    "Goed": "Good",
    "Zeer Goed": "Very Good",
    "Uitstekend": "Excellent",
}


# ── Export configuration ──────────────────────────────────────────────────────
# EXPORT_COLUMNS: column names to include, in order.
#   None  → evaluator, rol, all competency scores, evaluation, Q1…Q5
#   list  → e.g. ["evaluator", "rol", "Kwaliteit opzoekwerk", "evaluation"]
EXPORT_COLUMNS = None

# EXPORT_SORT_BY: column(s) to sort rows by before export.
#   None  → natural order (order data arrived in S3)
#   list  → e.g. ["rol"] or ["evaluator"]
EXPORT_SORT_BY = None


# ── Cached loaders ────────────────────────────────────────────────────────────

@st.cache_data(show_spinner=False)
def load_users():
    if "users" in st.secrets:
        return dict(st.secrets["users"])
    with open("data/users.yaml", "r") as f:
        return yaml.safe_load(f)["users"]


@st.cache_data(show_spinner=False, ttl=300)
def load_rubric():
    return pd.read_csv("data/rubric.csv")


@st.cache_data(show_spinner=False)
def load_assignments():
    opts = dict(skipinitialspace=True)
    if "assignments_csv" in st.secrets:
        return pd.read_csv(StringIO(st.secrets["assignments_csv"]), **opts)
    return pd.read_csv("data/assignments.csv", **opts)


# ── Qualtrics column mapping & preprocessing ─────────────────────────────────

def build_qualtrics_col_map(df_rubric):
    """Derive the C{cluster}_{comp} → competency-name mapping from rubric.csv.

    Qualtrics numbers clusters and competencies in the order they appear in
    the rubric (C1_1 = first competency of cluster 1, C1_2 = second, etc.).
    """
    cluster_order = list(dict.fromkeys(df_rubric["cluster"].tolist()))
    col_map = {}
    for ci, cluster in enumerate(cluster_order, start=1):
        comps = df_rubric[df_rubric["cluster"] == cluster]["competence"].unique().tolist()
        for cj, comp in enumerate(comps, start=1):
            col_map[f"C{ci}_{cj}"] = comp
    return col_map


def preprocess_qualtrics_data(df, df_rubric):
    """Transform a raw Qualtrics CSV export into the format the dashboard expects.

    Changes made:
    - C1_1, C1_2 … → competency names from rubric
    - Dutch score labels → English (matching rubric scale)
    - evaluator_4 + evaluator_5 → combined "evaluator" column
    - textual_feedback → evaluation
    - questions_1 … questions_5 → Q1 … Q5
    - Drop invalid/test rows (empty or placeholder student names)
    - Drop manually excluded (student, evaluator) pairs from st.secrets
    - Deduplicate: keep only the latest submission per (student, evaluator)
    """
    df = df.copy()
    col_map = build_qualtrics_col_map(df_rubric)

    # Rename competency columns
    df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})

    # Combine first/last name into one evaluator column
    if "evaluator_4" in df.columns and "evaluator_5" in df.columns:
        df["evaluator"] = (
            df["evaluator_4"].fillna("").str.strip()
            + " "
            + df["evaluator_5"].fillna("").str.strip()
        ).str.strip()
        df = df.drop(columns=["evaluator_4", "evaluator_5"])
    for col in ["evaluator_6"]:
        if col in df.columns:
            df = df.drop(columns=[col])

    # Translate Dutch score labels to English
    dutch_ci = {k.lower(): v for k, v in DUTCH_TO_EN_SCORE.items()}
    competency_cols = [c for c in df.columns if c in col_map.values()]
    for col in competency_cols:
        df[col] = df[col].map(
            lambda x: dutch_ci.get(str(x).strip().lower(), x) if pd.notna(x) else x
        )

    # Rename review / question columns
    rename = {"textual_feedback": "evaluation"}
    for i in range(1, 10):
        rename[f"questions_{i}"] = f"Q{i}"
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})

    # Drop invalid/test rows — student name missing or a placeholder
    if "student" in df.columns:
        invalid = df["student"].isna() | df["student"].str.strip().isin(["", "---", "-", "test", "Test"])
        df = df[~invalid]

    # Drop manually excluded (student, evaluator) pairs defined in secrets
    # Format in secrets.toml:  excluded = ["Leon Dehullu|Bas Baccarne", ...]
    if "excluded" in st.secrets:
        excluded_pairs = set(st.secrets["excluded"])
        if "evaluator" in df.columns:
            mask = df.apply(
                lambda r: f"{r.get('student', '')}|{r.get('evaluator', '')}" in excluded_pairs,
                axis=1,
            )
            df = df[~mask]

    # Deduplicate: if the same evaluator submitted for the same student more than
    # once, keep only the most recent entry based on RecordedDate
    if "evaluator" in df.columns and "student" in df.columns and "RecordedDate" in df.columns:
        df["RecordedDate"] = pd.to_datetime(df["RecordedDate"], errors="coerce")
        df = (
            df.sort_values("RecordedDate", ascending=False)
            .drop_duplicates(subset=["student", "evaluator"], keep="first")
        )

    return df.reset_index(drop=True)


# ── S3 / Qualtrics data fetch ─────────────────────────────────────────────────

def _s3_client():
    import boto3
    if "AWS_ACCESS_KEY_ID" in st.secrets:
        return boto3.client(
            "s3",
            aws_access_key_id=st.secrets["AWS_ACCESS_KEY_ID"],
            aws_secret_access_key=st.secrets["AWS_SECRET_ACCESS_KEY"],
            region_name=st.secrets.get("AWS_DEFAULT_REGION", "us-east-1"),
        )
    return boto3.client("s3")  # falls back to .env / ~/.aws credentials


def _fetch_bucket(s3, bucket_name):
    """Fetch and concatenate all CSVs from one S3 bucket. Returns empty list on error."""
    try:
        response = s3.list_objects_v2(Bucket=bucket_name)
        csv_files = [o for o in response.get("Contents", []) if o["Key"].endswith(".csv")]
        frames = []
        for file_obj in csv_files:
            obj = s3.get_object(Bucket=bucket_name, Key=file_obj["Key"])
            raw = obj["Body"].read().decode("utf-8")
            frames.append(pd.read_csv(StringIO(raw), skiprows=[1, 2]))
        return frames
    except Exception:
        return []


def fetch_qualtrics_data():
    """Fetch and combine ALL CSVs from both Qualtrics S3 buckets.

    - qualtrics-data-bucket-live  : per-entry exports (triggered on submission)
    - qualtrics-data-bucket-daily : full daily exports (~22:00 UTC)
    Both are concatenated; deduplication happens in preprocess_qualtrics_data().
    Returns (DataFrame | None, error_message | None).
    """
    try:
        s3 = _s3_client()
        frames = _fetch_bucket(s3, BUCKET_NAME) + _fetch_bucket(s3, BUCKET_NAME_DAILY)

        if not frames:
            return None, "Geen CSV-bestanden gevonden in de S3-buckets."

        df = pd.concat(frames, ignore_index=True)
        return df, None
    except Exception as e:
        return None, str(e)


def fallback_sample_data():
    """Load local sample data for development/testing when S3 is unavailable."""
    df_scores = pd.read_csv("data/sampledata.csv")
    df_reviews = pd.read_csv("data/sampledata_review.csv")
    # Merge into one frame with a fake student column
    df = df_scores.merge(df_reviews.drop(columns=["evaluator"]), left_index=True, right_index=True)
    df.insert(0, "student", "Leon Dehullu")
    return df


# ── CSV export ───────────────────────────────────────────────────────────────

def build_export_csv(df_student, competences):
    if EXPORT_COLUMNS is not None:
        cols = [c for c in EXPORT_COLUMNS if c in df_student.columns]
    else:
        score_cols = [c for c in competences if c in df_student.columns]
        q_cols = [c for c in df_student.columns if c.startswith("Q")]
        wanted = ["evaluator", "rol"] + score_cols + ["evaluation"] + q_cols
        cols = [c for c in wanted if c in df_student.columns]

    df_export = df_student[cols].copy()

    if EXPORT_SORT_BY:
        sort_cols = [c for c in EXPORT_SORT_BY if c in df_export.columns]
        if sort_cols:
            df_export = df_export.sort_values(sort_cols).reset_index(drop=True)

    return df_export.to_csv(index=False).encode("utf-8")


# ── Visualization helpers ─────────────────────────────────────────────────────

def calculate_cluster_averages(df_scores, df_rubric):
    scale_map = {label: i for i, label in enumerate(SCALE)}
    competences = df_rubric["competence"].unique().tolist()
    clusters_for_comp = df_rubric.set_index("competence")["cluster"].to_dict()

    cluster_comps = OrderedDict()
    for comp in competences:
        cluster_comps.setdefault(clusters_for_comp[comp], []).append(comp)

    df_num = df_scores.copy()
    for comp in competences:
        if comp in df_num.columns:
            df_num[comp] = df_num[comp].map(scale_map)

    cluster_avgs = {}
    for cluster, comps in cluster_comps.items():
        valid = [c for c in comps if c in df_num.columns]
        if not valid:
            cluster_avgs[cluster] = None
            continue
        vals = df_num[valid].values.flatten()
        vals = pd.to_numeric(vals, errors="coerce")
        vals = vals[~np.isnan(vals)]
        cluster_avgs[cluster] = float(np.mean(vals)) if len(vals) else None

    def avg_to_label(avg):
        if avg is None:
            return "N/A"
        lo, hi = int(np.floor(avg)), int(np.ceil(avg))
        return SCALE[lo] if lo == hi else f"{SCALE[lo]} – {SCALE[hi]}"

    return {c: avg_to_label(v) for c, v in cluster_avgs.items()}, cluster_comps


def plot_jury_evaluation(df_scores, df_rubric):
    competences = df_rubric["competence"].unique().tolist()
    descriptions = (
        df_rubric
        .pivot(index="competence", columns="score", values="description")
        .to_dict(orient="index")
    )
    cluster_avg_labels, cluster_comps = calculate_cluster_averages(df_scores, df_rubric)

    comp_y = {}
    y_counter = 0.0
    for cluster, comps in cluster_comps.items():
        for comp in comps:
            comp_y[comp] = y_counter
            y_counter += 1
        y_counter += 0.7

    palette = ["#636EFA", "#EF553B", "#00CC96", "#AB63FA", "#FFA15A", "#19D3F3", "#FF6692", "#B6E880"]
    fig = go.Figure()

    # Cluster background boxes and labels
    for cluster, comps in cluster_comps.items():
        ys = [comp_y[c] for c in comps]
        min_y, max_y = min(ys) - 0.5, max(ys) + 0.5
        fig.add_shape(
            type="rect", x0=-0.5, x1=len(SCALE) - 0.5,
            y0=min_y, y1=max_y,
            fillcolor="lightgrey", opacity=0.1, layer="below", line_width=0,
        )
        fig.add_annotation(
            x=-0.5, y=min_y - 0.05,
            text=f"<b>{cluster}</b> (gemiddelde: {cluster_avg_labels.get(cluster, 'N/A')})",
            showarrow=False, font=dict(size=14, color="black"),
            xanchor="left", yanchor="bottom",
        )

    # Collect which (competence, score) cells have evaluator points
    points_with_evals = set()
    for _, row in df_scores.iterrows():
        for comp in competences:
            if comp in row and pd.notna(row[comp]) and row[comp] in SCALE:
                points_with_evals.add((comp, row[comp]))

    # Grey placeholder dots for unscored cells
    for comp in competences:
        y = comp_y[comp]
        for i, label in enumerate(SCALE):
            if (comp, label) in points_with_evals:
                continue
            desc = descriptions.get(comp, {}).get(label, "")
            fig.add_trace(go.Scatter(
                x=[i], y=[y], mode="markers",
                marker=dict(size=8, color="lightgrey", opacity=0.2),
                hovertemplate=f"{comp}<br>{label}:<br>{desc}<extra></extra>",
                showlegend=False,
            ))

    # Evaluator score dots
    for i, row in df_scores.iterrows():
        evaluator_name = row.get("evaluator", f"Evaluator {i + 1}")
        color = palette[i % len(palette)]
        first = True
        for comp in competences:
            if comp not in row or pd.isna(row[comp]) or row[comp] not in SCALE:
                continue
            x_pos = SCALE.index(row[comp])
            y_jitter = comp_y[comp] + np.random.uniform(0.05, 0.06) * np.random.choice([-1, 1])
            desc = descriptions.get(comp, {}).get(row[comp], "")
            fig.add_trace(go.Scatter(
                x=[x_pos], y=[y_jitter], mode="markers",
                marker=dict(size=16, color=color, opacity=0.7),
                name=evaluator_name if first else None,
                showlegend=first,
                hovertemplate=f"{evaluator_name}<br>{comp}: {row[comp]}<br>{desc}<extra></extra>",
            ))
            first = False

    fig.update_xaxes(
        tickvals=list(range(len(SCALE))), ticktext=SCALE,
        title="Score", side="top", range=[-0.5, len(SCALE) - 0.5],
    )
    fig.update_yaxes(
        tickvals=[comp_y[c] for c in competences], ticktext=competences,
        title="Competentie", range=[-1, y_counter + 1], autorange="reversed",
    )
    fig.update_layout(
        title="Evaluatie per Competentie",
        height=max(600, int(60 * y_counter)),
        legend_title="Evaluatoren",
        margin=dict(l=120, r=40, t=60, b=40),
        plot_bgcolor="white",
    )
    return fig


def show_reviews(df_reviews):
    if df_reviews is None or df_reviews.empty:
        st.info("Geen schriftelijke evaluaties beschikbaar.")
        return

    if "evaluation" in df_reviews.columns:
        st.markdown("#### Review")
        for _, row in df_reviews.iterrows():
            name = row.get("evaluator", "Onbekend")
            st.markdown(f"**{name}**")
            if pd.notna(row.get("evaluation")):
                st.write(row["evaluation"])

    q_cols = [c for c in df_reviews.columns if c.startswith("Q")]
    if q_cols:
        st.markdown("#### Vragen")
        for _, row in df_reviews.iterrows():
            name = row.get("evaluator", "Onbekend")
            st.markdown(f"**{name}**")
            for col in q_cols:
                if pd.notna(row.get(col)):
                    st.write(f"- {row[col]}")


# ── Footer ────────────────────────────────────────────────────────────────────

def render_footer():
    try:
        img = Image.open("img/ugent.png")
        buf = BytesIO()
        img.save(buf, format="PNG")
        img_b64 = base64.b64encode(buf.getvalue()).decode()
        st.markdown(
            f"""
<style>
.footer {{
    position: fixed; left: 0; bottom: 0; width: 100%;
    background-color: white; text-align: center; padding: 8px 0; z-index: 1000;
    border-top: 1px solid #eee;
}}
.footer img {{ height: 40px; display: block; margin: 2px auto; }}
.footer p {{ color: #1E64C8; margin: 2px 0; font-size: 11px; }}
</style>
<div class="footer">
  <img src="data:image/png;base64,{img_b64}" alt="UGent Logo"/>
  <p>Built with ❤ by Bas Baccarne &amp; Davy Parmentier</p>
</div>""",
            unsafe_allow_html=True,
        )
    except Exception:
        pass


# ── Session state defaults ────────────────────────────────────────────────────

_defaults = {
    "logged_in": False,
    "user": None,
    "full_data": None,
    "using_sample_data": False,
    "selected_student": None,
    "selected_year": None,
}
for key, val in _defaults.items():
    if key not in st.session_state:
        st.session_state[key] = val


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 1 — Login
# ══════════════════════════════════════════════════════════════════════════════

if not st.session_state.logged_in:
    st.title("🎓 Master Thesis Evaluatie Dashboard")

    _, col, _ = st.columns([1, 1, 1])
    with col:
        st.markdown("### Log in using your UGent email adress")
        with st.form("login_form"):
            username = st.text_input("Email")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Log in", width="stretch")

        if submitted:
            users = load_users()
            username = username.strip().lower()
            users_lower = {k.lower(): v for k, v in users.items()}
            if username in users_lower and users_lower[username] == password:
                with st.spinner("Qualtrics data ophalen…"):
                    df, err = fetch_qualtrics_data()

                if err:
                    st.warning(
                        f"S3 niet bereikbaar — lokale testdata wordt gebruikt.  \n`{err}`"
                    )
                    df = fallback_sample_data()
                    st.session_state.using_sample_data = True
                else:
                    df = preprocess_qualtrics_data(df, load_rubric())

                st.session_state.full_data = df
                st.session_state.logged_in = True
                st.session_state.user = username
                st.rerun()
            else:
                st.error("Ongeldige gebruikersnaam of wachtwoord.")

        st.markdown(
            '<p style="color:grey;font-style:italic;text-align:center;margin-top:8px;">'
            "Problemen met toegang of data? Contacteer Bas.</p>",
            unsafe_allow_html=True,
        )

    render_footer()
    st.stop()


# ══════════════════════════════════════════════════════════════════════════════
# SHARED HEADER (logged-in pages)
# ══════════════════════════════════════════════════════════════════════════════

st.title("🎓 Master Thesis Evaluatie Dashboard")

col_info, col_logout = st.columns([5, 1])
with col_info:
    label = " *(testdata)*" if st.session_state.using_sample_data else ""
    st.caption(f"Ingelogd als **{st.session_state.user}**{label}")
with col_logout:
    if st.button("🔒 Log uit", width="stretch"):
        st.session_state.clear()
        st.rerun()

st.markdown("---")


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 2 — Student selection
# ══════════════════════════════════════════════════════════════════════════════

if st.session_state.selected_student is None:
    st.markdown("### Kies een student")

    assignments = load_assignments()
    mine = assignments[assignments["user"].str.lower() == st.session_state.user]

    if mine.empty:
        st.warning("Geen studenten toegewezen aan uw account.")
        render_footer()
        st.stop()

    years = sorted(mine["year"].unique())
    selected_year = st.selectbox("📅 Academiejaar", years)
    students = mine[mine["year"] == selected_year]["student"].unique()
    selected_student = st.selectbox("👤 Student", students)

    if st.button("▶ Bekijk evaluaties", type="primary"):
        st.session_state.selected_student = selected_student
        st.session_state.selected_year = selected_year
        st.rerun()

    render_footer()
    st.stop()


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 3 — Evaluation visualisation
# ══════════════════════════════════════════════════════════════════════════════

if st.button("⬅ Terug naar studentenoverzicht"):
    st.session_state.selected_student = None
    st.session_state.selected_year = None
    st.rerun()

student = st.session_state.selected_student
col_title, col_export = st.columns([5, 1])
with col_title:
    st.markdown(f"## {student}")
    st.caption(f"Academiejaar: {st.session_state.selected_year}")
with col_export:
    st.write("")  # vertical alignment nudge

df_all = st.session_state.full_data
df_rubric = load_rubric()

if df_all is None or df_all.empty:
    st.error("Geen data beschikbaar.")
    render_footer()
    st.stop()

# Filter to this student
if "student" in df_all.columns:
    df_student = df_all[df_all["student"] == student].copy()
else:
    df_student = df_all.copy()

if df_student.empty:
    st.info(f"Geen evaluatiedata gevonden voor **{student}**.")
    render_footer()
    st.stop()

# Build df_scores: evaluator column + rubric competence columns present in data
competences = df_rubric["competence"].unique().tolist()
score_cols = [c for c in competences if c in df_student.columns]

# Export button
with col_export:
    filename = f"{student.replace(' ', '_')}_{st.session_state.selected_year}.csv"
    st.download_button(
        label="⬇ Download CSV",
        data=build_export_csv(df_student, competences),
        file_name=filename,
        mime="text/csv",
        width="stretch",
    )

evaluator_col = next((c for c in ["evaluator", "Evaluator"] if c in df_student.columns), None)
if evaluator_col:
    df_scores = df_student[[evaluator_col] + score_cols].rename(columns={evaluator_col: "evaluator"})
else:
    df_scores = df_student[score_cols].copy()
    df_scores.insert(0, "evaluator", [f"Evaluator {i + 1}" for i in range(len(df_scores))])

df_scores = df_scores.reset_index(drop=True)

# Build df_reviews: evaluator + evaluation text + question columns
review_candidates = (
    ["evaluator"] +
    [c for c in df_student.columns if c == "evaluation" or c.startswith("Q")]
)
review_cols = [c for c in review_candidates if c in df_student.columns]
df_reviews = df_student[review_cols].reset_index(drop=True) if len(review_cols) > 1 else None

# ── Tabs ──────────────────────────────────────────────────────────────────────

tab_chart, tab_reviews = st.tabs(["📊 Visualisatie", "📝 Reviews"])

with tab_chart:
    if not score_cols:
        st.info("Geen scorekolommen gevonden die overeenkomen met het beoordelingsrooster.")
    else:
        fig = plot_jury_evaluation(df_scores, df_rubric)
        st.plotly_chart(fig, width="stretch")

with tab_reviews:
    show_reviews(df_reviews)

render_footer()
