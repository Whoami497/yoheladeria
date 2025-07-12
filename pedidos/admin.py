from django.contrib import admin
from django import forms # Importa forms
import os # Importa os para listar archivos
from django.conf import settings # Importa settings para BASE_DIR y STATIC_URL
from django.utils.html import format_html # Importa format_html para renderizar HTML seguro

from .models import Producto, Sabor, Pedido, DetallePedido

# --- Formulario personalizado para Producto en el Admin (para seleccionar imágenes estáticas) ---
class ProductoAdminForm(forms.ModelForm):
    imagen = forms.ChoiceField(
        label="Imagen del Producto",
        required=False,
        help_text="Selecciona una imagen de la carpeta 'static/images/'. Las imágenes deben subirse directamente al proyecto (vía Git/FTP)."
    )

    class Meta:
        model = Producto
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Ruta donde buscamos las imágenes estáticas
        static_images_path = os.path.join(settings.BASE_DIR, 'static', 'images')
        
        image_choices = [('', '---------')] # Opción por defecto (Ninguna)

        # Si la carpeta static/images existe, listar sus contenidos
        if os.path.exists(static_images_path):
            for filename in os.listdir(static_images_path):
                # Filtrar solo archivos de imagen
                if filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
                    # La ruta que Django guardará en la DB es relativa a static/
                    relative_path = os.path.join('images', filename) # Ej: 'images/helado_vainilla.png'
                    image_choices.append((relative_path, filename)) # (valor a guardar, texto a mostrar)
        
        # Asignar las opciones al campo 'imagen' del formulario
        self.fields['imagen'].choices = image_choices
        
        # Si ya hay una instancia (editando un producto existente), selecciona la imagen actual
        if self.instance.pk and self.instance.imagen:
            # Asegurarse de que el valor actual del campo sea una de las opciones
            if self.instance.imagen in [choice[0] for choice in image_choices]:
                self.initial['imagen'] = self.instance.imagen
            else: # Si la imagen guardada no está en las opciones actuales (ej. fue borrada), resetear
                self.initial['imagen'] = ''


# --- Clase ModelAdmin personalizada para Producto ---
class ProductoAdmin(admin.ModelAdmin):
    form = ProductoAdminForm # Usar nuestro formulario personalizado
    
    list_display = ('nombre', 'precio', 'sabores_maximos', 'disponible', 'display_image_thumbnail')
    list_filter = ('disponible',)
    search_fields = ('nombre', 'descripcion')

    # Función para mostrar la miniatura de la imagen en la lista del admin
    def display_image_thumbnail(self, obj):
        if obj.imagen: # Si el producto tiene una imagen asignada (la cadena de texto)
            # Construimos la URL estática usando settings.STATIC_URL
            # y usamos format_html para que Django lo renderice como HTML seguro
            return format_html('<img src="{}{}" style="width:50px; height:auto; border-radius:5px;" />', settings.STATIC_URL, obj.imagen)
        return "No Image" # Texto si no hay imagen
    display_image_thumbnail.short_description = 'Thumbnail' # Título de la columna

# Registra tus modelos en el admin.
admin.site.register(Producto, ProductoAdmin) # Registramos Producto con nuestra clase ProductoAdmin
admin.site.register(Sabor)
admin.site.register(Pedido)
admin.site.register(DetallePedido)