# Libraries
import os
import streamlit as st
import yaml
import pandas as pd
from dotenv import load_dotenv
import boto3
from io import StringIO

# Load AWS credentials from .env
load_dotenv()

# Connect to S3
s3 = boto3.client("s3")

# Gebruikers laden uit YAML
with open("users.yaml", "r") as f:
    users = yaml.safe_load(f)["users"]

# Sessiestatus instellen
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.user = None

st.title("🎓 Master Thesis Evaluation Dashboard")
st.set_page_config(layout="wide")

# ✅ Functie om data éénmalig te laden bij login
def load_data_once(bucket_name, prefix=""):
    try:
        response = s3.list_objects_v2(Bucket=bucket_name, Prefix=prefix)
        csv_files = [obj for obj in response.get("Contents", []) if obj["Key"].endswith(".csv")]
        if not csv_files:
            st.warning("Geen CSV-bestanden gevonden in de opgegeven bucket/prefix.")
            return None
        csv_files.sort(key=lambda x: x["LastModified"], reverse=True)
        latest_file = csv_files[0]
        st.info(f"Laatste bestand: {latest_file['Key']}")
        obj = s3.get_object(Bucket=bucket_name, Key=latest_file["Key"])
        csv_content = obj["Body"].read().decode("utf-8")
        df = pd.read_csv(StringIO(csv_content))
        return df
    except Exception as e:
        st.error(f"Fout bij ophalen van data uit S3: {e}")
        return None

# ✅ Loginformulier
if not st.session_state.logged_in:
    with st.form("login_form"):
        username = st.text_input("Gebruikersnaam")
        password = st.text_input("Wachtwoord", type="password")
        submitted = st.form_submit_button("Log in")

        if submitted:
            if username in users and users[username] == password:
                st.session_state.logged_in = True
                st.session_state.user = username

                # Laad data éénmalig bij login
                df = load_data_once("qualtrics-data-bucket-live")
                if df is not None:
                    df_cleaned = df.iloc[2:].copy()
                    df_cleaned.reset_index(drop=True, inplace=True)
                    st.session_state.full_data = df_cleaned

                st.rerun()
            else:
                st.error("Ongeldige gebruikersnaam of wachtwoord")
    st.markdown('<span style="color: grey; font-style: italic;">Problemen met je account, toegang of data? Contacteer Bas.</span>', unsafe_allow_html=True)

# Functie om toewijzingen te laden
def load_assignments(user):
    df = pd.read_csv("assignments.csv")
    return df[df["user"] == user]

# ✅ Alleen tonen als WEL ingelogd
if st.session_state.logged_in:
    st.success(f"Ingelogd als {st.session_state.user}")

    if st.button("🔒 Log uit"):
        st.session_state.clear()
        st.rerun()

    # Selectie academiejaar en student
    if "selected_student" not in st.session_state:
        user = st.session_state.user
        assignments = load_assignments(user)
        years = sorted(assignments["year"].unique())
        selected_year = st.selectbox("📅 Kies academiejaar", years)

        students = assignments[assignments["year"] == selected_year]["student"].unique()
        selected_student = st.selectbox("👤 Kies student", students)

        if st.button("Bekijk evaluaties"):
            st.session_state.selected_student = selected_student
            st.session_state.selected_year = selected_year
            st.rerun()

# ✅ Toon gefilterde evaluatie
if "selected_student" in st.session_state:
    st.button("⬅️ Terug", on_click=lambda: st.session_state.pop("selected_student"))

    student = st.session_state.selected_student
    df = st.session_state.full_data

    if df is None or "student" not in df.columns:
        st.warning("Geen geldige data beschikbaar.")
    else:
        filtered_df = df[df["student"] == student]

        if filtered_df.empty:
            st.info(f"Er werd geen data gevonden voor student **{student}**.")
        else:
            st.subheader(f"Evaluaties voor {student}")
            st.dataframe(filtered_df)

            if "category" in filtered_df.columns:
                st.bar_chart(filtered_df["category"].value_counts())


# footer
import streamlit as st
from PIL import Image
import base64
from io import BytesIO

# Load image and convert to base64
image = Image.open("img/ugent.png")
buffered = BytesIO()
image.save(buffered, format="PNG")
img_str = base64.b64encode(buffered.getvalue()).decode()

footer = f"""
<style>
.footer {{
    position: fixed;
    left: 0;
    bottom: 0;
    width: 100%;
    background-color: white;
    color: black;
    text-align: center;
    padding: 10px 0;
    z-index: 1000;
}}
.footer img {{
    height: 200px;
    display: block;
    margin: 0 auto 0 auto;
}}
.footer p {{
    color: #1E64C8;
    margin: 100;
}}
</style>

<div class="footer">
    <img src="data:image/png;base64,{img_str}" alt="UGent Logo"/>
    <p>Built with ❤ by Bas Baccarne & Davy Parmentier</p>
</div>
"""

st.markdown(footer, unsafe_allow_html=True)
