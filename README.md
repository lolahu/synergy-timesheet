# Synergy Timesheet

A lightweight internal timesheet web app for construction teams.

✅ Passwordless “magic link” login (dev mode prints link to terminal)  
✅ Foreman/Admin-only timesheet entry  
✅ Project-centric weekly grid (choose a project → enter Mon–Sun hours for all workers)  
✅ Django Admin for managing Workers/Projects/Rates + a Weekly Hours Dashboard

---

## Features

### Timesheet entry (Foreman/Admin only)
- URL: `/timesheet/`
- Choose:
  - **Project** (dropdown)
  - **Week of (Monday)** (date picker)
- Grid layout:
  - Rows = **Workers**
  - Columns = **Mon–Sun**
  - Cells = **hours**
- Save behavior:
  - Filled cell → upsert `TimeEntry`
  - Blank cell → deletes existing entry for that worker/project/day

### Admin site
- URL: `/admin/`
- Manage:
  - Workers
  - Projects
  - Rate overrides
  - Time entries (stored daily under the hood)
  - Access requests / magic tokens (dev)
- Weekly reporting:
  - TimeEntry list has a **Weekly dashboard** link
  - Dashboard groups hours by **(week, worker, project)**

---

## Roles & access control

### Foreman/Admin access to timesheets
Timesheet entry is restricted to:
- `User.is_staff = True` **OR**
- User in Group named `FOREMAN`

Regular workers should NOT be able to enter their own hours.

---

## Tech stack
- Python
- Django
- SQLite in development (default)

---

## Local setup

### 1) Create and activate a virtual environment
From the repo root:

```bash
python -m venv .venv
source .venv/bin/activate