from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone


class Course(models.Model):
    """
    A dance course that students can join.
    """

    # Default avoids interactive prompts when migrating an existing DB.
    # (Old rows will temporarily get the same default name.)
    name = models.CharField(max_length=100, default="Course")
    description = models.TextField(blank=True)
    duration = models.CharField(max_length=50, blank=True)
    fee = models.DecimalField(max_digits=10, decimal_places=0, default=1000)
    is_active = models.BooleanField(default=True)
    image = models.ImageField(upload_to="course_images/", blank=True, null=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Timetable(models.Model):
    """
    Schedule entry for a course.
    """

    MODE_ONLINE = "Online"
    MODE_OFFLINE = "Offline"
    MODE_CHOICES = [
        (MODE_ONLINE, "Online"),
        (MODE_OFFLINE, "Offline"),
    ]

    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="timetables")
    day = models.CharField(max_length=20)
    time = models.CharField(max_length=50)
    mode = models.CharField(max_length=10, choices=MODE_CHOICES)

    class Meta:
        ordering = ["course__name", "day", "time"]
        unique_together = ("course", "day", "time", "mode")

    def __str__(self) -> str:
        return f"{self.course.name} - {self.day} {self.time} ({self.mode})"


class Instructor(models.Model):
    """
    Instructor information displayed in the dashboard.
    """

    name = models.CharField(max_length=200)
    specialization = models.TextField(blank=True)
    experience = models.CharField(max_length=100, blank=True)
    about = models.TextField(blank=True)

    education_details = models.TextField(blank=True)
    performance_details = models.TextField(blank=True)
    teaching_details = models.TextField(blank=True)

    contact_phone = models.CharField(max_length=20, blank=True)
    contact_email = models.EmailField(blank=True)
    location = models.CharField(max_length=120, blank=True)
    image = models.ImageField(upload_to="instructor_images/", blank=True, null=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class UserProfile(models.Model):
    """
    Student profile + their selected course & timetable.
    """

    user = models.OneToOneField(User, on_delete=models.CASCADE)
    age = models.IntegerField()
    phone = models.CharField(max_length=15)
    address = models.TextField(blank=True, default="")
    profile_image = models.ImageField(upload_to="profile_images/", blank=True, null=True)

    selected_course = models.ForeignKey(
        Course,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="selected_by_students",
    )
    selected_timetable = models.ForeignKey(
        Timetable,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="selected_by_students",
    )

    admission_fee_paid = models.BooleanField(default=False)
    payment_id = models.CharField(max_length=100, blank=True, null=True)

    class Meta:
        ordering = ["user__username"]

    def __str__(self) -> str:
        return f"Profile({self.user.username})"


class GalleryImage(models.Model):
    """
    Gallery images uploaded by admin and shown to students.
    """

    title = models.CharField(max_length=200)
    image = models.ImageField(upload_to="gallery_images/", blank=True, null=True)
    description = models.TextField(blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    uploaded_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="gallery_images"
    )

    class Meta:
        ordering = ["-uploaded_at"]

    def __str__(self) -> str:
        return self.title


class Booking(models.Model):
    """
    Stores booking/payment details for a student after they complete payment.
    """

    PAYMENT_PENDING = "Pending"
    PAYMENT_PAID = "Paid"

    PAYMENT_STATUS_CHOICES = [
        (PAYMENT_PENDING, "Pending"),
        (PAYMENT_PAID, "Paid"),
    ]

    STATUS_ACTIVE = "Active"
    STATUS_CANCELLED = "Cancelled"

    BOOKING_STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    profile = models.OneToOneField(
        UserProfile, on_delete=models.CASCADE, related_name="booking"
    )
    course = models.ForeignKey(Course, on_delete=models.CASCADE)
    timetable = models.ForeignKey(Timetable, on_delete=models.CASCADE)
    booking_date = models.DateTimeField(auto_now_add=True)

    payment_status = models.CharField(
        max_length=20,
        choices=PAYMENT_STATUS_CHOICES,
        default=PAYMENT_PENDING,
    )
    payment_id = models.CharField(max_length=100, blank=True, null=True)
    status = models.CharField(
        max_length=20,
        choices=BOOKING_STATUS_CHOICES,
        default=STATUS_ACTIVE,
    )

    class Meta:
        ordering = ["-booking_date"]

    def __str__(self) -> str:
        return f"Booking({self.profile.user.username}) - {self.course.name}"


class Program(models.Model):
    """
    Upcoming academy programs (events/workshops) shown in Timetable section.
    """

    title = models.CharField(max_length=200)
    course = models.ForeignKey(
        Course,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="programs",
        help_text="Optional: link program to a specific course.",
    )
    starts_at = models.DateTimeField(default=timezone.now)
    description = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["starts_at", "title"]

    def __str__(self) -> str:
        return self.title


class OnlineClass(models.Model):
    """
    Admin-created online class for a course.
    Students select the course during admission; eligible students can join here.
    """

    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="online_classes")
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    scheduled_at = models.DateTimeField(default=timezone.now)
    meeting_url = models.URLField(help_text="URL students can open to join the class.")
    reminder_offset_minutes = models.PositiveIntegerField(default=60)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_online_classes"
    )

    class Meta:
        ordering = ["scheduled_at", "title"]

    def __str__(self) -> str:
        return f"{self.title} ({self.course.name})"


