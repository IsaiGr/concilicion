# Conciliación de recepciones — navegador local

Esta variante procesa un libro consolidado `.xlsx` dentro del navegador. No tiene cuentas, API de carga, base de datos ni almacenamiento de corridas. El resultado se descarga como `.xlsx` y la revisión se conserva únicamente mientras esta pestaña siga abierta; **Cerrar revisión** y recargar la vacían. Acepta formatos de tres y cuatro hojas probados con datos ficticios; la hoja WK puede estar ausente o vacía cuando el perfil lo permite.

## Construcción local

Requiere Node.js y npm. Desde esta carpeta:

```powershell
npm ci --ignore-scripts
npm run build
npm run serve
```

`dist/` es el sitio estático. `npm run serve` abre `http://127.0.0.1:8767/` solo en este equipo; sirve `.mjs` como `text/javascript`, `.wasm` como `application/wasm` y rechaza `POST`. No uses `python -m http.server` para esta prueba: en el entorno comprobado entrega `.mjs` como `text/plain` y el navegador bloquea el Worker antes de cargar Pyodide. `file://` tampoco permite cargar los módulos y recursos del motor. Vercel usa `vercel.json` para ejecutar el build, publicar `dist/` y aplicar cabeceras de seguridad. Este paquete **no autoriza el despliegue ni el uso de datos reales**: requiere revisión independiente de calidad y decisión de lanzamiento.

## Datos y límites

- El selector acepta un solo `.xlsx` de hasta 8 MB; el adaptador comprueba también límites de expansión ZIP. Las filas que no pueda interpretar pasan a Atención cuando el núcleo las clasifica así.
- Los repartos son decisiones explícitas en memoria; se pueden retirar. La descarga mantiene abierta la revisión hasta **Cerrar revisión**.
- El archivo descargado contiene las cinco hojas del exportador canónico. Debe cotejarse antes de utilizarlo en el proceso operativo. No ingresa datos en SAP ni modifica el Excel de entrada.
- El JavaScript del sitio crea un `Web Worker`, le transfiere los bytes del archivo y el motor Python procesa allí. No hay solicitud HTTP que incluya el libro. El archivo descargado sí queda en el dispositivo del usuario.
- El paquete incluye Pyodide, openpyxl, et_xmlfile y defusedxml con versiones y SHA-256 fijados. No requiere CDN en tiempo de ejecución. El sitio debe servirse por HTTPS en cualquier entorno remoto.

## Procedencia y comprobación

`engine/` es una copia de despliegue generada desde el núcleo canónico `../ui/`. `engine/engine-manifest.json` fija sus hashes. `vendor_wheels/wheels-manifest.json` fija los wheels Python. `scripts/build.mjs` verifica ambos manifiestos y produce `dist/asset-manifest.json`, que el Web Worker verifica antes de ejecutar el motor. Cambios en el núcleo canónico requieren regenerar esta copia con revisión y pruebas; no editarla como variante separada.

Los fixtures de prueba permanecen fuera de esta carpeta, en `../web_vercel/fixtures/`, y **no** se incorporan al sitio o al paquete GitHub. En el árbol interno del proyecto, `npm test` usa esos fixtures en la ruta adyacente. El paquete GitHub no incluye las pruebas ni sus datos; `npm run build` funciona de forma independiente.

Para crear una carpeta fuente autocontenida para GitHub, sin ejemplos ni salidas de pruebas:

```powershell
node scripts/package-github.mjs
```

La salida `github_ready/` contiene solo fuentes, dependencias Python fijadas, manifiestos y configuración. Subir esa carpeta a un repositorio privado y construir con `npm ci --ignore-scripts` y `npm run build`. Antes de cargar archivos de empresa en cualquier despliegue, TI debe revisar el código, dependencias, dominio, cabeceras y política de acceso. La URL por sí sola no restringe quién puede abrirla.

## Reversión

Eliminar la carpeta publicada o retirar el despliegue. No hay esquema, migración ni datos persistidos por la aplicación que revertir. La descarga realizada por cada usuario permanece bajo su control.
