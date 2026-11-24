"""The back office of the page: who runs it loads files and connects sensors.

    uvicorn --app-dir demo admin:app --port 8020       (in Docker: 127.0.0.1:3004)
    python demo/admin.py hash                          the hash of a password, for .env

It is off unless ``EGMS_ADMIN_USER`` and ``EGMS_ADMIN_PASSWORD_HASH`` are set.
The password is never in ``.env``: only its scrypt hash. One administrator.
It listens on its own port, which the public proxy does not publish.

* **Fonti**: the files the page reads, from every folder, with the records
  in each and the reasons a file is refused. Uploads and sensor files can be
  deleted; the folder ``records/`` is read-only.
* **Carica un file**: a ``.json``, ``.jsonl`` or ``.csv``, checked with the
  same rules as ``egms records``, shown, then saved on request.
* **Sensori**: register a sensor and get its token (shown once, kept as a
  hash), the address and an example; turn it off, give it a new token, or
  remove it. The last readings refused are shown with their reasons.
* **Registro**: every login, upload, deletion and change, with time and
  address. Never a password or a token.

Sessions live in memory (a restart logs out), last 8 hours, and travel in a
cookie that is ``HttpOnly`` and ``SameSite=Strict`` (and ``Secure`` behind
HTTPS). Every form carries a token against cross-site requests. After 5
wrong passwords from one address, it waits 15 minutes.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import os
import re
import secrets
import shutil
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response
from starlette.routing import Route

from egms_client.records import RecordError, read

sys.path.insert(0, str(Path(__file__).parent))
import sensors

#: The folder of the operator (read-only), the incoming one, and the state.
RECORDS = [
    Path(p)
    for p in os.environ.get(
        "EGMS_UI_RECORDS", str(Path(__file__).parent.parent / "examples" / "records")
    ).split(os.pathsep)
    if p.strip()
]
# An empty variable (as compose passes an unset one) means the default.
INCOMING = Path(os.environ.get("EGMS_UI_INCOMING") or "/srv/incoming")
STATE = Path(os.environ.get("EGMS_UI_STATE") or "/srv/state")
#: The address of the public page, for the example of a sensor.
PUBLIC = (os.environ.get("EGMS_UI_PUBLIC_URL") or "http://127.0.0.1:3003").rstrip("/")

SESSION_HOURS = 8
TRIES = 5
LOCK_MINUTES = 15
MAX_UPLOAD = 5 * 1024 * 1024
COOKIE = "egms_admin"
SUFFIXES = (".json", ".jsonl", ".csv")

# --- Passwords ----------------------------------------------------------------

_N, _R, _P = 2**15, 8, 1


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def hash_password(password: str) -> str:
    """``scrypt:N:r:p:salt:hash``, with no ``$``: Docker Compose reads ``$`` in .env."""
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, maxmem=2**26)
    return f"scrypt:{_N}:{_R}:{_P}:{_b64(salt)}:{_b64(digest)}"


def check_password(password: str, stored: str) -> bool:
    try:
        kind, n, r, p, salt, digest = stored.split(":")
        if kind != "scrypt":
            return False
        mine = hashlib.scrypt(
            password.encode(), salt=_unb64(salt), n=int(n), r=int(r), p=int(p), maxmem=2**26
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(mine, _unb64(digest))


# --- Sessions, tries and the log ---------------------------------------------


class Guard:
    """Sessions in memory, wrong passwords by address, and the log on disk."""

    def __init__(self, state: Path) -> None:
        self.state = state
        self.sessions: dict[str, dict[str, Any]] = {}
        self.failures: dict[str, list[float]] = {}
        self.pending: dict[str, tuple[Path, str, float]] = {}

    def locked(self, address: str, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        recent = [t for t in self.failures.get(address, []) if now - t < LOCK_MINUTES * 60]
        self.failures[address] = recent
        return len(recent) >= TRIES

    def failed(self, address: str) -> None:
        self.failures.setdefault(address, []).append(time.time())

    def open(self) -> tuple[str, str]:
        sid, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        self.sessions[sid] = {"expires": time.time() + SESSION_HOURS * 3600, "csrf": csrf}
        return sid, csrf

    def session(self, request: Request) -> dict[str, Any] | None:
        sid = request.cookies.get(COOKIE, "")
        found = self.sessions.get(sid)
        if found is None or found["expires"] < time.time():
            self.sessions.pop(sid, None)
            return None
        return found

    def close(self, request: Request) -> None:
        self.sessions.pop(request.cookies.get(COOKIE, ""), None)

    def log(self, request: Request, action: str, detail: str = "") -> None:
        self.state.mkdir(parents=True, exist_ok=True)
        line = {
            "time": datetime.now(UTC).isoformat(timespec="seconds"),
            "address": _address(request),
            "action": action,
            "detail": detail,
        }
        with (self.state / "log.jsonl").open("a", encoding="utf-8") as out:
            out.write(json.dumps(line, ensure_ascii=False) + "\n")

    def entries(self, last: int = 200) -> list[dict[str, Any]]:
        path = self.state / "log.jsonl"
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8").splitlines()[-last:]
        return [json.loads(line) for line in reversed(lines)]


def _address(request: Request) -> str:
    return request.client.host if request.client else "?"


def _configured() -> tuple[str, str] | None:
    user = os.environ.get("EGMS_ADMIN_USER", "").strip()
    stored = os.environ.get("EGMS_ADMIN_PASSWORD_HASH", "").strip()
    return (user, stored) if user and stored else None


# --- Pages --------------------------------------------------------------------

STYLE = """
body{font-family:"Titillium Web",system-ui,sans-serif;margin:0;color:#17324d;background:#f2f5f8}
header{background:#0066cc;color:#fff;padding:10px 20px;display:flex;gap:20px;align-items:center;flex-wrap:wrap}
header b{font-size:1.1rem;margin-right:auto}
header a,header button{color:#fff;font-weight:600;text-decoration:none;background:none;border:0;font:inherit;cursor:pointer}
main{max-width:1000px;margin:0 auto;padding:20px;background:#fff;min-height:80vh}
h1{font-size:1.5rem}h2{font-size:1.15rem;margin-top:28px}
table{border-collapse:collapse;width:100%;font-size:.9rem;margin:8px 0}
th,td{border-bottom:1px solid #e3e6ea;padding:6px 8px;text-align:left;vertical-align:top}
th{background:#f6f8fa}
.ok{color:#008055;font-weight:600}.no{color:#a61919;font-weight:600}.muted{color:#5c6f82}
form.inline{display:inline}
input,select{font:inherit;padding:4px 6px;border:1px solid #b9c4cf;border-radius:4px}
button.b{font:inherit;padding:6px 14px;border:0;border-radius:4px;background:#0066cc;color:#fff;cursor:pointer}
button.d{background:#a61919}button.s{background:#5c6f82}
.box{border:1px solid #e3e6ea;border-radius:6px;padding:12px 16px;margin:12px 0}
.warn{background:#fff4e5;border-left:4px solid #cc7a00;padding:10px 14px}
.token{font-family:monospace;background:#f6f8fa;padding:8px;word-break:break-all;border:1px solid #e3e6ea}
pre{background:#f6f8fa;border:1px solid #e3e6ea;padding:8px;overflow-x:auto;font-size:.8rem}
label{display:block;margin:6px 0}label span{display:inline-block;min-width:160px}
"""

HEADERS = {
    "Content-Security-Policy": "default-src 'self'; style-src 'unsafe-inline'; "
    "form-action 'self'; frame-ancestors 'none'; base-uri 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}

e = html.escape


def page(title: str, body: str, csrf: str | None = None, status: int = 200) -> HTMLResponse:
    nav = ""
    if csrf is not None:
        nav = (
            '<a href="/">Fonti</a><a href="/carica">Carica un file</a>'
            '<a href="/sensori">Sensori</a><a href="/registro">Registro</a>'
            f'<form class="inline" method="post" action="/esci">{_csrf(csrf)}'
            "<button>Esci</button></form>"
        )
    text = (
        f'<!doctype html><html lang="it"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<meta name="robots" content="noindex"><title>{e(title)} · backoffice</title>'
        f"<style>{STYLE}</style></head><body><header><b>Backoffice · dati aperti</b>{nav}"
        f"</header><main><h1>{e(title)}</h1>{body}</main></body></html>"
    )
    return HTMLResponse(text, status_code=status, headers=HEADERS)


def _csrf(token: str) -> str:
    return f'<input type="hidden" name="csrf" value="{e(token)}">'


async def _form(request: Request, session: dict[str, Any]) -> Any:
    form = await request.form()
    if not hmac.compare_digest(str(form.get("csrf", "")), session["csrf"]):
        raise PermissionError("the form expired: reload the page")
    return form


def _signed_in(handler: Any) -> Any:
    async def wrapper(request: Request) -> Response:
        if _configured() is None:
            return off()
        guard: Guard = request.app.state.guard
        session = guard.session(request)
        if session is None:
            return RedirectResponse("/accedi", status_code=303)
        try:
            response: Response = await handler(request, session)
        except PermissionError as exc:
            return page("Richiesta rifiutata", f"<p>{e(str(exc))}</p>", session["csrf"], 403)
        return response

    return wrapper


def off() -> HTMLResponse:
    return page(
        "Backoffice spento",
        "<p>Per accendere il backoffice servono, nel file <code>.env</code>, "
        "<code>EGMS_ADMIN_USER</code> e <code>EGMS_ADMIN_PASSWORD_HASH</code>. L'hash della "
        "password si ottiene con <code>make admin-password</code>.</p>",
        status=503,
    )


# --- Login ---------------------------------------------------------------------


async def login_page(_: Request) -> Response:
    if _configured() is None:
        return off()
    return page(
        "Accedi",
        '<form method="post" action="/accedi">'
        '<label><span>Utente</span><input name="user" autocomplete="username" required></label>'
        '<label><span>Password</span><input name="password" type="password" '
        'autocomplete="current-password" required></label>'
        '<button class="b">Accedi</button></form>',
    )


async def login(request: Request) -> Response:
    configured = _configured()
    if configured is None:
        return off()
    guard: Guard = request.app.state.guard
    address = _address(request)
    if guard.locked(address):
        guard.log(request, "accesso bloccato", "troppi tentativi")
        return page(
            "Accedi",
            f'<p class="warn">Troppi tentativi sbagliati: riprova tra {LOCK_MINUTES} minuti.</p>',
            status=429,
        )
    form = await request.form()
    user, password = str(form.get("user", "")), str(form.get("password", ""))
    good_user = hmac.compare_digest(user.encode(), configured[0].encode())
    good = check_password(password, configured[1]) and good_user
    if not good:
        guard.failed(address)
        guard.log(request, "accesso fallito", f"utente {user[:40]!r}")
        return page(
            "Accedi",
            '<p class="warn">Utente o password sbagliati.</p><p><a href="/accedi">Riprova</a></p>',
            status=401,
        )
    sid, _ = guard.open()
    guard.log(request, "accesso", user)
    response = RedirectResponse("/", status_code=303)
    secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    response.set_cookie(
        COOKIE,
        sid,
        max_age=SESSION_HOURS * 3600,
        httponly=True,
        samesite="strict",
        secure=secure,
        path="/",
    )
    return response


@_signed_in
async def logout(request: Request, session: dict[str, Any]) -> Response:
    await _form(request, session)
    guard: Guard = request.app.state.guard
    guard.close(request)
    guard.log(request, "uscita")
    response = RedirectResponse("/accedi", status_code=303)
    response.delete_cookie(COOKIE, path="/")
    return response


# --- Sources -------------------------------------------------------------------


def _folders() -> list[tuple[str, Path, bool]]:
    """Each folder the page reads: its name, path, and whether files can be deleted here."""
    return [
        *[(f"cartella {p}", p, False) for p in RECORDS],
        ("caricati dal backoffice", INCOMING / "uploads", True),
        ("sensori", INCOMING / "sensors", True),
    ]


def _describe(path: Path) -> tuple[bool, str, str]:
    try:
        records = read(path)
    except RecordError as exc:
        return False, "", "; ".join(exc.problems[:5])
    except (OSError, ValueError) as exc:
        return False, "", f"non è JSON o CSV: {exc}"
    names = sorted({r["source"]["name"] for r in records})
    return True, f"{len(records)} record · {', '.join(names)}", ""


@_signed_in
async def sources_page(_: Request, session: dict[str, Any]) -> Response:
    parts = [
        "<p>I file da cui la mappa si alimenta. Un file con anche un solo record non valido è "
        "rifiutato per intero, e la mappa non lo mostra.</p>"
    ]
    for name, folder, deletable in _folders():
        files = (
            sorted(p for p in folder.glob("*") if p.suffix in SUFFIXES) if folder.is_dir() else []
        )
        rows = []
        for path in files:
            ok, what, why = _describe(path)
            state = '<span class="ok">letto</span>' if ok else '<span class="no">rifiutato</span>'
            action = ""
            if deletable:
                action = (
                    f'<form class="inline" method="post" action="/file/elimina">{_csrf(session["csrf"])}'
                    f'<input type="hidden" name="folder" value="{e(folder.name)}">'
                    f'<input type="hidden" name="name" value="{e(path.name)}">'
                    '<button class="b d">Elimina</button></form>'
                )
            rows.append(
                f"<tr><td>{e(path.name)}</td><td>{state}</td><td>{e(what)}"
                f'<div class="no">{e(why)}</div></td><td>{action}</td></tr>'
            )
        body = (
            "<table><tr><th>File</th><th>Stato</th><th>Contenuto</th><th></th></tr>"
            + "".join(rows)
            + "</table>"
            if rows
            else '<p class="muted">Nessun file.</p>'
        )
        note = (
            "" if deletable else ' <span class="muted">(sola lettura: si cambia sul server)</span>'
        )
        parts.append(f"<h2>{e(name)}{note}</h2>{body}")
    return page("Fonti", "".join(parts), session["csrf"])


@_signed_in
async def delete_file(request: Request, session: dict[str, Any]) -> Response:
    form = await _form(request, session)
    folder = {"uploads": INCOMING / "uploads", "sensors": INCOMING / "sensors"}.get(
        str(form.get("folder"))
    )
    name = str(form.get("name", ""))
    if folder is None or "/" in name or "\\" in name or name.startswith("."):
        raise PermissionError("file non valido")
    path = folder / name
    if path.suffix in SUFFIXES and path.is_file():
        path.unlink()
        request.app.state.guard.log(request, "file eliminato", f"{folder.name}/{name}")
    return RedirectResponse("/", status_code=303)


# --- Upload --------------------------------------------------------------------


UPLOAD_FORM = """
<form method="post" action="/carica" enctype="multipart/form-data">{csrf}
<p>Un file <code>.json</code>, <code>.jsonl</code> o <code>.csv</code> (le colonne del template),
al massimo 5 MB. Prima lo controllo e te lo mostro; lo salvo solo se confermi.</p>
<p><input type="file" name="file" accept=".json,.jsonl,.csv" required></p>
<button class="b">Controlla</button></form>
<p class="muted">I template sono sulla pagina pubblica, in «I dati e come riusarli».</p>
"""


@_signed_in
async def upload_page(_: Request, session: dict[str, Any]) -> Response:
    return page("Carica un file", UPLOAD_FORM.format(csrf=_csrf(session["csrf"])), session["csrf"])


def _safe_name(name: str, suffix: str) -> str:
    stem = re.sub(r"[^a-z0-9-]+", "-", Path(name).stem.lower()).strip("-")[:60] or "file"
    return f"{stem}{suffix}"


@_signed_in
async def upload(request: Request, session: dict[str, Any]) -> Response:
    form = await _form(request, session)
    upload = form.get("file")
    if upload is None or not hasattr(upload, "read"):
        raise PermissionError("nessun file")
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix not in SUFFIXES:
        return page(
            "Carica un file",
            '<p class="warn">Il file deve essere .json, .jsonl o .csv.</p>'
            + UPLOAD_FORM.format(csrf=_csrf(session["csrf"])),
            session["csrf"],
            400,
        )
    data = await upload.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        return page(
            "Carica un file", '<p class="warn">Il file supera 5 MB.</p>', session["csrf"], 413
        )
    guard: Guard = request.app.state.guard
    pending = STATE / "pending"
    pending.mkdir(parents=True, exist_ok=True)
    for key, (old, _, made) in list(guard.pending.items()):
        if time.time() - made > 3600:
            old.unlink(missing_ok=True)
            guard.pending.pop(key)
    key = secrets.token_urlsafe(16)
    name = _safe_name(upload.filename or "file", suffix)
    path = pending / f"{key}-{name}"
    path.write_bytes(data)
    try:
        records = read(path)
    except (RecordError, OSError, ValueError) as exc:
        path.unlink(missing_ok=True)
        found = getattr(exc, "problems", [str(exc)])
        guard.log(request, "file rifiutato", f"{name}: {len(found)} problemi")
        items = "".join(f"<li>{e(p)}</li>" for p in found[:50])
        return page(
            "Carica un file",
            f'<p class="warn">Il file <b>{e(name)}</b> non è valido: non è stato salvato.</p>'
            f"<ul>{items}</ul>" + UPLOAD_FORM.format(csrf=_csrf(session["csrf"])),
            session["csrf"],
            400,
        )
    guard.pending[key] = (path, name, time.time())
    rows = "".join(
        "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
            e(r["source"]["name"]),
            e(r.get("property") or r.get("question") or r["kind"]),
            e("non misurato" if r.get("value", 0) is None else str(r.get("value", "—"))),
            e(r.get("unit", "")),
            e(json.dumps(r["time"]) if r["time"] else "senza date"),
        )
        for r in records[:20]
    )
    more = f'<p class="muted">… e altri {len(records) - 20}.</p>' if len(records) > 20 else ""
    return page(
        "Carica un file",
        f'<p class="ok">{e(name)}: {len(records)} record validi.</p>'
        "<table><tr><th>Fonte</th><th>Che cosa</th><th>Valore</th><th>Unità</th><th>Quando</th></tr>"
        f"{rows}</table>{more}"
        f'<form method="post" action="/carica/salva">{_csrf(session["csrf"])}'
        f'<input type="hidden" name="key" value="{e(key)}">'
        '<button class="b">Salva: la mappa lo mostrerà</button> '
        '<a href="/carica">Annulla</a></form>',
        session["csrf"],
    )


@_signed_in
async def save_upload(request: Request, session: dict[str, Any]) -> Response:
    form = await _form(request, session)
    guard: Guard = request.app.state.guard
    found = guard.pending.pop(str(form.get("key", "")), None)
    if found is None:
        raise PermissionError("il file in attesa è scaduto: caricalo di nuovo")
    path, name, _ = found
    target_dir = INCOMING / "uploads"
    target_dir.mkdir(parents=True, exist_ok=True)
    target, n = target_dir / name, 2
    while target.exists():
        target = target_dir / f"{Path(name).stem}-{n}{Path(name).suffix}"
        n += 1
    shutil.move(str(path), target)
    guard.log(request, "file caricato", target.name)
    return RedirectResponse("/", status_code=303)


# --- Sensors ---------------------------------------------------------------------


def _registry(request: Request) -> sensors.Registry:
    registry: sensors.Registry = request.app.state.registry
    return registry


def _last(sensor_id: str) -> tuple[str, list[dict[str, Any]]]:
    folder = INCOMING / "sensors"
    files = sorted(folder.glob(f"{sensor_id}-*.jsonl")) if folder.is_dir() else []
    last = "mai"
    if files:
        lines = files[-1].read_text(encoding="utf-8").strip().splitlines()
        if lines:
            r = json.loads(lines[-1])
            value = "nessuna misura" if r["value"] is None else f"{r['value']} {r['unit']}"
            last = f"{r['time'].get('instant', '')}: {value}"
    refused_path = folder / f"{sensor_id}.refused"
    refused = (
        [json.loads(x) for x in refused_path.read_text(encoding="utf-8").splitlines()[-5:]]
        if refused_path.exists()
        else []
    )
    return last, refused


SENSOR_FORM = """
<h2>Collega un sensore</h2>
<form method="post" action="/sensori" class="box">{csrf}
<label><span>Id del sensore</span><input name="id" required pattern="[a-z0-9][a-z0-9-]{{2,62}}"
 placeholder="pluvio-01"> <span class="muted">minuscole, cifre e trattini</span></label>
<label><span>Fonte (chi misura)</span><input name="source" required placeholder="Pluviometro del Comune"></label>
<label><span>Licenza</span><input name="licence" required value="CC BY 4.0"></label>
<label><span>Grandezza</span><input name="property" required pattern="[a-z][a-z0-9_]*" placeholder="rainfall"></label>
<label><span>Unità (UCUM)</span><input name="unit" required placeholder="mm"></label>
<label><span>Nome per le persone</span><input name="label" placeholder="Pioggia"></label>
<label><span>Significato del segno</span><input name="meaning" placeholder="solo per velocità e spostamenti"></label>
<label><span>Longitudine, latitudine</span><input name="lon" required size="10" placeholder="14.1262">
 <input name="lat" required size="10" placeholder="40.8262"></label>
<label><span>Valori ammessi (facoltativo)</span><input name="low" size="8" placeholder="min">
 <input name="high" size="8" placeholder="max"></label>
<button class="b">Crea il sensore e il suo token</button></form>
"""


def _example(sensor: sensors.Sensor, token: str) -> str:
    pack = json.dumps([{"bn": f"{sensor.id}/", "n": sensor.property, "u": sensor.unit, "v": 0.4}])
    return (
        f"curl -X POST {PUBLIC}/api/ingest/{sensor.id} \\\n"
        f'  -H "Authorization: Bearer {token}" \\\n'
        '  -H "Content-Type: application/senml+json" \\\n'
        f"  -d '{pack}'"
    )


def _token_page(sensor: sensors.Sensor, token: str, csrf: str, what: str) -> HTMLResponse:
    return page(
        f"Sensore {sensor.id}",
        f'<p class="ok">{e(what)}</p>'
        '<p class="warn">Copia il token adesso: non sarà mostrato di nuovo. Sul server resta '
        "solo la sua impronta (hash).</p>"
        f'<div class="token">{e(token)}</div>'
        f"<h2>Come invia i dati</h2><p>Un POST con il token, in SenML (RFC 8428), il formato "
        f"dei sensori di Limen. Senza <code>bt</code> il tempo è quello dell'arrivo.</p>"
        f"<pre>{e(_example(sensor, token))}</pre>"
        "<p>La risposta dice quante letture sono state accettate e perché le altre no. "
        "Al massimo una richiesta al secondo e 64 KB.</p>"
        '<p><a href="/sensori">← Sensori</a></p>',
        csrf,
    )


@_signed_in
async def sensors_page(request: Request, session: dict[str, Any]) -> Response:
    rows = []
    for s in _registry(request).load().values():
        last, refused = _last(s.id)
        why = "".join(f"<div class='no'>{e(r['time'])}: {e(r['reason'])}</div>" for r in refused)
        actions = "".join(
            f'<form class="inline" method="post" action="/sensori/{e(s.id)}/{verb}">'
            f'{_csrf(session["csrf"])}<button class="b {cls}">{label}</button></form> '
            for verb, label, cls in (
                ("stato", "Spegni" if s.active else "Accendi", "s"),
                ("token", "Nuovo token", "s"),
                ("elimina", "Elimina", "d"),
            )
        )
        state = '<span class="ok">acceso</span>' if s.active else '<span class="no">spento</span>'
        rows.append(
            f"<tr><td><b>{e(s.id)}</b><div class='muted'>{e(s.source)} · {e(s.licence)}</div></td>"
            f"<td>{e(s.property)} ({e(s.unit)})<div class='muted'>{s.lon}, {s.lat}</div></td>"
            f"<td>{state}</td><td>{e(last)}{why}</td><td>{actions}</td></tr>"
        )
    table = (
        "<table><tr><th>Sensore</th><th>Che cosa, dove</th><th>Stato</th>"
        "<th>Ultima lettura, letture rifiutate</th><th></th></tr>" + "".join(rows) + "</table>"
        if rows
        else '<p class="muted">Nessun sensore.</p>'
    )
    return page(
        "Sensori",
        f"<p>Ogni sensore invia le sue letture a <code>{e(PUBLIC)}/api/ingest/ID</code> con il "
        "suo token. Le letture diventano record, uno per riga, un file al giorno.</p>"
        + table
        + SENSOR_FORM.format(csrf=_csrf(session["csrf"])),
        session["csrf"],
    )


def _number(form: Any, name: str, low: float, high: float, required: bool = True) -> float | None:
    raw = str(form.get(name, "")).strip().replace(",", ".")
    if not raw and not required:
        return None
    try:
        value = float(raw)
    except ValueError:
        raise PermissionError(f"{name}: non è un numero") from None
    if not low <= value <= high:
        raise PermissionError(f"{name}: fuori dai limiti")
    return value


@_signed_in
async def create_sensor(request: Request, session: dict[str, Any]) -> Response:
    form = await _form(request, session)
    registry = _registry(request)
    found = dict(registry.load())
    sensor_id = str(form.get("id", "")).strip()
    if not sensors.SENSOR_ID.match(sensor_id) or sensor_id in found:
        raise PermissionError("id non valido o già usato")
    prop = str(form.get("property", "")).strip()
    if not re.fullmatch(r"[a-z][a-z0-9_]*", prop):
        raise PermissionError("grandezza non valida")
    text = {
        k: str(form.get(k, "")).strip()[:120]
        for k in ("source", "licence", "unit", "label", "meaning")
    }
    if not (text["source"] and text["licence"] and text["unit"]):
        raise PermissionError("fonte, licenza e unità servono")
    token = sensors.new_token()
    sensor = sensors.Sensor(
        id=sensor_id,
        source=text["source"],
        licence=text["licence"],
        property=prop,
        unit=text["unit"],
        lon=_number(form, "lon", -180, 180) or 0.0,
        lat=_number(form, "lat", -90, 90) or 0.0,
        token=sensors.token_hash(token),
        label=text["label"],
        meaning=text["meaning"],
        low=_number(form, "low", -1e9, 1e9, required=False),
        high=_number(form, "high", -1e9, 1e9, required=False),
    )
    found[sensor_id] = sensor
    registry.save(found)
    request.app.state.guard.log(request, "sensore creato", sensor_id)
    return _token_page(sensor, token, session["csrf"], f"Il sensore {sensor_id} è collegato.")


@_signed_in
async def change_sensor(request: Request, session: dict[str, Any]) -> Response:
    await _form(request, session)
    registry = _registry(request)
    found = dict(registry.load())
    sensor_id, verb = request.path_params["sensor"], request.path_params["verb"]
    sensor = found.get(sensor_id)
    if sensor is None:
        raise PermissionError("sensore sconosciuto")
    guard: Guard = request.app.state.guard
    if verb == "stato":
        sensor.active = not sensor.active
        guard.log(request, "sensore acceso" if sensor.active else "sensore spento", sensor_id)
    elif verb == "token":
        token = sensors.new_token()
        sensor.token = sensors.token_hash(token)
        registry.save(found)
        guard.log(request, "nuovo token", sensor_id)
        return _token_page(sensor, token, session["csrf"], "Il vecchio token non vale più.")
    elif verb == "elimina":
        found.pop(sensor_id)
        guard.log(request, "sensore eliminato", sensor_id)
    else:
        raise PermissionError("azione sconosciuta")
    registry.save(found)
    return RedirectResponse("/sensori", status_code=303)


# --- Log -----------------------------------------------------------------------


@_signed_in
async def log_page(request: Request, session: dict[str, Any]) -> Response:
    rows = "".join(
        f"<tr><td>{e(x['time'])}</td><td>{e(x['address'])}</td><td>{e(x['action'])}</td>"
        f"<td>{e(x['detail'])}</td></tr>"
        for x in request.app.state.guard.entries()
    )
    return page(
        "Registro",
        "<p>Le ultime 200 azioni, la più recente in alto. Mai password o token.</p>"
        "<table><tr><th>Quando (UTC)</th><th>Da</th><th>Azione</th><th>Dettaglio</th></tr>"
        f"{rows}</table>",
        session["csrf"],
    )


async def health(_: Request) -> Response:
    return Response("ok", headers={"Cache-Control": "no-store"})


def make_app() -> Starlette:
    app = Starlette(
        routes=[
            Route("/health", health),
            Route("/accedi", login_page),
            Route("/accedi", login, methods=["POST"]),
            Route("/esci", logout, methods=["POST"]),
            Route("/", sources_page),
            Route("/file/elimina", delete_file, methods=["POST"]),
            Route("/carica", upload_page),
            Route("/carica", upload, methods=["POST"]),
            Route("/carica/salva", save_upload, methods=["POST"]),
            Route("/sensori", sensors_page),
            Route("/sensori", create_sensor, methods=["POST"]),
            Route("/sensori/{sensor}/{verb}", change_sensor, methods=["POST"]),
            Route("/registro", log_page),
        ]
    )
    app.state.guard = Guard(STATE)
    app.state.registry = sensors.Registry(STATE / "sensors.json")
    return app


app = make_app()


def main() -> None:  # pragma: no cover - interactive
    import getpass

    if sys.argv[1:] != ["hash"]:
        print("usage: python demo/admin.py hash")
        raise SystemExit(2)
    first = getpass.getpass("Password dell'amministratore: ")
    if len(first) < 12:
        print("Almeno 12 caratteri.")
        raise SystemExit(1)
    if getpass.getpass("Di nuovo: ") != first:
        print("Le due password sono diverse.")
        raise SystemExit(1)
    print(f"EGMS_ADMIN_PASSWORD_HASH={hash_password(first)}")


if __name__ == "__main__":  # pragma: no cover
    main()
