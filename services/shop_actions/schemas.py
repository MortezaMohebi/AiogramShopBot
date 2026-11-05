"""Public business Action inputs/outputs; no ORM, transport SDK or credentials."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from services.shop_actions.contracts import StrictModel

Id = Annotated[int, Field(ge=1, le=9_007_199_254_740_991)]
Quantity = Annotated[int, Field(ge=1, le=99)]


class Empty(StrictModel):
    """An Action with no caller-controlled business parameters."""


class Page(StrictModel):
    """Bounded pagination never advertises an artificial Store/Bot capacity."""

    page: int = Field(default=1, ge=1, le=10001)
    page_size: int = Field(default=20, ge=1, le=50)


class Search(Page):
    """Search allowlisted public product fields under the current Bot ACL."""

    query: str = Field(default="", max_length=100)
    field: Literal["all", "name", "sku", "description"] = "all"
    category_id: Id | None = None

    @model_validator(mode="after")
    def valid_query(self):
        """Match the shared customer search's minimum printable query length."""
        if self.query and (len(self.query.strip()) < 2 or not self.query.isprintable()):
            raise ValueError("invalid_catalog_query")
        return self


class ProductInput(StrictModel):
    """Only an owned, Bot-visible product ID may be resolved by the service."""

    product_id: Id


class AddItem(ProductInput):
    """Add an integral count of the product's existing sales unit."""

    quantity: Quantity = 1


class CartRevision(StrictModel):
    """Pin confirmation/mutation to the cart state actually reviewed."""

    expected_cart_revision: int = Field(ge=1)


class UpdateItem(AddItem, CartRevision):
    """Set an absolute whole-unit quantity with an optimistic cart base."""


class RemoveItem(ProductInput, CartRevision):
    """Remove one exact product from the reviewed current cart."""


class OrderInput(StrictModel):
    """An order ID alone never grants customer visibility."""

    order_id: Id


class SupportInput(StrictModel):
    """Support text is stored only in the support domain, never execution logs."""

    topic: Literal["general", "order", "payment", "delivery", "refund"] = "general"
    body: str = Field(min_length=1, max_length=4000)
    order_id: Id | None = None


class ReturnInput(OrderInput):
    """Future return executor input, still explicitly unavailable in Layer 2."""

    reason: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=2000)


class WholesaleInput(StrictModel):
    """Future wholesale input; does not create a real application today."""

    company: str = Field(min_length=1, max_length=200)


class NotifyInput(StrictModel):
    """Future notification text never becomes an arbitrary destination URL."""

    message: str = Field(min_length=1, max_length=4000)


class Uom(StrictModel):
    """Exact existing Store unit values without floating-point conversion."""

    id: str
    name: str
    symbol: str
    ratio_num: int
    ratio_den: int
    rounding: str


class ProductPublic(StrictModel):
    """Customer-visible product fields only; no media paths or provider file IDs."""

    id: Id
    name: str
    sku: str | None
    description: str
    product_type: Literal["physical", "digital"]
    price_irr: int = Field(ge=0)
    price_stars: int | None = Field(default=None, ge=1)
    in_stock: bool
    uom: Uom


class ProductPage(StrictModel):
    """A bounded catalog page including the real visible total."""

    items: list[ProductPublic]
    total: int
    page: int
    has_more: bool


class Category(StrictModel):
    """A published same-Store category containing an entitled product."""

    id: Id
    name: str


class CategoryPage(StrictModel):
    """A bounded category page without hidden category names."""

    items: list[Category]
    total: int
    page: int
    has_more: bool


class Visibility(StrictModel):
    """A denied product reveals only a false visibility flag."""

    visible: bool


class PriceUom(StrictModel):
    """Read existing native price values and the exact sales unit."""

    product_id: Id
    price_irr: int
    price_stars: int | None
    uom: Uom


class CartLine(StrictModel):
    """A live quote line in existing whole sales units."""

    product_id: Id
    name: str
    quantity: Quantity
    unit_price_irr: int
    line_total_irr: int
    uom: Uom


class CartView(StrictModel):
    """A safe cart read never exposes private addresses or contact information."""

    cart_id: int | None
    revision: int
    items: list[CartLine]
    subtotal_irr: int | None
    discount_irr: int | None
    shipping_irr: int | None
    total_irr: int | None
    shipping_required: bool
    shipping_ready: bool
    quote_available: bool = True
    quote_error: Literal["action_cart_rejected"] | None = None
    unquoted_items: list["CartItemReference"] = Field(default_factory=list)


class CartItemReference(StrictModel):
    """Owned line identifiers allow cleanup without revealing denied product data."""

    product_id: Id
    quantity: Quantity


class OrderStatus(StrictModel):
    """Preserve the native currency/amount and original Bot ownership."""

    order_id: Id
    status: str
    currency: Literal["IRR", "XTR"]
    amount: int
    bot_id: str
    platform: Literal["telegram", "bale"]


class OrderPage(StrictModel):
    """Only orders belonging to the verified identity cluster are listed."""

    items: list[OrderStatus]
    total: int
    page: int
    has_more: bool


class CheckoutView(StrictModel):
    """Readiness/preparation performs no order creation or payment capture."""

    ready: bool
    missing: list[str]
    cart_revision: int
    mode: str
    terms_version: str
    total_irr: int | None
    total_stars: int | None


class TicketResult(StrictModel):
    """Return safe ticket identifiers rather than echoing its private body."""

    ticket_id: Id
    status: str


class RequestResult(StrictModel):
    """Reserved unavailable business contract, never fabricated live success."""

    request_id: int | None = None
    status: str = "unavailable"
