# pedidos/forms.py
from django import forms
from django.contrib.auth.models import User
from .models import ClienteProfile


class ClienteSignupForm(forms.ModelForm):
    # Campos visibles del registro simple
    username = forms.CharField(
        label="Usuario",
        max_length=150,
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "Elegí un usuario",
            "autocomplete": "username",
        }),
        help_text="",
    )
    first_name = forms.CharField(
        label="Nombre",
        max_length=150,
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "Tu nombre",
            "autocomplete": "given-name",
        }),
        help_text="",
    )
    last_name = forms.CharField(
        label="Apellido",
        max_length=150,
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "Tu apellido",
            "autocomplete": "family-name",
        }),
        help_text="",
    )
    email = forms.EmailField(
        label="Email",
        widget=forms.EmailInput(attrs={
            "class": "form-control",
            "placeholder": "tuemail@gmail.com",
            "autocomplete": "email",
        }),
        help_text="",
    )
    password1 = forms.CharField(
        label="Contraseña",
        widget=forms.PasswordInput(attrs={
            "class": "form-control",
            "placeholder": "Mínimo 6 caracteres",
            "autocomplete": "new-password",
        }),
        help_text="Mínimo 6 caracteres.",
    )
    password2 = forms.CharField(
        label="Confirmar contraseña",
        widget=forms.PasswordInput(attrs={
            "class": "form-control",
            "placeholder": "Repetí la contraseña",
            "autocomplete": "new-password",
        }),
        help_text="",
    )

    class Meta:
        model = User
        fields = ["username", "first_name", "last_name", "email"]
        # Por si algún template mostrara help_text del modelo:
        help_texts = {
            "username": "",
            "first_name": "",
            "last_name": "",
            "email": "",
        }

    # ---------- Validaciones simples ----------
    def clean_username(self):
        u = (self.cleaned_data.get("username") or "").strip()
        if not u:
            raise forms.ValidationError("Ingresá un usuario.")
        if User.objects.filter(username__iexact=u).exists():
            raise forms.ValidationError("Ese usuario ya existe.")
        return u

    def clean_first_name(self):
        return (self.cleaned_data.get("first_name") or "").strip()

    def clean_last_name(self):
        return (self.cleaned_data.get("last_name") or "").strip()

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip().lower()
        if not email:
            raise forms.ValidationError("Ingresá un email.")
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Ya existe una cuenta con ese email.")
        return email

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get("password1") or ""
        p2 = cleaned.get("password2") or ""
        if len(p1) < 6:
            self.add_error("password1", "La contraseña debe tener al menos 6 caracteres.")
        if p1 != p2:
            self.add_error("password2", "Las contraseñas no coinciden.")
        return cleaned

    # ---------- Guardado ----------
    def save(self, commit=True):
        user = super().save(commit=False)
        user.username = self.cleaned_data["username"].strip()
        user.first_name = self.cleaned_data["first_name"].strip()
        user.last_name = self.cleaned_data["last_name"].strip()
        user.email = self.cleaned_data["email"]
        user.is_staff = False
        user.is_superuser = False
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
        return user


class ClienteProfileForm(forms.ModelForm):
    """
    Form de perfil usado en views.perfil_cliente:
    edita teléfono/dirección del perfil y, en el mismo form,
    nombre, apellido y email del User.
    """
    first_name = forms.CharField(
        label="Nombre",
        max_length=150,
        widget=forms.TextInput(attrs={"class": "form-control"}),
        required=False,
    )
    last_name = forms.CharField(
        label="Apellido",
        max_length=150,
        widget=forms.TextInput(attrs={"class": "form-control"}),
        required=False,
    )
    email = forms.EmailField(
        label="Email",
        widget=forms.EmailInput(attrs={"class": "form-control"}),
        required=False,
    )

    class Meta:
        model = ClienteProfile
        fields = ["telefono", "direccion"]
        widgets = {
            "telefono": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ej: 3834 123456"}),
            "direccion": forms.TextInput(attrs={"class": "form-control", "placeholder": "Calle y número"}),
        }
        help_texts = {"telefono": "", "direccion": ""}

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip().lower()
        if not email:
            return email
        qs = User.objects.exclude(pk=getattr(self.instance, "user_id", None))
        if qs.filter(email__iexact=email).exists():
            raise forms.ValidationError("Ya existe una cuenta con ese email.")
        return email
