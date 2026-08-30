# SONiC ConfigDB validation

`osism sonic validate` checks a SONiC `config_db.json` against schemas derived
from the SONiC YANG models. These are notes on the parts that are not apparent
from the code — above all what the validator does *not* check, and the one
caveat worth knowing before trusting a result.

## How it fits together

```
files/sonic/yang_models/*.yang          vendored upstream YANG (see Giltfile.yaml)
        │
        │  tools/sonic_yang_to_pydantic.py     run by hand, needs pyang + black
        ▼
osism/tasks/conductor/sonic/_generated/  committed, never edited by hand
        │    _schemas.py    one Pydantic model per ConfigDB table
        │    _leafrefs.py   cross-table reference constraints
        ▼
osism/tasks/conductor/sonic/validator.py
```

The generated code is committed so the runtime needs no YANG tooling — pydantic
is the only dependency. `pyang` and `black` are needed only to regenerate.

Two callers: the `osism sonic validate` command, and a unit test that runs the
validator over every ConfigDB artifact the repository ships, so a change that
starts rejecting one fails at PR time.

## The caveat: the models are a different SONiC to the devices

`files/sonic/yang_models/` is vendored from **community** SONiC
(`sonic-net/sonic-buildimage`). The switches in `SUPPORTED_HWSKUS` run
**Enterprise** SONiC builds (Broadcom lineage — the same reason the BGP tables
are `BGP_GLOBALS*` and the consumer is `frrcfgd` rather than `bgpcfgd`).

Most tables are identical between the two — `sonic-bgp-common.yang` is
byte-for-byte the same file. Some are not, and there the community model
describes a table the devices do not implement:

| field                    | community model   | what the devices run   |
|--------------------------|-------------------|------------------------|
| `SYSLOG_SERVER.protocol` | enum `tcp`/`udp`  | enum `TCP`/`UDP`/`TLS` |
| `MGMT_PORT.autoneg`      | pattern `on\|off` | boolean                |

Tables like these are listed in `PLATFORM_DIVERGENT_TABLES` in the generator.
They get no schema and are reported as a warning naming the reason, instead of
producing errors about values that are correct.

Where the divergence is one leaf rather than a whole table, dropping the table
gives up too much. Those are listed in `PLATFORM_DIVERGENT_FIELDS` instead,
which retypes just that leaf to what the platform accepts and emits the reason
as a comment beside the generated field. The rest of the table stays validated,
and so does the leaf — against the platform rather than against the model.

| field                          | community model | what the devices run |
|--------------------------------|-----------------|----------------------|
| `BGP_NEIGHBOR_AF.admin_status` | enum `up`/`down`| `true`/`false`       |

### Why `BGP_NEIGHBOR_AF.admin_status` is `true`/`false`

This one is worth spelling out, because the community model is not merely a
different flavour here — following it takes BGP down on the builds we run.

`BGP_NEIGHBOR_AF` belongs to the unified FRR management interface, and that
feature's own CONFIG_DB schema types the leaf as a boolean, in the same
document where `PORT` and the interface tables are `up`/`down`:

    admin_status = "true" / "false" ; Neighbor admin status

— `doc/mgmt/SONiC_Design_Doc_Unified_FRR_Mgmt_Interface.md` §3.2.1.7 in
`sonic-net/SONiC`.

The consumer agrees. In `frrcfgd`, the address-family `admin_status` entries of
`nbr_af_key_map` are bound to the token pair `['true', 'false', False]`. A
value outside that pair does not fall back to anything: `get_command_cmn` logs
`Input token up is neither true or false` and returns no command, so
`neighbor <x> activate` is never issued and the address family is silently left
inactive. A config that reads correctly produces a peering that carries no
routes.

