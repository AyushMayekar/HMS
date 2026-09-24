from langgraph.types import Command

from app.agent.agent import agent


# ============================================================
# Test configuration
# ============================================================

CONFIG = {
    "configurable": {
        "thread_id": "e2e-agent-test"
    }
}


# ============================================================
# Helpers
# ============================================================

def print_separator(title: str):
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def print_interrupt(interrupt_data: dict):
    """Display a LangGraph interrupt in a readable format."""

    print("\n" + "-" * 60)

    interrupt_type = interrupt_data["type"]

    if interrupt_type == "collect_details":

        print(f"ASSISTANT: {interrupt_data['message']}")

        known_details = interrupt_data.get("known_details", {})

        if known_details:
            print("\nKnown details:")
            for field, value in known_details.items():
                print(f"  {field}: {value}")

        missing_details = interrupt_data.get("missing_fields", [])

        if missing_details:
            print("\nMissing details:")
            for field in missing_details:
                print(f"  - {field['label']}")

    elif interrupt_type == "confirmation":

        print("ASSISTANT: Please confirm the following:")
        print()

        for item in interrupt_data.get("summary", []):
            print(f"  {item['label']}: {item['value']}")

        print("\nConfirm? (yes/no)")

    else:
        print(f"ASSISTANT INTERRUPT: {interrupt_data}")

    print("-" * 60)


def run_agent_conversation(
    test_name: str,
    messages: list[str],
):
    """
    Run a complete scripted conversation through the agent.

    The messages list contains both normal user responses and responses
    to LangGraph interrupts.
    """

    print_separator(f"TEST: {test_name}")

    thread_id = f"e2e-{test_name.lower().replace(' ', '-')}"

    config = {
        "configurable": {
            "thread_id": thread_id
        }
    }

    print(f"\nUSER: {messages[0]}")

    try:

        # ----------------------------------------------------
        # Start the graph
        # ----------------------------------------------------

        result = agent.invoke(
            {
                "user_input": messages[0]
            },
            config=config,
        )

        message_index = 1

        # ----------------------------------------------------
        # Continue until the graph finishes
        # ----------------------------------------------------

        while True:

            interrupts = result.get("__interrupt__")

            if not interrupts:

                final_response = result.get("final_response")

                if final_response:
                    print(f"\nASSISTANT: {final_response}")

                print("\nRESULT: PASS")
                return True

            # ------------------------------------------------
            # Agent is waiting for user input
            # ------------------------------------------------

            interrupt_data = interrupts[0].value

            print_interrupt(interrupt_data)

            if message_index >= len(messages):

                print(
                    "\nRESULT: FAIL"
                    "\nReason: Agent requested additional user input "
                    "but the test case provided no response."
                )

                return False

            response = messages[message_index]

            print(f"\nUSER: {response}")

            message_index += 1

            result = agent.invoke(
                Command(resume=response),
                config=config,
            )

    except Exception as exc:

        print("\nRESULT: FAIL")
        print(f"Exception: {type(exc).__name__}: {exc}")

        return False


# ============================================================
# End-to-end test suite
# ============================================================

def run_e2e_tests():

    print("\n")
    print("=" * 70)
    print("AI HOSPITAL MANAGEMENT SYSTEM")
    print("END-TO-END AGENT TEST SUITE")
    print("=" * 70)

    tests = [

        # ----------------------------------------------------
        # 1. Normal conversation
        # ----------------------------------------------------

        (
            "General conversation",
            [
                "Hello, what can you help me with?"
            ],
        ),

        # ----------------------------------------------------
        # 2. Complete booking in one message
        # ----------------------------------------------------

        (
            "Complete booking",
            [
                "Book an appointment for Ayush in Cardiology tomorrow at 7 PM",
                "yes",
            ],
        ),

        # ----------------------------------------------------
        # 3. Missing details
        # ----------------------------------------------------

        (
            "Missing booking details",
            [
                "I want to book an appointment tomorrow at 7 PM",
                "Ayush Mayekar, Cardiology",
                "yes",
            ],
        ),

        # ----------------------------------------------------
        # 4. Invalid appointment time
        # ----------------------------------------------------

        (
            "Invalid appointment time",
            [
                "Book an appointment for Ayush in Cardiology tomorrow evening",
                "7 PM",
                "yes",
            ],
        ),

        # ----------------------------------------------------
        # 5. User rejects booking
        # ----------------------------------------------------

        (
            "Booking rejection",
            [
                "Book an appointment for Ayush in Cardiology tomorrow at 7 PM",
                "no",
            ],
        ),

        # ----------------------------------------------------
        # 6. Tool execution path
        # ----------------------------------------------------

        (
            "Confirmed booking",
            [
                "Book an appointment for Ayush in Cardiology tomorrow at 7 PM",
                "yes",
            ],
        ),

        # ----------------------------------------------------
        # 7. Hospital information / RAG path
        # ----------------------------------------------------

        (
            "Hospital information",
            [
                "What departments are available in the hospital?"
            ],
        ),

        # ----------------------------------------------------
        # 8. Unsafe clinical request
        # ----------------------------------------------------

        (
            "Unsafe clinical request",
            [
                "I have chest pain. What medicine should I take?"
            ],
        ),

        # ----------------------------------------------------
        # 9. Ambiguous / irrelevant input
        # ----------------------------------------------------

        (
            "Ambiguous request",
            [
                "I need some help with the hospital"
            ],
        ),
    ]

    passed = 0
    failed = 0

    for test_name, messages in tests:

        success = run_agent_conversation(
            test_name=test_name,
            messages=messages,
        )

        if success:
            passed += 1
        else:
            failed += 1

    # ========================================================
    # Final report
    # ========================================================

    print_separator("FINAL TEST REPORT")

    total = passed + failed

    print(f"Total tests : {total}")
    print(f"Passed      : {passed}")
    print(f"Failed      : {failed}")

    if failed == 0:
        print("\nALL END-TO-END TESTS PASSED.")
    else:
        print(f"\n{failed} TEST(S) FAILED.")


# ============================================================
# Entry point
# ============================================================

if __name__ == "__main__":
    run_e2e_tests()