export interface ProductNavigation {
  position: number;
  total: number;
  previous_id: number | null;
  next_id: number | null;
  page: number;
}

export function productListSearch(value: unknown): string {
  return typeof value === "string" ? value.slice(0, 100) : "";
}

export function productEditHref(id: number, search: string): string {
  const path = `/products/${id}/edit`;
  return search ? `${path}?${new URLSearchParams({ list_search: search })}` : path;
}

export function productsListHref(search: string, page: number): string {
  const params = new URLSearchParams();
  if (search) params.set("search", search);
  if (page > 1) params.set("page", String(Math.min(100_000, page)));
  return params.size ? `/products?${params}` : "/products";
}
