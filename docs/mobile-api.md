# The mobile app's API (`/api/v1/`): the contract kept from PayRole

The existing mobile app must keep working without an update, so this API answers exactly as
PayRole's did (`PayRole/Api/`, DRF 3.15 + simplejwt 5.5). This file is that contract, taken from
PayRole's code (there was no other documentation); `apps/mobile/tests/` checks it.

**What is different on purpose** (compatible with the app):

- Multi-tenant: the app talks to its client's own address (`https://<client>.<domain>/api/v1/`);
  the client comes from the host, as for every request. A token of one client is refused on
  another's host.
- Night shifts: a check-out after midnight belongs to the work day it started (PayRole refused
  it with `no_check_in`). The day is the work day of the schedule, as on the screens.
- Punches from the app are clock punches (source "mobile"), judged by the same rules as the
  device's; nothing is deleted (PayRole deleted the device's rows of the day).
- Switches (biometric, tracking, geofence) are the client's features, not server settings.
- Leave and its balance follow this system's leave rules (types, working days, approval).

## Conventions

- Paths have **no trailing slash** (`/api/v1/me`; `/api/v1/me/` is a 404).
- Auth: `Authorization: Bearer <access>` (JWT HS256, claims `token_type`, `exp`, `iat`, `jti`,
  `user_id`). Access 8 hours, refresh 30 days, rotated on refresh.
- JSON responses, Arabic messages unescaped. Accept-Language is ignored.
- Datetimes: local time of the client, ISO **without offset**: `2026-10-29T09:15:03` (with
  `.ffffff` when there are microseconds). Dates `YYYY-MM-DD`. Decimals are **strings**
  (`"30.044400"`), null as `null`.
- Business errors: `{"detail": "<Arabic>", "code": "<code>"}`. Field errors: DRF's shape
  (`{"field": ["msg"]}`, `{"non_field_errors": [...]}`, nested for objects and lists), English
  DRF messages ("This field is required." …).
- Standard auth errors (401): no header → `{"detail":"Authentication credentials were not
  provided."}` (+ `WWW-Authenticate: Bearer realm="api"`); bad token →
  `{"detail":"Given token not valid for any token type","code":"token_not_valid","messages":[
  {"token_class":"AccessToken","token_type":"access","message":"Token is expired"}]}`
  (message "Token is expired" / "Token is invalid" / "Token has wrong type"); user inactive →
  `{"detail":"User is inactive","code":"user_inactive"}`; not found →
  `{"detail":"User not found","code":"user_not_found"}`. Wrong method: 405.
- The signed-in user → employee: the member's linked employee, still employed (an app login
  given on the employee's page, or an existing user linked on their user form, as PayRole's
  `Users.emp`; apps/mobile/access.py); none →
  `no_employee` (`"لا يوجد ملف موظف مرتبط بهذا المستخدم"`): **404** everywhere except
  `attendance/punch` and `DELETE leaves/<ser>` (**400**); `login` and `me` for a superuser give
  `employee: null`.

## Objects

- **Employee**: `{"eco":int,"name":str,"branch_code":int|null,"branch_name":str|null,
  "group":str|null,"photo":absolute URL|null,"day_off":str|null}` (code, name, branch code and
  name, department, photo, days off).
- **Attendance**: `{"id":int,"date":"YYYY-MM-DD","timestamp":ISO,"status":0|1,
  "status_text":"حضور"|"انصراف","latitude":"30.044400"|null,"longitude":…|null}`.
- **TrackSession**: `{"id","started_at","ended_at"|null,"is_active":bool,
  "end_reason":"checkout"|"timeout"|"manual"|null,"points_count":int,
  "total_distance_m":"0.00","duration_minutes":int}`.
- **MonitorSession**: TrackSession + `end_reason_text` ("انصراف" / "إيقاف تلقائى" /
  "إيقاف يدوى" / null), `app_version`, `branch_name`, `employee` (`{"eco","name","photo"}`), in
  the order id, started_at, ended_at, is_active, end_reason, end_reason_text, points_count,
  total_distance_m, duration_minutes, app_version, branch_name, employee.
- **Leave**: `{"ser":int,"date":"YYYY-MM-DD","date1":…|null,"date2":…|null,"days":int|null,
  "acept":bool,"status_text":"معتمدة"|"بانتظار الاعتماد"}`.

## Signing in by QR

Additive: nothing PayRole's app calls has changed. A manager gives an employee a QR from their
page. It reads `payroll://link?url=<the client's address>&code=<one-time code>`: never a password
or a token. The app sends the code to `<url>/api/v1/auth/qr` and gets what `auth/login` gives. A
code works once, for the minutes set on the company page (15 by default, a week at most), and
only its SHA-256 is stored.

