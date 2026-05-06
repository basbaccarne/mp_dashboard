# Libraries
import streamlit as st
import yaml

# Bestaande gebruikers laden
with open("users.yaml", "r") as f:
    users = yaml.safe_load(f)["users"]

# Sessiestatus instellen
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.user = None

st.title("🔐 UGent Dashboard")

# Alleen tonen als NIET ingelogd
if not st.session_state.logged_in:
    with st.form("login_form"):
        username = st.text_input("Gebruikersnaam")
        password = st.text_input("Wachtwoord", type="password")
        submitted = st.form_submit_button("Log in")

        if submitted:
            if username in users and users[username] == password:
                st.session_state.logged_in = True
                st.session_state.user = username
                st.success(f"Ingelogd als {username}")
                st.rerun()
            else:
                st.error("Ongeldige gebruikersnaam of wachtwoord")

# Alleen tonen als WEL ingelogd
if st.session_state.logged_in:
    st.success(f"Ingelogd als {st.session_state.user}")
    st.write("Welkom op jouw persoonlijke dashboard 🎉")

    if st.button("Log uit"):
        st.session_state.logged_in = False
        st.session_state.user = None
        st.rerun()
