# Team 13 — Bug findings (MCP validated 2026-09-21)

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

## Not bugs (validated — do not file)

| Probe | Result |
|-------|--------|
| Create leave with `from_date` > `to_date` | Correctly rejected: “End date cannot be before start date” |
| Create leave with `status=approved` / `banana` | Correctly rejected (state machine; starts at draft) |
| Update `pending_approval` leave to `approved` via `.update` | Correctly blocked |
| Seat 403 on other apps | Intentional boundary |

---

## Probe artefacts left on the shared book

Created by team13 for validation (safe to leave or cancel in UI):

- `LA-2026-00570` — pending_approval (keep for Approve UI test)
- `LA-2026-00571` — draft multi-day (keep for date-filter UI test)
- `LA-2026-00572` — cancelled (withdraw proof)
- Attendance rows on 2026-09-16 / 17 / 18 for prakash.salunkhe8091@corp.in
