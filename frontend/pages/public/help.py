"""
Public Help/FAQ page.
"""
from __future__ import annotations

import streamlit as st

from frontend.components.navbar import page_head, section_title
from frontend.config import HOSPITAL


def render() -> None:
    page_head(
        "Help & FAQ",
        "Find answers to common questions about our services.",
    )

    # -------------------------------------------------------------
    section_title("Getting Started")

    with st.expander("How do I create an account?"):
        st.write(
            """
            1. Open **Sign In / Sign Up** in the top navigation
            2. Switch to the **Sign Up** tab and enter your name, email, phone,
               date of birth, and gender
            3. Click **Create account**, we email you an **8-digit code**
            4. Enter the 8-digit code to verify your email
            5. Your patient account is ready, you land in your dashboard
            """
        )

    with st.expander("How do I sign in?"):
        st.write(
            """
            1. Open **Sign In** in the top navigation
            2. Enter your registered email and click **Send 8-digit code**
            3. Check your email for the **8-digit code**
            4. Enter the code to verify, you're signed in

            No password is required.
            """
        )

    with st.expander("How do I book an appointment?"):
        st.write(
            """
            **Online (Patient Portal):**
            1. Sign in to your account
            2. Go to **Appointments** → **Book New Appointment**
            3. Select department, doctor, date, and an available time slot
            4. Enter a visit reason (optional) and confirm
            5. Complete payment if required

            **Via AI Assistant:**
            1. Open **AI Assistant** from your dashboard
            2. Say "I want to book an appointment"
            3. Follow the guided conversation
            """
        )

    with st.expander("What is the 8-digit code (OTP) login?"):
        st.write(
            """
            We use passwordless sign-in with a one-time code sent to your email:
            - No passwords to remember
            - We email an **8-digit code** to your registered address
            - Enter the 8 digits exactly as received to verify it's you
            - Codes are short-lived, if yours expires, request a new one
            - Didn't receive it? Check your spam folder, confirm the email
              address, then choose **Start over, sign in again** to request a
              new code
            """
        )

    # -------------------------------------------------------------
    section_title("Appointments")

    with st.expander("Can I reschedule or cancel my appointment?"):
        st.write(
            """
            Yes, you can manage your own bookings:
            - Go to **Appointments** in your portal and open the booking
            - **Reschedule:** pick a new available slot for the same doctor
            - **Cancel:** cancel an upcoming appointment, the slot is released
              for other patients
            - Please reschedule or cancel before your visit time so the slot
              can be reused
            """
        )

    with st.expander("What happens if I miss my appointment?"):
        st.write(
            """
            - Appointments missed without cancellation are marked as **No Show**
            - Missed visits affect your appointment history, so please cancel
              ahead of time if you can't attend
            - Contact the care desk if you had an emergency, we can review
              your record
            """
        )

    with st.expander("How do I know if my appointment is confirmed?"):
        st.write(
            """
            - You'll receive an email confirmation after booking
            - Open **Appointments** in your portal, the status will show
              "Confirmed"
            - You'll receive a reminder 24 hours before your visit
            """
        )

    # -------------------------------------------------------------
    section_title("Payments & Billing")

    with st.expander("What payment methods are accepted?"):
        st.write(
            """
            We accept secure payment methods:
            - UPI
            - Credit / Debit cards
            - Cash at the billing counter
            - Insurance, with claim assistance from our team
            """
        )

    with st.expander("How does insurance work?"):
        st.write(
            """
            - Choose **Insurance** during payment
            - Enter your policy details
            - If a claim is required, we initiate the process
            - You pay the non-covered portion (co-pay/deductible)
            """
        )

    with st.expander("Can I get a refund?"):
        st.write(
            f"""
            - Raise a **Refund Request** (category: refund) via **Admin
              Requests** in your portal, or contact the care desk at
              {HOSPITAL.phone}
            - Refunds are processed to the original payment method after
              approval
            """
        )

    # -------------------------------------------------------------
    section_title("AI Assistant")

    with st.expander("What can the AI Assistant help with?"):
        st.write(
            """
            - Book, reschedule, or cancel appointments
            - Look up your upcoming appointments
            - Create administrative requests (refunds, records, etc.)
            - Answer questions about departments, doctors, and procedures
            - Explain billing, insurance, and hospital policies
            - Provide visiting information and directions within the hospital

            *The AI cannot provide medical advice, diagnoses, or prescriptions.*
            """
        )

    with st.expander("Is my conversation with the AI private?"):
        st.write(
            """
            - Conversations are logged for quality improvement
            - No conversation data is shared with third parties
            - You can request deletion of your chat history
            - Sensitive medical information should be discussed with your
              doctor directly
            """
        )

    # -------------------------------------------------------------
    section_title("Technical Support")

    with st.expander("The page isn't loading properly"):
        st.write(
            """
            - Refresh the page (Ctrl+R / Cmd+R)
            - Clear browser cache and cookies
            - Try a different browser or incognito mode
            - Check your internet connection
            """
        )

    with st.expander("I didn't receive the 8-digit code email"):
        st.write(
            """
            - Check your spam/junk folder
            - Wait a minute or two for delivery
            - Ensure you entered the correct email address
            - Choose **Start over, sign in again** on the verification screen
              to return to sign-in and request a new code
            - Contact the care desk if the problem persists
            """
        )

    with st.expander("How do I report a bug or issue?"):
        st.write(
            f"""
            Use the **Feedback** option in your portal, or contact us:
            - **Email:** {HOSPITAL.email}
            - **Care desk:** {HOSPITAL.phone} ({HOSPITAL.care_desk})
            """
        )

    # -------------------------------------------------------------
    section_title("Still Need Help?")

    registry = st.session_state.get("_mc_pages", {}) or {}
    col1, col2 = st.columns(2, gap="large")

    with col1:
        with st.container(border=True):
            st.markdown("#### :material/phone: Care Desk")
            st.write(HOSPITAL.phone)
            st.caption(f"{HOSPITAL.care_desk} for appointments and support.")
            st.write(f"**Emergency:** {HOSPITAL.emergency}")

    with col2:
        with st.container(border=True):
            st.markdown("#### :material/mail: Email")
            st.write(HOSPITAL.email)
            st.caption("We reply to general enquiries as soon as we can.")
            st.page_link(
                registry.get("contact") or "pages/public/contact.py",
                label="Open the Contact page",
                icon=":material/contact_mail:",
                width="stretch",
            )




if __name__ == "__main__":
    render()
