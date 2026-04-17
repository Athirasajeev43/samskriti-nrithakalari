from django.shortcuts import get_object_or_404, redirect, render
from django.contrib import messages
from django.contrib.auth.models import User
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from datetime import timedelta
import datetime
from typing import Optional
from django.db.models import Q

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
from .forms import (
    AdminUserEditForm,
    CourseForm,
    ContactUsForm,
    ContactInfoForm,
    FeedbackForm,
    GalleryImageForm,
    InstructorForm,
    AdminOnlineClassForm,
    UserProfileForm,
    ProgramForm,
    TimetableForm,
)
import uuid


# ----------------------------
# Helpers
# ----------------------------

def is_admin_user(user):
    return bool(user and user.is_authenticated and (user.is_staff or user.is_superuser))


def get_profile_or_redirect(request):
    """
    The refactor introduced stricter models for `UserProfile`.
    Some existing/auth users (e.g. superusers created earlier) may not
    have a profile row. Instead of raising 404, redirect to register.
    """

    profile = UserProfile.objects.filter(user=request.user).first()
    if profile is not None:
        return profile

    # Allow staff/superusers (Django admin users) to still access the app dashboard
    # even if they were created before this refactor introduced `UserProfile`.
    if request.user.is_staff or request.user.is_superuser:
        return UserProfile.objects.create(
            user=request.user,
            date_of_birth=None,
            phone="0000000000",
        )

    messages.error(request, "Please complete registration to access your dashboard.")
    return None


FEE_CYCLE_DAYS = 30


def get_fee_cycle_key_for_user(user, now=None) -> str:
    """
    30-day fee cycle starts from account registration time (`user.date_joined`).
    Returns a stable cycle identifier (as string) used as a key.
    """
    now = now or timezone.now()
    start = getattr(user, "date_joined", None) or now
    if start > now:
        return "0"
    days_elapsed = (now - start).days
    cycle_number = days_elapsed // FEE_CYCLE_DAYS
    return str(cycle_number)


def get_fee_cycle_start_for_user(user, cycle_key: str):
    start = getattr(user, "date_joined", None) or timezone.now()
    cycle_number = int(cycle_key)
    return start + timedelta(days=cycle_number * FEE_CYCLE_DAYS)


def get_fee_cycle_end_for_user(user, cycle_key: str):
    return get_fee_cycle_start_for_user(user, cycle_key) + timedelta(days=FEE_CYCLE_DAYS)


def student_has_paid_admission(profile: UserProfile) -> bool:
    """
    Admission payment gating for joining online classes and for reminder targeting.
    """

    return bool(profile.admission_fee_paid and hasattr(profile, "booking"))


def student_booking_is_paid(profile: UserProfile) -> bool:
    return Booking.objects.filter(
        profile=profile,
        payment_status=Booking.PAYMENT_PAID,
        status=Booking.STATUS_ACTIVE,
    ).exists()


def ensure_fee_due_notification(request, profile: UserProfile, cycle_key: str):
    """
    Create a monthly fee reminder notification if the student hasn't paid yet.
    """
    booking_obj = getattr(profile, "booking", None)
    if booking_obj is not None and booking_obj.status != Booking.STATUS_ACTIVE:
        # If student is stopped, do not create new fee reminders.
        return

    if MonthlyFeePayment.objects.filter(profile=profile, month=cycle_key).exists():
        return

    exists = Notification.objects.filter(
        user=request.user,
        notification_type=Notification.NOTIF_FEE_DUE,
        month=cycle_key,
    ).exists()
    if exists:
        return

    cycle_start = get_fee_cycle_start_for_user(request.user, cycle_key)
    Notification.objects.create(
        user=request.user,
        notification_type=Notification.NOTIF_FEE_DUE,
        month=cycle_key,
        message=f"Monthly fee reminder: Please pay your fee for cycle {cycle_key} (started {cycle_start}).",
        due_at=timezone.now(),
    )


DAY_NAME_TO_WEEKDAY_INDEX = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


def parse_timetable_start_time(time_range: str) -> datetime.time:
    """
    Timetable.time is stored as a range like: '5 PM - 6 PM'
    We use only the start time (left side) to build OnlineClass.scheduled_at.
    """
    if not time_range:
        raise ValueError("Invalid timetable time.")

    start_str = time_range.split("-")[0].strip()
    start_str = " ".join(start_str.split())  # normalize spaces

    # Try common formats used in your sample: '5 PM', '5:30 PM', '17:00'
    for fmt in ("%I %p", "%I:%M %p", "%H:%M"):
        try:
            return datetime.datetime.strptime(start_str, fmt).time().replace(second=0, microsecond=0)
        except ValueError:
            continue

    raise ValueError(f"Unsupported timetable start time format: {start_str}")


def compute_scheduled_at_from_date_and_timetable(
    class_date: datetime.date, timetable_slot: Timetable
) -> datetime.datetime:
    expected_weekday = DAY_NAME_TO_WEEKDAY_INDEX.get(timetable_slot.day.strip().lower())
    if expected_weekday is not None and class_date.weekday() != expected_weekday:
        raise ValueError(
            f"Selected date does not match timetable day '{timetable_slot.day}'."
        )

    start_time = parse_timetable_start_time(timetable_slot.time)
    naive_dt = datetime.datetime.combine(class_date, start_time)
    return timezone.make_aware(naive_dt, timezone.get_current_timezone())


def infer_timetable_slot_from_online_class(online_class: OnlineClass) -> Optional[Timetable]:
    """
    Best-effort: infer the Timetable row whose (day, start_time) matches
    OnlineClass.scheduled_at.
    """
    scheduled_at = online_class.scheduled_at
    weekday_key = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"][
        scheduled_at.weekday()
    ]
    scheduled_time = scheduled_at.time().replace(second=0, microsecond=0)

    qs = Timetable.objects.filter(course=online_class.course, mode=Timetable.MODE_ONLINE)
    for slot in qs:
        if slot.day.strip().lower() != weekday_key:
            continue
        try:
            slot_start = parse_timetable_start_time(slot.time)
        except ValueError:
            continue
        if slot_start == scheduled_time:
            return slot
    return None


# Home Page
def home(request):
    return render(request, 'home.html')


# Register Page
def register(request):
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        email = request.POST.get("email", "").strip()
        password = request.POST.get("password", "").strip()
        dob = request.POST.get("dob", "").strip()
        phone = request.POST.get("phone", "").strip()

        if not username or not email or not password or not dob or not phone:
            messages.error(request, "All fields are required!")
            return redirect("register")

        if not phone.isdigit() or len(phone) != 10:
            messages.error(request, "Enter valid 10 digit phone number")
            return redirect("register")

        if len(password) < 6:
            messages.error(request, "Password must be at least 6 characters")
            return redirect("register")

        if User.objects.filter(username=username).exists():
            messages.error(request, "Username already exists")
            return redirect("register")

        if User.objects.filter(email=email).exists():
            messages.error(request, "Email already registered")
            return redirect("register")

        user = User.objects.create_user(
            username=username,
            email=email,
            password=password
        )

        UserProfile.objects.create(
            user=user,
            date_of_birth=dob,
            phone=phone
        )

        messages.success(request, "Registration Successful!")
        return redirect("login")

    return render(request, "register.html")

