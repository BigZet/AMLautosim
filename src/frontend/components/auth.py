import streamlit as st
import requests
from streamlit_cookies_controller import CookieController
import time

API_URL = "http://localhost:8000"

# Initialize controller only once per session
if 'cookie_controller' not in st.session_state:
    st.session_state.cookie_controller = CookieController()

controller = st.session_state.cookie_controller

def check_auth():
    # Wait a tiny bit for the cookie controller to initialize if just starting
    token = controller.get("auth_token")
    if token:
        headers = {"Authorization": f"Bearer {token}"}
        try:
            response = requests.get(f"{API_URL}/me", headers=headers)
            if response.status_code == 200:
                st.session_state.user = response.json()
                return True
        except requests.exceptions.ConnectionError:
            st.error("Cannot connect to backend API. Is it running?")
            return False
    return False

def logout():
    controller.remove("auth_token")
    if 'user' in st.session_state:
        del st.session_state.user
    time.sleep(0.5) # Allow cookie removal to sync
    st.rerun()

def show_auth_page():
    st.title("Welcome to AML Simulator")
    
    tab1, tab2 = st.tabs(["Login", "Register"])
    
    with tab1:
        st.subheader("Login to your account")
        with st.form("login_form"):
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            submit = st.form_submit_button("Login")
            
            if submit:
                try:
                    response = requests.post(f"{API_URL}/login", data={"username": email, "password": password})
                    if response.status_code == 200:
                        token = response.json().get("access_token")
                        controller.set("auth_token", token)
                        st.success("Login successful!")
                        time.sleep(0.5) # Allow cookie to set
                        st.rerun()
                    else:
                        st.error("Invalid email or password")
                except requests.exceptions.ConnectionError:
                    st.error("Cannot connect to backend API. Is it running?")
                    
    with tab2:
        st.subheader("Create a new account")
        with st.form("register_form"):
            reg_email = st.text_input("Email")
            reg_password = st.text_input("Password", type="password")
            reg_password_confirm = st.text_input("Confirm Password", type="password")
            reg_submit = st.form_submit_button("Register")
            
            if reg_submit:
                if reg_password != reg_password_confirm:
                    st.error("Passwords do not match")
                else:
                    try:
                        response = requests.post(f"{API_URL}/register", json={"email": reg_email, "password": reg_password})
                        if response.status_code == 200:
                            st.success("Registration successful! Please login.")
                        else:
                            detail = response.json().get("detail", "Registration failed")
                            st.error(f"Registration failed: {detail}")
                    except requests.exceptions.ConnectionError:
                        st.error("Cannot connect to backend API. Is it running?")
