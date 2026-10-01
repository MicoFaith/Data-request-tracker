import re
from datetime import timedelta
from zoneinfo import ZoneInfo

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import DatasetRequest, User


def normalize_task(value):
    return " ".join(value.strip().casefold().split())


def kigali_today():
    return timezone.localdate(timezone=ZoneInfo("Africa/Kigali"))


class EpisodeCountField(forms.IntegerField):
    def to_python(self, value):
        if value not in self.empty_values and (
            isinstance(value, bool) or not re.fullmatch(r"[0-9]+", str(value).strip())
        ):
            raise ValidationError("Enter a whole number of episodes.")
        return super().to_python(value)


class RequestForm(forms.Form):
    task_name = forms.CharField(
        max_length=160,
        help_text="Describe the recording task, for example pick cup.",
        widget=forms.TextInput(attrs={"placeholder": "e.g. pick cup"}),
    )
    episodes_requested = EpisodeCountField(
        min_value=1,
        max_value=1000000,
        label="Number of episodes",
        help_text="A whole number from 1 to 1,000,000.",
    )
    deadline = forms.DateField(
        input_formats=["%Y-%m-%d"],
        widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
        help_text="Choose tomorrow or later (Kigali time).",
    )
    notes = forms.CharField(
        max_length=4000,
        required=False,
        help_text="Add preferences or delivery requirements. Up to 4,000 characters.",
        widget=forms.Textarea(
            attrs={"rows": 4, "placeholder": "What should the operations team know?"}
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["deadline"].widget.attrs["min"] = (
            kigali_today() + timedelta(days=1)
        ).isoformat()

    def clean_task_name(self):
        name = normalize_task(self.cleaned_data["task_name"])
        if not name:
            raise ValidationError("Task name is required.")
        if len(name) > 160:
            raise ValidationError(
                "Task name must be at most 160 characters after normalization."
            )
        return name

    def clean_deadline(self):
        deadline = self.cleaned_data["deadline"]
        if deadline <= kigali_today():
            raise ValidationError(
                "Deadline must be a future date (tomorrow or later in Kigali)."
            )
        return deadline


class NewUserForm(forms.Form):
    email = forms.EmailField(max_length=User._meta.get_field("username").max_length)
    name = forms.CharField(max_length=120)
    organisation = forms.CharField(max_length=120, required=False)
    role = forms.ChoiceField(choices=User.Role.choices)
    password = forms.CharField(
        min_length=12,
        max_length=128,
        strip=False,
        help_text="Use 12–128 characters. Share credentials with the user securely.",
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if len(email) > User._meta.get_field("username").max_length:
            raise ValidationError(
                "Email must be at most 150 characters for this login system."
            )
        return email

    def clean_password(self):
        password = self.cleaned_data["password"]
        if not password.strip():
            raise ValidationError("Password cannot contain only whitespace.")
        return password


class RequestFilterForm(forms.Form):
    q = forms.CharField(max_length=160, required=False)
    status = forms.ChoiceField(
        choices=[("", "All statuses"), *DatasetRequest.Status.choices], required=False
    )
    attention = forms.ChoiceField(
        choices=[("", "All deadlines"), ("overdue", "Overdue")], required=False
    )
    sort = forms.ChoiceField(
        choices=[("newest", "Newest first"), ("deadline", "Deadline first")],
        required=False,
    )


class EpisodeFilterForm(forms.Form):
    task_name = forms.CharField(max_length=160, required=False)
    quality = forms.ChoiceField(
        choices=[
            ("", "All quality"),
            ("good", "Good"),
            ("usable", "Usable"),
            ("bad", "Bad"),
        ],
        required=False,
    )
    available = forms.ChoiceField(
        choices=[("", "All episodes"), ("true", "Unassigned"), ("false", "Assigned")],
        required=False,
    )


class AnalyticsFilterForm(forms.Form):
    start = forms.DateField(
        label="Start date",
        input_formats=["%Y-%m-%d"],
        widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
    )
    end = forms.DateField(
        label="End date",
        input_formats=["%Y-%m-%d"],
        widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
    )

    def clean(self):
        values = super().clean()
        start, end = values.get("start"), values.get("end")
        if start and start.year < 2:
            self.add_error("start", "Choose a year from 0002 onward.")
        if end and end.year == 9999:
            self.add_error("end", "Choose a year before 9999.")
        if start and end and start > end:
            self.add_error("end", "End date must be on or after the start date.")
        return values


class UserFilterForm(forms.Form):
    q = forms.CharField(max_length=160, required=False)
    role = forms.ChoiceField(
        choices=[("", "All roles"), *User.Role.choices], required=False
    )
    active = forms.ChoiceField(
        choices=[("", "All accounts"), ("true", "Active"), ("false", "Inactive")],
        required=False,
    )