# Login Page
def login_view(request):
    if request.method == "POST":
        email = request.POST.get("email")
        password = request.POST.get("password")

        # ✅ Empty validation
        if not email or not password:
            messages.error(request, "All fields are required!")
            return redirect("login")

        try:
            user_obj = User.objects.get(email=email)
        except User.DoesNotExist:
            messages.error(request, "Invalid email or password")
            return redirect("login")

        user = authenticate(username=user_obj.username, password=password)

        if user is not None:
            login(request, user)

            # 🔥 ADMIN CHECK
            if user.is_superuser:
                return redirect('/admin/')   # admin panel

            # 👤 STUDENT
            return redirect("dashboard")

        else:
            messages.error(request, "Invalid email or password")
            return redirect("login")

    return render(request, "login.html")


def admin_login_view(request):
    """
    Separate admin login page.
    We still use the same `username`/`password` authentication as the student login.
    """

    if request.user.is_authenticated:
        return redirect("admin_dashboard" if is_admin_user(request.user) else "dashboard")

    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")
        user = authenticate(request, username=username, password=password)

        if user is None or not (user.is_staff or user.is_superuser):
            messages.error(request, "Admin credentials are not valid.")
        else:
            login(request, user)
            return redirect("admin_dashboard")

    return render(request, "admin_login.html")


# Dashboard Page
@login_required
def dashboard(request):
    """
    Main dashboard entry after login.
    Links here should go to dashboard-only pages (course details, timetable, instructors).
    """

    if is_admin_user(request.user):
        return redirect("admin_dashboard")

    profile = get_profile_or_redirect(request)
    if profile is None:
        return redirect("register")

    # Create fee reminder notifications for the current 30-day cycle (if needed).
    current_cycle_key = get_fee_cycle_key_for_user(request.user)
    ensure_fee_due_notification(request, profile, current_cycle_key)

    notifications = Notification.objects.filter(
        user=request.user,
        is_read=False,
        due_at__lte=timezone.now(),
    ).order_by("-created_at")[:10]
    return render(
        request,
        "dashboard.html",
        {
            "admission_fee_paid": profile.admission_fee_paid,
            "selected_course": profile.selected_course,
            "notifications": notifications,
        },
    )

# Join Page
@login_required
def join(request):
    """
    Join landing page (admission flow entry).
    """

    if is_admin_user(request.user):
        return redirect("admin_dashboard")

    profile = get_profile_or_redirect(request)
    if profile is None:
        return redirect("register")

    # Keep payment inside the Join flow only:
    # - If course + timetable are selected but payment isn't done yet,
    #   redirect the user directly to the payment step.
    if profile.selected_course and profile.selected_timetable and not profile.admission_fee_paid:
        return redirect("payment")

    return render(request, "join.html", {"profile": profile})


# Course Selection
@login_required
def course_selection(request):
    """
    Step 1 of Join flow: select an active course.
    - Save selected course in DB.
    - Clear previously selected timetable + payment status.
    """

    if is_admin_user(request.user):
        return redirect("admin_dashboard")

    profile = get_profile_or_redirect(request)
    if profile is None:
        return redirect("register")

    if profile.admission_fee_paid:
        messages.info(request, "You have already completed admission. You can still change your course selection below.")

    if request.method == "POST":
        course_id = request.POST.get("course")
        course = get_object_or_404(Course, pk=course_id, is_active=True)

        profile.selected_course = course
        profile.selected_timetable = None
        profile.admission_fee_paid = False
        profile.payment_id = None
        profile.save()
        # Reset booking if the student changes course/timetable before payment.
        Booking.objects.filter(profile=profile).delete()
        # Reset monthly fee payments as well (since cycle 0 payment depends on this selection).
        MonthlyFeePayment.objects.filter(profile=profile).delete()

        messages.success(request, "Course selected. Next: choose your timetable slot.")
        return redirect("join_timetable")

    courses = Course.objects.filter(is_active=True).order_by("name")
    selected_course = profile.selected_course
    return render(
        request,
        "course_selection.html",
        {"courses": courses, "selected_course": selected_course},
    )


# Timetable Page
@login_required
def join_timetable(request):
    """
    Step 2 of Join flow:
    - Show timetable entries ONLY for the selected course.
    - Save the selected timetable entry in the user's profile.
    """

    if is_admin_user(request.user):
        return redirect("admin_dashboard")

    profile = get_profile_or_redirect(request)
    if profile is None:
        return redirect("register")

    if profile.admission_fee_paid:
        messages.info(request, "You have already completed admission. You can still change your timetable selection below.")

    if not profile.selected_course:
        messages.error(request, "Please select a course first.")
        return redirect("course_selection")

    if request.method == "POST":
        timetable_id = request.POST.get("timetable")
        timetable_entry = get_object_or_404(
            Timetable,
            pk=timetable_id,
            course=profile.selected_course,
        )

        profile.selected_timetable = timetable_entry
        profile.admission_fee_paid = False
        profile.payment_id = None
        profile.save()
        # Reset booking if the student changes course/timetable before payment.
        Booking.objects.filter(profile=profile).delete()
        # Reset monthly fee payments as well.
        MonthlyFeePayment.objects.filter(profile=profile).delete()

        messages.success(request, "Timetable selected. Next: admission fee payment.")
        return redirect("payment")

    timetable_entries = (
        Timetable.objects.filter(course=profile.selected_course)
        .select_related("course")
        .order_by("day", "time")
    )

    upcoming_programs = (
        Program.objects.filter(
            starts_at__gte=timezone.now(),
        )
        .filter(
            Q(course__isnull=True) | Q(course=profile.selected_course)
        )
        .order_by("starts_at")[:10]
    )
    return render(
        request,
        "join_timetable.html",
        {
            "course": profile.selected_course,
            "timetable_entries": timetable_entries,
            "upcoming_programs": upcoming_programs,
        },
    )

