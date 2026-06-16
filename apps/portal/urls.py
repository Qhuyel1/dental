from django.urls import path

from . import views

app_name = "portal"

urlpatterns = [
    path("login/", views.PortalLoginView.as_view(), name="login"),
    path("logout/", views.PortalLogoutView.as_view(), name="logout"),
    path("", views.PortalHomeView.as_view(), name="home"),
    path("profile/", views.PortalProfileView.as_view(), name="profile"),
    path("appointments/", views.PortalAppointmentListView.as_view(), name="appointments"),
    path("invoices/", views.PortalInvoiceListView.as_view(), name="invoices"),
    path("prescriptions/", views.PortalPrescriptionListView.as_view(), name="prescriptions"),
    # Tin nhắn hỗ trợ
    path("messages/", views.PortalConversationListView.as_view(), name="messages-list"),
    path("messages/create/", views.PortalConversationCreateView.as_view(), name="messages-create"),
    path("messages/<int:pk>/", views.PortalConversationDetailView.as_view(), name="messages-detail"),
    path("messages/<int:pk>/send/", views.PortalMessageSendView.as_view(), name="messages-send"),
    path("messages/<int:pk>/poll/", views.PortalMessagePollView.as_view(), name="messages-poll"),
    path("messages/<int:pk>/close/", views.PortalConversationCloseView.as_view(), name="messages-close"),
]
