"""The fixed parts of the mobile app's contract (docs/mobile-api.md): its messages, its error
shape and its formats. The messages are the app's words, Arabic, whatever the request's
language: the app shows them as they are."""

from __future__ import annotations

from decimal import Decimal

from django.utils import timezone

# code → (message, HTTP status). The status of `no_employee` depends on the endpoint.
MESSAGES = {
    "no_employee": "لا يوجد ملف موظف مرتبط بهذا المستخدم",
    "biometric_not_enrolled": "لم تُسجَّل بصمتك على هذا الجهاز بعد",
    "biometric_required": "تسجيل الحضور يتطلب التحقق بالبصمة",
    "biometric_revoked": "هذا الجهاز لم يعد مسجَّلاً — تم تسجيل بصمتك على جهاز آخر",
    "biometric_device_mismatch": "الجهاز لا يطابق الجهاز المسجَّل",
    "biometric_stale": "توقيت الجهاز غير مضبوط — اضبط ساعة الهاتف تلقائياً وأعد المحاولة",
    "biometric_invalid": "تعذّر التحقق من البصمة",
    "biometric_replay": "طلب مكرر",
    "tracking_required": "لا يمكن تسجيل الحضور قبل السماح بالموقع «طوال الوقت» من إعدادات الهاتف",
    "no_check_in": "لا يمكن تسجيل الانصراف قبل تسجيل الحضور",
    "outside_geofence": "أنت خارج نطاق الفرع",
    "location_required": "تعذّر تحديد موقعك — فعّل الموقع وأعد المحاولة",
    "insufficient_balance": "رصيد الإجازات لا يكفى — المتبقى {left} يوم والمطلوب {days} يوم",
    "not_found": "طلب الإجازة غير موجود",
    "already_accepted": "لا يمكن حذف إجازة معتمدة",
    "no_leave_type": "لا يوجد نوع إجازة سنوية",
    "wrong_password": "كلمة المرور الحالية غير صحيحة",
    "same_password": "كلمة المرور الجديدة مطابقة للحالية",
    "weak_password": "كلمة المرور ضعيفة",
    "nothing_to_update": "لا توجد بيانات للتحديث",
    "image_too_large": "حجم الصورة أكبر من 5 ميجابايت",
    "no_active_session": "لا توجد جلسة تتبّع مفتوحة",
    "session_closed": "الجلسة مغلقة",
    "session_not_found": "الجلسة غير موجودة أو خارج صلاحيتك",
}
STATUS = {"biometric_replay": 409, "duplicate": 409, "no_active_session": 409,
          "session_closed": 409, "not_found": 404, "session_not_found": 404}
BIOMETRIC_403 = {"biometric_not_enrolled", "biometric_required", "biometric_revoked",
                 "biometric_device_mismatch", "biometric_stale", "biometric_invalid"}

PASSWORDS_DIFFER = "كلمتا المرور غير متطابقتين"
PASSWORD_CHANGED = "تم تغيير كلمة المرور"
LEAVE_ENDS_FIRST = "تاريخ نهاية الإجازة قبل تاريخ بدايتها"
TOO_MANY_POINTS = "الحد الأقصى 500 نقطة فى الدفعة الواحدة"
BAD_PHONE = "رقم هاتف غير صالح"
MONITOR_ONLY = "متابعة المسارات متاحة للمشرف العام فقط"
WEAK = {"too common": "كلمة المرور شائعة جداً", "entirely numeric": "كلمة المرور أرقام فقط",
        "too short": "كلمة المرور قصيرة جداً", "too similar": "كلمة المرور تشبه بياناتك الشخصية"}
STATUS_TEXT = {0: "حضور", 1: "انصراف"}
LEAVE_TEXT = {True: "معتمدة", False: "بانتظار الاعتماد"}
END_REASON_TEXT = {"checkout": "انصراف", "timeout": "إيقاف تلقائى", "manual": "إيقاف يدوى"}


class AppError(Exception):
    """A refusal in the app's shape: {"detail", "code"} (plus `extra` keys)."""

    def __init__(self, code: str, *, status: int | None = None, detail: str = "",
                 **extra):
        super().__init__(code)
        self.code = code
        self.detail = detail or MESSAGES.get(code, code)
        self.status = status or (403 if code in BIOMETRIC_403 else STATUS.get(code, 400))
        self.extra = extra


def duplicate(direction: int, at) -> AppError:
    word = "حضور" if direction == 0 else "انصراف"
    return AppError("duplicate", detail=f"يوجد تسجيل {word} بالفعل اليوم الساعة "
                                        f"{timezone.localtime(at):%H:%M}")


# --- formats -----------------------------------------------------------------------------------


def moment(value):
    """A datetime as the app reads it: the client's local time, ISO, no offset."""
    return timezone.localtime(value).replace(tzinfo=None).isoformat() if value else None


def day(value):
    return value.isoformat() if value else None


def decimal(value, places: int = 2):
    """Decimals are strings ("30.044400"), as DRF wrote them."""
    if value is None:
        return None
    return str(Decimal(value).quantize(Decimal(1).scaleb(-places)))