@login_required
def payment(request):
    """
    Step 3 of Join flow: mock admission fee payment.
    Saves `admission_fee_paid` + `payment_id` while keeping the selected
    course and timetable in the profile.
    """

    if is_admin_user(request.user):
        return redirect("admin_dashboard")

    profile = get_profile_or_redirect(request)
    if profile is None:
        return redirect("register")

    if not profile.selected_course or not profile.selected_timetable:
        messages.error(request, "Please complete course + timetable selection before payment.")
        return redirect("course_selection")

    # ✅ Already paid → Dashboard lekku redirect
    if profile.admission_fee_paid:
        messages.info(request, "Admission fee already paid.")
        return redirect('dashboard')

    if request.method == "POST":
        # Fake payment id generate.
        payment_id = f"PAY{uuid.uuid4().hex[:8].upper()}"

        profile.admission_fee_paid = True
        profile.payment_id = payment_id
        profile.save()

        # Create/overwrite booking details after successful (mock) payment.
        Booking.objects.update_or_create(
            profile=profile,
            defaults={
                "course": profile.selected_course,
                "timetable": profile.selected_timetable,
                "payment_status": Booking.PAYMENT_PAID,
                "payment_id": payment_id,
                "status": Booking.STATUS_ACTIVE,
            },
        )

        # Registration payment counts as this user's current 30-day fee cycle (cycle 0).
        cycle_key = get_fee_cycle_key_for_user(request.user)
        amount = int(profile.selected_course.fee) if profile.selected_course else 0

        payment_record, _created = MonthlyFeePayment.objects.get_or_create(
            profile=profile,
            month=cycle_key,
            defaults={
                "course": profile.selected_course,
                "amount": amount,
                "payment_id": payment_id,
                "paid_at": timezone.now(),
            },
        )

        Notification.objects.filter(
            user=request.user,
            notification_type=Notification.NOTIF_FEE_DUE,
            month=cycle_key,
        ).update(is_read=True)

        # Optional confirmation notification for this cycle.
        if _created:
            Notification.objects.create(
                user=request.user,
                notification_type=Notification.NOTIF_FEE_PAID,
                month=cycle_key,
                fee_payment=payment_record,
                message=f"Monthly fee payment successful for cycle {cycle_key}.",
                due_at=timezone.now(),
            )

        messages.success(request, f"Payment successful. Your payment id is {payment_id}.")

        # ✅ FINAL FIX → Dashboard lekku redirect
        return redirect("dashboard")

    return render(
        request,
        "payment.html",
        {
            "course": profile.selected_course,
            "timetable": profile.selected_timetable,
            "fee": profile.selected_course.fee,
        },
    )

@login_required
def instructors(request):
    """
    Instructor Details page (dashboard display).
    Fully database-driven.
    """

    if is_admin_user(request.user):
        return redirect("admin_dashboard")

    profile = get_profile_or_redirect(request)
    if profile is None:
        return redirect("register")

    instructors_list = Instructor.objects.all().order_by("name")
    return render(request, "instructors.html", {"instructors": instructors_list})


@login_required
def dashboard_course_details(request):
    """
    Student view: show all course details (not just the registered course).
    """

    if is_admin_user(request.user):
        return redirect("admin_dashboard")

    # Profile is not required for this page; students can browse all courses.
    # Still ensure the user is a valid student profile to keep role consistency.
    profile = get_profile_or_redirect(request)
    if profile is None:
        return redirect("register")

    courses = Course.objects.filter(is_active=True).order_by("name")

    return render(
        request,
        "course_details.html",
        {
            "courses": courses,
        },
    )


@login_required
def dashboard_timetable(request):
    """
    Dashboard timetable: show all timetable entries for all courses.
    """

    if is_admin_user(request.user):
        return redirect("admin_dashboard")

    profile = get_profile_or_redirect(request)
    if profile is None:
        return redirect("register")

    timetable_entries = Timetable.objects.select_related("course").all().order_by(
        "course__name", "day", "time"
    )

    upcoming_programs = Program.objects.filter(
        starts_at__gte=timezone.now()
    ).order_by("starts_at")[:10]
    return render(
        request,
        "dashboard_timetable.html",
        {
            "timetable_entries": timetable_entries,
            "upcoming_programs": upcoming_programs,
        },
    )


@login_required
def profile(request):
    if is_admin_user(request.user):
        return redirect("admin_dashboard")

    profile_obj = get_profile_or_redirect(request)
    if profile_obj is None:
        return redirect("register")

    booking = Booking.objects.filter(profile=profile_obj).first()

    if request.method == "POST":
        date_of_birth = request.POST.get("date_of_birth")
        phone = request.POST.get("phone")
        address = request.POST.get("address", "")
        name = request.POST.get("name", "").strip()
        new_password = request.POST.get("new_password")
        confirm_password = request.POST.get("confirm_password")

        if not phone:
            messages.error(request, "Phone is required.")
            return redirect("profile")

        profile_obj.date_of_birth = date_of_birth or None
        profile_obj.phone = phone
        profile_obj.address = address
        profile_obj.save()

        if name:
            request.user.first_name = name
            request.user.save(update_fields=["first_name"])

        if new_password:
            if new_password != confirm_password:
                messages.error(request, "New password and confirmation do not match.")
                return redirect("profile")

            if len(new_password) < 4:
                messages.error(request, "Password is too short.")
                return redirect("profile")

            request.user.set_password(new_password)
            request.user.save()
            update_session_auth_hash(request, request.user)

        messages.success(request, "Profile updated successfully.")
        return redirect("profile")

    return render(
        request,
        "profile.html",
        {
            "profile": profile_obj,
            "booking": booking,
        },
    )

@login_required
def gallery(request):
    """
    Student gallery page (images uploaded by admin).
    """

    images = GalleryImage.objects.all().order_by("-uploaded_at")
    return render(request, "gallery.html", {"images": images})


