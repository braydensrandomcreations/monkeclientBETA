import hashlib
import hmac
import json
import mimetypes
import os
import re
import secrets
import time
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


mimetypes.add_type("application/wasm", ".wasm")

ROOT = Path(__file__).parent
GAMES_FILE = ROOT / "games.json"
GAMES_DIR = ROOT / "games"
IMAGES_DIR = ROOT / "images"
PORT = 5000
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "br4y")
ADMIN_PASSWORD_HASH = os.environ.get(
    "ADMIN_PASSWORD_HASH",
    "995cbb347e14061c665d09ed6a1be57add69d77e54de608b5f3ff9c505241e97",
)
SESSION_SECRET = os.environ.get("SESSION_SECRET") or secrets.token_hex(32)
SESSIONS = {}


def read_games():
    try:
        with GAMES_FILE.open("r", encoding="utf-8") as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def write_games(games):
    temporary = GAMES_FILE.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as file:
        json.dump(games, file, indent=2)
        file.write("\n")
    temporary.replace(GAMES_FILE)


def apply_order(games, order):
    """Reorder the games matching `order` among themselves, anchored at the
    position of the earliest one of them in the original list. Games not
    named in `order` keep their exact relative position untouched. Passing
    every game's id reorders the whole list; passing a subset (e.g. just the
    collection) reorders only that subset in place."""
    games_by_id = {game.get("id"): game for game in games}
    subset_ids = [game_id for game_id in order if game_id in games_by_id]
    if not subset_ids:
        return games

    subset_set = set(subset_ids)
    result = []
    inserted = False
    for game in games:
        if game.get("id") in subset_set:
            if not inserted:
                result.extend(games_by_id[game_id] for game_id in subset_ids)
                inserted = True
        else:
            result.append(game)
    if not inserted:
        result.extend(games_by_id[game_id] for game_id in subset_ids)
    return result


def normalize_link(link):
    return str(link).strip().rstrip("/")


