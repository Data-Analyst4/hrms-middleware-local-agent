# V8 Manual UAT Checklist — dev.erp.k95foods.com

Run **after** automated tests pass:

```powershell
cd "C:\Users\DELL\HR Module"
# Credentials loaded from configs/integration.local.env (gitignored)
python scripts/run_v8_integration_tests.py
```

Use a dedicated test employee code (e.g. `UAT88002`) so production users are not affected.

---

## Prerequisites

| Item | Check |
|------|-------|
| **Ports**: middleware gateway `8080` / FK `8081` on site PC; K95 local dev `8090` only if coding on laptop | ☐ |
| Branch **V8** seeded on dev VPS (`seed-v8-middleware-branch.mjs`) | ☐ |
| **Backend deployed** on dev VPS with `middlewarePunchRoutes` (punch webhook) | ☐ |
| `outbound_hmac_secret` in middleware = `webhook_secret` on Branch V8 | ☐ |
| Cloudflare tunnel `v8-mw.k95foods.com` → site PC `:8080` | ☐ |
| Middleware running (gateway `:8080`, FK listener `:8081`, outbound worker) | ☐ |
| T501 online at `192.168.29.44:5005`, machine #2 | ☐ |
| HR login on https://dev.erp.k95foods.com — use `configs/integration.local.env` (admin / hr_manager) | ☐ |

---

## Phase 1 — Create employee in ERP web app

1. Open **HR → Employees** (`/HREmployees`).
2. Click **Register Employee**.
3. Fill:
   - Employee code: `UAT88002` (or your test code)
   - Name: `V8 Manual UAT`
   - **Enroll no**: machine user ID (e.g. `88002`)
   - **Branch**: `V8`
   - Department, designation, phone
4. Save.
5. **Verify**: Device sync chip shows **Pending** then **On device** (or retry via ⋮ → Push to device).

| Step | Pass |
|------|------|
| Employee visible in list | ☐ |
| Auto-push attempted | ☐ |
| Device sync status updated | ☐ |

---

## Phase 2 — Enroll fingerprint on T501 (physical)

1. On T501 device menu → User management → find user ID matching **enroll_no**.
2. If user not on device: use ERP **⋮ → Create on device** first.
3. Enroll **fingerprint** (and/or card if used).
4. Optional: enroll **face/photo** if device supports it on this firmware.

| Step | Pass |
|------|------|
| User exists on machine | ☐ |
| Fingerprint enrolled | ☐ |
| Photo/face enrolled (if applicable) | ☐ |

---

## Phase 3 — Punch test

1. Punch IN on T501 with enrolled finger.
2. Wait ~5–10 s (outbound worker poll).
3. In ERP: **Attendance** → find log for `UAT88002`.
4. Punch OUT (optional second test).

| Step | Pass |
|------|------|
| Punch in middleware DB (`attendance.db` outbox → sent) | ☐ |
| Punch in K95 `AttendanceLog` on dev VPS | ☐ |
| Idempotency: same punch not duplicated | ☐ |

---

## Phase 4 — Update details from ERP web app

1. Edit employee in **HREmployees**.
2. Change: name, phone, department, designation.
3. Save → auto-push should run.
4. **⋮ → Read from device** — confirm name/card on machine (may lag SDK read-back).

| Step | Pass |
|------|------|
| ERP record updated | ☐ |
| Push to device succeeded | ☐ |
| Read-from-device returns user | ☐ |

---

## Phase 5 — Import all employees from device

1. As **admin**, click **Import V8 from device** (toolbar).
2. Wait for completion toast.
3. Verify machine users appear in employee list with `device_sync_status: On device`.

| Step | Pass |
|------|------|
| Import completes without error | ☐ |
| Known machine users in ERP | ☐ |
| Enroll_no matches machine user ID | ☐ |

---

## Phase 6 — Disable / enable from web app

1. **⋮ → Disable on device** for `UAT88002`.
2. Try punch on T501 — should **fail** (card/finger blocked).
3. **⋮ → Enable on device**.
4. Punch again — should **succeed**.

| Step | Pass |
|------|------|
| Disable blocks punch | ☐ |
| ERP chip shows **Disabled on device** | ☐ |
| Enable restores punch | ☐ |
| ERP chip shows **On device** | ☐ |

---

## Phase 7 — Remove / resign / cleanup

1. **⋮ → Remove from device** — user deleted from T501.
2. Confirm read-from-device shows not on machine.
3. Optional resign flow: set resignation date, inactive — confirm disable + remove.
4. Delete or archive test employee in ERP if policy allows.

| Step | Pass |
|------|------|
| Remove from device OK | ☐ |
| Punch fails after remove | ☐ |
| ERP employee record retained (resign = no delete) | ☐ |

---

## Sign-off

| Role | Name | Date | Result |
|------|------|------|--------|
| HR | | | |
| IT / Middleware | | | |

**Notes:**

- SDK `ReadAllUserID` may still show `enabled: true` after disable — trust **punch blocked** as truth.
- IN/OUT direction is computed in K95, not middleware.
- For issues: check middleware `var/worker/health.json`, K95 backend logs, tunnel status on Branch V8.