@login_required
def admin_dashboard(request):
    """
    Separate admin dashboard (staff/superuser only).
    Provides summary + simple payment actions.
    """

    if not is_admin_user(request.user):
        return redirect("dashboard")

    if request.method == "POST":
        action = request.POST.get("action")
        profile_id = request.POST.get("profile_id")

        if action in {"mark_paid", "mark_pending"} and profile_id:
            student_profile = get_object_or_404(UserProfile, pk=profile_id)

            if action == "mark_paid":
                if not student_profile.selected_course or not student_profile.selected_timetable:
                    messages.error(request, "Student must select course and timetable before payment.")
                else:
                    payment_id = student_profile.payment_id or (
                        f"PAY{uuid.uuid4().hex[:8].upper()}"
                    )

                    # Admin marking admission as paid also counts as monthly fee for current 30-day cycle.
                    cycle_key = get_fee_cycle_key_for_user(student_profile.user)
                    student_profile.admission_fee_paid = True
                    student_profile.payment_id = payment_id
                    student_profile.save()

                    Booking.objects.update_or_create(
                        profile=student_profile,
                        defaults={
                            "course": student_profile.selected_course,
                            "timetable": student_profile.selected_timetable,
                            "payment_status": Booking.PAYMENT_PAID,
                            "payment_id": payment_id,
                            "status": Booking.STATUS_ACTIVE,
                        },
                    )

                    MonthlyFeePayment.objects.get_or_create(
                        profile=student_profile,
                        month=cycle_key,
                        defaults={
                            "course": student_profile.selected_course,
                            "amount": int(student_profile.selected_course.fee),
                            "payment_id": payment_id,
                            "paid_at": timezone.now(),
                        },
                    )

                    messages.success(request, "Payment marked as Paid.")

            elif action == "mark_pending":
                cycle_key = get_fee_cycle_key_for_user(student_profile.user)
                student_profile.admission_fee_paid = False
                student_profile.payment_id = None
                student_profile.save()

                # Remove monthly fee for current cycle to block joining.
                MonthlyFeePayment.objects.filter(profile=student_profile, month=cycle_key).delete()

                booking_obj = getattr(student_profile, "booking", None)
                if booking_obj is not None:
                    booking_obj.payment_status = Booking.PAYMENT_PENDING
                    booking_obj.payment_id = None
                    booking_obj.status = Booking.STATUS_CANCELLED
                    booking_obj.save()

                messages.success(request, "Payment marked as Pending/Unpaid.")

            return redirect("admin_dashboard")

    courses_count = Course.objects.count()
    timetables_count = Timetable.objects.count()
    instructors_count = Instructor.objects.count()
    gallery_count = GalleryImage.objects.count()
    students_count = (
        UserProfile.objects.exclude(user__is_staff=True).exclude(user__is_superuser=True).count()
    )
    paid_count = (
        UserProfile.objects.exclude(user__is_staff=True)
        .exclude(user__is_superuser=True)
        .filter(admission_fee_paid=True)
        .count()
    )
    pending_count = (
        UserProfile.objects.exclude(user__is_staff=True)
        .exclude(user__is_superuser=True)
        .filter(admission_fee_paid=False)
        .count()
    )

    students = (
        UserProfile.objects.select_related(
            "user", "selected_course", "selected_timetable", "booking"
        )
        .exclude(user__is_staff=True)
        .exclude(user__is_superuser=True)
        .order_by("user__username")
    )

    return render(
        request,
        "admin_dashboard.html",
        {
            "courses_count": courses_count,
            "timetables_count": timetables_count,
            "instructors_count": instructors_count,
            "gallery_count": gallery_count,
            "students_count": students_count,
            "paid_count": paid_count,
            "pending_count": pending_count,
            "students": students,
        },
    )


@login_required
def admin_profile(request):
    """
    Admin's own profile editor (name/email/password only).
    """

    if not is_admin_user(request.user):
        return redirect("dashboard")

    user = request.user

    if request.method == "POST":
        form = AdminUserEditForm(request.POST)
        if form.is_valid():
            user.first_name = form.cleaned_data["name"]
            user.email = form.cleaned_data["email"]

            new_password = form.cleaned_data.get("new_password")
            if new_password:
                user.set_password(new_password)

            user.save()
            messages.success(request, "Admin profile updated successfully.")
            return redirect("admin_profile")
    else:
        form = AdminUserEditForm(
            initial={
                "name": user.first_name,
                "email": user.email,
            }
        )

    return render(request, "admin_profile.html", {"form": form})


@login_required
def admin_courses(request):
    if not is_admin_user(request.user):
        return redirect("dashboard")

    courses = Course.objects.all().order_by("name")
    return render(request, "admin_courses.html", {"courses": courses})


@login_required
def admin_course_add(request):
    if not is_admin_user(request.user):
        return redirect("dashboard")

    if request.method == "POST":
        form = CourseForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            messages.success(request, "Course added successfully.")
            return redirect("admin_courses")
    else:
        form = CourseForm()

    return render(request, "admin_course_form.html", {"form": form, "mode": "Add Course"})


@login_required
def admin_course_edit(request, pk):
    if not is_admin_user(request.user):
        return redirect("dashboard")

    course_obj = get_object_or_404(Course, pk=pk)

    if request.method == "POST":
        form = CourseForm(request.POST, request.FILES, instance=course_obj)
        if form.is_valid():
            form.save()
            messages.success(request, "Course updated successfully.")
            return redirect("admin_courses")
    else:
        form = CourseForm(instance=course_obj)

    return render(request, "admin_course_form.html", {"form": form, "mode": "Edit Course"})


@login_required
def admin_course_delete(request, pk):
    if not is_admin_user(request.user):
        return redirect("dashboard")

    course_obj = get_object_or_404(Course, pk=pk)

    if request.method == "POST":
        course_obj.delete()
        messages.success(request, "Course deleted successfully.")
        return redirect("admin_courses")

    return render(request, "admin_confirm_delete.html", {"obj": course_obj, "type_name": "Course"})


@login_required
def admin_timetables(request):
    if not is_admin_user(request.user):
        return redirect("dashboard")

    timetable_entries = (
        Timetable.objects.select_related("course").all().order_by("course__name", "day", "time")
    )
    return render(request, "admin_timetables.html", {"timetable_entries": timetable_entries})


@login_required
def admin_timetable_add(request):
    if not is_admin_user(request.user):
        return redirect("dashboard")

    if request.method == "POST":
        form = TimetableForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Timetable added successfully.")
            return redirect("admin_timetables")
    else:
        form = TimetableForm()

    return render(request, "admin_timetable_form.html", {"form": form, "mode": "Add Timetable"})


@login_required
def admin_timetable_edit(request, pk):
    if not is_admin_user(request.user):
        return redirect("dashboard")

    timetable_obj = get_object_or_404(Timetable, pk=pk)

    if request.method == "POST":
        form = TimetableForm(request.POST, instance=timetable_obj)
        if form.is_valid():
            form.save()
            messages.success(request, "Timetable updated successfully.")
            return redirect("admin_timetables")
    else:
        form = TimetableForm(instance=timetable_obj)

    return render(request, "admin_timetable_form.html", {"form": form, "mode": "Edit Timetable"})


@login_required
def admin_timetable_delete(request, pk):
    if not is_admin_user(request.user):
        return redirect("dashboard")

    timetable_obj = get_object_or_404(Timetable, pk=pk)

    if request.method == "POST":
        timetable_obj.delete()
        messages.success(request, "Timetable deleted successfully.")
        return redirect("admin_timetables")

    return render(
        request,
        "admin_confirm_delete.html",
        {"obj": timetable_obj, "type_name": "Timetable"},
    )


@login_required
def admin_instructors(request):
    if not is_admin_user(request.user):
        return redirect("dashboard")

    instructors_list = Instructor.objects.all().order_by("name")
    return render(request, "admin_instructors.html", {"instructors": instructors_list})


@login_required
def admin_instructor_add(request):
    if not is_admin_user(request.user):
        return redirect("dashboard")

    if request.method == "POST":
        form = InstructorForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            messages.success(request, "Instructor added successfully.")
            return redirect("admin_instructors")
    else:
        form = InstructorForm()

    return render(request, "admin_instructor_form.html", {"form": form, "mode": "Add Instructor"})


