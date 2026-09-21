AgentSwitch — team brief
Measured against the live systems on 2026-09-16.

1. Two businesses, and why both
You work against a running business platform: 424 entity types, real workflow states, real permissions, real data. There are two of them.

Suryodaya Precision Works	Keystone Precision Works LLC
URL	https://agentswitch.theschoolofai.in	https://class.agentswitch.theschoolofai.in
Country	India	United States
Accounting standard	Ind AS / Schedule III	US GAAP (ASC)
Tax regime	GST	Sales & Use Tax
Invoices in the book	415	187
Your login	teamNN@theschoolofai.in	teamNN@theschoolofai.in
Your password	different per business	different per business
Same software, same seat rules, two different jurisdictions. Start on Suryodaya. Move to Keystone when you want the US contrast — an invoice, a tax line and a financial statement all behave differently there, and an agent that assumed India will be wrong in ways worth discovering.

The accounting locale is data, not a separate product: GET /api/accounting/locale tells you which regime you are in, and there is a supported switch (PUT /api/accounting/locale, audited with switched_by and migration_note). Switching a company's locale is a real operation — think before you run it on a book other teams are using.

2. Your seat
Each team owns one seat. A seat is an app plus the roles that go with it.

Team	Seat	App	What it is about
01	Ledger	accounting	invoices, bills, payments, the general ledger
02	Ledger	accounting	same book as 01 and 03 — see §3
03	Ledger	accounting	same book as 01 and 02
04	Production	manufacturing	work orders, BOMs, routings, job cards
05	Stock	inventory	stock entries, warehouses, valuation
06	Pipeline	crm	leads, opportunities, accounts
07	Pipeline	crm	same pipeline as 06
08	Storefront	storefront	web orders, catalogue, checkout
09	Website	website	pages, blog, publication
10	Email	email	mailboxes, threads, campaigns
11	Email	email	same mail estate as 10
12	Payroll	payroll	pay runs, salary structures
13	HR	payroll	employees, the same payroll app
14	Projects	projects	projects, tasks, resourcing
15	Helpdesk	support	tickets, SLAs, canned responses
16	Assets	assets	asset register, depreciation, custody
17	Contracts	contracts	contracts, clauses, renewals
18	E-sign	esign	documents, signatures, evidence
19	Scheduling	scheduling	calendars, bookings, availability
20	Directory	core	parties, contacts, the shared spine
21	Design review	designreview	design files, versions, reviews
22	Knowledgebase	knowledgebase	notes, vault, search
23	Checklists	checklists	SOPs, runs, CAPA
24	Approvals	approvals	requests, policies, delegation
25	Forms	forms	forms, responses, consent
27	Files	core	drive, folders, shares
Every seat also holds agent (your agent's own workspace) and crm (the shared customer spine). Keystone additionally has a team 26; Suryodaya does not.

3. What you can and cannot see
Your app: yes. Another team's app: no. Ask for payroll data from a manufacturing seat and you get 403. That is not a bug to report — it is the boundary. Cross-app data is obtained by asking an EA, an admin or a human. That escalation is part of the exercise.

Verified on both instances today: from every seat that does not own them, SalarySlip, Contract and EsignDocument all return 403.

Teams sharing a seat type share a book. Teams 01, 02 and 03 all see the same 415 invoices — the same rows, not copies. If 01 edits an invoice, 02 and 03 see the change. If 01 deletes one, it is gone for everyone.

This is deliberate. Your agent runs in a world where other agents are changing data underneath it, which is what production actually looks like. Write an agent that tolerates it: re-read before you act, do not assume a row you saw a minute ago is unchanged, and do not "tidy up" data you did not create.

Your agent's own memory is private. Anything your agent writes to AgentMemory, AgentMessage or AgentSkill from now on is owned by you and invisible to other teams. Pre-existing seed rows are shared.

4. Three doors, one set of rules
You have one login per business. It opens three doors onto the same data and the same permission rules.

MCP — the primary interface. This is what your agent drives. §6.
The web UI — same URL in a browser, same credentials. This is how you see what your agent did and learn the domain.
REST — the fallback. Documented, secondary. §7.
Start with the UI for ten minutes before writing any agent code. Sign in, open your app, look at a real record — a Work Order with its actual fields and workflow states, a real Invoice with its tax lines. A team that has seen the data writes a better agent than a team guessing at schemas. The UI is for understanding; MCP is for working.

Your navigation shows only your own apps. That is the same allowed_apps boundary the API enforces — different door, same answer.

5. Logging in
export AS=https://agentswitch.theschoolofai.in        # Suryodaya (India)
# export AS=https://class.agentswitch.theschoolofai.in  # Keystone (US)

export TOKEN=$(curl -s -X POST "$AS/api/auth/login" \
  -H 'Content-Type: application/json' \
  -d '{"email":"teamNN@theschoolofai.in","password":"YOUR_PASSWORD"}' \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["token"])')
Every later call carries Authorization: Bearer $TOKEN. Anonymous is refused (401). Bearer requests need no CSRF token.

Check who you are:

curl -s "$AS/api/auth/me" -H "Authorization: Bearer $TOKEN"
The response shows your roles and allowed_apps — that is your seat, stated by the server.

6. MCP — the interface your agent drives
One endpoint, JSON-RPC 2.0: POST $AS/api/mcp.

Methods: initialize, notifications/initialized, tools/list, tools/call. Protocol version 2025-11-25. There is no SSE stream — GET /api/mcp answers 405 with Allow: POST, which is the spec's way of saying "no stream here", so your client should stop looking for one. There is no batching.

Handshake:

curl -s -X POST "$AS/api/mcp" -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize",
       "params":{"protocolVersion":"2025-11-25","capabilities":{},
                 "clientInfo":{"name":"team-NN","version":"0.1"}}}'