def slugify(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or name.lower()


def slug_to_title(name):
    words = re.sub(r"[-_]+", " ", name).strip().split()
    small_caps = {"2", "3d", "vr", "2d"}
    return " ".join(w.upper() if w.lower() in small_caps else w.capitalize() for w in words) or name


def find_image_for_slug(slug):
    if not IMAGES_DIR.is_dir():
        return None
    for ext in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
        candidate = IMAGES_DIR / f"{slug}{ext}"
        if candidate.is_file():
            return f"images/{slug}{ext}"
    normalized = slug.replace("-", "")
    for file in IMAGES_DIR.iterdir():
        if file.is_file() and file.stem.lower().replace("-", "").replace("_", "") == normalized:
            return f"images/{file.name}"
    return None


def sync_games_from_folder():
    """Scan games/ for subfolders not yet in games.json and add them automatically."""
    games = read_games()
    if not GAMES_DIR.is_dir():
        return games

    existing_links = {normalize_link(game.get("link", "")) for game in games}
    added = False

    for entry in sorted(GAMES_DIR.iterdir()):
        if not entry.is_dir():
            continue
        link = f"games/{entry.name}/"
        if normalize_link(link) in existing_links:
            continue

        slug = slugify(entry.name)
        game = {
            "id": f"{slug}-{secrets.token_hex(3)}",
            "title": slug_to_title(entry.name),
            "category": "ARCADE",
            "image": find_image_for_slug(slug) or "images/logo.png",
            "link": link,
            "collection": False,
        }
        games.append(game)
        existing_links.add(normalize_link(link))
        added = True

    if added:
        write_games(games)

    return games


def valid_game(value):
    title = str(value.get("title", "")).strip()
    category = str(value.get("category", "ARCADE")).strip().upper()
    image = str(value.get("image", "")).strip()
    link = str(value.get("link", "")).strip()
    return (
        2 <= len(title) <= 60
        and 2 <= len(category) <= 20
        and image.startswith("images/")
        and ".." not in image
        and (ROOT / image).is_file()
        and (link.startswith("games/") or link.startswith("https://") or link.startswith("http://"))
    )


def make_session(username):
    issued = str(int(time.time()))
    token = hmac.new(
        SESSION_SECRET.encode(), f"{username}:{issued}".encode(), hashlib.sha256
    ).hexdigest()
    SESSIONS[token] = (username, time.time() + 60 * 60 * 8)
    return token


def logged_in(handler):
    token_cookie = handler.cookies().get("blazer_session")
    token = token_cookie.value if token_cookie else None
    session = SESSIONS.get(token)
    if not session or session[1] < time.time():
        if token:
            SESSIONS.pop(token, None)
        return False
    return hmac.compare_digest(session[0], ADMIN_USERNAME)


def session_cookie(handler, token, max_age):
    forwarded_proto = handler.headers.get("X-Forwarded-Proto", "").split(",")[0].strip()
    is_https = forwarded_proto == "https" or handler.headers.get("Origin", "").startswith("https://")
    same_site = "None; Secure" if is_https else "Lax"
    return f"blazer_session={token}; Path=/; HttpOnly; SameSite={same_site}; Max-Age={max_age}"


class BlazerHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def cookies(self):
        from http.cookies import SimpleCookie

        cookie = SimpleCookie()
        cookie.load(self.headers.get("Cookie", ""))
        return cookie

    def json_response(self, payload, status=HTTPStatus.OK):
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def request_body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length > 20_000:
            return None
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return None

    def do_GET(self):
        route = urlparse(self.path).path
        if route == "/api/games":
            self.json_response(sync_games_from_folder())
            return
        if route == "/api/session":
            self.json_response({"authenticated": logged_in(self)})
            return
        super().do_GET()

    def do_POST(self):
        route = urlparse(self.path).path
        body = self.request_body()
        if body is None:
            self.json_response({"error": "Invalid request."}, HTTPStatus.BAD_REQUEST)
            return

        if route == "/api/login":
            username = str(body.get("username", ""))
            password_hash = hashlib.sha256(
                str(body.get("password", "")).encode()
            ).hexdigest()
            if hmac.compare_digest(username, ADMIN_USERNAME) and hmac.compare_digest(
                password_hash, ADMIN_PASSWORD_HASH
            ):
                token = make_session(username)
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json")
                self.send_header(
                    "Set-Cookie",
                    session_cookie(self, token, 28800),
                )
                self.end_headers()
                self.wfile.write(b'{"authenticated":true}')
            else:
                self.json_response({"error": "Incorrect username or password."}, HTTPStatus.UNAUTHORIZED)
            return

        if route == "/api/logout":
            token = self.cookies().get("blazer_session")
            if token:
                SESSIONS.pop(token.value, None)
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json")
            self.send_header(
                "Set-Cookie",
                session_cookie(self, "", 0),
            )
            self.end_headers()
            self.wfile.write(b'{"authenticated":false}')
            return

        if route == "/api/games":
            if not logged_in(self):
                self.json_response({"error": "Log in to add games."}, HTTPStatus.UNAUTHORIZED)
                return
            if not valid_game(body):
                self.json_response(
                    {"error": "Add a title, category, images/ image path, and games/ link."},
                    HTTPStatus.BAD_REQUEST,
                )
                return
            games = read_games()
            slug = re.sub(r"[^a-z0-9]+", "-", body["title"].lower()).strip("-")
            game = {
                "id": f"{slug}-{secrets.token_hex(3)}",
                "title": body["title"].strip(),
                "category": body["category"].strip().upper(),
                "image": body["image"].strip(),
                "link": body["link"].strip(),
                "collection": bool(body.get("collection")),
            }
            games.append(game)
            write_games(games)
            self.json_response(game, HTTPStatus.CREATED)
            return

        if route == "/api/games/reorder":
            if not logged_in(self):
                self.json_response({"error": "Log in to reorder games."}, HTTPStatus.UNAUTHORIZED)
                return
            order = body.get("order")
            if not isinstance(order, list) or not all(isinstance(item, str) for item in order):
                self.json_response({"error": "Provide an ordered list of game ids."}, HTTPStatus.BAD_REQUEST)
                return
            games = apply_order(read_games(), order)
            write_games(games)
            self.json_response(games)
            return

        if route == "/api/games/collection":
            if not logged_in(self):
                self.json_response({"error": "Log in to edit the collection."}, HTTPStatus.UNAUTHORIZED)
                return
            game_id = body.get("id")
            collection_flag = body.get("collection")
            if not isinstance(game_id, str) or not isinstance(collection_flag, bool):
                self.json_response(
                    {"error": "Provide a game id and a true/false collection flag."},
                    HTTPStatus.BAD_REQUEST,
                )
                return
            games = read_games()
            for game in games:
                if game.get("id") == game_id:
                    game["collection"] = collection_flag
                    break
            else:
                self.json_response({"error": "Game not found."}, HTTPStatus.NOT_FOUND)
                return
            write_games(games)
            self.json_response(games)
            return

        self.json_response({"error": "Not found."}, HTTPStatus.NOT_FOUND)


if __name__ == "__main__":
    sync_games_from_folder()
    print(f"Serving on http://localhost:{PORT}")
    ThreadingHTTPServer(("0.0.0.0", PORT), BlazerHandler).serve_forever()