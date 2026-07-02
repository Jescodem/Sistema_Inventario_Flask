# Acceso desde la red local (HTTP + proxy inverso)

`lanzar.bat` levanta un **proxy inverso** ([Caddy](https://caddyserver.com))
en el **puerto 80** delante de la aplicación Flask. Así cualquier equipo de
la red local entra sin instalar nada.

```
Navegador ──HTTP──► Caddy (:80) ──► Flask (127.0.0.1:5051)
```

> ⚠️ **Es HTTP, sin cifrado.** Se eligió a propósito para no tener que
> instalar certificados en cada PC. Úsalo **solo en una red de confianza**
> (las contraseñas viajan sin cifrar por la red local). Si en el futuro
> quieres el candado, hace falta un dominio real (ver el final).

---

## Cómo se accede

Desde **cualquier** equipo de la red local:

| Forma | URL | Necesita |
|---|---|---|
| **Por IP** (funciona siempre) | `http://192.168.18.137` | Nada. Solo estar en la red. |
| **Por nombre** (bonito) | `http://inventario.porteroseguro.com` | Una entrada DNS en el router (una vez). |

La IP del servidor aparece en el banner al lanzar (`Por IP: http://...`).

## Qué hace `lanzar.bat`

1. Pide **permisos de administrador** (para el `hosts`, el firewall y el puerto 80).
2. Descarga `caddy.exe` la primera vez.
3. Abre el **firewall** para el puerto 80 (regla "Portero Seguro (Caddy)").
4. Registra el dominio en el `hosts` de **este** equipo (servidor).
5. Arranca Caddy + Flask. Ctrl+C detiene ambos.

---

## Que el NOMBRE funcione en todos los equipos (DNS en el router)

Para no tocar cada PC, se añade **una sola entrada** en el router
(`192.168.18.1`). Los pasos generales:

1. Abre el navegador y entra al router: `http://192.168.18.1`
   (usuario/clave suelen estar en una pegatina del propio router).
2. Reserva una **IP fija** para el servidor (`192.168.18.137`) en la
   sección de **DHCP / Reserva de direcciones** (así no cambia nunca).
3. Busca una sección tipo **"DNS local"**, **"DNS estático"**,
   **"Host Name Mapping"**, **"Dominios locales"** o similar, y crea:

   ```
   Nombre:  inventario.porteroseguro.com
   IP:      192.168.18.137
   ```
4. Guarda. En los clientes puede hacer falta reconectar el Wi-Fi (o
   ejecutar `ipconfig /flushdns`) para que tome el cambio.

> **¿El router no tiene esa opción?** Muchos routers de operador no la
> traen. Alternativas:
> - Usar simplemente la **IP**: `http://192.168.18.137` (cero configuración).
> - Ejecutar en cada equipo el *fallback* `configurar_cliente.bat 192.168.18.137`
>   (solo añade el nombre al `hosts` de ese PC).

---

## Solución de problemas

| Síntoma | Causa probable / solución |
|---|---|
| Por IP no abre desde otro PC | 1) El **firewall** del servidor bloquea el 80: `lanzar.bat` crea la regla; comprueba que exista. 2) Ambos equipos deben estar en la **misma red/subred** (`192.168.18.x`). 3) Prueba `Test-NetConnection 192.168.18.137 -Port 80` desde el cliente. |
| Por IP sí, por nombre no | Falta la entrada DNS en el router, o el cliente aún cachea; prueba `ipconfig /flushdns` o reconecta el Wi-Fi. |
| No arranca el proxy | Mira `logs/caddy.log`. Suele ser el **puerto 80 ocupado** por otro servicio (IIS, "World Wide Web Publishing Service", Skype antiguo…). |
| Se cierra sesión sola / no entra el login | La cookie de sesión no puede ser `Secure` sobre HTTP. Ya está resuelto (`SESSION_COOKIE_SECURE=false` en el launcher); no lo cambies a `true` mientras sea HTTP. |
| Falla la descarga de Caddy | Sin internet. Descarga `caddy.exe` a mano desde caddyserver.com/download (Windows, amd64) y ponlo junto a `lanzar.bat`. |

## Revertir los cambios del sistema

- **Quitar el dominio local del servidor:** borra la línea
  `... inventario.porteroseguro.com` de `C:\Windows\System32\drivers\etc\hosts`.
- **Quitar la regla de firewall:**
  `netsh advfirewall firewall delete rule name="Portero Seguro (Caddy)"`

---

## Si algún día quieres HTTPS (candado verde)

Con HTTP no hay candado. Para tenerlo **sin configurar cada PC** hace falta
un **dominio real registrado** (~10 €/año): se pone un registro DNS público
apuntando a la IP del servidor y Caddy obtiene un certificado gratis de
Let's Encrypt, en el que todos los navegadores confían automáticamente.
Si te interesa esa vía, pídelo y se adapta la configuración.
