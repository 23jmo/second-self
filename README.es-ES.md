# Second Self

Un pipeline en segundo plano que construye un perfil psicológico y conductual multicapa a partir de tu Gmail, Google Calendar y presencia web. El resultado se convierte en el "primer" para un agente gemelo digital que actúa en tu nombre.

## Architecture

Second Self construye un sistema de memoria de 6 capas. Esta rama implementa las Capas 1-4:

```
Layer 1  identity.md         Quién eres — rol, voz, intereses, patrones conductuales
Layer 2  preferences.md      Cómo trabajas — horario, herramientas, estilo de comunicación, áreas de enfoque
Layer 2.5 relationships.json  A quién conoces — grafo de contactos con puntuaciones de cercanía
Layer 3  (reservado)         Memoria contextual (futuro)
Layer 4  episodic.md         Qué sucedió — eventos de vida fechados extraídos del historial de correos
```

Todos los archivos de perfil se escriben en `~/.secondself/` para ser consumidos por el agente gemelo.

## Pipeline

```
Gmail OAuth ──> Fetch Emails ──> Clean ──> Analyze (parallel) ──> Build Profiles
                                             |
Google Auth ──> Calendar Fetch ─────────────┘
                                             |
              Tavily Search ─────────────────┘
```

### Analysis passes (Layer 1)

| Module | Input | Output |
|--------|-------|--------|
| `voice_analyzer` | Correos enviados | Perfil de voz — tono, aperturas, cierres, alternancia de código |
| `topic_extractor` | Todos los correos | Top 15 temas recurrentes con frecuencia y confianza |
| `behavior_analyzer` | Todos los correos + hilos | Velocidad de respuesta, horas activas, ratio de iniciación |
| `relationship_mapper` | Todos los correos | Grafo de contactos — círculo interno, colegas, conocidos |
| `tavily_synthesizer` | Resultados de búsqueda web | Perfil público — rol, empresa, enlaces sociales |

### Layer 2: Preferences

`build/preferences_builder.py` sintetiza las preferencias de trabajo a partir de datos de comportamiento, eventos del calendario, temas y relaciones mediante una llamada a un LLM. Genera patrones de horario, compromisos recurrentes, áreas de enfoque, estilo de comunicación y herramientas inferidas.

### Layer 4: Episodic Memory

`analyze/event_extractor.py` extrae eventos de vida (cambios de trabajo, viajes, hitos educativos) del historial de correos utilizando workers paralelos por año con `ProcessPoolExecutor`. Los eventos se escriben en `episodic.md` con sus marcas de tiempo originales.

`utils/episodic_writer.py` proporciona una API de anexo con bloqueo de archivo para que el agente gemelo registre eventos en tiempo de ejecución.

## Project Structure

```
second-self/
├── main.py                        # Orquestador del pipeline
├── auth/
│   ├── firebase_auth.py           # Intercambio de tokens de Firebase
│   ├── gmail_auth.py              # Credenciales de Google desde token de acceso
│   └── web_oauth.py               # Servidor FastAPI para OAuth basado en navegador
├── fetch/
│   ├── gmail_fetch.py             # Obtención de Gmail API con caché de 24h
│   ├── tavily_fetch.py            # Búsqueda web de Tavily (3 consultas)
│   └── calendar_fetch.py          # Obtención de Google Calendar (90d pasado + 30d futuro)
├── clean/
│   └── email_cleaner.py           # Eliminación de HTML, firmas y deduplicación
├── analyze/
│   ├── voice_analyzer.py          # Análisis de estilo de escritura en correos enviados
│   ├── topic_extractor.py         # Extracción de temas/intereses vía LLM
│   ├── behavior_analyzer.py       # Patrones de respuesta y hábitos
│   ├── relationship_mapper.py     # Puntuación y clustering de contactos
│   ├── tavily_synthesizer.py      # Extracción de perfil público vía LLM
│   └── event_extractor.py         # Extracción de eventos de vida vía workers LLM paralelos
├── build/
│   ├── identity_builder.py        # Ensambla identity.md (Layer 1)
│   └── preferences_builder.py     # Ensambla preferences.md (Layer 2)
├── utils/
│   └── episodic_writer.py         # Escritor de memoria episódica con bloqueo de archivo (Layer 4)
├── static/
│   └── login.html                 # Página de autenticación de Google Identity Services
├── output/                        # Caché local de todas las salidas del pipeline
└── tests/                         # 430+ pruebas unitarias
```

