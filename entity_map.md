# Team 13 HR — Entity map (Step 1b)

Seat check (`/api/auth/me`): roles include `hr_user`, `payroll_user`; `allowed_apps`: `payroll`, `agent`, `crm`.  
MCP catalogue: **340** tools total; HR-core entities live in domain **`people`** (not `payroll`).

## Bar request → tools

| Bar part | Primary tools | Key fields | Workflow / filters | Notes |
|----------|---------------|------------|--------------------|-------|
| Who is on leave next week? | `LeaveApplication.list` (+ `Employee.get` for names) | `employee_id`, `from_date`, `to_date`, `status`, `leave_type` | Confirmed states from transition tools: `draft`, `pending_approval`, `rejected`, `cancelled`. UI also shows **Approved** — **no `LeaveApplication.approve*` tool** in our catalogue; approved rows may still be listable. | Filter by date overlap with next week. Prefer non-draft statuses; exact “approved” value still to confirm on live rows. |
| Whose attendance does not look right? | `Attendance.list` (+ cross-check `LeaveApplication.list`) | `status`, `check_in`, `check_out`, `overtime_hours`, **`is_lop`**, **`lop_hours`**, `date` | Status enum: `present` \| `absent` \| `half_day` \| `on_leave` \| `work_from_home` | Schema-backed anomaly signals: `is_lop` / `lop_hours`; absent vs leave mismatch; present with empty punches. Rules still HYPOTHESIS until live sample. |
| Who is due for confirmation? | `Employee.list` / `Employee.get` | **`probation_end_date`**, `status`, `date_of_joining` | Employee `status`: `active` \| `on_leave` \| `suspended` \| `left` — **no confirmation workflow entity** | Confirmation = field on Employee, not a separate doc type. Due ≈ `probation_end_date` near/past + not `left`/`suspended`. |

Supporting (optional): `LeaveType.*`, `LeaveBalance.*`, `HolidayList.*` (holidays vs absence).  
UI-only: **Manager Absence Calendar** — **no matching MCP entity/tool**.

## Entity detail

### Employee (`people`)
- Tools: `list`, `get`, `create`, `update`
- Bar-critical: `probation_end_date`, `status`, `first_name`/`last_name`/`employee_id_number`
- Permissions: `hr_user` read/create/write

### LeaveApplication (`people`, submittable)
- Tools: `list`, `get`, `create`, `update`, `submit` (draft→pending_approval), `cancel.draft.cancelled`, `revise` (rejected→draft), `withdraw` (pending_approval→cancelled)
- Bar-critical: `from_date`, `to_date`, `status`, `employee_id`
- Gap: no approve transition tool for this seat

### Attendance (`people`)
- Tools: `list`, `get`, `create`, `update`
- Bar-critical: `status`, punches, `is_lop`, `lop_hours`, `overtime_hours`

## Still open (need live sample — not done yet)
1. Exact string for “approved” leave status in API responses vs UI label.
2. How often `is_lop` is populated vs blank punches.
3. Distribution of `probation_end_date` on active employees.
