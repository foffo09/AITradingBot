# Local desktop sidecar

Use Python 3.11 and the repository runtime requirements. Install
`packaging/backend/requirements.txt`, then run `python scripts/build_backend.py`.
The build uses the current native OS and architecture, never cross-compilation.
The artifact is `dist/backend/aitradingbot-service-<target-triple>[.exe]`.
Tauri externalBin uses base name `aitradingbot-service`; copy the native artifact
to its binaries directory before bundling. React static assets stay separate.

Runtime: `aitradingbot-service --port 0 --ui-dir ABSOLUTE_UI_DIR --data-dir ABSOLUTE_APPDATA_DIR`.
The application must supply a new `AITradingBot/local-service` appdata directory,
never a legacy project data directory. Both local ledgers are service-owned files
`local-v1-demo.sqlite3` and `local-v1-simulation.sqlite3`; no default/personal DB.

One JSON readiness line on stdout: `{ "port": 1234, "pid": 123, "supervisor_pid": null, "instance_id": "..." }`.
The line appears after server startup. In a frozen executable, supervisor_pid
is the OS parent process ID (the PyInstaller onefile bootloader); in script mode
it is null. The actual service pid is also the identity endpoint pid. A launcher
may match actual pid or native supervisor_pid to its owned Child handle; it must
keep that owned handle as its only termination target, never kill arbitrary PIDs. All diagnostics use stderr or appdata logs.
The socket remains bound from allocation through server lifetime. Bind is only
IPv4 127.0.0.1; proxy headers and websockets are disabled.
The parent keeps stdin open, writes `shutdown\n` to quit, or closes the pipe.
Signals and the authenticated POST shutdown endpoint also stop only this process.
The UI loads `http://127.0.0.1:<port>/` and uses relative `/api/v1` fetches.
For development, use a same-origin development proxy; no permissive CORS is exposed.

GET session requires the exact Origin, or browser Sec-Fetch-Site:same-origin
with X-Local-Request:1. Mutations require exact Origin plus X-Local-Request:1 and
an HttpOnly SameSite=strict cookie. No token in argv, JSON, URL or frontend storage.

The executable is unsigned. macOS signing/notarization and Windows signing are
separate release steps. MetaTrader5 is optional and Windows-only; this bundle
never installs a terminal and has no MT5 trading method. On Windows an explicit
POST connection invokes SDK initialize(timeout=5000), which may launch the
installed terminal and use its last configured account. Install optional
`packaging/backend/requirements-mt5.txt` before the native Windows build to enable
terminal reads. macOS never imports that module. The SDK documents the initialization
timeout but exposes no per-call timeout for account/positions/orders/bars/ticks;
a hard deadline for native reads or shutdown is not guaranteed. Process isolation
would be needed before promising that deadline. No terminal or genuine account
was accessed in the offline checks.