@login_required
def admin_instructor_edit(request, pk):
    if not is_admin_user(request.user):
        return redirect("dashboard")

    instructor_obj = get_object_or_404(Instructor, pk=pk)

    if request.method == "POST":
        form = InstructorForm(request.POST, request.FILES, instance=instructor_obj)
        if form.is_valid():
            form.save()
            messages.success(request, "Instructor updated successfully.")
            return redirect("admin_instructors")
    else:
        form = InstructorForm(instance=instructor_obj)

    return render(request, "admin_instructor_form.html", {"form": form, "mode": "Edit Instructor"})


@login_required
def admin_instructor_delete(request, pk):
    if not is_admin_user(request.user):
        return redirect("dashboard")

    instructor_obj = get_object_or_404(Instructor, pk=pk)

    if request.method == "POST":
        instructor_obj.delete()
        messages.success(request, "Instructor deleted successfully.")
        return redirect("admin_instructors")

    return render(
        request,
        "admin_confirm_delete.html",
        {"obj": instructor_obj, "type_name": "Instructor"},
    )


@login_required
def admin_gallery_images(request):
    if not is_admin_user(request.user):
        return redirect("dashboard")

    images = GalleryImage.objects.all().order_by("-uploaded_at")
    return render(request, "admin_gallery_images.html", {"images": images})


@login_required
def admin_gallery_image_add(request):
    if not is_admin_user(request.user):
        return redirect("dashboard")

    if request.method == "POST":
        if "image" not in request.FILES:
            messages.error(request, "Please upload an image.")
            form = GalleryImageForm(request.POST, request.FILES)
            return render(
                request,
                "admin_gallery_image_form.html",
                {"form": form, "mode": "Add Gallery Image"},
            )
        form = GalleryImageForm(request.POST, request.FILES)
        if form.is_valid():
            gallery_obj = form.save(commit=False)
            gallery_obj.uploaded_by = request.user
            gallery_obj.save()
            messages.success(request, "Gallery image uploaded successfully.")
            return redirect("admin_gallery_images")
    else:
        form = GalleryImageForm()

    return render(request, "admin_gallery_image_form.html", {"form": form, "mode": "Add Gallery Image"})


@login_required
def admin_gallery_image_edit(request, pk):
    if not is_admin_user(request.user):
        return redirect("dashboard")

    image_obj = get_object_or_404(GalleryImage, pk=pk)

    if request.method == "POST":
        form = GalleryImageForm(request.POST, request.FILES, instance=image_obj)
        if form.is_valid():
            form.save()
            messages.success(request, "Gallery image updated successfully.")
            return redirect("admin_gallery_images")
    else:
        form = GalleryImageForm(instance=image_obj)

    return render(request, "admin_gallery_image_form.html", {"form": form, "mode": "Edit Gallery Image"})


@login_required
def admin_gallery_image_delete(request, pk):
    if not is_admin_user(request.user):
        return redirect("dashboard")

    image_obj = get_object_or_404(GalleryImage, pk=pk)

    if request.method == "POST":
        image_obj.delete()
        messages.success(request, "Gallery image deleted successfully.")
        return redirect("admin_gallery_images")

    return render(
        request,
        "admin_confirm_delete.html",
        {"obj": image_obj, "type_name": "Gallery Image"},
    )

@login_required
def admin_students(request):
    if not is_admin_user(request.user):
        return redirect("dashboard")

    students = (
        UserProfile.objects.select_related(
            "user", "selected_course", "selected_timetable", "booking"
        )
        .exclude(user__is_staff=True)
        .exclude(user__is_superuser=True)
        .order_by("user__username")
    )
    return render(request, "admin_students.html", {"students": students})


@login_required
def admin_student_edit(request, pk):
    """
    Admin page to edit student profile details (age/phone/address/profile image).
    """
    if not is_admin_user(request.user):
        return redirect("dashboard")

    student_profile = get_object_or_404(UserProfile, pk=pk)

    if request.method == "POST":
        form = UserProfileForm(
            request.POST,
            request.FILES,
            instance=student_profile,
        )
        if form.is_valid():
            form.save()
            messages.success(request, "Student profile updated successfully.")
            return redirect("admin_students")
    else:
        form = UserProfileForm(instance=student_profile)

    return render(
        request,
        "admin_student_edit.html",
        {"form": form, "student_profile": student_profile},
    )


@login_required
def admin_student_toggle_course_status(request, pk):
    """
    Admin action to stop/resume a student's selected course.
    Uses Booking.status:
    - Active => student taking the course
    - Cancelled => student stopped
    """
    if not is_admin_user(request.user):
        return redirect("dashboard")

    student_profile = get_object_or_404(UserProfile, pk=pk)
    booking_obj = getattr(student_profile, "booking", None)
    if booking_obj is None:
        messages.error(request, "No booking found for this student.")
        return redirect("admin_students")

    if request.method != "POST":
        return redirect("admin_students")

    action = request.POST.get("action")
    if action == "stop":
        booking_obj.status = Booking.STATUS_CANCELLED
        booking_obj.save(update_fields=["status"])

        # Mark pending reminders as read so stopped students don't see them.
        Notification.objects.filter(
            user=student_profile.user,
            is_read=False,
            notification_type__in=[
                Notification.NOTIF_FEE_DUE,
                Notification.NOTIF_ONLINE_CLASS,
                Notification.NOTIF_PROGRAM,
            ],
        ).update(is_read=True)

        messages.success(request, "Student course stopped successfully.")
    elif action == "resume":
        booking_obj.status = Booking.STATUS_ACTIVE
        booking_obj.save(update_fields=["status"])
        messages.success(request, "Student course resumed successfully.")
    else:
        messages.error(request, "Invalid action.")

    return redirect("admin_students")


