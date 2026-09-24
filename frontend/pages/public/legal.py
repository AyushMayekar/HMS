"""
Public Legal page - Privacy Policy & Terms of Service.
"""
import streamlit as st

from frontend.components.navbar import page_head, section_title
from frontend.config import HOSPITAL


def render():
    page_head(
        "Privacy Policy & Terms of Service",
        "Important legal information about your data and use of our services.",
    )

    tab1, tab2, tab3 = st.tabs(["Privacy Policy", "Terms of Service", "Cookie Notice"])

    with tab1:
        section_title("Privacy Policy", "How we collect, use, and protect your information")
        st.markdown(
            f"""
            **Effective Date:** September 2026  
            **Last Updated:** September 2026  

            **1. Information We Collect**
            - **Account Information:** Name, email, phone, date of birth, gender
            - **Health Information:** Appointment history, medical records (with consent)
            - **Payment Information:** Payment details required to complete transactions
            - **Usage Data:** Logs, IP address, browser type, pages visited
            - **Communication:** Messages with AI assistant, feedback, support requests

            **2. How We Use Your Information**
            - Provide and manage healthcare services
            - Process appointments and payments
            - Send reminders and notifications
            - Improve our services and AI assistant
            - Comply with legal obligations
            - **Never:** Sell your data to third parties

            **3. Data Sharing**
            - **Healthcare Providers:** Your doctors and care team (for treatment)
            - **Insurance:** For claims processing (with your consent)
            - **Legal Requirements:** When required by law
            - **Service Providers:** Trusted partners under strict confidentiality

            **4. Your Rights**
            - Access your data
            - Correct inaccurate information
            - Request deletion (subject to legal retention)
            - Restrict or object to processing
            - Data portability
            - Withdraw consent

            **5. Data Security**
            - Encryption in transit and at rest
            - Access controls and audit logs
            - Regular security assessments
            - Staff training on data protection

            **6. Retention**
            - Medical records: As per regulatory requirements
            - Account data: While account is active + 2 years
            - Analytics data: Aggregated, anonymized after 12 months

            **7. Contact**
            Data Protection Officer enquiries: {HOSPITAL.email}
            """
        )

    with tab2:
        section_title("Terms of Service", "Rules and agreements for using our platform")
        st.markdown(
            f"""
            **1. Acceptance**
            By using {HOSPITAL.short_name}'s digital services, you agree to these terms.

            **2. Eligibility**
            - Must be 18+ or have guardian consent
            - Provide accurate information
            - One account per person

            **3. Services Provided**
            - Online appointment booking
            - Patient portal access
            - AI assistant for administrative tasks
            - Secure online payment processing
            - Access to hospital information

            **4. User Responsibilities**
            - Keep credentials secure
            - Provide accurate health information
            - Attend or cancel appointments timely
            - Use AI assistant appropriately (no clinical requests)
            - Respect intellectual property

            **5. Medical Disclaimer**
            {HOSPITAL.disclaimer}
            
            This platform is for **administrative and informational purposes only**.
            It does not provide medical advice, diagnosis, or treatment.
            Always consult qualified healthcare professionals for medical concerns.

            **6. AI Assistant Limitations**
            - Administrative tasks only (booking, info, requests)
            - Cannot diagnose, prescribe, or make clinical decisions
            - Responses based on published hospital knowledge
            - May occasionally provide incorrect information
            - Verify critical information with staff

            **7. Payment Terms**
            - Payments are processed through secure payment gateways
            - Transaction receipts are provided electronically
            - Insurance claims are processed with your consent
            - Refunds follow the cancellation policy outlined in Help & FAQ

            **8. Intellectual Property**
            - All content © {HOSPITAL.name}
            - Personal, non-commercial use permitted
            - No scraping, copying, or redistribution

            **9. Limitation of Liability**
            - Service provided "as is"
            - No warranty of uninterrupted access
            - Not liable for indirect damages
            - Maximum liability limited to service fees paid

            **10. Termination**
            - We may suspend for violations
            - You may close account anytime
            - Medical records retained per law

            **11. Governing Law**
            - Governed by laws of India
            - Jurisdiction: Bengaluru courts

            **12. Changes**
            - Terms may be updated
            - Notice provided via email/platform
            - Continued use = acceptance
            """
        )

    with tab3:
        section_title("Cookie Notice", "How we use cookies and similar technologies")
        st.markdown(
            f"""
            **What Are Cookies?**
            Small text files stored on your device to improve your experience.

            **What We Use:**

            **Essential cookies (always active)**
            - Session management, so you stay signed in securely
            - Security protection (CSRF protection, rate limiting)
            - Remembering dismissible UI notices during your visit

            These are strictly necessary for the site to function, so they
            cannot be turned off while you use the platform.

            **What We Do Not Use**
            - No advertising cookies
            - No third-party tracking or social-media cookies
            - No cross-site profiling of patients or visitors

            **Your Choices**
            - You can clear cookies at any time: browser settings → clear
              browsing data
            - Clearing cookies ends your session and signs you out
            - You can also sign out at any time from the top navigation

            **Contact:** {HOSPITAL.email}
            """
        )

    st.caption(HOSPITAL.disclaimer)


if __name__ == "__main__":
    render()