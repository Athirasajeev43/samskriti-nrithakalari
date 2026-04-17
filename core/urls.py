from django.urls import path
from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("register/", views.register, name="register"),
    path("login/", views.login_view, name="login"),
    path("admin-login/", views.admin_login_view, name="admin_login"),

    path("dashboard/", views.dashboard, name="dashboard"),
    path("dashboard/course-details/", views.dashboard_course_details, name="dashboard_course_details"),
    path("dashboard/timetable/", views.dashboard_timetable, name="dashboard_timetable"),
    path("dashboard/instructors/", views.instructors, name="instructors"),

    path("admin-dashboard/", views.admin_dashboard, name="admin_dashboard"),

    # Custom admin-panel pages (no Django-inbuild admin pages)
    path("admin-panel/profile/", views.admin_profile, name="admin_profile"),
    path("admin-panel/courses/", views.admin_courses, name="admin_courses"),
    path("admin-panel/courses/add/", views.admin_course_add, name="admin_course_add"),
    path("admin-panel/courses/<int:pk>/edit/", views.admin_course_edit, name="admin_course_edit"),
    path("admin-panel/courses/<int:pk>/delete/", views.admin_course_delete, name="admin_course_delete"),

    path("admin-panel/timetables/", views.admin_timetables, name="admin_timetables"),
    path("admin-panel/timetables/add/", views.admin_timetable_add, name="admin_timetable_add"),
    path("admin-panel/timetables/<int:pk>/edit/", views.admin_timetable_edit, name="admin_timetable_edit"),
    path("admin-panel/timetables/<int:pk>/delete/", views.admin_timetable_delete, name="admin_timetable_delete"),

    path("admin-panel/instructors/", views.admin_instructors, name="admin_instructors"),
    path("admin-panel/instructors/add/", views.admin_instructor_add, name="admin_instructor_add"),
    path("admin-panel/instructors/<int:pk>/edit/", views.admin_instructor_edit, name="admin_instructor_edit"),
    path("admin-panel/instructors/<int:pk>/delete/", views.admin_instructor_delete, name="admin_instructor_delete"),

    path("admin-panel/gallery/", views.admin_gallery_images, name="admin_gallery_images"),
    path("admin-panel/gallery/add/", views.admin_gallery_image_add, name="admin_gallery_image_add"),
    path("admin-panel/gallery/<int:pk>/edit/", views.admin_gallery_image_edit, name="admin_gallery_image_edit"),
    path("admin-panel/gallery/<int:pk>/delete/", views.admin_gallery_image_delete, name="admin_gallery_image_delete"),

    path("admin-panel/students/", views.admin_students, name="admin_students"),
    path("admin-panel/payments/", views.admin_payments, name="admin_payments"),
    path("admin-panel/students/<int:pk>/edit/", views.admin_student_edit, name="admin_student_edit"),
    path(
        "admin-panel/students/<int:pk>/course-status/",
        views.admin_student_toggle_course_status,
        name="admin_student_toggle_course_status",
    ),

    path("profile/", views.profile, name="profile"),
    path("gallery/", views.gallery, name="gallery"),

    path("join/", views.join, name="join"),
    path("join/course-selection/", views.course_selection, name="course_selection"),
    path("join/timetable/", views.join_timetable, name="join_timetable"),
    path("join/payment/", views.payment, name="payment"),

    # Student dashboard extras
    path("online-classes/", views.online_classes, name="online_classes"),
    path("monthly-fee/", views.monthly_fee_payment, name="monthly_fee_payment"),
    path("feedback/", views.feedback, name="feedback"),
    path("contact-us/", views.contact_us, name="contact_us"),
    path("notifications/<int:notification_id>/read/", views.mark_notification_read, name="mark_notification_read"),

    path("logout/", views.logout_view, name="logout"),

    # Admin panel: Online classes
    path("admin-panel/online-classes/", views.admin_online_classes, name="admin_online_classes"),
    path("admin-panel/online-classes/add/", views.admin_online_class_add, name="admin_online_class_add"),
    path("admin-panel/online-classes/<int:pk>/edit/", views.admin_online_class_edit, name="admin_online_class_edit"),
    path("admin-panel/online-classes/<int:pk>/delete/", views.admin_online_class_delete, name="admin_online_class_delete"),

    # Admin panel: Programs
    path("admin-panel/programs/", views.admin_programs, name="admin_programs"),
    path("admin-panel/programs/add/", views.admin_program_add, name="admin_program_add"),
    path("admin-panel/programs/<int:pk>/edit/", views.admin_program_edit, name="admin_program_edit"),
    path("admin-panel/programs/<int:pk>/delete/", views.admin_program_delete, name="admin_program_delete"),

    # Admin panel: Monthly fees
    path("admin-panel/monthly-fees/", views.admin_monthly_fees, name="admin_monthly_fees"),

    # Admin panel: Feedback + Contact
    path("admin-panel/feedback/", views.admin_feedback, name="admin_feedback"),
    path(
        "admin-panel/contact-submissions/",
        views.admin_contact_submissions,
        name="admin_contact_submissions",
    ),
    path(
        "admin-panel/contact-info/",
        views.admin_contact_info,
        name="admin_contact_info",
    ),
]