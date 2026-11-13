# bazaar-contrib-server-market

The Bazaar Server Contrib market. Each target uses its own configured
indexes, installed distributions and manager. The server's own environment is
a separate target for administrators.

Enable `server-market` alongside `server`, `server-access`, `server-computer`
and `contrib-manager` in the server's configuration.

The market registers `contribs.view` and `contribs.update` on computer shares.
Accounts need the role's permission and ownership or a share of the selected
computer for that permission. Read access lists the computer and its catalog;
edit access allows changes. The server supplies the authenticated account on
each request.

## Market pages

Open `/market` from the Extensions group. The market owns its pages, styles,
translations and navigation entry, and uses the server's existing shell on
computers and phones. The target picker includes accessible computers and,
for administrators, Bazaar Server itself. Each target's package counts, indexes,
operating system and connection state come from that host.

Installed cards show actual versions, configured entry switches, runtime
states and package actions. Compatible update checks use
the selected host's resolver and saved package sources; available updates show
their resolved version. Contrib parameters belong to the page that uses the
Contrib: agent setup, computer management or server settings. The manager retains
dependency checks and reports
configuration saving, runtime application and restart requirements separately.

Discover searches the target's subscribed indexes, filters sources and
installation state, and opens package details before installation. Missing
`summary`, `description` or `icon_url` omits its display region. Manage indexes
adds, removes and refreshes subscriptions and opens their Contrib entries.
Users without accessible computers see the existing computer enrollment guide.
Opening an installed package uses its configured source for the details and
installation form. Choosing a particular catalog source keeps that explicit
selection, including when another source offers the same package.

Installation and management retain the target's operation ID in the address.
Reloading resumes the same operation, including after a lost connection. The
installed metadata includes every exported entry, its configuration model and
Python dependency requirements. Agent channel and runtime choices link here
with their computer selected.

Discover retains its target and filters during installation and refreshes cards
and the installed count when the operation completes. The available-only filter
then removes the installed package from the results. Windows targets include
their platform icon, and local index titles use the filename for both Windows
and Unix paths.
Package cards opened from an index lead to the same package details and install
form as Discover. An update-check error is displayed alongside the host's
installed cards and count. Environment reads share the manager's existing
lock with package changes.
Background checks and operation-completion refreshes use the Server's existing
morph updates to preserve open menus. Installed-list refreshes check updates
directly.
Choosing a menu action closes that menu. Activation, upgrade and removal show
their operation immediately, using the same progress response as installation.
They do not reload installed metadata before showing the queued operation.
Completion refreshes cards and open package details; successful removal clears
those details.

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
| GET | `/packages/{name}` | Actual version, all entries, configuration schemas and requirements |
| POST | `/install` | Queue an installation with `package`, `source` and optional `version` |
| POST | `/indexes` | Add a subscription with `{"location": "…"}`; remove it with `"remove": true` |
| POST | `/indexes/refresh` | Refresh the target's online indexes |
| GET | `/operations/{id}` | The target manager's operation record |

Index changes return the manager's operation, including its ID and installation,
configuration and application state. Operations remain on the host that runs
them. `summary`, `description` and `icon_url` come from the target's indexes and
may be omitted. Resource addresses, local paths and HTTP(S) subscriptions are
resolved by that target.

The node exposes `contrib-catalog` for index reads and refreshes,
`contrib-manager` for package and entry operations, `configuration.read` for
its current document and `contrib-status.states` for its public lifecycle
query. Edit permissions are checked before every management request.

The development lock pins the manager and status contracts from
[BCN PR 182](https://github.com/yuchanns/bazaar-compute-node/pull/182).
The isolated wheel tests install those same revisions. Publishing this feature
requires published manager/status versions containing those contracts and updated
release dependency bounds.

Run `uv sync --locked --prerelease allow`, install Chromium with
`uv run --no-sync playwright install chromium`, then use
`uv run --no-sync python scripts/ci_pytest.py`. The tests use real HTTP,
Starlink nodes and isolated wheel-installed host environments.
The installation checks verify catalog cards, installed counts including
dependencies and available-only filtering before reloading the page, then
verify that the saved operation can still be restored.
They also stop the real private registry and verify that a failed remote update
check retains the installed packages and count. Index controls exercise both
package-title and install links from an expanded index.
Management controls assert the submitted operation ID before awaiting its real
terminal state. The installed-host workflows also keep package details open and
verify their upgraded version, refreshed switch state and removal.
The 2026-11-13 progress-response revision passed all 11 acceptance cases on Linux
with blocking-call detection and uv 0.13: 10 passed in the full run (206.22
seconds), and the lifecycle/refusal case passed separately (12.53 seconds) after
correcting its configuration snapshot to precede the refused change.
The source-selection revision passed the five page/browser cases (147.76-second
run) and the installed-host case separately (167.91 seconds). The latter uses
two real HTTP sources for the same package and verifies explicit source
selection, installed-card details and a browser reinstall preserving the saved
source on both the server and remote computer.
Ruff and Pyright passed. The same acceptance suite runs on native Windows and
macOS in the PR checks.

## Releases

Run the `Release` workflow with a version such as `0.3.0rc1`. It prepares a
verified release commit, runs the reusable CI against that commit, builds a
wheel and sdist with their checksum manifest, and verifies isolated
installations on Linux, macOS and Windows. The `pypi` environment publishes
those same artifacts through PyPI Trusted Publishing, verifies a clean PyPI
installation, then creates the annotated version tag.

Configure the PyPI publisher for `open-bazaar/contrib-server-market`, workflow
`release.yml`, environment `pypi`.

Publish the new manager/status contracts from BCN before releasing these market
pages. Set the market's dependency bounds to those published versions, refresh
the development lock and verify clean PyPI installations. The agent page links
can be released independently of the market package.
Upgrade connected computers' manager/status packages before deploying the new
market pages to servers.

Add a new Contrib's index entry after its distribution is published. Merge index
display changes before building a BCN release so its bundled snapshot includes
the same metadata as the online index.