The community YANG model says otherwise — `stypes:admin_status`, the `up`/`down`
enumeration — and upstream resolved the contradiction in the consumer, not in
the model: `frrcfgd` was taught to accept `up`/`down` *in addition to*
`true`/`false`, explicitly so that existing deployments keep working
([sonic-buildimage#21697][af-admin], merged 2025-03-12). That change is in
community `master` and `202505`; it is **not** in `202411`, `202405` or
`202311`.

So the generator emits `true`, and this entry keeps the validator from calling
that an error.

### When this entry can go

When every switch OSISM manages runs a build whose `frrcfgd` carries that
change. Then `up`/`down` becomes the better value — it satisfies both the model
and the consumer, and `config reload` on newer `sonic-utilities` YANG-validates
`/etc/sonic/config_db.json` and aborts on a value outside the model.

Establish it on a device, not from a release note. Enterprise builds are cut
from community branches, but which branch a given build carries is not
something a version number answers, and no published mapping settles it. The
check is in the `bgp` container's `frrcfgd.py`: the `admin_status|ipv4` entry
of `nbr_af_key_map` must name a handler function rather than the literal token
list.

Change both sides together. Emitting `up` while this entry still says
`true`/`false` turns every generated AF row into a validation error; retyping
the leaf while the generator still emits `true` does the same in reverse. And
neither is safe until the fleet has moved, whatever the validator says.

[af-admin]: https://github.com/sonic-net/sonic-buildimage/pull/21697

Vendoring the devices' own models instead is not currently possible: there is
no authoritative published Enterprise model set. The management-framework
lineage in `sonic-net/sonic-mgmt-common` carries only a handful of modules, the
full sets ship inside vendor distributions, and `SUPPORTED_HWSKUS` spans two
vendors anyway. Treat community YANG as what it is — a good approximation that
is authoritative for neither vendor.

**When a new error looks like a false positive**, check the field against what
the *device* expects. Do not check it against our own generated configs or
against a `config_db.json` pulled from a switch OSISM manages: the config
generator wrote those values, so they only tell you what we already emit. This
has produced wrong conclusions more than once.

## What it actually buys you

Worth calibrating before reading the list of gaps below, because the two halves
of the validator pull very different weight. Measured over nine E2E goldens and
two live configs:

| check                     | coverage on those artifacts            |
|---------------------------|----------------------------------------|
| per-field type validation | 34 tables, 911 rows, 5857 field values |
| cross-table leafref pass  | 17 of 136 constraints, 303 values      |

Type validation is the broader of the two, and every error class found so far
has come from it — an enum written in the wrong case, a leaf-list emitted in a
shape the schema did not accept, and so on. The leafref pass is narrower but
covers what type checking cannot: that port channel and VLAN membership, BGP
neighbour and VRF references and interface names actually point at something.
Most of the remaining constraints are for tables no artifact here contains.

## What the validator does not check

Do not read a clean result as "this config is correct". Known gaps:

- **Tables with no schema pass untouched.** Upstream YANG does not model every
  ConfigDB table, and the Enterprise-only tables are largely absent from the
  community models. They are reported as warnings. Warnings are a coverage
  signal, not a defect signal — a gate should key on errors only.
- **Unknown fields are allowed.** Row models are generated with
  `extra="allow"`, so a misspelled or platform-specific field is never
  reported. Several fields written for `SYSLOG_SERVER` are invisible this way.
- **`must` statements are not modelled at all,** for any field. `adv_speeds`
  carries one restricting `all` to appear alone, for instance, and `"all,100000"`
  validates here although SONiC would reject it.
- **A reference is only judged against the tables the config carries.** A
  generated config is a fragment — the device layers it onto its own base
  config — so naming an `MGMT_PORT` it does not itself contain is legitimate,
  and a union leafref may name a `PORTCHANNEL` while the fragment holds only
  `PORT`. A value that resolves nowhere is an error only when *every* target
  table is present; otherwise it is reported as a warning naming the value and
  the missing tables. A typo lands there too and cannot be told apart, which is
  why it warns rather than passing silently. A target table that is *present
  but empty* still errors, since there the config does model it.
- **Leafrefs the generator could not resolve are absent entirely.** The XPath
  parser gives up on relative paths (`../..`) and on any path carrying a
  predicate — `BGP_NEIGHBOR_AF.neighbor` is both — so those references are not
  among the generated constraints and nothing checks them here.
- **Patterns are matched unanchored in `_schemas.py`.** YANG patterns are XSD
  regexes and match a whole value, but the generated `pattern=` constraints are
  searched, so a valid value with junk around it passes. (The leafref side does
  anchor.)
- **Nothing validates during a sync.** The validator does not run when a config
  is generated or pushed.

## ConfigDB shapes the schemas have to accommodate

Two places where ConfigDB does not look like the YANG suggests, both handled in
the generator and worth knowing before changing it:

- **Some leaf-lists are a single delimited string,** not a JSON array —
  `adv_speeds` is `"100000,50000"`. The exceptions are not guessable; upstream
  keeps the list in `LEAF_LIST_WITH_STRING_VALUE_DICT`
  (`src/sonic-yang-mgmt/sonic_yang_ext.py`) and the generator mirrors it as
  `LEAF_LIST_STRING_DELIMITERS`. Note one field separates on `;`.
- **A union may mix leafrefs with plain types.** `BGP_NEIGHBOR.local_addr`
  takes a literal IP *or* an interface name. A value the plain arms admit is
  legal even though it resolves to no table, so the leafref check has to let it
  through — see `plain_arms` on the generated constraints.

## Regenerating

Needed whenever the vendored YANG or the generator changes. `_generated/` is
committed; do not hand-edit it.

```
pip install pyang black
python tools/sonic_yang_to_pydantic.py
```

Generation fails rather than emitting a union arm pattern that the runtime
would read differently from XSD: each is checked against pyang's XSD matcher
first. The `pattern=` constraints in `_schemas.py` do not go through that check
— that is the unanchored-matching gap noted above.

## Refreshing the vendored YANG

`Giltfile.yaml` pins the upstream commit, and the header there records two
traps: the overlay does not reproduce the committed tree, and three models are
rendered from Jinja templates upstream so the overlay does not produce them at
all. Read it before refreshing, and regenerate the schemas and re-check the
shipped artifacts afterwards.
