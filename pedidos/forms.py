# pedidos/forms.py

from django import forms
from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from django.contrib.auth.models import User
from .models import ClienteProfile # Importamos nuestro modelo ClienteProfile

# Formulario para el registro de nuevos usuarios
class ClienteRegisterForm(UserCreationForm):
    # Campos básicos del usuario
    email = forms.EmailField(required=True, help_text='Dirección de correo electrónico (será tu nombre de usuario).')
    first_name = forms.CharField(max_length=150, required=False, label='Nombre')
    last_name = forms.CharField(max_length=150, required=False, label='Apellido')

    # Campos adicionales para ClienteProfile
    direccion = forms.CharField(max_length=255, required=False, label='Dirección')
    telefono = forms.CharField(max_length=20, required=False, label='Teléfono')

    class Meta(UserCreationForm.Meta):
        model = User
        fields = UserCreationForm.Meta.fields + ('email', 'first_name', 'last_name', 'direccion', 'telefono',)

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email'] # Asegurarse de que el email se guarde en el User
        if commit:
            user.save()
            # Crear o actualizar el ClienteProfile
            cliente_profile = ClienteProfile.objects.get_or_create(user=user)[0]
            cliente_profile.direccion = self.cleaned_data['direccion']
            cliente_profile.telefono = self.cleaned_data['telefono']
            cliente_profile.save()
        return user

# Formulario para editar el perfil del cliente
class ClienteProfileForm(forms.ModelForm):
    first_name = forms.CharField(max_length=150, required=False, label='Nombre')
    last_name = forms.CharField(max_length=150, required=False, label='Apellido')
    email = forms.EmailField(required=True, label='Correo Electrónico')

    class Meta:
        model = ClienteProfile
        fields = ['direccion', 'telefono'] # Solo los campos del perfil

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Pre-cargar los datos del User asociado al perfil
        if self.instance and self.instance.user:
            self.initial['first_name'] = self.instance.user.first_name
            self.initial['last_name'] = self.instance.user.last_name
            self.initial['email'] = self.instance.user.email

    def save(self, commit=True):
        profile = super().save(commit=False)
        user = profile.user

        # Actualizar los campos del User
        user.first_name = self.cleaned_data['first_name']
        user.last_name = self.cleaned_data['last_name']
        user.email = self.cleaned_data['email']

        if commit:
            user.save()
            profile.save() # Guardar también el perfil

        return profile