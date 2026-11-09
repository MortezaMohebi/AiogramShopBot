import type { Category } from "@/lib/types";

export function categoryPath(category: Category, byId: ReadonlyMap<number, Category>) {
  const names = [category.name];
  const visited = new Set([category.id]);
  let parent = category.parent_id;
  while (parent != null && !visited.has(parent)) {
    visited.add(parent);
    const item = byId.get(parent);
    if (!item || item.store_id !== category.store_id) break;
    names.unshift(item.name);
    parent = item.parent_id;
  }
  return names.join(" / ");
}

export function categoryParentOptions(categories: Category[], currentId?: number) {
  const byId = new Map(categories.map(item => [item.id, item]));
  return categories.filter(item => {
    const visited = new Set<number>();
    let id: number | null | undefined = item.id;
    while (id != null && !visited.has(id)) {
      if (id === currentId) return false;
      visited.add(id);
      id = byId.get(id)?.parent_id;
    }
    return id == null;
  }).map(item => ({ id: item.id, label: categoryPath(item, byId) }));
}
