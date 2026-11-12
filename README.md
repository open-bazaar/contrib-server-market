# bazaar-contrib-server-market

The Bazaar Compute server's plugin market. Each target uses its own configured
indexes, installed distributions and manager. The server's own environment is
a separate target for administrators.

Enable `server-market` alongside `server`, `server-access`, `server-computer`
and `contrib-manager` in the server's configuration.

The market registers `contribs.view` and `contribs.update` on computer shares.
Accounts need the role's permission and ownership or a share of the selected
computer for that permission. Read access lists the computer and its catalog;
edit access allows changes. The server supplies the authenticated account on
each request.

## Catalog and management API

`GET /api/market/targets` returns accessible computers with their short ref,
name, connection state and edit permission, plus whether the server target is
available. Use `/api/market/computers/{ref}` for a computer, or
`/api/market/server` for the server, followed by:

| Method | Path | Result |
| --- | --- | --- |
| GET | `/indexes` | Subscribed indexes, last read time, errors and cached entries |
| GET | `/catalog` | Entries merged by package and source, with their index locations |
| GET | `/installed` | Installed contrib packages and their entry points |
| POST | `/indexes` | Add a subscription with `{"location": "…"}`; remove it with `"remove": true` |
| POST | `/indexes/refresh` | Refresh the target's online indexes |
| GET | `/operations/{id}` | The target manager's operation record |

Index changes return the manager's operation, including its ID and installation,
configuration and application state. Operations remain on the host that runs
them. `summary`, `description` and `icon_url` come from the target's indexes and
may be omitted. Resource addresses, local paths and HTTP(S) subscriptions are
resolved by that target.

The node's manager must expose `contrib-catalog` (`indexes`, `entries`, `refresh`)
and `contrib-manager` (`installed`, `detail`, `index`, `operation`). Development
pins the manager source to the BCN commit reviewed in
[yuchanns/bazaar-compute-node#181](https://github.com/yuchanns/bazaar-compute-node/pull/181)
for these newly exposed members. Run `uv sync --locked --prerelease allow` to
install that combination, then `uv run --no-sync python scripts/ci_pytest.py`
for the real HTTP, node and permission tests.

## Releases

Run the `Release` workflow with a version such as `0.3.0rc1`. It prepares a
verified release commit, runs the reusable CI against that commit, builds a
wheel and sdist with their checksum manifest, and verifies isolated
installations on Linux, macOS and Windows. The `pypi` environment publishes
those same artifacts through PyPI Trusted Publishing, verifies a clean PyPI
installation, then creates the annotated version tag.

Configure the PyPI publisher for `open-bazaar/contrib-server-market`, workflow
`release.yml`, environment `pypi`.

Publish the plugin first, then add it to `open-bazaar/contrib-index`. Build and
publish the BCN main repository last so its bundled index snapshot includes
the released plugin.
