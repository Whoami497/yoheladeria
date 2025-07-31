import base64
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

# 1. Generar un par de claves en la curva P-256
private_key = ec.generate_private_key(ec.SECP256R1())
public_key = private_key.public_key()

# 2. Obtener la clave privada como un número de 32 bytes
private_key_bytes = private_key.private_numbers().private_value.to_bytes(32, byteorder='big')

# 3. Obtener la clave pública en formato de punto no comprimido (estándar VAPID)
public_key_bytes = public_key.public_bytes(
    encoding=serialization.Encoding.X962,
    format=serialization.PublicFormat.UncompressedPoint
)

# 4. Codificar ambas claves en Base64 URL-safe
encoded_private_key = base64.urlsafe_b64encode(private_key_bytes).rstrip(b'=').decode('utf-8')
encoded_public_key = base64.urlsafe_b64encode(public_key_bytes).rstrip(b'=').decode('utf-8')

# 5. Imprimir las claves
print("\n--- ¡Claves Generadas con Éxito! ---\n")
print(f"VAPID_PUBLIC_KEY = '{encoded_public_key}'")
print(f"VAPID_PRIVATE_KEY = '{encoded_private_key}'")
print("\n--- Copia estas claves en tu archivo settings.py ---\n")