`auth/login` and `auth/qr` take an optional `device_id`. A sign-in that names its phone gets
tokens with a `did` claim, and signing that phone out (from the employee's page) answers 401 at
once on every request and refresh. Tokens without the claim work as they always did.

## Endpoints

| Path | Method | Auth | Success |
|---|---|---|---|
| `auth/login` | POST `{username,password}` | none | 200 `{refresh,access,username,role,is_superuser,employee}` |
| `auth/qr` | POST `{code,device_id?}` (new, additive) | none | 200, as `auth/login`. 400 `qr_invalid`, `qr_expired`, `qr_used`; 429 `qr_locked` |
| `auth/refresh` | POST `{refresh}` | none | 200 `{access,refresh}` |
| `auth/verify` | POST `{token}` | none | 200 `{}` |
| `auth/change-password` | POST `{current_password,new_password(≥8),confirm_password}` | JWT | 200 `{"detail":"تم تغيير كلمة المرور",access,refresh}` |
| `me` | GET | JWT | 200 `{username,is_superuser,employee,leave_balance,today,active_session,notifications_unread}` |
| `config` | GET | JWT | 200 `{track_interval_seconds,track_distance_filter_m,track_batch_size,track_max_session_hours,track_retention_days,enforce_geofence,tracking_required,biometric_required}` |
| `profile` | GET, PATCH `{tel?,add?,image_base64? / image file}` | JWT | 200 profile |
| `biometric/enroll` | POST `{device_id,app_version?}` | JWT | 201 `{enrollment_id,secret,device_id,enrolled_at}` |
| `biometric/revoke` | POST | JWT | 204 |
| `biometric/status` | GET | JWT | 200 `{enrolled,enrollment_id,device_id,enrolled_at}` |
| `attendance/punch` | POST | JWT | 201 `{attendance,session,tracking}` |
| `attendance/today` | GET | JWT | 200 `{date,check_in,check_out,records,tracking,session}` |
| `attendance/history` | GET `?from&to` | JWT | 200 `[Attendance]` (≤500, newest first) |
| `leaves` | GET `?year`, POST `{date?,date1,date2,days}` | JWT | 200 `[Leave]` / 201 Leave; POST 403 `leave_off` while the client's Leave feature is off |
| `leaves/<ser>` | DELETE | JWT | 204 |
| `leaves/balance` | GET `?year` | JWT | 200 `{year,allowed,used,remaining}` |
| `notifications` | GET `?unread=1&before=<id>` | JWT | 200 `{unread,items:[{id,kind,title,body,read,created_at}],has_more}` (30 a page) |
| `notifications/read` | POST `{ids?}` | JWT | 200 `{marked,unread}` (no ids: all) |
| `track/batch` | POST `{session_id?,points:[…≤500]}` | JWT | 200 `{saved,received,session,tracking:true}` |
| `track/stop` | POST | JWT | 200 `{session,tracking:false}` |
| `monitor/live` | GET | superuser | 200 `{interval_seconds,rows:[{session,position,silent_minutes}]}` |
| `monitor/sessions` | GET `?key&from&to&active&page` | superuser | 200 `{page,pages,has_next,totals,results}` (20 a page) |
| `monitor/sessions/<id>` | GET | superuser | 200 `{session,route,endpoints,mock_count,retention_days}` |

### Login

200 body, keys in this order: `refresh`, `access`, `username`, `role` (`"employee"`,
`"owner"`, `"staff"`, `"superuser"` or null), `is_superuser`, `employee` (Employee or null).
Wrong password, unknown or inactive user, or too many attempts (5 per address and username in 15
minutes): 401 `{"detail":"No active account found with the given credentials"}`. Missing fields:
400 `{"username":["This field is required."], …}`. Usernames match case-insensitively.

### Refresh / verify

Refresh: 401 `{"detail":"Token is invalid","code":"token_not_valid"}` (or "Token is expired",
"Token has wrong type"); inactive user: 401 `{"detail":"No active account found for the given
token."}`. Verify: 200 `{}` or the same 401.

### Change password

400 `{"non_field_errors":["كلمتا المرور غير متطابقتين"]}` when they differ; 400
`{"detail","code"}` with `"كلمة المرور الحالية غير صحيحة"`/`wrong_password`,
`"كلمة المرور الجديدة مطابقة للحالية"`/`same_password`, `weak_password` with the validators'
messages: "too common" → `كلمة المرور شائعة جداً`, "entirely numeric" → `كلمة المرور أرقام فقط`,
"too short" → `كلمة المرور قصيرة جداً`, "too similar" → `كلمة المرور تشبه بياناتك الشخصية`,
joined with `" · "`, else `"كلمة المرور ضعيفة"`.

### Me

`leave_balance`: `{"year","allowed","used","remaining"}` (ints); `today`: today's Attendance
(oldest first); `active_session`: TrackSession or null (sessions over the maximum hours are
closed first); `notifications_unread`: int.

### Profile

GET/PATCH 200: `{"tel","add","photo","eco","name","branch_name","group","job_title",
"hire_date","birth_date","national_id","day_off","annual_leave"}`; `national_id` masked
(`'*' * (n-4)` + last 4), null if not digits. PATCH: `tel` (`^\+?\d{7,15}$` after removing
spaces, else `{"tel":["رقم هاتف غير صالح"]}`; `01…` → `+201…`; no `+` → `+` added), `add`
(≤100), `image_base64` (`data:image/<jpg|jpeg|png|webp>;base64,…` or bare base64: errors
`"صيغة صورة غير مدعومة"`, `"تعذّر قراءة الصورة"`, `"الصورة فارغة"`,
`"حجم الصورة أكبر من 5 ميجابايت"` under `image_base64`), or a multipart `image` (over 5 MiB:
400 `{"detail":"حجم الصورة أكبر من 5 ميجابايت","code":"image_too_large"}`). Nothing to change:
400 `{"detail":"لا توجد بيانات للتحديث","code":"nothing_to_update"}`.

### Biometric proof

`enroll` revokes the employee's earlier enrollment (one phone per employee) and returns a
32-byte secret as 64 lowercase hex characters, once. `punch` carries
`biometric: {enrollment_id, timestamp, nonce, proof}` with
`proof = hex(HMAC-SHA256(key=bytes.fromhex(secret),
msg=f"{enrollment_id}|{device_id}|{status}|{timestamp}|{nonce}"))`, `timestamp` local
`YYYY-MM-DDTHH:MM:SS` (or with a space) within ±120 s of the server; each nonce once (kept 600
s). Failures:

| Code | HTTP | Message |
|---|---|---|
| `biometric_not_enrolled` | 403 | `لم تُسجَّل بصمتك على هذا الجهاز بعد` |
| `biometric_required` | 403 | `تسجيل الحضور يتطلب التحقق بالبصمة` |
| `biometric_revoked` | 403 | `هذا الجهاز لم يعد مسجَّلاً — تم تسجيل بصمتك على جهاز آخر` |
| `biometric_device_mismatch` | 403 | `الجهاز لا يطابق الجهاز المسجَّل` |
| `biometric_stale` | 403 | `توقيت الجهاز غير مضبوط — اضبط ساعة الهاتف تلقائياً وأعد المحاولة` |
| `biometric_invalid` | 403 | `تعذّر التحقق من البصمة` |
| `biometric_replay` | 409 | `طلب مكرر` |

### Punch

Body: `status` 0|1 (required), `latitude`, `longitude` (9,6), `accuracy_m` (8,2), `device_id`,
`app_version`, `tracking_enabled` (bool), `biometric`. Checks in order: fields; employee (400);
biometric (when required, check-in and check-out); tracking (check-in only, when required:
400 `"لا يمكن تسجيل الحضور قبل السماح بالموقع «طوال الوقت» من إعدادات الهاتف"`/
`tracking_required`); duplicate of the same status on the work day: 409
`"يوجد تسجيل حضور بالفعل اليوم الساعة HH:MM"` (`انصراف` for a check-out)/`duplicate`;
check-out without check-in: 400 `"لا يمكن تسجيل الانصراف قبل تسجيل الحضور"`/`no_check_in`.
A check-in opens a tracking session (closing any open one as `timeout`); a check-out closes it
as `checkout`. Geofence (when on): outside the branch's radius → 400
`"أنت خارج نطاق الفرع"`/`outside_geofence` (new: PayRole never checked).

### Leaves

POST: `date2 < date1` → 400 `{"non_field_errors":["تاريخ نهاية الإجازة قبل تاريخ بدايتها"]}`;
not enough balance → 400 `"رصيد الإجازات لا يكفى — المتبقى {n} يوم والمطلوب {days} يوم"`/
`insufficient_balance`. DELETE: 404 `"طلب الإجازة غير موجود"`/`not_found`; approved: 400
`"لا يمكن حذف إجازة معتمدة"`/`already_accepted`. `ser` is the request's number.

### Tracking

Points: `latitude`, `longitude` (required, 9,6), `accuracy_m`, `speed`, `heading`, `battery`,
`recorded_at` (required), `is_mock`. More than 500: `{"points":["الحد الأقصى 500 نقطة فى الدفعة
الواحدة"]}`. No open session: 409 `{"detail":"لا توجد جلسة تتبّع مفتوحة",
"code":"no_active_session","tracking":false}`; closed: 409 `{"detail":"الجلسة مغلقة",
"code":"session_closed","tracking":false}`. Points already stored at the same time are skipped;
distance is the haversine sum (R = 6,371,000 m) in time order.

### Monitor

Others than a superuser (here: a member with `mobile.monitor.view`): 403
`{"detail":"متابعة المسارات متاحة للمشرف العام فقط"}`. Unknown session: 404
`{"detail":"الجلسة غير موجودة أو خارج صلاحيتك","code":"not_found"}`.