List your tools:

curl -s -X POST "$AS/api/mcp" -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'
Call one:

curl -s -X POST "$AS/api/mcp" -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call",
       "params":{"name":"WorkOrder.list","arguments":{}}}'
The catalogue is scoped to you. A tenant admin sees ~2,639 tools; a team seat sees a few hundred — only the entities and app endpoints your seat may use. A tool you may not use is absent from the list, not refused when called. So you cannot name another app's tool: it does not exist for you.

Tool names follow the data model: <Entity>.list, <Entity>.get, <Entity>.create, <Entity>.update, one tool per workflow transition, plus your app's own endpoints. Every tool carries a JSON Schema for its arguments, and the schema is closed — an argument that is not in it is rejected rather than ignored.

A JSON-RPC error still returns HTTP 200; the failure is in the envelope. Only authentication answers at the HTTP layer (401). If your client treats non-200 as the only failure, it will read every denial as success.

7. REST, and the docs that are live
REST works and is fully documented, but MCP is the interface to build against.

URL	What
$AS/docs	API explorer — every endpoint, try calls in the browser
$AS/redoc	the same surface, laid out for reading
$AS/api/schemas	all 424 entity schemas: fields, types, options, required
$AS/api/agent/tools	the 13 agent tools with their JSON Schemas
/api/schemas is the one to read first — it is the shape of the whole business.

8. What you are actually building
An agent for your seat, running on your machine, with your own model keys, driving this platform over MCP. Your own harness, not a wrapper around ours.

Four steps, in this order. Step 2 is the one teams skip, and everything after it depends on knowing what good looks like.

Step 1. Learn the domain
Open the UI and find real records. Read /api/schemas for your entities. Learn the workflow states, because most business objects move through a state machine and the transitions carry the rules.

Ten minutes in the UI teaches you more than an hour of guessing at schemas.

Step 2. Go and find the best product in your domain
Every seat has a modern product doing the same job, usually better than we do. Finding it is your work, not ours. Search, ask people who do this job, read what the good teams are using this year.

Then study it seriously: sign up for a trial, watch the demos, read the docs and the changelog, look at what they put on the pricing page. A day here is not too much.

Look for the AI-native ones. A twenty-year-old product with a chatbot bolted on will teach you less than something built in the last three years around the assumption that an agent is driving it.

Step 3. Write the gap report
A deliverable, due in week one. One page, three questions, answered with specifics.

What do they do that we do not? Name features concretely. "No bank feed reconciliation, no multi-entity consolidation, revenue recognition is manual" is useful. "Accounting feels thin" is not.

Which of those gaps can an agent close with the tools your seat already has? Some gaps need new tables and new endpoints, which is our problem to fix. Others are orchestration over what already exists, which is yours to build.

What can an agent do that their product cannot? This is the interesting one. Their software is a UI over a database, so a human drives every step. Your agent can hold a goal across twenty steps, re-read state that changed underneath it, and decide.

Step 4. Build the agent, then the harness
The agent answers your seat's questions. The harness proves that it does.

The one example we will give you: Ledger against Rillet
We are showing one worked example so the standard is clear. Everyone else finds their own.

Why Rillet. www.rillet.com is an AI-native ERP rather than an old ledger with a chat window added. More to the point, look at what their AI layer actually is. Aura is an assistant that answers questions against the live general ledger, a set of agents you configure by writing rules in plain English, and a continuous process that watches for anomalies and proposes accruals on its own. They also publish an MCP server over their ledger, so other tools can drive their accounting the way your agent will drive ours.

Read that again. A funded competitor has already shipped the thing you are being asked to build, and they did it in public. The bar is visible, and you can go and look at it this afternoon.

A gap report against them would say: we have invoices, bills, payments and a general ledger with real workflow states. We have no bank feed, so no reconciliation. Revenue recognition is not modelled. Consolidation across entities does not exist. The close is not a tracked process with a checklist and a sign-off.

Then the agent question: reconciliation needs a bank feed we do not have, so that one is a platform gap and it belongs to us. A close checklist can be assembled today out of data that already exists, by an agent that walks the ledger, finds unposted entries, checks the control accounts and reports what is blocking the close. That is orchestration over the current API, and it is yours.

