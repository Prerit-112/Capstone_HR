Team 13 (HR) — Gap report  
Against: Calamari.io  
Selected seat: AgentSwitch HR  

Sources: Calamari docs, What’s New through Sep 2026, live MCP tools/list (17 tools after OAuth in Cursor); AgentSwitch UI walkthrough, /api/schemas, team13 MCP catalogue. Shared book with Team 12 (Payroll).

---

### 1. What Calamari.io does which AgentSwitch does not?

| Area | Calamari | AgentSwitch |
|------|----------|-------------|
| Time capture | Clock-in from web, mobile, Slack/Teams, geofence, QR/NFC kiosk, watch, office NFC tags | Attendance stores `check_in` / `check_out` and status; no capture stack — punches are fields on a record |
| Leave policy | Restrictions on notice/retro, min/max length; block leave on chosen weekdays; cap overlapping absences in a group (warn or block); optional/required substitute | LeaveApplication + submit path (draft → pending_approval, withdraw, etc.); no weekday blocks, group overlap caps, or required cover |
| Leave extras | Team absence calendar; Gmail OOO with cover person named | Manager Absence Calendar in UI only (not an MCP entity) |
| Attendance quality | Productised abnormalities: long/short shifts, overlaps, late/early, work on a day off, no-shows; overlapping shifts as a live irregularity; “Absence” abnormality can be switched off | Raw signals only: status, empty punches, `is_lop` / `lop_hours` — no abnormalities config or report |
| Other HR surfaces | Employee Requests (numbered forms, PDF), Smart Table bulk people edits, Performance goals, scheduling “coming soon” | Payroll-linked book (EPF/ESI, salary structures, LOP toward pay). Calamari exports time; it does not run that book |
| Confirmation | Probation end date on the person; no dedicated confirmation workflow | Same pattern: `probation_end_date` on Employee; no confirmation entity |

---

### 2. Which gaps can an AgentSwitch agent close with tools already on the seat? Which need platform work?

**Agent-closable (orchestration over existing AgentSwitch MCP)**

| Goal | How on AgentSwitch today |
|------|--------------------------|
| Who is on leave next week | `LeaveApplication.list` by date overlap + status; names via `Employee` |
| Who is due for confirmation | `Employee.list` on `probation_end_date` (exclude left/suspended). Field exists; due-rule is defined by the agent |
| Attendance that does not look right (first cut) | Cross `Attendance` with `LeaveApplication`: absent without leave, present with blank punches, `is_lop`. Judgment rules are the agent’s; columns exist |
| Balance / holiday context | `LeaveBalance`, `HolidayList` when the question needs them |

**Needs AgentSwitch platform work (not inventable by the agent alone)**

| Gap | Why it is platform |
|-----|-------------------|
| Real clock-in methods + configurable abnormalities engine | No capture channels or irregularities product surface |
| Leave restrictions (weekday blocks, group overlap caps, required substitute) and mail OOO | Not in LeaveApplication schema / tools |
| Employee Requests, bulk HR table ops, shift scheduling | No matching entities |
| `LeaveApplication.approve*` | UI shows Approved; approve transition missing from team13 tools — add in-seat or keep on Approvals and escalate |
| Calamari’s employee self-serve MCP | Different product shape from AgentSwitch’s seat agent on the company book |

---

### 3. What can an AgentSwitch agent do that Calamari’s UI (and Calamari’s MCP) cannot?

| | Calamari | AgentSwitch agent |
|--|----------|-------------------|
| How work gets done | Human opens Time Off, then Attendance, then People | One goal held across entities in one run |
| MCP focus | Real MCP (17 tools): clock in, book *my* leave, *my* balances, who’s out on *my* team — mostly self-service | Seat MCP on the shared HR/payroll book: list/filter company leave, attendance, employees |
| Approve leave | Not in live Calamari tools/list | Also missing approve* on team13 — same hole; escalate or wait on platform |
| Abnormalities as a tool | No abnormalities-report tool on Calamari MCP | Agent can *derive* a first-pass anomaly list from Attendance + LeaveApplication fields |
| Confirmation scan | `getMyProfile` returns *my* probation date only | `Employee.list` can scan who is due across the book |
| Shared / changing data | Single-tenant HR app, user-driven screens | Re-read under Team 12 writes; call out draft leave, missing punches, or rows that moved since last read |
| Seat boundary | Not part of the product story | Refuse manufacturing / GL (403 / missing tools) — part of the exercise |

Example thread the AgentSwitch agent can run as one job: next week’s leave → attendance that disagrees with leave or carries LOP → probation endings coming due → what is still fuzzy. Calamari makes each click faster; it does not run that whole thread against a live shared payroll book.
