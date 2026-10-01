\# REEF AI — Hub Project Context



\## Product



Reef AI Hub is the always-on backend/server for the Reef AI application.



Project:



C:\\Users\\Ganesh\\Projects\\reef\_ai\_hub



Technology:

\- Python

\- FastAPI

\- Uvicorn

\- SQLite



Development server:



python -m uvicorn api.app:app --host 127.0.0.1 --port 8080



\## Architecture



Flutter

&#x20;   ↓ REST

Reef AI Hub

&#x20;   ↓

Device integrations

&#x20;   ↓

Vendor APIs



Flutter MUST NOT communicate directly with vendors.



Hub owns:

\- authentication

\- device registry

\- credentials

\- vendor integrations

\- polling

\- telemetry storage

\- scheduling

\- automation

\- reconciliation



\## Database



Development database:



C:\\Users\\Ganesh\\Projects\\reef\_ai\_hub\\reef\_ai\_hub.db



Main tables:



devices

device\_credentials

aquawiz\_data

telemetry

alerts

commands

equipment

connection\_history

api\_users



\## Device Registry



devices is the generic device registry.



Actual schema includes:



id

name

device\_type

brand

model

integration

enabled

poll\_interval\_seconds

status

config

credential\_ref

...



IMPORTANT:

Primary key is:



id



There is NOT a device\_id column in devices.



Physical identity:



integration + serial



Example:



aquawiz + KH1-00-02544



Duplicate registration must be rejected.



Use 409 Conflict.



\## Credentials



Generic device record contains:



credential\_ref



Secrets are stored in the secure credential vault.



Do NOT store vendor passwords in:



devices.config



Do NOT store Hub bearer tokens in devices.config.



AquaWiz access tokens must not appear in normal device API responses or logs.



Never log:

\- password

\- bearer token

\- AquaWiz access token

\- secret payload



\## AquaWiz API



Real AquaWiz base URL:



https://server.aquawiz.net



Authentication:



POST /api/v1/KH/auth



Payload:



{

&#x20; "user": "<username>",

&#x20; "password": "<password>",

&#x20; "token": {

&#x20;   "access\_token": ""

&#x20; }

}



Response:



{

&#x20; "access\_token": "...",

&#x20; "user": {

&#x20;   "devices": \[

&#x20;     "KH1-00-02544",

&#x20;     "CA1-00-00646"

&#x20;   ]

&#x20; }

}



IMPORTANT:



user.devices is list\[str]



NOT list\[dict].



Device data:



POST /api/v1/KH/{serial}/all\_field



Payload:



{

&#x20; "user": "<username>",

&#x20; "password": "<password>",

&#x20; "serial": "<serial>",

&#x20; "token": {

&#x20;   "access\_token": "<AquaWiz token>"

&#x20; }

}



Flutter MUST NOT call AquaWiz directly.



\## AquaWiz Models



Internal values:



kh

carx



User-facing values:



kh → KHA

carx → CRA



Do not change internal values simply to change display labels.



Known devices:



KH1-00-02544 → KHA

CA1-00-00646 → CRA



\## Brand Storage



Each vendor gets brand-specific historical storage.



AquaWiz:



aquawiz\_data



Future examples:



kamoer\_data

inkbird\_data

smart\_switch\_data



Generic telemetry remains available for universal telemetry where appropriate.



Do NOT store AquaWiz historical measurements in devices.



\## AquaWiz Data Table



Current structure:



id

device\_id

serial

reading\_time

kh

ph

kh\_dosing

kh\_target

delta\_kh

co2\_bubbles

created\_at



Each poll creates historical rows.



Never overwrite historical readings.



\## API Authentication



Public:



GET /health

GET /docs

GET /openapi.json



Protected:



all normal API/data/control endpoints



Protected requests require:



Authorization: Bearer <Hub token>



Never accept authentication tokens in query strings.



AquaWiz vendor token and Hub token are completely separate.



\## Important Backend Files



Start with these for normal tasks:



api/app.py

api/routes/auth.py

api/routes/devices.py

api/routes/aquawiz.py

api/middleware/auth.py

devices/manager.py

creds/manager.py

aquawiz/

database/connection.py



Only search unrelated modules when required.



\## Testing



Run:



pytest tests/ -v



Current known baseline:

All existing tests should remain passing.



Do not alter tests merely to hide production failures.



Tests must not depend on:



reef\_ai\_hub.db



Use isolated temporary databases where database state matters.



\## Security



Never:

\- print passwords

\- print access tokens

\- return secret payloads

\- put tokens in URLs

\- store secrets in normal device config

\- commit the real database



\## Development Database



The real development DB is:



reef\_ai\_hub.db



Do NOT delete or reset it during normal coding tasks.



Before any manual database cleanup:



create a backup first.

## Project Memory Accuracy Rule

`CLAUDE.md` and `docs/PROJECT_STATUS.md` are project context and historical guidance, not authoritative truth.

Always verify important claims against the current code, tests, database schema, API contracts, Git state, and observable behavior.

If any project memory conflicts with verified current behavior:

1. Do not silently follow the incorrect memory.
2. Clearly report the discrepancy.
3. Identify which source is inconsistent.
4. Prefer verified current implementation/test evidence for the active task.
5. Continue the requested task without silently changing the project plan.
6. Do not rewrite project memory merely to make it agree with the current code.
7. Recommend updating the memory file only after the discrepancy is understood and the relevant change is confirmed.

Never invent missing information to reconcile conflicting project memory.



\## Development Workflow



ChatGPT defines phase

↓

Claude implements

↓

User manually tests

↓

ChatGPT reviews

↓

Phase approved

↓

Git commit

↓

Next phase



Claude MUST NOT launch the emulator unless explicitly instructed.



\## Task Rules



1\. Read this CLAUDE.md first.

2\. Start with files relevant to the current task.

3\. Do not scan the entire repository unnecessarily.

4\. Do not modify unrelated files.

5\. Preserve existing architecture.

6\. Report exact root cause.

7\. Report exact files changed.

8\. Run tests after changes.

9\. Do not claim success without verification.

10\. Do not implement future phases unless explicitly requested.



\## Current Project Status



Completed:

\- FastAPI Hub

\- Hub authentication

\- device registry

\- duplicate prevention

\- credential vault

\- AquaWiz discovery

\- AquaWiz registration

\- AquaWiz credential management

\- AquaWiz Test Connection

\- AquaWiz historical data table

\- Dashboard device read path



Next major phase:

AquaWiz polling → /all\_field → normalization → aquawiz\_data → Dashboard live/latest readings



Do NOT implement polling until explicitly requested.