Then the harder question: what can your agent do that Rillet's UI cannot? Rillet makes an accountant fast. Your agent can take "a customer disputes last quarter" and work the whole thread alone: find what was billed, find what was paid, reconcile the difference, isolate the disputed lines, check whether a credit note is even permitted in that period, and draft it. Nobody clicks through twelve screens.

Do that for your own seat, against a product you found yourself.

The request your agent must handle
One per seat. Each has several steps, a judgement call, and a state change in the middle. An agent that answers "list my invoices" is a demo. This is the bar.

Team	Seat	The request
01	Ledger	"A customer disputes last quarter. Work out what we billed, what they paid, and draft the credit note."
02	Ledger (AR)	"Who is over 60 days late, how much is at risk, and draft the chase for the worst three."
03	Ledger (AP and tax)	"What is our tax liability this period, what is unclaimed, and is any vendor being paid twice?"
04	Production	"This work order is late. Find out why, tell me what it blocks downstream, and reschedule what you can."
05	Stock	"We are short a component next week. Work out what we can still build, and what to order first."
06	Pipeline (sales)	"What closes this month, what is at risk, and quote 500 units off the real BOM price."
07	Pipeline (CRM)	"Which deals are rotting, who has not been contacted, and what is the next action on each?"
08	Storefront	"How did the launch coupon perform, and find any order where payment and stock disagree."
09	Website	"Publish a post about the new fixture line, and tell me which pages nobody reads."
10	Email	"What needs my reply today, and find the mail where they agreed the price."
11	Email (campaigns)	"Send the festive offer to customers who bought last year, and tell me who is unsubscribing and why."
12	Payroll	"Run this pay period. Flag anything unusual, and explain why one net pay changed."
13	HR	"Who is on leave next week, whose attendance does not look right, and who is due for confirmation?"
14	Projects	"Which projects are behind, who is overloaded next week, and what would you move?"
15	Helpdesk	"Triage the new tickets, draft a first response from the knowledge base, and tell me which will breach SLA."
16	Assets	"What is due for maintenance, which machine had the most downtime, and what is this asset worth now?"
17	Contracts	"What expires in 60 days, review this draft against our playbook, and list the obligations we are missing."
18	E-sign	"What is pending signature and with whom, and chase everything sitting over a week."
19	Scheduling	"Find thirty minutes with the plant head this week, and move everything after the audit."
20	Directory	"Deduplicate the customer list, and tell me who we know at this company."
21	Design review	"What changed between rev B and rev C, and are there manufacturability problems in this part?"
22	Knowledgebase	"How do we handle a customer rejection, and what do we already know about this customer?"
23	Checklists	"Start the monthly safety audit, tell me which checklists are overdue, and turn this process description into an SOP."
24	Approvals	"What is waiting on me, who is the bottleneck approver, and route everything while I travel."
25	Forms	"Build a supplier onboarding form, and summarise what came back this week."
27	Files	"Find the drawing for part J-BRKT-04, and tidy the incoming folder."
What we are grading
The gap report, in week one. What they have, what we lack, which gaps an agent can close today, and which need platform work from us.

The agent, answering your seat's questions against live data that other teams are changing underneath it.

The harness, which is the part most teams will underbuild. Your own loop, a task set with verifiers that read the database rather than your agent's prose, and every run written to disk before anything is scored.

At least one task where the correct answer is refusal. Ask your agent something the data cannot support, or something its seat is not permitted to do. It must say so. An agent that invents a confident answer has failed that task however well it handled the others.

Tests you wrote by hand. Ten points a test, and a hundred points for every real bug you find in AgentSwitch. A test written by Claude or Codex scores zero.

9. Credentials
Your two logins are posted in your own team channel. They are not published here.

Each team gets two passwords: the same email, one password per business. They are yours alone. Every write is attributed to whoever is signed in, so a team holding another team's password can act as that team.

10. Reporting bugs
In the app: the "Report a problem" button, in the main shell, Mission Control and the agent Office view. It captures the page and agent seat automatically, which is exactly the context that makes a report fixable.

Over the API:

curl -s -X POST "$AS/api/bug-report" -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"description":"what happened, what you expected",
       "page":"MissionControl","agent_seat":"Production","job_id":"..."}'
Your identity is taken from your session, never from the body — a report is always attributable to the team that filed it. Limit 20 per hour.

See your own reports: GET $AS/api/bug-report/mine. You see yours and not other teams'.

What makes a report fixable: what you did, what you expected, what happened, and the ids — the page, the agent seat, the job id. "The agent broke" is not actionable. "WorkOrder.transition to completed returned 200 but the state stayed in_progress, job id abc123" gets fixed.

Known and not worth reporting:

403 reading another app's data — that is the seat boundary (§3).
Another team changing data in your shared book — intentional (§3).
A tool missing from tools/list that another seat has — scoping (§6).
On Keystone, two empty placeholder companies alongside Keystone Precision Works; and 100 pre-seeded AgentTask rows that are not visible. Both known.