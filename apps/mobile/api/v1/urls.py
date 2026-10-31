"""`/api/v1/`: the mobile app's paths, exactly PayRole's (no trailing slash)."""

from django.urls import path

from .views import attendance, auth, biometrics, leaves, monitor, notifications, profile, tracking

urlpatterns = [
    path("auth/login", auth.LoginView.as_view(), name="api_login"),
    path("auth/qr", auth.QrLoginView.as_view(), name="api_qr_login"),
    path("auth/refresh", auth.RefreshView.as_view(), name="api_refresh"),
    path("auth/verify", auth.VerifyView.as_view(), name="api_verify"),
    path("auth/change-password", auth.ChangePasswordView.as_view(),
         name="api_change_password"),
    path("me", profile.MeView.as_view(), name="api_me"),
    path("config", profile.ConfigView.as_view(), name="api_config"),
    path("profile", profile.ProfileView.as_view(), name="api_profile"),
    path("biometric/enroll", biometrics.EnrollView.as_view(), name="api_biometric_enroll"),
    path("biometric/revoke", biometrics.RevokeView.as_view(), name="api_biometric_revoke"),
    path("biometric/status", biometrics.BiometricStatusView.as_view(), name="api_biometric_status"),
    path("attendance/punch", attendance.PunchView.as_view(), name="api_punch"),
    path("attendance/today", attendance.TodayView.as_view(), name="api_today"),
    path("attendance/history", attendance.HistoryView.as_view(), name="api_history"),
    path("leaves", leaves.LeavesView.as_view(), name="api_leaves"),
    path("leaves/balance", leaves.LeaveBalanceView.as_view(), name="api_leave_balance"),
    path("leaves/<int:ser>", leaves.LeaveDetailView.as_view(), name="api_leave_detail"),
    path("notifications", notifications.NotificationsView.as_view(), name="api_notifications"),
    path("notifications/read", notifications.NotificationsReadView.as_view(),
         name="api_notifications_read"),
    path("track/batch", tracking.TrackBatchView.as_view(), name="api_track_batch"),
    path("track/stop", tracking.TrackStopView.as_view(), name="api_track_stop"),
    path("monitor/live", monitor.MonitorLiveView.as_view(), name="api_monitor_live"),
    path("monitor/sessions", monitor.MonitorSessionsView.as_view(), name="api_monitor_sessions"),
    path("monitor/sessions/<int:session_id>", monitor.MonitorSessionView.as_view(),
         name="api_monitor_session"),
]
