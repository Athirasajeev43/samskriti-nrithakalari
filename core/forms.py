from django import forms

from .models import (
    Booking,
    Course,
    FeedbackSubmission,
    GalleryImage,
    Instructor,
    ContactInfo,
    MonthlyFeePayment,
    OnlineClass,
    Program,
    ContactSubmission,
    Timetable,
    UserProfile,
)
from django.contrib.auth.models import User


class RegisterForm(forms.Form):
    username = forms.CharField(max_length=150)
    password = forms.CharField(widget=forms.PasswordInput)

    date_of_birth = forms.DateField(
        widget=forms.DateInput(attrs={'type': 'date'})
    )

    phone = forms.CharField(max_length=15)

class CourseForm(forms.ModelForm):
    class Meta:
        model = Course
        fields = ["name", "description", "duration", "fee", "is_active", "image"]


class TimetableForm(forms.ModelForm):
    class Meta:
        model = Timetable
        fields = ["course", "day", "time", "mode"]


class InstructorForm(forms.ModelForm):
    class Meta:
        model = Instructor
        fields = [
            "name",
            "specialization",
            "experience",
            "about",
            "education_details",
            "teaching_details",
            "performance_details",
            "contact_phone",
            "contact_email",
            "location",
            "image",
        ]


class GalleryImageForm(forms.ModelForm):
    class Meta:
        model = GalleryImage
        fields = ["title", "image", "description"]


class UserProfileForm(forms.ModelForm):
    """
    Used for editing student profile and admin profile.
    """

    class Meta:
        model = UserProfile
        fields = ["date_of_birth", "phone", "address", "profile_image"]

        widgets = {
            "date_of_birth": forms.DateInput(attrs={"type": "date"}),
        }
        
class AdminUserEditForm(forms.Form):
    """
    Custom admin profile editing: name + email + (optional) new password.
    We edit Django's `User` model fields (not `UserProfile`).
    """

    name = forms.CharField(max_length=150)
    email = forms.EmailField()
    new_password = forms.CharField(
        widget=forms.PasswordInput, required=False, help_text="Leave blank to keep current password."
    )


class OnlineClassForm(forms.ModelForm):
    class Meta:
        model = OnlineClass
        fields = [
            "course",
            "title",
            "description",
            "scheduled_at",
            "meeting_url",
            "reminder_offset_minutes",
            "is_active",
        ]


class TimetableSlotChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.day} | {obj.time}"


class AdminOnlineClassForm(forms.Form):
    """
    Admin form to create/update OnlineClass using:
    - course
    - timetable slot (day + time range; only mode=Online)
    - explicit schedule date (so scheduled_at is concrete DateTime)
    """

    course = forms.ModelChoiceField(
        queryset=Course.objects.filter(is_active=True).order_by("name"),
        required=True,
        label="Course",
    )

    timetable_slot = TimetableSlotChoiceField(
        queryset=Timetable.objects.filter(mode=Timetable.MODE_ONLINE).select_related("course").order_by("day", "time"),
        required=True,
        label="Schedule (Day + Time)",
        empty_label="Select Schedule",
    )

    class_date = forms.DateField(
        required=True,
        label="Schedule Date",
        widget=forms.DateInput(attrs={"type": "date"}),
    )

    title = forms.CharField(max_length=200, required=True, label="Class Title")
    description = forms.CharField(
        required=False, label="Description", widget=forms.Textarea(attrs={"rows": 3})
    )
    meeting_url = forms.URLField(required=True, label="Meeting URL")
    reminder_offset_minutes = forms.IntegerField(
        required=True,
        min_value=0,
        initial=60,
        label="Reminder Offset (minutes)",
    )
    is_active = forms.BooleanField(required=False, initial=True, label="Active")


class ProgramForm(forms.ModelForm):
    class Meta:
        model = Program
        fields = ["title", "course", "starts_at", "description"]


class FeedbackForm(forms.ModelForm):
    class Meta:
        model = FeedbackSubmission
        fields = ["message"]


class ContactUsForm(forms.ModelForm):
    class Meta:
        model = ContactSubmission
        fields = ["name", "email", "phone", "message"]


class ContactInfoForm(forms.ModelForm):
    class Meta:
        model = ContactInfo
        fields = ["phone", "email", "address"]
