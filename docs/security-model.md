# Modelo de seguridad del harness

El harness asume que un agente puede equivocarse, desviarse o ser demasiado "servicial". Las reglas
importantes no se le piden: **se le imponen** con hooks de Claude Code (`.claude/hooks/`) y con el
sistema de permisos (`.claude/settings.json`).

## Capas

| Capa | Mecanismo | Qué garantiza |
|---|---|---|
| Escritura de ficheros | `guard_write.py` (PreToolUse) | propiedad por rol, fase, scope, rutas protegidas, secretos |
| Shell | `guard_bash.py` (PreToolUse) | orgs permitidas, puertas humanas, git seguro, el shell no esquiva la capa anterior |
| Revisión inmediata | `post_edit_checks.py` (PostToolUse) | errores típicos de Salesforce detectados al guardar |
| Traspaso | `subagent_start.py` / `subagent_stop.py` | contexto inyectado; nadie termina sin entregable |
| Continuidad | `session_context.py`, `stop_guard.py` | el estado se relee de disco; queda nota del próximo paso |
| Estado | `./hx` (CLI) | transiciones solo con precondiciones y evidencia vigente |
| Permisos | `settings.json` | `ask` en puertas humanas y push; `deny` a credenciales; sin modo bypass |

## Qué se bloquea

**Orgs**
- Solo existen la org de desarrollo (`org.targetOrgAlias`), la de validación (check-only) y el DevHub
  (crear la scratch). Cualquier otro alias o usuario → bloqueado.
- Los alias de `org.protectedAliases` (producción) → bloqueados para todo, lecturas incluidas.
- `--target-org` explícito siempre: el harness no se fía de la org por defecto de la CLI.
- Modificar la org (deploy real, DML, Apex anónimo, publicar agentes): solo implementers y solo en `build`.
- Credenciales y configuración de la CLI (`org login/logout/display`, `config`, `alias`, `--url-only`,
  ficheros `~/.sf*`), paquetes, plugins, sandboxes y usuarios: solo humano.
- `./hx doctor` comprueba además que la org objetivo **no es producción** (`Organization.IsSandbox`).

**Repositorio**
- Rutas protegidas (el propio harness, su estado y su evidencia): ningún agente las modifica.
- Configuración sensible (`sfdx-project.json`, `package.json`, `config/`): pide confirmación.
- Producto: solo el rol dueño, en su fase, dentro del scope.
- Secretos en el contenido (auth URLs, claves privadas, tokens, credenciales en claro): bloqueados.
- Git: commits solo del orquestador; push pide confirmación; nunca force-push ni push a ramas
  protegidas; reescrituras de historia piden confirmación.

**Puertas humanas** — `./hx approve` y `./hx close` siempre piden confirmación al humano, y solo
puede solicitarlas el orquestador. Los subagentes no pueden cambiar el estado ni registrar el
veredicto de otro rol.

## Modo mantenimiento

Para trabajar sobre el propio harness, un humano lanza Claude Code con `HARNESS_MAINTENANCE=1`
(desactiva las guardas de escritura y de shell para esa sesión). No lo uses para trabajo de producto.

## Límites: qué NO es

- **No es un sandbox.** Las guardas inspeccionan el texto de los comandos; una invocación
  deliberadamente ofuscada puede esquivarlas. Protegen de errores y derivas, no de un adversario.
  Para aislamiento real: el sandbox de Claude Code, una org desechable y credenciales de mínimo
  privilegio.
- **La mejor defensa es no tener la credencial.** No autentiques producción en la máquina donde
  trabajan los agentes. Si la CLI no conoce el alias, ningún comando puede usarlo.
- **Las herramientas MCP no pasan por `guard_bash`.** El harness trabaja a propósito solo con la CLI
  `sf`. Si conectas un servidor MCP de Salesforce, sus acciones quedan fuera de estas guardas:
  limítalo a la org de desarrollo y a herramientas de solo lectura.
- **La evidencia no está firmada.** Está protegida contra escritura por los hooks, no criptográficamente.
- `sf project retrieve` escribe en el packageDir sin pasar por la matriz de propiedad (el cambio se
  detecta después: scope en `./hx advance` y revisión).
- Las comprobaciones de `post_edit_checks.py` son heurísticas: avisan pronto, no sustituyen a Code
  Analyzer ni a los revisores.

## Falsos positivos

Si una guarda bloquea algo legítimo, el mensaje indica la regla (`[harness:<regla>]`). Lo habitual:
un texto que solo *menciona* un comando (usa Write/Edit para ese fichero) o un tipo de metadata sin
dueño asignado (añádelo a `harness/roles.json`). Todos los bloqueos quedan en `.harness/events.jsonl`.

