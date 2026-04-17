from django.contrib import admin

from .models import (
    Booking,
    ContactSubmission,
    ContactInfo,
    Course,
    FeedbackSubmission,
    GalleryImage,
    Instructor,
    MonthlyFeePayment,
    Notification,
    OnlineClass,
    Program,
    Timetable,
    UserProfile,
)


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ("name", "duration", "fee", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "description")


@admin.register(Timetable)
class TimetableAdmin(admin.ModelAdmin):
    list_display = ("course", "day", "time", "mode")
    list_filter = ("mode", "day", "course")
    search_fields = ("course__name", "day", "time")


@admin.register(Instructor)
class InstructorAdmin(admin.ModelAdmin):
    list_display = ("name", "experience")
    search_fields = ("name", "specialization", "about")


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "age",
        "phone",
        "selected_course",
        "admission_fee_paid",
        "payment_id",
    )
    list_filter = ("admission_fee_paid", "selected_course")
    search_fields = ("user__username", "phone", "payment_id")


@admin.register(GalleryImage)
class GalleryImageAdmin(admin.ModelAdmin):
    list_display = ("title", "uploaded_at", "uploaded_by")
    list_filter = ("uploaded_at",)
    search_fields = ("title", "description")


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = (
        "profile",
        "course",
        "timetable",
        "booking_date",
        "payment_status",
        "status",
        "payment_id",
    )
    list_filter = ("payment_status", "status", "booking_date")
    search_fields = ("profile__user__username", "payment_id", "course__name")


@admin.register(Program)
class ProgramAdmin(admin.ModelAdmin):
    list_display = ("title", "course", "starts_at")
    list_filter = ("starts_at", "course")
    search_fields = ("title", "description")


@admin.register(OnlineClass)
class OnlineClassAdmin(admin.ModelAdmin):
    list_display = ("title", "course", "scheduled_at", "is_active")
    list_filter = ("scheduled_at", "is_active", "course")
    search_fields = ("title", "meeting_url", "description")


@admin.register(MonthlyFeePayment)
class MonthlyFeePaymentAdmin(admin.ModelAdmin):
    list_display = ("profile", "course", "month", "amount", "paid_at")
    list_filter = ("month", "paid_at", "course")
    search_fields = ("profile__user__username", "payment_id")


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("user", "notification_type", "due_at", "is_read")
    list_filter = ("notification_type", "is_read", "due_at")
    search_fields = ("user__username", "message", "month")


@admin.register(FeedbackSubmission)
class FeedbackSubmissionAdmin(admin.ModelAdmin):
    list_display = ("user", "created_at")
    search_fields = ("user__username", "message")


@admin.register(ContactSubmission)
class ContactSubmissionAdmin(admin.ModelAdmin):
    list_display = ("name", "email", "created_at")
    search_fields = ("name", "email", "phone", "message")


@admin.register(ContactInfo)
class ContactInfoAdmin(admin.ModelAdmin):
    list_display = ("phone", "email", "updated_at")
    search_fields = ("phone", "email", "address")