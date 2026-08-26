# BlazerGames

## Running on Replit

This is an HTML/CSS/JavaScript game portal with a small Python standard-library
server for the catalog and admin login. Replit runs it with the
`Start application` workflow:

```sh
python3 server.py
```

Open the Replit Preview to view the site. No package installation or external
service configuration is required. The catalog is stored in `games.json`.

## Admin game management

Select **Admin login** in the header and use the configured admin credentials.
After signing in, add a game by providing its title, category, an image path
inside `images/`, and a game folder or URL. New entries are saved to
`games.json` and appear in the arcade automatically.