@login_required
def admin_payments(request):
    if not is_admin_user(request.user):
        return redirect("dashboard")

    if request.method == "POST":
        action = request.POST.get("action")
        profile_id = request.POST.get("profile_id")

        if action in {"mark_paid", "mark_pending"} and profile_id:
            student_profile = get_object_or_404(UserProfile, pk=profile_id)

            if action == "mark_paid":
                if not student_profile.selected_course or not student_profile.selected_timetable:
                    messages.error(request, "Student must select course and timetable before payment.")
                else:
                    payment_id = student_profile.payment_id or (
                        f"PAY{uuid.uuid4().hex[:8].upper()}"
                    )

                    # Admin marking admission as paid also counts as monthly fee for current cycle.
                    cycle_key = get_fee_cycle_key_for_user(student_profile.user)
                    student_profile.admission_fee_paid = True
                    student_profile.payment_id = payment_id
                    student_profile.save()

                    Booking.objects.update_or_create(
                        profile=student_profile,
                        defaults={
                            "course": student_profile.selected_course,
                            "timetable": student_profile.selected_timetable,
                            "payment_status": Booking.PAYMENT_PAID,
                            "payment_id": payment_id,
                            "status": Booking.STATUS_ACTIVE,
                        },
                    )

                    MonthlyFeePayment.objects.get_or_create(
                        profile=student_profile,
                        month=cycle_key,
                        defaults={
                            "course": student_profile.selected_course,
                            "amount": int(student_profile.selected_course.fee),
                            "payment_id": payment_id,
                            "paid_at": timezone.now(),
                        },
                    )
                    messages.success(request, "Payment marked as Paid.")

            elif action == "mark_pending":
                cycle_key = get_fee_cycle_key_for_user(student_profile.user)
                student_profile.admission_fee_paid = False
                student_profile.payment_id = None
                student_profile.save()

                # Remove monthly fee for current cycle to block joining.
                MonthlyFeePayment.objects.filter(profile=student_profile, month=cycle_key).delete()

                booking_obj = getattr(student_profile, "booking", None)
                if booking_obj is not None:
                    booking_obj.payment_status = Booking.PAYMENT_PENDING
                    booking_obj.payment_id = None
                    booking_obj.status = Booking.STATUS_CANCELLED
                    booking_obj.save()

                messages.success(request, "Payment marked as Pending/Unpaid.")

            return redirect("admin_payments")

    students = (
        UserProfile.objects.select_related(
            "user", "selected_course", "selected_timetable", "booking"
        )
        .exclude(user__is_staff=True)
        .exclude(user__is_superuser=True)
        .order_by("user__username")
    )

    return render(request, "admin_payments.html", {"students": students})


# ----------------------------
# Student dashboard extras
# ----------------------------


@login_required
def online_classes(request):
    if is_admin_user(request.user):
        return redirect("admin_dashboard")

    profile = get_profile_or_redirect(request)
    if profile is None:
        return redirect("register")

    if not profile.selected_course:
        messages.error(request, "Please select a course first.")
        return redirect("course_selection")

    now = timezone.now()
    cycle_key = get_fee_cycle_key_for_user(request.user)
    cycle_start = get_fee_cycle_start_for_user(request.user, cycle_key)
    booking_obj = getattr(profile, "booking", None)
    is_student_active = booking_obj is not None and booking_obj.status == Booking.STATUS_ACTIVE
    is_online_timetable_student = (
        profile.selected_timetable is not None
        and profile.selected_timetable.mode == Timetable.MODE_ONLINE
    )

    fee_paid_for_current_cycle = MonthlyFeePayment.objects.filter(
        profile=profile, month=cycle_key
    ).exists()

    can_join = is_student_active and is_online_timetable_student and fee_paid_for_current_cycle

    upcoming_classes = OnlineClass.objects.filter(
        course=profile.selected_course,
        is_active=True,
        scheduled_at__gte=now - timedelta(hours=1),
    ).order_by("scheduled_at")

    # If the student selected an Offline timetable slot, they should not see
    # Online class schedules at all.
    if not is_online_timetable_student:
        upcoming_classes = OnlineClass.objects.none()

    reminder_notifications = Notification.objects.filter(
        user=request.user,
        notification_type=Notification.NOTIF_ONLINE_CLASS,
        is_read=False,
        due_at__lte=now,
    ).order_by("-due_at")[:10]
    if not is_online_timetable_student:
        reminder_notifications = Notification.objects.none()

    return render(
        request,
        "online_classes.html",
        {
            "online_classes": upcoming_classes,
            "can_join": can_join,
            "notifications": reminder_notifications,
            "course": profile.selected_course,
            "fee_due_message": (
                (
                    "Your course is currently stopped. Please contact admin to resume."
                    if not is_student_active
                    else f"Monthly fee due for cycle {cycle_key} (started {cycle_start})."
                )
                if not can_join
                else ""
            ),
            "is_online_timetable_student": is_online_timetable_student,
        },
    )


@login_required
def monthly_fee_payment(request):
    if is_admin_user(request.user):
        return redirect("admin_dashboard")

    profile = get_profile_or_redirect(request)
    if profile is None:
        return redirect("register")

    booking_obj = getattr(profile, "booking", None)
    if booking_obj is not None and booking_obj.status != Booking.STATUS_ACTIVE:
        messages.error(
            request, "Your course is currently stopped. Monthly fee payment is disabled."
        )
        return redirect("dashboard")

    selected_course = profile.selected_course
    cycle_key = get_fee_cycle_key_for_user(request.user)

    payment_obj = MonthlyFeePayment.objects.filter(profile=profile, month=cycle_key).first()
    amount = int(selected_course.fee) if selected_course else 0
    cycle_start = get_fee_cycle_start_for_user(request.user, cycle_key)
    cycle_end = get_fee_cycle_end_for_user(request.user, cycle_key)

    if request.method == "POST":
        # Avoid payment duplication for the same 30-day cycle.
        existing = MonthlyFeePayment.objects.filter(profile=profile, month=cycle_key).first()
        if existing is not None:
            messages.info(request, "Already Paid for this fee cycle.")
            return redirect("monthly_fee_payment")

        if not selected_course:
            messages.error(request, "Please select a course before paying monthly fee.")
            return redirect("course_selection")

        payment_id = f"FEE{uuid.uuid4().hex[:8].upper()}"
        payment_obj = MonthlyFeePayment.objects.create(
            profile=profile,
            course=selected_course,
            month=cycle_key,
            amount=amount,
            payment_id=payment_id,
            paid_at=timezone.now(),
        )

        # Mark due reminders as read and create confirmation notification.
        Notification.objects.filter(
            user=request.user,
            notification_type=Notification.NOTIF_FEE_DUE,
            month=cycle_key,
        ).update(is_read=True)

        Notification.objects.create(
            user=request.user,
            notification_type=Notification.NOTIF_FEE_PAID,
            month=cycle_key,
            fee_payment=payment_obj,
            message=f"Monthly fee payment successful for cycle {cycle_key}.",
            due_at=timezone.now(),
        )

        messages.success(request, f"Payment successful. Payment ID: {payment_id}")
        return redirect("monthly_fee_payment")

    return render(
        request,
        "monthly_fee_payment.html",
        {
            "course": selected_course,
            "cycle_key": cycle_key,
            "cycle_start": cycle_start,
            "cycle_end": cycle_end,
            "payment": payment_obj,
            "amount": amount,
        },
    )


