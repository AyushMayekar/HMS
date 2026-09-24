"""
Public About page.
"""
from __future__ import annotations

import streamlit as st

from frontend.components.navbar import page_head, section_title
from frontend.config import HOSPITAL


def render() -> None:
    page_head(
        f"About {HOSPITAL.short_name}",
        "Learn about our hospital, mission, and values.",
    )

    section_title("Our Mission", "Why we exist and what drives us")
    st.write(
        f"""
        {HOSPITAL.name} is committed to providing
        comprehensive, compassionate, and cutting-edge healthcare services
        to our community. We believe that quality healthcare should be
        accessible, affordable, and patient-centered.
        """
    )

    section_title("Our Values", "The principles that guide everything we do")
    values = [
        (
            ":material/favorite:",
            "Patient First",
            "Every decision we make starts with our patients' well-being",
        ),
        (
            ":material/science:",
            "Clinical Excellence",
            "We maintain the highest standards of medical care and safety",
        ),
        (
            ":material/lightbulb:",
            "Innovation",
            "We embrace technology and research to improve outcomes",
        ),
        (
            ":material/volunteer_activism:",
            "Compassion",
            "We treat every patient with dignity, respect, and empathy",
        ),
        (
            ":material/verified_user:",
            "Integrity",
            "We are transparent, ethical, and accountable in all we do",
        ),
        (
            ":material/trending_up:",
            "Continuous Improvement",
            "We constantly learn and evolve to serve you better",
        ),
    ]

    cols = st.columns(2, gap="large")
    for idx, (icon, title, desc) in enumerate(values):
        with cols[idx % 2]:
            with st.container(border=True):
                st.markdown(f"### {icon} {title}")
                st.write(desc)

    section_title("Our Facilities", "Infrastructure built around patient care")
    facilities = [
        "Specialized departments with dedicated wards and clinics",
        "Consultants and specialists across major disciplines",
        "Advanced diagnostic imaging (MRI, CT, X-Ray, Ultrasound)",
        "Fully equipped modular operation theatres",
        "24/7 emergency and trauma care",
        "Critical care units with advanced life support",
        "In-house pharmacy and laboratory services",
        "Comfortable patient rooms and waiting areas",
        "Ample parking and a cafeteria",
    ]

    for facility in facilities:
        st.markdown(f"- {facility}")

    section_title(
        "Visit & Contact",
        "Everything you need to reach us — straight from our hospital directory.",
    )
    col1, col2 = st.columns(2, gap="large")
    with col1:
        with st.container(border=True):
            st.markdown("#### :material/pin_drop: Address")
            st.write(HOSPITAL.address)
            st.caption(HOSPITAL.website)
    with col2:
        with st.container(border=True):
            st.markdown("#### :material/phone: Reach Us")
            st.write(f"**Care desk:** {HOSPITAL.phone} ({HOSPITAL.care_desk})")
            st.write(f"**Emergency:** {HOSPITAL.emergency}")
            st.write(f"**Email:** {HOSPITAL.email}")

    st.caption(HOSPITAL.disclaimer)


if __name__ == "__main__":
    render()
