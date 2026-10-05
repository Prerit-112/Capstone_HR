# Team 13 — Bug findings (MCP validated 2026-09-21; round 2 filed 2026-09-29; round 3 filed 2026-10-05)

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

## Bug 7 — Attendance for exited (`status=left`) employees (filed)

**Report id:** `0a770f42-cc28-4145-b154-680c43496640`  
**UI record:** Attendance `00022dd1-8f6e-46e4-9d08-d921dc05eb14`  
**Employee:** priya.naik@suryodaya.in (`2fd8fbe9-2fe5-434a-b68a-58cf14401142`)  
**Employee status:** `left` (`exit_date=2025-04-15`)  
**Attendance:** `present` on 2026-09-30 with check_in/out

### MCP evidence
- `Employee.get` confirms `status=left`.
- `Attendance.create` for that employee succeeded; `Attendance.get` still shows the row.

### UI check
1. Open Employee priya.naik@suryodaya.in — confirm Left / exit date.
2. Open Attendance id above — confirm present punches against that person.

---

## Bug 8 — Leave create+submit for suspended employees (filed)

**Report id:** `ab41ecc5-c470-4228-ba9d-e4e5777189d3`  
**UI record:** Leave `LA-2026-00595`  
**id:** `4ec3768b-9499-449c-bc47-3afd29896b79`  
**Employee:** meera.more8916@corp.in (`441e6779-ef91-44d0-ba9d-4ffba7b38622`)  
**Status:** `pending_approval` (casual 2028-04-10)  
**Employee status:** `suspended`

### MCP evidence
- `LeaveApplication.create` + `submit` moved leave to `pending_approval` while employee remained suspended.

### UI check
Open Leave `LA-2026-00595` and Employee meera.more8916@corp.in (Suspended).

---

## Bug 9 — Leave before `date_of_joining` (filed)

**Report id:** `7f507a7e-ba5e-4c20-ba39-5f7f39d744af`  
**UI record:** Leave `LA-2026-00596`  
**id:** `fee41e61-79f8-4a07-bdbc-b2fbe39df845`  
**Employee:** girish@suryodaya.in (`baf152b3-e8ee-4da2-bee4-592637b9f94c`)  
**DOJ:** 2025-06-09  
**Leave:** sick `pending_approval` 2001-03-01 → 2001-03-03 (days=3)

### MCP evidence
- Platform rejects `from_date > to_date`, but accepts leave entirely before joining, including submit.

### UI check
Open Leave `LA-2026-00596` and Employee girish@suryodaya.in (DOJ 2025-06-09).

---

## Bug 10 — LeaveBalance.create accepts absurd FY / opening (filed)

**Report id:** `63b555c3-b4d6-4045-95a0-5f748f571640`  
**UI record:** LeaveBalance `59443ce6-06ac-4796-8944-8c93c19058fe`  
**Employee:** girish@suryodaya.in  
**Values accepted:** `fiscal_year=2099-00`, `opening_balance=9999`, `balance_days=9999`, `leave_type=casual`

### MCP evidence
- `LeaveBalance.create` with malformed FY string and huge opening balance succeeded and is readable via get/list.

### UI check
Open LeaveBalance id above.

---

## Bug 11 — Employee active + `exit_date`; MCP cannot clear null (filed)

**Report id:** `84ca2ac7-1b28-411e-a329-ebd9af4604f0`  
**UI record:** Employee anita.bhalerao@suryodaya.in (`908e36c2-4b9f-4d0c-8c91-81211d6f0891`)  
**State left for UI:** `status=active`, `exit_date=2019-06-01` (before DOJ 2025-03-03)

### MCP / REST evidence
- MCP `Employee.update` `exit_date=2019-06-01` while active succeeded.
- MCP `Employee.update` `exit_date=null` → `/exit_date must be string` (empty string also rejected).
- REST `PUT /api/Employee/{id}` with `{"exit_date": null}` **does** clear (used to restore girish after accidental set).

### UI check
Open Employee anita.bhalerao@suryodaya.in — active with exit_date 2019-06-01. Try clearing exit in UI.

---

## Bug 12 — Attendance non-times / negative OT / LOP inconsistency (filed)

**Report id:** `09302d04-49d5-48ea-addc-4e97d90521e3`  
Follow-up to Bug 3 with sharper invalid inputs. Employee: girish@suryodaya.in

| id | date | what was accepted |
|----|------|-------------------|
| `d4af054c-5a2a-4cb9-9a59-0683234dad36` | 2026-09-27 | `present`, check_in **25:99**, check_out **not-a-time** |
| `9865af84-1346-484b-92aa-d482b77185b6` | 2026-09-28 | `present`, overtime_hours **-99**, check_in **99:99** |
| `ce234c7e-8b5e-44b8-bf07-94dcad31503b` | 2026-09-24 | `present`, `is_lop=false`, `lop_hours=4` |
| `61309d0f-8f12-4f2e-aa65-ea0066df04ef` | 2026-09-29 | `on_leave` with punches + `is_lop=true` lop_hours=8 |

### UI check
Open each Attendance id above and confirm bad values display.

---

## Bug 13 — Paternity leave on female employee (filed)

**Report id:** `47127e68-9064-40da-b712-6f291026dd47`  
**UI record:** Leave `LA-2026-00597`  
**id:** `d2a99229-6562-4678-ac1e-03dd21f00f9f`  
**Employee:** kavita.patil@suryodaya.in (`ead82eb1-65e4-4a23-a635-fb6ec0c96ab1`)  
**gender:** female  
**Leave:** paternity draft 2028-05-01 → 2028-05-15 (days=15)

### MCP evidence
- Mirror of Bug 6 maternity-on-male: `LeaveApplication.create` with `leave_type=paternity` for female succeeded.

### UI check
Open Leave `LA-2026-00597` and Employee kavita.patil@suryodaya.in (female).

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

**Round 3 (2026-10-05)**
- Attendance `00022dd1-…` — present for left employee priya.naik (Bug 7)
- `LA-2026-00595` — pending_approval for suspended meera.more (Bug 8)
- `LA-2026-00596` — pending_approval leave before DOJ on girish (Bug 9)
- LeaveBalance `59443ce6-…` — FY 2099-00 / 9999 days on girish (Bug 10)
- Employee anita.bhalerao@suryodaya.in — active + exit_date=2019-06-01 (Bug 11 artefact)
- Attendance rows on girish 2026-09-24 / 27 / 28 / 29 (Bug 12)
- `LA-2026-00597` — draft paternity on female kavita.patil (Bug 13)
- **Restored:** girish@suryodaya.in `exit_date` cleared via REST `PUT` `{"exit_date": null}` (MCP could not clear)
