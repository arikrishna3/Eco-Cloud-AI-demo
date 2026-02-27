from django import forms

from .models import SustainabilityTip


class SustainabilityTipForm(forms.ModelForm):
    class Meta:
        model = SustainabilityTip
        fields = ["title", "description"]