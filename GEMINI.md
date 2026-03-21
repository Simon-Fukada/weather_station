# Project: Local Weather Station API
This is a local, highly optimized Raspberry Pi weather station. It relies on an RTL-SDR radio to capture 433MHz sensor data and stores it in SQLite.

## Tech Stack
- **Backend:** Python 3, FastAPI, Uvicorn
- **Database:** SQLite3 (Raw SQL strictly, NO ORMs like SQLAlchemy)
- **Frontend:** Vanilla JavaScript (ES5/ES6), HTML, CSS, Chart.js v2.9.4
- **Testing:** pytest

When executing python commands remember to use the virtual environment

## Architectural Rules
1. **The Repository Pattern:** All SQL execution must live inside `api/repository.py`. The `main.py` file orchestrates the HTTP requests and business logic, but it must never execute raw SQL.
2. **Dependency Injection:** Database connections are managed via FastAPI's `Depends(get_db)`. Do not manually open/close connections inside endpoints.
3. **Database Concurrency:** The SQLite database utilizes WAL mode and `check_same_thread=False` to prevent locking. 
4. **Defensive Programming:** The frontend and backend must fail gracefully. Missing sensor data (e.g., a dead battery or missing wind sensor) must result in `None` or `--`, never a hard crash or a `TypeError`.

## Testing Guidelines
- Use `pytest`.
- Database tests must use an in-memory database (`sqlite3.connect(":memory:")`). Never run tests against the production `weather_data.db` file.
- **Boundary & Edge Case Testing:** All tests must explicitly verify boundaries. Do not just test the "happy path." For time-series queries, you must inject fake data just outside the target time window (e.g., 25 hours ago for a 24-hour query) to mathematically prove the SQL filters work.
- **Empty States (Data Absence):** Explicitly test how functions handle missing data. You must write tests for querying non-existent `sensor_id`s, querying metrics that a sensor hasn't recorded yet, and querying empty tables to ensure the functions return `None` or `[]` without throwing `TypeError`s.
- **API Endpoint Testing:** Use FastAPI's `TestClient` to test web endpoints. 
- **Dependency Mocking:** When testing `main.py` endpoints, use FastAPI's `app.dependency_overrides` to swap out the production `get_db` connection with the `pytest` in-memory database fixture. Alternatively, mock the `repository` functions directly using `unittest.mock.patch` to isolate the web logic from the database layer.
## Frontend Testing Guidelines (JavaScript)
- Use **Jest** as the testing framework.
- Set the test environment to `jsdom` so the tests have access to a simulated browser `document` and `window`.
- **Mocking:** You must explicitly mock the global `fetch` API to return fake JSON responses. You must also mock the global `Chart` object, as Chart.js requires a real HTML canvas to render, which `jsdom` does not fully support.
- **DOM Testing:** Write tests that explicitly assert DOM side-effects (e.g., verify that `document.getElementById('ui-temp').innerHTML` updates after a mocked fetch).

## Code Review & Mentorship
- **Continuous Code Review:** When modifying existing code, actively scan for architectural anti-patterns, security risks, or performance bottlenecks. 
- **Explain the "Why":** If you identify an anti-pattern or suggest a best practice, briefly explain *why* it is superior at the compiler/system level. 
- **Pragmatism:** Prioritize pointing out major structural issues over trivial stylistic preferences.