# Setup and Test Instructions

## Prerequisites
- Python 3.13+
- Supabase project with database schema deployed
- LLM API access (LLM_BASE_URL, LLM_API_KEY, LLM_MODEL)

## Environment Variables
Create `.env` in `integrated_hospital/` with:
```
LLM_BASE_URL=https://your-llm-gateway
LLM_API_KEY=your-llm-api-key
LLM_MODEL=your-model-name
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-anon-key
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
```

## Installation
```bash
cd integrated_hospital
pip install -r requirements.txt
# Or install manually:
pip install fastapi httpx joblib langchain langchain-community langchain-openai langchain-text-splitters langgraph numpy pandas scikit-learn==1.9.1 pydantic python-dotenv supabase uvicorn
```

## Running the Application
```bash
cd integrated_hospital
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## Running Tests

### Contract Tests (unit tests with mocks)
```bash
cd integrated_hospital
PYTHONPATH=. python -m pytest tests/test_agent_contracts.py -v
```

### E2E Tests (requires real Supabase connection and test user)
```bash
# Set test user ID (patient role)
export AGENT_USER_ID=your-patient-uuid
export AGENT_ROLE=patient

cd integrated_hospital
PYTHONPATH=. python tests/test_agent.py
```

### Test User Requirements
The e2e tests require a real patient user in the database with existing appointments. The test user must have:
- Role: `patient`
- Status: `active`
- Some appointments in the database (for lookup/reschedule/cancel tests)

## Verified Agent Flows
1. **General Conversation** - Basic hospital info queries
2. **Appointment Booking** - Department → Doctor → Slot discovery → Confirmation → Execution
3. **Missing Details Collection** - Agent asks for missing required fields
4. **Invalid Time Handling** - Rejects vague times (morning/evening), asks for specific time
5. **Booking Rejection** - User can decline at confirmation, no mutation occurs
6. **Appointment Lookup** - Shows user's appointments with selection
4. **Appointment Reschedule** - Select appointment → New date/time → Slot discovery → Confirm → Execute
5. **Appointment Cancellation** - Select appointment → Confirm → Execute
6. **Administrative Request** - Category + Description → Confirm → Execute
7. **Hospital Information (RAG)** - Answers from knowledge base
8. **Unsafe Clinical Request** - Refuses medical advice, directs to emergency
9. **Analytics Recommendations** - Staff/admin only, converts real analytics to operational recommendations

## Architecture Notes
- **Agent/LLM Orchestration**: LangGraph state machine in `app/agent/`
- **Discovery/Read Tools**: `app/agent/tools.py` - calls existing services for live data
- **Thin Execution Tools**: `app/agent/tools.py` - calls mutation services after confirmation
- **Business/Service Layer**: `app/services/` - unchanged existing services
- **Database**: Supabase with RLS, accessed via service-layer functions
- **RAG**: Preserved existing implementation in `app/services/rag_service.py` and `app/rag/`

## Key Implementation Details
- IDs are **never invented** by LLM - resolved from live discovery
- **Explicit confirmation** required before any mutation
- **Real service execution** - uses existing `book_appointment`, `reschedule_patient_appointment`, `cancel_patient_appointment`, `create_admin_request`
- **Discovery flow**: department → doctor → availability (slots)
- **Confirmation gate**: Router prevents `execute_tool` if `confirmed=False`
- **Tool result handling**: Distinguishes discovery results from execution results