class MonthlyFeePayment(models.Model):
    """
    Per-student monthly fee payments.
    Month format: YYYY-MM (e.g. 2026-03).
    """

    profile = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name="monthly_fee_payments")
    course = models.ForeignKey(
        Course,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="monthly_fee_payments",
    )
    month = models.CharField(max_length=7)  # YYYY-MM
    amount = models.DecimalField(max_digits=10, decimal_places=0, default=0)
    payment_id = models.CharField(max_length=100, blank=True, null=True)
    paid_at = models.DateTimeField(default=timezone.now)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-paid_at"]
        unique_together = ("profile", "month")

    def __str__(self) -> str:
        return f"{self.profile.user.username} - {self.month}"


class Notification(models.Model):
    """
    Notifications and reminders for online classes, programs, and fee payments.
    """

    NOTIF_ONLINE_CLASS = "online_class"
    NOTIF_PROGRAM = "program"
    NOTIF_FEE_DUE = "fee_due"
    NOTIF_FEE_PAID = "fee_paid"

    NOTIFICATION_TYPE_CHOICES = [
        (NOTIF_ONLINE_CLASS, "Online Class Reminder"),
        (NOTIF_PROGRAM, "Program Reminder"),
        (NOTIF_FEE_DUE, "Monthly Fee Reminder"),
        (NOTIF_FEE_PAID, "Monthly Fee Paid Confirmation"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notifications")
    notification_type = models.CharField(max_length=30, choices=NOTIFICATION_TYPE_CHOICES)
    message = models.TextField()

    due_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)

    # Optional relations for de-duplication and context.
    online_class = models.ForeignKey(
        OnlineClass, on_delete=models.CASCADE, null=True, blank=True, related_name="notifications"
    )
    program = models.ForeignKey(
        Program, on_delete=models.CASCADE, null=True, blank=True, related_name="notifications"
    )
    fee_payment = models.ForeignKey(
        MonthlyFeePayment, on_delete=models.CASCADE, null=True, blank=True, related_name="notifications"
    )
    month = models.CharField(max_length=7, null=True, blank=True)  # For fee reminders/paid

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Notification({self.user.username}, {self.notification_type})"


class FeedbackSubmission(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="feedback_submissions")
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Feedback({self.user.username})"


class ContactSubmission(models.Model):
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="contact_submissions")
    name = models.CharField(max_length=200, blank=True, default="")
    email = models.EmailField(blank=True, default="")
    phone = models.CharField(max_length=20, blank=True, default="")
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Contact({self.name or 'Anonymous'})"


class ContactInfo(models.Model):
    """
    Global contact information shown on the student Contact Us page.
    Admin can edit this record.
    """

    phone = models.CharField(max_length=20, blank=True, default="")
    email = models.EmailField(blank=True, default="")
    address = models.TextField(blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return self.email or self.phone or "Contact Info"