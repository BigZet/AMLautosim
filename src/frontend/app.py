import streamlit as st
import sys
from pathlib import Path

# Add project root to sys.path so we can import components
sys.path.append(str(Path(__file__).parent.parent.parent))

from src.frontend.components.auth import check_auth, show_auth_page, logout

st.set_page_config(page_title="AML Simulator", layout="centered")

def main():
    if check_auth():
        st.sidebar.title(f"User: {st.session_state.user.get('email')}")
        if st.sidebar.button("Logout"):
            logout()
            
        st.title("Dashboard")
        st.write("Welcome to the AML Simulator Dashboard.")
        st.success("You are successfully authenticated!")
        
        st.info("Here you can access protected data fetched from the FastAPI backend.")
    else:
        show_auth_page()

if __name__ == "__main__":
    main()
