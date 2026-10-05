# Team 13 — Bug findings (MCP validated 2026-09-21; round 2 filed 2026-09-29)

Filed via `POST /api/bug-report` (see `GET /api/bug-report/mine`). Please re-check each in the UI.

---

## Bug 1 — Leave Approve/Reject missing from MCP (filed)

**Report id:** `d2378a94-ddd6-4422-9465-d4ef1479886f`  
**UI record to open:** Leave `LA-2026-00570`  
**id:** `b1e2d154-963c-4d1e-ab61-d7eaae4cd6e1`  
**Employee:** prakash.salunkhe8091@corp.in  
**Status:** `pending_approval` (leave 2026-10-12)

### MCP / REST evidence
- `LeaveApplication.get` returns `_transitions`: Approve → approved, Reject → rejected, Withdraw → cancelled.
- Seat `tools/list` has `LeaveApplication.withdraw` only — **no approve / reject tools**.
- Calling `LeaveApplication.approve.pending_approval.approved` → `tool_not_available`.
- `LeaveApplication.withdraw` **does** work (proved on `LA-2026-00572` → cancelled).
- REST `POST .../transition` with `{"action":"Approve","target_state":"approved"}` → **400**  
  `Role(s) ... hr_user ... cannot perform transition 'Approve' (requires 'admin')`  
  (same for Reject). Other body shapes return `Invalid target state 'None'`.

### UI check
1. Open Leave Application `LA-2026-00570`.
2. Confirm status Pending Approval.
3. Note whether Approve / Reject buttons appear for team13.
4. If buttons show: try Approve — expect fail or require admin. If they work in UI, MCP/REST still broken for agents.

---

## Bug 1b — `_transitions` advertises actions the role cannot run (filed)

**Report id:** `a574096b-d5f4-417b-8c7f-f0e29f85aeb4`  
Same record as Bug 1 (`LA-2026-00570`). Distinct issue: get advertises Approve/Reject to `hr_user`, but transition requires `admin`. Agents that trust `_transitions` hit a dead path.

### UI check
Same leave — if Approve is visible to HR in UI, that matches the bad `_transitions` advertisement.

---

## Bug 2 — Leave list date filters are equality, not overlap (filed)

**Report id:** `3a8221f4-5fc3-4881-a9cd-986d1de3258f`  
**UI record:** Leave `LA-2026-00571`  
**id:** `aa4dd201-a18f-48a1-afa4-f97ff26481f1`  
**Dates:** 2026-11-10 → 2026-11-15 (draft)

### MCP evidence
| Query | Result |
|-------|--------|
| `from_date=2026-11-12`, `to_date=2026-11-12` (inside range) | **total=0** |
| `from_date=2026-11-10`, `to_date=2026-11-15` (exact ends) | **total=1** |

Breaks “who is on leave next week” unless the agent pulls everything and filters client-side.

### UI check
1. Open leave list / filter UI.
2. Filter for a single day inside 11–15 Nov (e.g. 12 Nov).
3. Confirm whether `LA-2026-00571` appears. If UI uses overlap but MCP does not (or both miss it) — note which.

---

## Bug 3 — Attendance accepts invalid punches / LOP (filed)

**Report id:** `174d72a8-77c3-4d4c-bfd0-93bb44ba77f6`  
**Employee:** prakash.salunkhe8091@corp.in (`baf152b3-e8ee-4da2-bee4-592637b9f94c`)

| id | date | what was accepted |
|----|------|-------------------|
| `5156c22d-00cc-4abe-89e7-05277143b449` | 2026-09-18 | `present`, **null** check_in/out |
| `8bda4daf-8fbd-40a1-80c3-05f87fc4242c` | 2026-09-17 | `present`, `is_lop=true`, `lop_hours=0` |
| `d2ea209e-c637-4d14-b5e3-5f2d8be1b93a` | 2026-09-16 | `present`, check_in **18:00**, check_out **09:00** |

Future attendance dates correctly rejected — so validation exists, but punch/LOP consistency does not.

### UI check
Open each Attendance id above and confirm the bad values display. Try creating the same combo in UI — note if UI blocks what MCP allowed (or vice versa).

---

## Bug 4 — Leave create accepted for exited (`status=left`) employees (filed)

**Report id:** `82709252-97d4-4025-b74e-809459a457e5`  
**UI record:** Leave `LA-2026-00582`  
**id:** `2b6fcd89-1056-48f5-88c8-f0b05dce3b86`  
**Employee:** anil.patil8093@corp.in (`2fd8fbe9-2fe5-434a-b68a-58cf14401142`)  
**Employee status:** `left` (`exit_date=2025-04-15`)  
**Leave:** casual draft 2027-06-15

