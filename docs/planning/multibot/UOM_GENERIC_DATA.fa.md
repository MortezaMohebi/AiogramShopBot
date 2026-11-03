# UoM + Generic Model Data Toolkit — Store-safe design

**Branch:** `feat/uom-generic-data-io-search-20261104` — stacked on
`feat/multistore-context-user-access-20261104`.
**Status:** **Source implemented; QA not run.**

## 1. StoreContext, BotContext and ENV coverage

The application is **not** Odoo: it has no universal Odoo `env` object
automatically injected into every arbitrary class/model. Instead:

- **Signed Next.js Admin**: `StoreContext` comes from the revocable session
  plus live `shop_staff_store_access` grants. `current_store_id` is the one
  write owner; `active_store_ids` is the permitted read union. `ContextVar`
  binds it to the lifetime of a verified admin request.
- **Existing Store ORM record rules**: `STORE_OWNED_MODELS` is an explicit
  allowlist filtered by active Store IDs. Create/edit/**delete** checks the
  current Store. These hooks do not cover arbitrary raw SQL or unrelated
  models; such routes must implement their own Store predicates and security
  gates. No implicit superadmin cross-Store bypass exists.
- **Provider/Webhook Runtime**: BotContext is resolved from authenticated bot
  tokens/webhooks, independent of an administrator's session. No provider
  callback can read or select StoreContext.
- **UoM API and Model Data Toolkit**: both explicitly validate the active
  Store context (and role). Generic query always adds a Store filter. Imports
  bind to one current Store only, never to a Store ID in the spreadsheet.
- **New models**: register fields with `Dataset`, add Store ownership/record
  rules and explicit per-operation permissions. Adding a SQLAlchemy model is
  not sufficient to grant automatic access. The HTTP resource is also
  explicitly mapped in the signed Admin boundary.

## 2. Reusable UoM model

- `shop_uom_categories`: one unit category per Store (count, mass, volume,
  length, extensible), one reference unit per category.
- `shop_uoms`: codes, names, symbol, exact rational factor
  `ratio_num / ratio_den` relative to the reference, decimal rounding,
  active/reference flags. No floating point conversions or Store/cross-category
  conversion.
- `shop_products.uom_id`: mandatory sales unit; historic Products are
  migrated to the original count unit `piece` ('عدد').
- `shop_products.purchase_uom_id`: optional unit of the same category.
- Product editor lets staff select units only from that Product's Store;
  `/uoms` configures categories and conversions.
- Bot product details include unit of price and stock. New OrderLine entries
  snapshot `uom_code_snapshot`; historical lines are backfilled `piece`.
- Sale UoM cannot be changed on a Product with stock or historical/open order
  references, to avoid retrospectively reinterpreting inventory and invoices.
- **Conservative limit**: Checkout, Cart and stock quantities remain integral.
  One sale unit may be 'kg', but 0.5 kg cannot yet be entered as a quantity;
  it requires a reviewed migration of all quantity/pricing/stock flows. The
  library can perform exact rational conversions; no silent fractional
  order/stock conversion takes place.

## 3. Reusable model registry

Files: `services/shop_model_registry.py`,
`services/shop_model_query.py`, `services/shop_model_io.py`,
`dashboard/shop_model_data_api.py`.

- Each `Dataset` registers a model, safe label, role read/write permissions,
  and `Field` definitions with typed operators, sortable/groupable/importable
  flags, friendly names, and constraints.
- Search is multi-condition, paginated (max 100/page) and allowlisted;
  operators: `eq/ne/contains/starts/gte/lte/in`, with escaped SQL wildcards.
- Group By uses categorical fields or UTC day/week/month/quarter/year buckets.
  Temporal model support: Order `created_at`/`paid_at`; StoreCustomer
  `created_at`. Additional models register a Dataset without cloning API/UI.
- Initial datasets: `products`, `customers` (merchant `StoreCustomer`, not
  raw messenger identities), `orders` (read-only).
- All list, count and group queries have `store_id IN active_store_ids`
  explicit constraints. Write/import always uses `current_store_id`.
- UI: `/data-models/products`, `/data-models/customers`,
  `/data-models/orders` — one metadata-driven frontend component.

### Extending to another model

1. Implement/store `store_id` plus indexes/foreign-key checks and register
   the model with Store record rules.
2. Add a `Dataset(name, ModelClass, label, read_permission,
   write_permission, fields)` with **only intentionally exposed attributes**.
3. Register the Dataset in `REGISTRY`; the existing metadata/search/group/
   export routes and React workbench become available automatically.
4. For importing a new model, add an explicit model-specific validation/upsert
   adapter in `shop_model_io.py`, with transactional validation and
   immutable-record restrictions. Imports are **opt-in**, never generic
   `setattr` for unknown ORM fields.
5. Include permission, Store isolation and legacy regression tests.
   Background provider/services must maintain independent BotContext.

## 4. CSV and Excel Import/Export

- Formats: UTF-8 BOM `.csv` for Persian Excel compatibility and `.xlsx`
  created/read with the pinned `openpyxl` runtime dependency.
- Both templates are **generated dynamically from the same Dataset fields**
  (Excel also includes a Guide sheet). Import rejects unknown/duplicate fields.
- Limits: 8 MiB raw file, 32 MiB uncompressed XLSX, 1000 imported rows,
  5000 exported rows per request. Larger datasets require a future streaming
  batch Job with cursor, progress and separate approval.
- Workflow: download template → fill → upload → **Preview** (create/update
  counts and SHA-256) → explicit Apply of **the exact same file** → atomic DB
  commit. A changed file cannot reuse a Preview Hash.
- Product matching: exact Store-scoped `external_ref` or `sku`, never
  name. Customer matching: exact Store-scoped `external_ref` **only**; do not
  merge customers by phone, name, or platform user ID.
- Import never modifies existing wallet balances/entries, provider tokens,
  consent, CRM-linked identities, or paid orders.
- Import cannot bulk-publish new Products or overwrite existing stock:
  an authorized inventory adjustment flow is needed. Changing UoM of a
  Product with stock/orders is also prohibited.
- CSV export neutralizes leading spreadsheet formulas; XLSX similarly emits
  safe literal text. Formula cells in imported XLSX are rejected.
- The file route uses a signed server-to-server bridge, live Staff membership
  and StoreContext; neither filenames nor body fields can select a Store.
- Customer import has a separate `customers.import` capability for Sales
  and Superadmin. Export requires `customers.read`; Product import requires
  `catalog.write`; Orders are export-only.

## 5. Additive migration

`20261104w001_uom_data_registry.py` (after `20261104v001`) creates
unit tables, stable per-Store defaults, Product UoM/purchase-UoM FKs,
OrderLine unit snapshots and stable per-Store External References.

- Legacy Product inventory/prices and OrderLine quantities remain unchanged.
- Existing customers receive deterministic `legacy-customer-<id>`
  references; Products `legacy-product-<id>`, allowing idempotent exports.
- The migration fails atomically if a Product has no Store/reference unit.
- Existing StoreCustomer identity linking and wallet financial state remain
  untouched.
- No destructive downgrade is allowed.

## 6. QA backlog — **no test run**

- [ ] `python -m pytest -q tests/test_uom_model_data_offline.py`.
- [ ] `python -m pytest -q tests/test_shared_cart.py tests/test_shared_payment_settlement.py tests/test_multibot_runtime_offline.py`.
- [ ] `npm --prefix dashboard-next run typecheck`, lint, build, and Store
  switcher / Product Editor / Data Workbench Playwright tests.
- [ ] Run Alembic w001 on a backed-up PostgreSQL copy; record product/order/
  identity/wallet counts, stock totals and payment/refund sums before/after.
- [ ] Import CSV and XLSX with Persian text and Excel-generated numeric cells;
  invalid headers, formulas, zip bombs, duplicate keys, late reauthorization,
  imported 1000+ rows, 5000+ exports and ambiguous network outcomes.
- [ ] Two Stores with matching SKU/UoM names; export only selected Stores,
  import only one current Store; denied Staff cannot read/modify another
  Store. Test direct PK reads, count queries, aggregates and ORM deletes.
- [ ] UoM conversion precision, new Store initialization, referenced Product
  UoM cannot change, existing OrderLine snapshot immutability.
- [ ] Verify bot catalog/checkout/Bale/Telegram provider compatibility.
- [ ] Explicit operator signoff prior to Production import/cutover; leave
  the stacked PR as Draft while acceptance remains pending.

**Production readiness: NOT VERIFIED.** No migration has been applied to a
live database, and no bot, payment Provider or Worker has been activated.