## Los hooks necesitan Python (y fallan cerrado)

Los hooks se lanzan con `.claude/hooks/run`, que busca un Python 3.8+ que realmente funcione
(descarta el alias de la Microsoft Store de Windows). Si no hay Python, los hooks `guard_*`
**bloquean** la acción (exit 2): sin guardas no se trabaja. El resto (contexto, métricas, checks)
se omite con un aviso para no tumbar la sesión. Antes, un hook roto era un error "no bloqueante" y
la acción se ejecutaba sin ninguna guarda.

## PowerShell (Windows)

Claude Code en Windows trae una herramienta **PowerShell** además de Bash. Las guardas se escribieron para
Bash, así que PowerShell queda **denegada** en `settings.json` (los agentes usan Bash, que en Windows es Git
Bash) y, como segunda capa, `guard_bash` también está enganchada a `PowerShell`. Sin esto, un agente podía
ejecutar `sf` o escribir ficheros sin pasar por ownership ni por la lista de orgs.

## Invocar la CLI de Salesforce

Los guardas clasifican cada `sf …` (lectura, test, validación, mutación) y lo cruzan con el rol, la
fase y el alias de org. Por eso solo hay una forma de llamar a la CLI: `sf` (o `sfdx`, `npx sf`, o una
ruta que termine en `/sf`). Lanzarla saltándose ese nombre —`node …/run.js`, `sf.cmd`— se bloquea
(`sf-direct`): fue lo que, en una prueba real, dejó a un orquestador desplegar sin pasar por los
guardas. En Windows, `bin/sf` (shim del harness, en el PATH de la sesión) elige una CLI que funcione
desde bash, así que nadie necesita el rodeo.

## Centro de control

`./hx watch` sirve un panel en `127.0.0.1` desde el que el humano aprueba, cierra y habla con el
orquestador. Es la única vía, además de la terminal, para pasar las puertas humanas, así que:

- **Solo tu navegador actúa.** Al arrancar se genera una clave aleatoria que solo vive en memoria y en
  el enlace que se imprime (`?k=…`). No va en el HTML, ni a disco, ni al entorno de Claude. Toda
  llamada a `/api` la exige; sin ella solo se ve el visor.
- **Ninguna web externa puede usarlo.** Se rechaza cualquier `Host` que no sea `127.0.0.1`/`localhost`
  con su puerto (DNS rebinding), cualquier `Origin` ajeno, y los POST que no son `application/json`.
- **Los agentes no pueden.** `./hx watch` lo deniega el guarda para todos los roles (`hx-human`), y
  cualquier comando que apunte a la API local se bloquea (`console-api`). El orquestador que lanza el
  panel lleva `HX_CONSOLE=1`: ahí `./hx approve`/`close` se le deniegan y te los pide en el chat.
- **Mismas reglas que la terminal.** Cada botón ejecuta `./hx` en un proceso propio con una lista
  cerrada de acciones (`propose`, `approve`, `start`, `close`, `block`, `unblock`, `rework`, `reverify`).
  Si la CLI dice que no, el panel enseña su mensaje. Queda en `events.jsonl` como `human_action`.
- **El mensaje al orquestador va por stdin, nunca por argv** (en Windows `claude.cmd` pasa por `cmd.exe`).
- `git push`, borrar datos u orgs y las credenciales siguen fuera del panel.

No compartas el enlace con clave ni abras el puerto a la red. `--read-only` sirve solo el visor.

### Qué ve el visor de cada agente

Para la oficina del visor, `activity.py` (lecturas, búsquedas, delegaciones, web y conectores) y
`guard_bash.py` (solo si el comando pasa) registran **un resumen seguro**: un verbo («despliega en la
org»), el sitio y como mucho un nombre de fichero o de gate. Nunca argumentos de comandos, contenido,
prompts ni patrones de búsqueda: un comando con un token queda como «ejecuta curl». Del encargo del
orquestador se guarda solo su `description` corta, y del informe del agente, la primera línea de
*Resumen* y de *Pendiente*. Este hook no decide nada y nunca bloquea.

## Secretos

El gate `secrets` busca credenciales literales en los ficheros que cambia la feature (contraseñas y
tokens en variables, cabeceras `Authorization` con valor, `Blob.valueOf('usuario:clave')`, claves
privadas, JWT, IDs de sesión). La deuda existente fuera de la feature no la bloquea. Las excepciones
las aprueba el humano en `secrets-allowlist.txt` (`<ruta> <huella>`), ruta protegida.