## Live System

El pipeline de identidad alimenta a un gemelo digital activo que controla un escritorio de macOS.

```
SESIÓN PRIMARIA (tú)                    SESIÓN SECONDSELF (fondo)

 SecondSelf.app (SwiftUI notch app)      agent-server :8421
   ├─ orchestrator :8420                   ├─ Stream de escritorio MJPEG
   │   ├─ Claude API (Sonnet 4)            ├─ Herramientas de escritorio (click, escribir, etc.)
   │   └─ Tool routing                     └─ Captura de pantalla Quartz
   ├─ VNC PiP (feed de escritorio en vivo)
   └─ Chat (streaming SSE)              Chrome :9222 (CDP para browser-use)
                                         Vine Server :5901 (VNC opcional)
```

### Quick Start (ya provisionado)

```bash
# 1. Lanzar la app (inicia el orquestador automáticamente)
cd SecondSelf && swift build && swift run

# 2. Cmd+Shift+T para alternar el panel de chat
# 3. Habla con tu gemelo
```

### First-Time Setup

```bash
# 1. Provisionar la cuenta de usuario y servicios de secondself
./setup/provision.sh

# 2. Cambiar a la sesión de usuario secondself (clic en icono de usuario en barra de menú)
#    Otorgar Grabación de Pantalla a python3:
python3 -c "import Quartz; ref = Quartz.CGWindowListCreateImage(Quartz.CGRectInfinite, Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID, Quartz.kCGWindowImageDefault); print(ref)"
#    Hacer clic en Permitir cuando macOS lo solicite, luego volver a tu cuenta

# 3. Reiniciar agent-server para aplicar el permiso
./setup/restart-agent.sh

# 4. Verificar que todo funcione
./setup/smoke-test.sh
```

### Common Commands

| Comando | Qué hace |
|---------|-------------|
| `cd SecondSelf && swift build && swift run` | Lanzar la app |
| `./setup/smoke-test.sh` | Probar todos los servicios |
| `./setup/restart-agent.sh` | Reiniciar agent-server (copia el código más reciente) |
| `./setup/update-agent-server.sh` | Actualizar código de agent-server + reiniciar |
| `open -a TigerVNC --args localhost:5901` | Ver el escritorio de secondself |
| `curl -s http://localhost:8421/health \| python3 -m json.tool` | Salud del servidor del agente |
| `sudo kill $(sudo lsof -ti :8420) 2>/dev/null` | Matar orquestador colgado |

### Environment Variables

Crea un archivo `.env`:

```
ANTHROPIC_API_KEY=
TAVILY_API_KEY=
CLAUDE_MODEL=claude-sonnet-4-20250514
FIREBASE_API_KEY=
FIREBASE_AUTH_DOMAIN=
FIREBASE_PROJECT_ID=
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
```

### Ports

| Puerto | Servicio | Sesión |
|------|---------|---------|
| 8420 | Orchestrator (puente API de Claude) | Primaria (lanzada por la app) |
| 8421 | Agent Server (herramientas de escritorio + stream MJPEG) | secondself (LaunchAgent) |
| 5901 | Vine Server VNC (opcional) | secondself (LaunchAgent) |
| 9222 | Chrome DevTools Protocol | secondself (LaunchAgent) |

## Identity Pipeline

### Full pipeline

```bash
python main.py
```

Ejecuta todas las capas: obtención de Gmail, búsqueda en Tavily, limpieza de correos, todos los analizadores en paralelo, construcción de identidad, extracción de eventos, obtención de calendario y síntesis de preferencias.

### Flags

| Flag | Descripción |
|------|-------------|
| `--dry-run` | Ejecutar pipeline sin escribir en `~/.secondself/` |
| `--no-cache` | Ignorar todas las cachés y volver a obtener datos de las APIs |
| `--tavily-only` | Omitir Gmail, construir identidad solo desde búsqueda web de Tavily |
| `--memory-only` | Omitir obtención de Gmail y analizadores Capa 1, solo refrescar Capa 2 + 4 |
| `--verbose` | Habilitar registro DEBUG |

## Output

Después de una ejecución exitosa:

```
~/.secondself/
├── identity.md          # Capa 1 — quién eres
├── preferences.md       # Capa 2 — cómo trabajas
└── episodic.md          # Capa 4 — qué sucedió
```

## Tests

```bash
python -m pytest tests/ -v
```

## License

Privado.