@login_required
def feedback(request):
    recent_feedback = FeedbackSubmission.objects.select_related("user").order_by(
        "-created_at"
    )[:20]

    if request.method == "POST":
        form = FeedbackForm(request.POST)
        if form.is_valid():
            FeedbackSubmission.objects.create(
                user=request.user,
                message=form.cleaned_data["message"],
            )
            messages.success(request, "Thank you! Your feedback has been submitted.")
            return redirect("feedback")
    else:
        form = FeedbackForm()

    return render(request, "feedback.html", {"form": form, "recent_feedback": recent_feedback})


@login_required
def contact_us(request):
    contact_info = ContactInfo.objects.first()
    if request.method == "POST":
        form = ContactUsForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data
            ContactSubmission.objects.create(
                user=request.user,
                name=cd.get("name", ""),
                email=cd.get("email", ""),
                phone=cd.get("phone", ""),
                message=cd.get("message", ""),
            )
            messages.success(request, "Thanks! We received your message.")
            return redirect("dashboard")
    else:
        # Pre-fill name/email for logged-in students.
        form = ContactUsForm(
            initial={
                "name": request.user.first_name or request.user.username,
                "email": request.user.email,
                "phone": "",
            }
        )

    return render(request, "contact_us.html", {"form": form, "contact_info": contact_info})


@login_required
def admin_feedback(request):
    if not is_admin_user(request.user):
        return redirect("dashboard")

    items = FeedbackSubmission.objects.select_related("user").order_by("-created_at")
    return render(request, "admin_feedback.html", {"items": items})


@login_required
def admin_contact_submissions(request):
    if not is_admin_user(request.user):
        return redirect("dashboard")

    items = ContactSubmission.objects.all().order_by("-created_at")
    return render(request, "admin_contact_submissions.html", {"items": items})


@login_required
def admin_contact_info(request):
    if not is_admin_user(request.user):
        return redirect("dashboard")

    contact_info = ContactInfo.objects.first()
    if contact_info is None:
        contact_info = ContactInfo.objects.create()

    if request.method == "POST":
        form = ContactInfoForm(request.POST, instance=contact_info)
        if form.is_valid():
            form.save()
            messages.success(request, "Contact information updated successfully.")
            return redirect("admin_contact_info")
    else:
        form = ContactInfoForm(instance=contact_info)

    return render(request, "admin_contact_info.html", {"form": form, "contact_info": contact_info})


@login_required
def mark_notification_read(request, notification_id: int):
    if request.method != "POST":
        return redirect("dashboard")

    notification = get_object_or_404(Notification, pk=notification_id, user=request.user)
    notification.is_read = True
    notification.save(update_fields=["is_read"])
    return redirect("dashboard")


# ----------------------------
# Admin panel: Online classes
# ----------------------------


@login_required
def admin_online_classes(request):
    if not is_admin_user(request.user):
        return redirect("dashboard")

    classes = OnlineClass.objects.select_related("course").all().order_by("-scheduled_at")
    return render(request, "admin_online_classes.html", {"classes": classes})


@login_required
def admin_online_class_add(request):
    if not is_admin_user(request.user):
        return redirect("dashboard")

    timetable_slots_for_js = Timetable.objects.filter(
        mode=Timetable.MODE_ONLINE
    ).select_related("course").only("id", "course_id", "day", "time")

    if request.method == "POST":
        form = AdminOnlineClassForm(request.POST)
        if form.is_valid():
            course = form.cleaned_data["course"]
            slot = form.cleaned_data["timetable_slot"]
            class_date = form.cleaned_data["class_date"]

            # Safety: ensure admin selected a slot matching the course.
            if slot.course_id != course.id:
                messages.error(request, "Selected schedule does not match the selected course.")
            else:
                try:
                    scheduled_at = compute_scheduled_at_from_date_and_timetable(
                        class_date, slot
                    )
                except ValueError as e:
                    messages.error(request, str(e))
                else:
                    online_class = OnlineClass.objects.create(
                        course=course,
                        title=form.cleaned_data["title"],
                        description=form.cleaned_data["description"],
                        scheduled_at=scheduled_at,
                        meeting_url=form.cleaned_data["meeting_url"],
                        reminder_offset_minutes=form.cleaned_data["reminder_offset_minutes"],
                        is_active=form.cleaned_data.get("is_active", True),
                        created_by=request.user,
                    )

                    # Create reminders for eligible students of this course.
                    due_at = scheduled_at - timedelta(
                        minutes=online_class.reminder_offset_minutes
                    )
                    if due_at < timezone.now():
                        due_at = timezone.now()

                    eligible_profiles = (
                        UserProfile.objects.select_related(
                            "user", "selected_timetable"
                        )
                        .filter(
                            selected_course=course,
                            selected_timetable__mode=Timetable.MODE_ONLINE,
                        )
                        .exclude(user__is_staff=True)
                        .exclude(user__is_superuser=True)
                        .distinct()
                    )
                    for prof in eligible_profiles:
                        Notification.objects.get_or_create(
                            user=prof.user,
                            online_class=online_class,
                            notification_type=Notification.NOTIF_ONLINE_CLASS,
                            defaults={
                                "message": f"Online class reminder: '{online_class.title}' starts at {online_class.scheduled_at}.",
                                "due_at": due_at,
                            },
                        )

                    messages.success(request, "Online class created successfully.")
                    return redirect("admin_online_classes")
    else:
        form = AdminOnlineClassForm()

    return render(
        request,
        "admin_online_class_form.html",
        {"form": form, "mode": "Add Online Class", "timetable_slots_for_js": timetable_slots_for_js},
    )