### MCP evidence
- `Employee.list` / `Employee.get` confirm `status=left`.
- `LeaveApplication.create` for that employee succeeded (draft).
- Earlier probe: `LA-2026-00575` (same pattern; cancelled).

### UI check
1. Open Employee anil.patil8093@corp.in — confirm Left / exit date.
2. Open Leave `LA-2026-00582` — confirm it exists against that person.
3. Try creating leave for a left employee in UI — note if UI blocks what MCP allowed.

---

## Bug 5 — Leave submit ignores negative LeaveBalance (filed)

**Report id:** `836c4c83-9e87-4e03-bd3d-c76c82c18bbe`  
**UI record:** Leave `LA-2026-00583`  
**id:** `08f0e68b-7c95-479b-92b6-fafc57761380`  
**Employee:** anita.bhalerao@suryodaya.in (`908e36c2-4b9f-4d0c-8c91-81211d6f0891`)  
**Status:** `pending_approval` (casual 2027-08-20)  
**Balance id:** `45deae46-9b02-4a45-90eb-128451615778` — `balance_days=-1`, `used_days=1`, `opening_balance=0`, `accrued_days=0`

### MCP evidence
- Full scan (2026-09-29): **294/294** `LeaveBalance` rows had `balance_days < 0`.
- `LeaveApplication.create` + `submit` still moved leave to `pending_approval`.
- Prior repros (withdrawn): `LA-2026-00577`, `LA-2026-00581`.

### UI check
1. Open Leave `LA-2026-00583` (Pending Approval).
2. Open LeaveBalance for anita.bhalerao@suryodaya.in / casual — confirm negative.
3. Note whether UI warns or blocks submit when balance is insufficient.

---

## Bug 6 — Leave create accepts inconsistent spans / types (filed)

**Report id:** `e67d80f3-b0fb-41b2-80a5-1d2b16bffbd1`

| Leave | id | what was accepted |
|-------|-----|-------------------|
| `LA-2026-00584` | `f7773e60-1093-476b-8bcd-95cba866b473` | sick, **half_day**, 2027-03-01→03-05, **days=4.5** (prakash.rane8085@corp.in) |
| `LA-2026-00585` | `ae9aa3f3-76e4-44cd-86ab-4bb29c440b2a` | **maternity** on **male** prakash.salunkhe8091@corp.in, 122 days (2027-09-01→12-31) |
| `LA-2026-00573` (pre-existing) | `76bda086-6e9f-49c0-856a-f3d6fa131d6d` | paternity **7405.5** days, half_day, 2004-06-15→2024-09-23 |

Also accepted then cancelled after probe: full-year leave in 2010 (`LA-2026-00579`, days=365).

### UI check
Open `LA-2026-00584`, `LA-2026-00585`, and `LA-2026-00573`. Confirm bad combos display. Try the same creates in UI.

---

## Not bugs (validated — do not file)

| Probe | Result |
|-------|--------|
| Create leave with `from_date` > `to_date` | Correctly rejected: “End date cannot be before start date” |
| Create leave with `status=approved` / `banana` | Correctly rejected (state machine; starts at draft) |
| Update `pending_approval` leave to `approved` via `.update` | Correctly blocked |
| Seat 403 on other apps | Intentional boundary |
| Overlapping leave for same employee | Correctly rejected |
| Duplicate Attendance same employee+date | Correctly rejected |
| `is_lop=true` with `lop_hours=-5` | Correctly rejected (“must be greater than 0”) |
| Bogus `leave_type` outside enum | Schema rejects (`Invalid tool arguments`) |
| `days` override vs date span | Platform recomputes days from dates |

### Held (not filed)

| Probe | Why held |
|-------|----------|
| `LeaveType.list` empty (0 rows); all balances negative | May be seed/config on shared book; Bug 5 already covers the agent-facing failure |
| `HolidayList.list` empty | Data gap, not clearly a platform defect |

---

## Probe artefacts left on the shared book

Created by team13 for validation (safe to leave or cancel in UI):

**Round 1 (2026-09-21)**
- `LA-2026-00570` — pending_approval (Approve UI test)
- `LA-2026-00571` — draft multi-day (date-filter UI test)
- `LA-2026-00572` — cancelled (withdraw proof)
- Attendance rows on 2026-09-16 / 17 / 18 for prakash.salunkhe8091@corp.in

**Round 2 (2026-09-29)**
- `LA-2026-00582` — draft leave for left employee (Bug 4)
- `LA-2026-00583` — pending_approval with negative balance (Bug 5)
- `LA-2026-00584` — draft half_day multi-day (Bug 6)
- `LA-2026-00585` — draft maternity on male (Bug 6)
- `LA-2026-00573` — pre-existing extreme paternity (cited in Bug 6; not ours)
