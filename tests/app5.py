import streamlit as st
st.set_page_config(layout="wide")

import pandas as pd
import plotly.graph_objects as go
import numpy as np
from collections import OrderedDict

def calculate_cluster_averages(df_scores, df_rubric):
    scale = ["Weak", "Insufficient", "Sufficient", "Good", "Very Good", "Excellent"]
    scale_map = {label: i for i, label in enumerate(scale)}

    competences = df_rubric["competence"].unique().tolist()
    clusters = df_rubric.set_index("competence")["cluster"].to_dict()

    cluster_comps = OrderedDict()
    for comp in competences:
        cluster = clusters[comp]
        cluster_comps.setdefault(cluster, []).append(comp)

    df_numeric = df_scores.copy()
    for comp in competences:
        df_numeric[comp] = df_numeric[comp].map(scale_map)

    cluster_avgs = {}
    for cluster, comps in cluster_comps.items():
        cluster_scores = df_numeric[comps]
        all_scores = cluster_scores.values.flatten()
        all_scores = all_scores[~np.isnan(all_scores)]
        if len(all_scores) == 0:
            avg_score = None
        else:
            avg_score = np.mean(all_scores)
        cluster_avgs[cluster] = avg_score

    def avg_score_to_range(avg):
        if avg is None:
            return "N/A"
        lower = int(np.floor(avg))
        upper = int(np.ceil(avg))
        if lower == upper:
            return scale[lower]
        else:
            return f"{scale[lower]} - {scale[upper]}"

    cluster_avg_labels = {cluster: avg_score_to_range(avg) for cluster, avg in cluster_avgs.items()}

    return cluster_avg_labels, cluster_comps

def plot_jury_evaluation(df_scores, df_rubric):
    scale = ["Weak", "Insufficient", "Sufficient", "Good", "Very Good", "Excellent"]

    competences = df_rubric["competence"].unique().tolist()
    clusters = df_rubric.set_index("competence")["cluster"].to_dict()

    descriptions = (
        df_rubric
        .pivot(index="competence", columns="score", values="description")
        .to_dict(orient="index")
    )

    cluster_avg_labels, cluster_comps = calculate_cluster_averages(df_scores, df_rubric)

    # Map competences to y-coordinates, with spacing between clusters
    comp_y = {}
    y_counter = 0
    for cluster, comps in cluster_comps.items():
        for comp in comps:
            comp_y[comp] = y_counter
            y_counter += 1
        y_counter += 0.7  # spacing between clusters

    palette = ["#636EFA", "#EF553B", "#00CC96", "#AB63FA", "#FFA15A", "#19D3F3", "#FF6692", "#B6E880"]

    fig = go.Figure()

    # Layer 0: shaded rectangles and cluster labels with averages
    for cluster, comps in cluster_comps.items():
        y_values = [comp_y[comp] for comp in comps]
        min_y, max_y = min(y_values) - 0.5, max(y_values) + 0.5

        # Light grey box for the cluster
        fig.add_shape(
            type="rect",
            x0=-0.5, x1=len(scale) - 0.5,
            y0=min_y, y1=max_y,
            fillcolor="lightgrey",
            opacity=0.1,
            layer="below",
            line_width=0,
        )

        avg_label = cluster_avg_labels.get(cluster, "N/A")

        # Bold cluster name ABOVE the box with average
        fig.add_annotation(
            x=-0.5,
            y=min_y - 0.05,
            text=f"<b>{cluster}</b> (average: {avg_label})",
            showarrow=False,
            font=dict(size=14, color="black"),
            xanchor="left",
            yanchor="bottom"
        )

    # Prepare set of (competence, score) that have evaluator points
    points_with_evals = set()
    for i, row in df_scores.iterrows():
        for comp in competences:
            score_label = row[comp]
            if pd.isna(score_label):
                continue
            points_with_evals.add((comp, score_label))

    # Layer 1: grey hover points only where no evaluation exists
    for comp in competences:
        y = comp_y[comp]
        for i, label in enumerate(scale):
            if (comp, label) in points_with_evals:
                continue
            desc = descriptions[comp][label]
            fig.add_trace(go.Scatter(
                x=[i], y=[y],
                mode='markers',
                marker=dict(size=8, color="lightgrey", opacity=0.2),
                hovertemplate=f"{comp}<br>{label}:<br>{desc}<extra></extra>",
                showlegend=False
            ))

    # Layer 2: evaluator scores with jitter
    for i, row in df_scores.iterrows():
        name = row["evaluator"]
        color = palette[i % len(palette)]
        first = True
        for comp in competences:
            score_label = row[comp]
            if pd.isna(score_label):
                continue
            x_base = scale.index(score_label)
            y = comp_y[comp]

            # Jitter range
            min_offset = 0.05
            max_offset = 0.06

            x_sign = np.random.choice([-1, 1])
            x_offset = np.random.uniform(0, 0)
            x = x_base + x_sign * x_offset

            y_sign = np.random.choice([-1, 1])
            y_offset = np.random.uniform(min_offset, max_offset)
            y = y + y_sign * y_offset

            desc = descriptions[comp][score_label]
            hover = f"{name}<br>{comp}: {score_label}<br>{desc}"
            fig.add_trace(go.Scatter(
                x=[x], y=[y],
                mode='markers',
                marker=dict(size=16, color=color, opacity=0.7),
                name=name if first else None,
                showlegend=first,
                hovertemplate=hover + "<extra></extra>"
            ))
            first = False

    fig.update_xaxes(
        tickvals=list(range(len(scale))),
        ticktext=scale,
        title="Score",
        side='top',
        range=[-0.5, len(scale) - 0.5]
    )

    fig.update_yaxes(
        tickvals=[comp_y[comp] for comp in competences],
        ticktext=competences,
        title="Competence",
        range=[-1, y_counter + 1],
        autorange="reversed"
    )

    fig.update_layout(
        title="Evaluation per Competence",
        height=60 * y_counter,
        legend_title="Evaluators",
        margin=dict(l=120, r=40, t=60, b=40),
        plot_bgcolor="white"
    )

    return fig

def show_reviews(csv_file="sampledata_review.csv"):
    """Show evaluations and questions from reviewers."""
    df = pd.read_csv(csv_file)

    # Section 1: Reviews
    st.markdown("#### **Review**")
    for _, row in df.iterrows():
        st.markdown(f"**{row['evaluator']}**: ")
        st.write(row['evaluation'])

    # Section 2: Questions
    st.markdown("#### **Questions**")
    for _, row in df.iterrows():
        st.markdown(f"**{row['evaluator']}**")
        for col in df.columns:
            if col.startswith("Q") and pd.notna(row[col]):
                st.write(f"- {row[col]}")

# Streamlit app
df_scores = pd.read_csv("sampledata.csv")
df_rubric = pd.read_csv("rubric.csv")

st.title("Jury Evaluation Dashboard")

fig = plot_jury_evaluation(df_scores, df_rubric)
st.plotly_chart(fig, use_container_width=True)
show_reviews("sampledata_review.csv")
