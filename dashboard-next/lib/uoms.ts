/** One Store's unit categories and exact rational conversion metadata. */

export interface UomUnit {
  id: string;
  code: string;
  name: string;
  symbol: string;
  category_id: string;
  ratio_num: number;
  ratio_den: number;
  rounding: string;
  reference: boolean;
  active: boolean;
}

export interface UomCategory {
  id: string;
  code: string;
  name: string;
}

export interface UomList {
  store_id: string;
  categories: UomCategory[];
  items: UomUnit[];
}