@login_required
def admin_online_class_edit(request, pk):
    if not is_admin_user(request.user):
        return redirect("dashboard")

    online_class = get_object_or_404(OnlineClass, pk=pk)

    timetable_slots_for_js = Timetable.objects.filter(
        mode=Timetable.MODE_ONLINE
    ).select_related("course").only("id", "course_id", "day", "time")

    if request.method == "POST":
        form = AdminOnlineClassForm(request.POST)
        if form.is_valid():
            course = form.cleaned_data["course"]
            slot = form.cleaned_data["timetable_slot"]
            class_date = form.cleaned_data["class_date"]

            if slot.course_id != course.id:
                messages.error(request, "Selected schedule does not match the selected course.")
            else:
                try:
                    scheduled_at = compute_scheduled_at_from_date_and_timetable(
                        class_date, slot
                    )
                except ValueError as e:
                    messages.error(request, str(e))
                else:
                    online_class.course = course
                    online_class.title = form.cleaned_data["title"]
                    online_class.description = form.cleaned_data["description"]
                    online_class.scheduled_at = scheduled_at
                    online_class.meeting_url = form.cleaned_data["meeting_url"]
                    online_class.reminder_offset_minutes = form.cleaned_data[
                        "reminder_offset_minutes"
                    ]
                    online_class.is_active = form.cleaned_data.get("is_active", True)
                    online_class.save()

                    # Refresh notifications to avoid stale reminders.
                    Notification.objects.filter(
                        online_class=online_class,
                        notification_type=Notification.NOTIF_ONLINE_CLASS,
                    ).delete()

                    due_at = scheduled_at - timedelta(
                        minutes=online_class.reminder_offset_minutes
                    )
                    if due_at < timezone.now():
                        due_at = timezone.now()

                    eligible_profiles = (
                        UserProfile.objects.select_related(
                            "user", "selected_timetable"
                        )
                        .filter(
                            selected_course=course,
                            selected_timetable__mode=Timetable.MODE_ONLINE,
                        )
                        .exclude(user__is_staff=True)
                        .exclude(user__is_superuser=True)
                        .distinct()
                    )
                    for prof in eligible_profiles:
                        Notification.objects.create(
                            user=prof.user,
                            online_class=online_class,
                            notification_type=Notification.NOTIF_ONLINE_CLASS,
                            message=f"Online class reminder: '{online_class.title}' starts at {online_class.scheduled_at}.",
                            due_at=due_at,
                        )

                    messages.success(request, "Online class updated successfully.")
                    return redirect("admin_online_classes")
    else:
        inferred_slot = infer_timetable_slot_from_online_class(online_class)
        form = AdminOnlineClassForm(
            initial={
                "course": online_class.course,
                "timetable_slot": inferred_slot,
                "class_date": online_class.scheduled_at.date(),
                "title": online_class.title,
                "description": online_class.description,
                "meeting_url": online_class.meeting_url,
                "reminder_offset_minutes": online_class.reminder_offset_minutes,
                "is_active": online_class.is_active,
            }
        )

    return render(
        request,
        "admin_online_class_form.html",
        {"form": form, "mode": "Edit Online Class", "timetable_slots_for_js": timetable_slots_for_js},
    )


@login_required
def admin_online_class_delete(request, pk):
    if not is_admin_user(request.user):
        return redirect("dashboard")

    online_class = get_object_or_404(OnlineClass, pk=pk)

    if request.method == "POST":
        online_class.delete()
        messages.success(request, "Online class deleted successfully.")
        return redirect("admin_online_classes")

    return render(
        request,
        "admin_confirm_delete.html",
        {"obj": online_class, "type_name": "Online Class"},
    )


# ----------------------------
# Admin panel: Programs
# ----------------------------


@login_required
def admin_programs(request):
    if not is_admin_user(request.user):
        return redirect("dashboard")

    programs = Program.objects.select_related("course").all().order_by("-starts_at")
    return render(request, "admin_programs.html", {"programs": programs})


@login_required
def admin_program_add(request):
    if not is_admin_user(request.user):
        return redirect("dashboard")

    if request.method == "POST":
        form = ProgramForm(request.POST)
        if form.is_valid():
            program = form.save(commit=False)
            program.save()

            due_at = program.starts_at - timedelta(minutes=60)
            if due_at < timezone.now():
                due_at = timezone.now()

            eligible_profiles = (
                UserProfile.objects.exclude(user__is_staff=True)
                .exclude(user__is_superuser=True)
            )
            if program.course:
                eligible_profiles = eligible_profiles.filter(selected_course=program.course)
            else:
                eligible_profiles = eligible_profiles.exclude(selected_course__isnull=True)

            eligible_profiles = eligible_profiles.distinct().select_related("user")
            for prof in eligible_profiles:
                Notification.objects.get_or_create(
                    user=prof.user,
                    program=program,
                    notification_type=Notification.NOTIF_PROGRAM,
                    defaults={
                        "message": f"Program reminder: '{program.title}' starts at {program.starts_at}.",
                        "due_at": due_at,
                    },
                )
            messages.success(request, "Program created successfully.")
            return redirect("admin_programs")
    else:
        form = ProgramForm()

    return render(request, "admin_program_form.html", {"form": form, "mode": "Add Program"})


@login_required
def admin_program_edit(request, pk):
    if not is_admin_user(request.user):
        return redirect("dashboard")

    program = get_object_or_404(Program, pk=pk)

    if request.method == "POST":
        form = ProgramForm(request.POST, instance=program)
        if form.is_valid():
            program = form.save(commit=False)
            program.save()

            due_at = program.starts_at - timedelta(minutes=60)
            if due_at < timezone.now():
                due_at = timezone.now()

            eligible_profiles = (
                UserProfile.objects.exclude(user__is_staff=True)
                .exclude(user__is_superuser=True)
            )
            if program.course:
                eligible_profiles = eligible_profiles.filter(selected_course=program.course)
            else:
                eligible_profiles = eligible_profiles.exclude(selected_course__isnull=True)

            eligible_profiles = eligible_profiles.distinct().select_related("user")

            for prof in eligible_profiles:
                Notification.objects.update_or_create(
                    user=prof.user,
                    program=program,
                    notification_type=Notification.NOTIF_PROGRAM,
                    defaults={
                        "message": f"Program reminder: '{program.title}' starts at {program.starts_at}.",
                        "due_at": due_at,
                    },
                )
            messages.success(request, "Program updated successfully.")
            return redirect("admin_programs")
    else:
        form = ProgramForm(instance=program)

    return render(request, "admin_program_form.html", {"form": form, "mode": "Edit Program"})


@login_required
def admin_program_delete(request, pk):
    if not is_admin_user(request.user):
        return redirect("dashboard")

    program = get_object_or_404(Program, pk=pk)

    if request.method == "POST":
        program.delete()
        messages.success(request, "Program deleted successfully.")
        return redirect("admin_programs")

    return render(
        request,
        "admin_confirm_delete.html",
        {"obj": program, "type_name": "Program"},
    )


# ----------------------------
# Admin panel: Monthly fees
# ----------------------------


@login_required
def admin_monthly_fees(request):
    if not is_admin_user(request.user):
        return redirect("dashboard")

    dt_now = timezone.now()

    student_profiles = (
        UserProfile.objects.select_related("user", "selected_course")
        .exclude(user__is_staff=True)
        .exclude(user__is_superuser=True)
        .order_by("user__username")
    )

    rows = []
    for prof in student_profiles:
        cycle_key = get_fee_cycle_key_for_user(prof.user, now=dt_now)
        cycle_start = get_fee_cycle_start_for_user(prof.user, cycle_key)
        paid = MonthlyFeePayment.objects.filter(profile=prof, month=cycle_key).first()
        rows.append(
            {
                "profile": prof,
                "cycle_key": cycle_key,
                "cycle_start": cycle_start,
                "paid": paid is not None,
                "payment": paid,
                "amount": int(prof.selected_course.fee) if prof.selected_course else 0,
            }
        )

    return render(
        request,
        "admin_monthly_fees.html",
        {"rows": rows},
    )

# Logout
def logout_view(request):
    logout(request)
    return redirect('/')