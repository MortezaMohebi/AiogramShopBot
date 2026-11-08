# Multi-product chat gallery

## Intent

When a customer enters the shop or a category, show four published, permitted product previews at once on Telegram and Bale. Each preview has its own cover photo when available, short name/price/availability copy, and a button opening that exact product. A text-only card remains usable when no published cover exists.

## Constraints

- Use the existing database, bot/store entitlement predicate, publication policy, price formatting and stock visibility settings.
- Keep requested product media in chat; gallery covers are previews, never product file requests.
- Provide a bounded next/previous page control and return to the originating list after inspecting a product.
- Support both providers without a Mini App or a new migration. Do not expose unpublished, denied or other-store products through stale callbacks.

## Approaches

- Chosen: four separate preview cards per page, each with its own inline detail button. This makes every product independently selectable with a photo in both providers.
- Considered: one album/collage plus numbered selection buttons. The photo-to-product association is less direct and Bale support differs.
- Considered: a Mini App grid. It gives a richer browsing surface but adds a separate customer application and platform-specific integration.

## Interaction

The bot sends up to four cards and a compact page navigation message. A card opens its product details, add-to-cart and optional media actions. Back returns to the same page and category. Subsequent pages show the next four products. Empty and denied catalogs retain their existing messages.
