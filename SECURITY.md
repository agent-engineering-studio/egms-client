# Security

If you find a vulnerability, do not open a public issue: use the private
report of the repository ("Report a vulnerability" in the Security tab), with
the version, the steps to reproduce it and what it allows. You will get an
answer within 7 days.

What the project handles, to judge a report:

- **One secret: the service key of the Copernicus Land Monitoring Service.**
  The library reads it from `EGMS_SERVICE_KEY` or from the file named by
  `EGMS_SERVICE_KEY_FILE`, signs a short-lived token with it, and never logs
  or writes it. `.env`, `secrets/` and `*service-key*.json` are never
  committed. The page run with `make demo` needs no key.
- **No personal data.** The library reads open data of the European Ground
  Motion Service. The page keeps the tiles it downloads and the records you
  give it, nothing about its visitors.
- **The page and the MCP server answer anyone who reaches them.** In
  `compose.yaml` every port is bound to `127.0.0.1`. The API reads a
  longitude and a latitude and answers only inside the area of the page, so
  no visitor can start a download elsewhere. Put a reverse proxy with HTTPS
  and a rate limit in front of it before you publish it.
- **The back office has one administrator.** Its password is kept as a
  scrypt hash in `.env` (`make admin-password`), every form carries a token
  against cross-site requests, and it listens on `127.0.0.1:3004`: reach it
  through a tunnel or a proxy with HTTPS, never by publishing the port. An
  upload is at most 5 MB and is checked against the record schema before it
  is kept.
- **A sensor sends readings with a token of its own**, shown once and kept
  as a hash. The readings are not signed: anyone who holds the token can send
  values for that sensor, and the back office can turn it off or give it a
  new token.
- **`ANTHROPIC_API_KEY` is read only by `benchmarks/faithful.py`**, to ask a
  model for answers that the library then checks. Nothing in the library, the
  command line, the MCP server or the page calls a model.

Whoever hosts the page stays responsible for HTTPS, for the tiles of the
background map (`EGMS_UI_TILES`: by default they come from OpenStreetMap,
which sees the address of every visitor) and for keeping the image up to
date.
