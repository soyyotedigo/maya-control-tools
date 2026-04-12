# Public Sync Commands

Guia rapida para sincronizar este repo de desarrollo (`maya-control-tools-dev`) con el repo publico (`maya-control-tools`).

## Flujo recomendado

1. Ejecutar sincronizacion desde la raiz del repo dev:

```bash
bash ./scripts/sync-public.sh
```

2. O si ya estas dentro de `scripts/`:

```bash
bash sync-public.sh
```

3. Empujar cambios al repo publico:

```bash
git -C C:/repos/maya-control-tools push
```

## Comandos utiles

Crear repo publico si no existe (y clonarlo):

```bash
gh repo create soyyotedigo/maya-control-tools --public --clone
```

Validar autenticacion de GitHub CLI:

```bash
gh auth status
```

Ver estado del repo publico local:

```bash
git -C C:/repos/maya-control-tools status
```

Ver cambios antes de push:

```bash
git -C C:/repos/maya-control-tools diff --stat
```

Forzar formato LF del script si Bash marca errores de `\r` o `pipefail`:

```bash
sed -i 's/\r$//' scripts/sync-public.sh
```

## Errores comunes

Ruta mal escrita en Bash:

- Incorrecto: `.scripts\sync-public.sh`
- Correcto: `./scripts/sync-public.sh`

Motivo: Bash usa `/` y no `\` para rutas.

Error `Public repo not found`:

- Asegurate de tener este path local: `C:/repos/maya-control-tools`
- Si no existe, crea/clona con el comando de `gh repo create` de arriba.

Error `cannot create directory ... docs/screenshots`:

- El script ya crea `docs/` antes de copiar screenshots.
- Si persiste, reintenta desde la raiz del repo:

```bash
cd C:/repos/maya-control-tools-dev
bash ./scripts/sync-public.sh
```
