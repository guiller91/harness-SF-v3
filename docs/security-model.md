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
