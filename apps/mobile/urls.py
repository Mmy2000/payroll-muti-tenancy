"""`/api/v1/`: the mobile app's paths, exactly PayRole's (no trailing slash)."""

from django.urls import path

from . import views

urlpatterns = [
    path("auth/login", views.LoginView.as_view(), name="api_login"),
    path("auth/refresh", views.RefreshView.as_view(), name="api_refresh"),
    path("auth/verify", views.VerifyView.as_view(), name="api_verify"),
    path("auth/change-password", views.ChangePasswordView.as_view(),
         name="api_change_password"),
    path("me", views.MeView.as_view(), name="api_me"),
    path("config", views.ConfigView.as_view(), name="api_config"),
    path("profile", views.ProfileView.as_view(), name="api_profile"),
    path("biometric/enroll", views.EnrollView.as_view(), name="api_biometric_enroll"),
    path("biometric/revoke", views.RevokeView.as_view(), name="api_biometric_revoke"),
    path("biometric/status", views.BiometricStatusView.as_view(), name="api_biometric_status"),
    path("attendance/punch", views.PunchView.as_view(), name="api_punch"),
    path("attendance/today", views.TodayView.as_view(), name="api_today"),
    path("attendance/history", views.HistoryView.as_view(), name="api_history"),
    path("leaves", views.LeavesView.as_view(), name="api_leaves"),
    path("leaves/balance", views.LeaveBalanceView.as_view(), name="api_leave_balance"),
    path("leaves/<int:ser>", views.LeaveDetailView.as_view(), name="api_leave_detail"),
    path("notifications", views.NotificationsView.as_view(), name="api_notifications"),
    path("notifications/read", views.NotificationsReadView.as_view(),
         name="api_notifications_read"),
    path("track/batch", views.TrackBatchView.as_view(), name="api_track_batch"),
    path("track/stop", views.TrackStopView.as_view(), name="api_track_stop"),
    path("monitor/live", views.MonitorLiveView.as_view(), name="api_monitor_live"),
    path("monitor/sessions", views.MonitorSessionsView.as_view(), name="api_monitor_sessions"),
    path("monitor/sessions/<int:session_id>", views.MonitorSessionView.as_view(),
         name="api_monitor_session"),
]
