# Datos de usuarios y RGPD

Resumen práctico de qué datos personales guarda la app, para qué y cómo se cumplen los
derechos de los usuarios. Sirve de base para la política de privacidad y para el registro
de actividades de tratamiento. **No es asesoramiento jurídico**: revisarlo con un
abogado o un delegado de protección de datos antes del lanzamiento.

Implementación técnica: `supabase/app_usuarios.sql` (pruebas en `tests/sql/`).

## Qué se guarda

| Dato | Tabla | Finalidad | Base legal | Conservación |
|---|---|---|---|---|
| Correo y contraseña (cifrada) | `auth.users` (Supabase Auth) | Acceso a la cuenta | Contrato (términos de uso) | Mientras exista la cuenta |
| Alias, avatar, idioma, privacidad | `app.perfiles` | Mostrar el perfil | Contrato | Mientras exista la cuenta |
| Cimas subidas y fecha | `app.ascensiones` | Función principal de la app | Contrato | Mientras exista la cuenta |
| Distancia a la cumbre al registrar | `app.ascensiones` | Verificar la ascensión | Consentimiento (`ubicacion`) | Mientras exista la cuenta |
| Recorridos GPS (tracks) | `app.tracks` | Guardar la ruta | Consentimiento (`tracks`) | **2 años** (`app.conservacion_tracks()`) |
| Historial de consentimientos | `app.consentimientos` | Demostrar el consentimiento | Obligación legal | Mientras exista la cuenta |

Lo que **no** se guarda: nombre real, fecha de nacimiento, teléfono, ni la posición GPS
al registrar una cima (se usa para calcular la distancia y se descarta).

## Privacidad desde el diseño

- Perfiles y ascensiones **privados por defecto**; el usuario decide hacerlos públicos.
- Los tracks se guardan **recortados 200 m** en cada extremo (ajustable por el usuario en
  `recorte_privacidad_m`) para no revelar el domicilio ni dónde aparca.
- Row Level Security en todas las tablas: cada usuario solo accede a lo suyo. Los
  visitantes sin sesión no ven nada de usuarios.
- La verificación GPS la calcula el servidor: el usuario no puede marcarla a mano.
- Datos de usuarios separados del catálogo de cimas (esquema `app` frente a `catalogo`).
- Servidor en la UE (proyecto de Supabase en Frankfurt o París).

## Derechos de los usuarios

| Derecho | Cómo se ejerce en la app |
|---|---|
| Acceso y portabilidad | `app.exportar_mis_datos()` devuelve todos sus datos en JSON |
| Rectificación | Editar perfil y ascensiones desde la app |
| Supresión | `app.borrar_mi_cuenta()` borra la cuenta y, en cascada, todos sus datos |
| Retirar el consentimiento | Añadir un consentimiento con `aceptado = false`; si es el de tracks, se borran sus tracks al momento |

## Tareas pendientes fuera de la base de datos

- Redactar la política de privacidad y los términos, con su número de versión (es el
  `version_texto` que se guarda con cada consentimiento).
- Pantallas de consentimiento en FlutterFlow **antes** de pedir permisos de ubicación.
- Si se añaden fotos (Supabase Storage), borrarlas también al eliminar la cuenta.
- Activar `pg_cron` para la purga diaria de tracks caducados (ver final del SQL).
- Firmar el acuerdo de encargado de tratamiento (DPA) con Supabase.
